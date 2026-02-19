"""Generic MCP form-mode elicitation infrastructure.

Pure functions and data structures for building elicitation schemas,
normalizing/validating elicited values, rehydrating nested dicts, and
orchestrating the full elicit-and-rehydrate flow.

Tool-specific validation rules live in their own modules (e.g.
``shipment_validator``, ``rating_validator``). This module is the shared
foundation they all build on.
"""

from __future__ import annotations

import copy
import json
import math
import re
from dataclasses import dataclass
from typing import Any, Callable, Literal

from mcp.server.elicitation import (
    AcceptedElicitation,
    DeclinedElicitation,
    CancelledElicitation,
)
from mcp.server.fastmcp import Context
from mcp.server.fastmcp.exceptions import ToolError
from pydantic import BaseModel, Field, create_model


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MissingField:
    """A required field that is absent from the request body.

    Carries optional type metadata so that ``build_elicitation_schema`` can
    produce richer JSON Schema types (enums, numbers, defaults, constraints).

    Set ``elicitable=False`` for structural fields (dicts/arrays) that cannot
    be meaningfully collected via flat key→value forms.  These fields carry
    guidance in their ``prompt`` and trigger an immediate error instead of
    entering the elicitation form.
    """
    dot_path: str   # e.g. "ShipmentRequest.Shipment.Shipper.Name"
    flat_key: str   # e.g. "shipper_name"
    prompt: str     # e.g. "Shipper name"
    type_hint: type = str
    enum_values: tuple[str, ...] | None = None
    enum_titles: tuple[str, ...] | None = None
    default: Any = None
    constraints: tuple[tuple[str, Any], ...] | None = None
    elicitable: bool = True


@dataclass(frozen=True)
class FieldRule:
    """A rule for a required field — either a full dot-path or a sub-path for packages.

    Optional type metadata drives richer elicitation schemas (enums, numbers,
    defaults, constraints) instead of defaulting everything to str.
    """
    dot_path: str
    flat_key: str
    prompt: str
    type_hint: type = str
    enum_values: tuple[str, ...] | None = None
    enum_titles: tuple[str, ...] | None = None  # paired with enum_values for oneOf
    default: Any = None
    constraints: tuple[tuple[str, Any], ...] | None = None  # min, max, pattern, maxLength, etc.


# ---------------------------------------------------------------------------
# Dict navigation helpers
# ---------------------------------------------------------------------------

def _parse_path_segment(segment: str) -> tuple[str, int | None]:
    """Parse 'Key[0]' into ('Key', 0) or 'Key' into ('Key', None)."""
    if "[" in segment:
        key, bracket = segment.split("[", 1)
        idx = int(bracket.rstrip("]"))
        return key, idx
    return segment, None


def _field_exists(data: dict, dot_path: str) -> bool:
    """Check if a dot-path resolves to a non-empty value in a nested dict.

    Returns False for None, empty string, and whitespace-only strings.
    Returns True for 0, False, and other falsy-but-meaningful values.
    """
    current: Any = data
    for segment in dot_path.split("."):
        key, idx = _parse_path_segment(segment)
        if not isinstance(current, dict) or key not in current:
            return False
        current = current[key]
        if idx is not None:
            if not isinstance(current, list) or len(current) <= idx:
                return False
            current = current[idx]
    if current is None:
        return False
    if isinstance(current, str) and current.strip() == "":
        return False
    return True


def _set_field(data: dict, dot_path: str, value: Any) -> None:
    """Set a value at a dot-path, creating intermediate dicts/lists as needed.

    Only creates intermediates when the node is missing. If an existing node
    has an incompatible type (e.g. a string where a dict is needed), raises
    TypeError instead of silently overwriting data.
    """
    segments = dot_path.split(".")
    current = data
    for segment in segments[:-1]:
        key, idx = _parse_path_segment(segment)
        if key not in current:
            current[key] = [] if idx is not None else {}
        target = current[key]
        if idx is not None:
            if not isinstance(target, list):
                raise TypeError(
                    f"Expected list at '{key}' in path '{dot_path}', "
                    f"got {type(target).__name__}"
                )
            while len(target) <= idx:
                target.append({})
            if not isinstance(target[idx], dict):
                raise TypeError(
                    f"Expected dict at '{key}[{idx}]' in path '{dot_path}', "
                    f"got {type(target[idx]).__name__}"
                )
            current = target[idx]
        else:
            if not isinstance(target, dict):
                raise TypeError(
                    f"Expected dict at '{key}' in path '{dot_path}', "
                    f"got {type(target).__name__}"
                )
            current = target

    last_key, last_idx = _parse_path_segment(segments[-1])
    if last_idx is not None:
        if last_key not in current:
            current[last_key] = []
        if not isinstance(current[last_key], list):
            raise TypeError(
                f"Expected list at '{last_key}' in path '{dot_path}', "
                f"got {type(current[last_key]).__name__}"
            )
        while len(current[last_key]) <= last_idx:
            current[last_key].append(None)
        current[last_key][last_idx] = value
    else:
        current[last_key] = value


# ---------------------------------------------------------------------------
# FieldRule -> MissingField helper
# ---------------------------------------------------------------------------

def _missing_from_rule(
    rule: FieldRule,
    dot_path: str | None = None,
    flat_key: str | None = None,
    prompt: str | None = None,
) -> MissingField:
    """Create a MissingField from a FieldRule, propagating type metadata.

    Optional overrides for dot_path/flat_key/prompt allow customization
    (e.g. per-package indexing) without losing the rule's type information.

    Uses ``is not None`` rather than ``or`` to avoid silently falling back
    to the rule's value when an empty string is passed as an override.
    """
    return MissingField(
        dot_path=dot_path if dot_path is not None else rule.dot_path,
        flat_key=flat_key if flat_key is not None else rule.flat_key,
        prompt=prompt if prompt is not None else rule.prompt,
        type_hint=rule.type_hint,
        enum_values=rule.enum_values,
        enum_titles=rule.enum_titles,
        default=rule.default,
        constraints=rule.constraints,
    )


# ---------------------------------------------------------------------------
# Elicitation schema generation
# ---------------------------------------------------------------------------

# Pydantic Field() natively supports these constraint keys.
# Everything else goes into json_schema_extra for the JSON Schema output.
_PYDANTIC_NATIVE_CONSTRAINTS: frozenset[str] = frozenset({
    "gt", "ge", "lt", "le", "multiple_of",
    "min_length", "max_length", "pattern",
})


def build_elicitation_schema(
    missing: list[MissingField],
    model_name: str = "MissingFields",
) -> type[BaseModel]:
    """Create a dynamic flat Pydantic model from missing field metadata.

    Uses MissingField type information to produce richer schema types:
    - ``enum_values`` with ``enum_titles`` -> ``Literal`` (renders as oneOf)
    - ``enum_values`` without titles -> ``Literal`` (renders as enum)
    - ``type_hint == float`` -> ``float``
    - ``type_hint == int`` -> ``int``
    - ``type_hint == bool`` -> ``bool``
    - default -> ``str``

    Defaults and constraints from the MissingField are forwarded to the
    Pydantic ``Field``.

    This model is suitable for passing to ``ctx.elicit(schema=...)``.
    """

    field_definitions: dict[str, Any] = {}
    for mf in missing:
        field_kwargs: dict[str, Any] = {"description": mf.prompt}
        if mf.default is not None:
            field_kwargs["default"] = mf.default

        if mf.constraints:
            json_extras: dict[str, Any] = {}
            for k, v in mf.constraints:
                if k in _PYDANTIC_NATIVE_CONSTRAINTS:
                    field_kwargs[k] = v
                else:
                    # JSON Schema keys like maxLength, minLength
                    json_extras[k] = v
            if json_extras:
                field_kwargs["json_schema_extra"] = json_extras

        if mf.enum_values:
            field_type = Literal[mf.enum_values]  # type: ignore[valid-type]
            # When titles are paired with enum values, inject oneOf with
            # const+title into json_schema_extra so MCP clients can show
            # human-readable labels for opaque codes.
            if mf.enum_titles and len(mf.enum_titles) == len(mf.enum_values):
                one_of = [
                    {"const": val, "title": title}
                    for val, title in zip(mf.enum_values, mf.enum_titles)
                ]
                extras = field_kwargs.get("json_schema_extra", {})
                extras["oneOf"] = one_of
                field_kwargs["json_schema_extra"] = extras
        else:
            field_type = mf.type_hint

        field_definitions[mf.flat_key] = (field_type, Field(**field_kwargs))
    return create_model(model_name, **field_definitions)


# ---------------------------------------------------------------------------
# Post-elicitation normalization
# ---------------------------------------------------------------------------

# Flat key patterns for normalization
_COUNTRY_CODE_KEYS = re.compile(r".*_country_code$")
_STATE_KEYS = re.compile(r".*_state$")
_WEIGHT_UNIT_KEYS = re.compile(r".*_weight_unit$")
_CURRENCY_CODE_KEYS = re.compile(r".*_currency_code$")


def normalize_elicited_values(flat_data: dict[str, str]) -> dict[str, str]:
    """Apply minimal normalization to elicited values before rehydration.

    - Trims all values
    - Uppercases country codes, state codes, and weight unit codes
    - Strips weight values
    - Removes empty/whitespace-only values
    """
    result: dict[str, str] = {}
    for key, value in flat_data.items():
        if not isinstance(value, str):
            value = str(value)
        value = value.strip()
        if not value:
            continue
        if (
            _COUNTRY_CODE_KEYS.match(key) or _STATE_KEYS.match(key)
            or _WEIGHT_UNIT_KEYS.match(key) or _CURRENCY_CODE_KEYS.match(key)
        ):
            value = value.upper()
        result[key] = value
    return result


# ---------------------------------------------------------------------------
# Post-elicitation semantic validation
# ---------------------------------------------------------------------------

_WEIGHT_VALUE_KEYS = re.compile(r".*_weight$")
_TWO_ALPHA = re.compile(r"^[A-Z]{2}$")
_THREE_ALPHA = re.compile(r"^[A-Z]{3}$")

_POSTAL_CODE_US = re.compile(r"^\d{5}(-\d{4})?$")
_POSTAL_CODE_CA = re.compile(r"^[A-Z]\d[A-Z] ?\d[A-Z]\d$")
_POSTAL_CODE_KEYS = re.compile(r".*_postal_code$")


def validate_elicited_values(
    flat_data: dict[str, str],
    missing: list[MissingField],
) -> list[str]:
    """Validate elicited values before rehydration.

    Returns a list of human-readable error messages (empty if all valid).
    Checks:
    - Weight fields: must be positive numbers
    - Country/state codes: must be 2-letter uppercase alpha
    - Postal codes: US (5 or 5+4 digit) and CA (A1A 1A1) format
    - Enum fields: value must be in the MissingField's enum_values tuple
    """
    metadata_by_key = {mf.flat_key: mf for mf in missing}
    errors: list[str] = []

    for key, value in flat_data.items():
        mf = metadata_by_key.get(key)
        label = mf.prompt if mf else key

        # Enum validation from MissingField metadata
        if mf and mf.enum_values and value not in mf.enum_values:
            allowed = ", ".join(mf.enum_values)
            errors.append(f"{label}: must be one of [{allowed}]")

        # Weight: must be a positive number
        if _WEIGHT_VALUE_KEYS.match(key):
            try:
                w = float(value)
                if not math.isfinite(w) or w <= 0:
                    errors.append(f"{label}: must be a positive, finite number")
            except (ValueError, TypeError):
                errors.append(f"{label}: must be a number")

        # Country code: 2-letter uppercase alpha
        if _COUNTRY_CODE_KEYS.match(key) and not _TWO_ALPHA.match(value):
            errors.append(f"{label}: must be a 2-letter country code")

        # State code: 2-letter uppercase alpha
        if _STATE_KEYS.match(key) and not _TWO_ALPHA.match(value):
            errors.append(f"{label}: must be a 2-letter state/province code")

        # Currency code: 3-letter uppercase alpha (ISO 4217)
        if _CURRENCY_CODE_KEYS.match(key) and not _THREE_ALPHA.match(value):
            errors.append(f"{label}: must be a 3-letter currency code (e.g. USD, EUR, GBP)")

        # Postal code: format depends on associated country code
        if _POSTAL_CODE_KEYS.match(key):
            # Determine associated country: shipper_postal_code -> shipper_country_code
            prefix = key.rsplit("_postal_code", 1)[0]
            country_key = f"{prefix}_country_code"
            country = flat_data.get(country_key, "").upper()
            if country == "US" and not _POSTAL_CODE_US.match(value):
                errors.append(f"{label}: must be a valid US postal code (e.g. 10001 or 10001-1234)")
            elif country == "CA" and not _POSTAL_CODE_CA.match(value):
                errors.append(f"{label}: must be a valid Canadian postal code (e.g. K1A 0B1)")

    return errors


# ---------------------------------------------------------------------------
# Rehydration
# ---------------------------------------------------------------------------

class RehydrationError(Exception):
    """Raised when rehydration encounters a structural conflict in the request body."""
    def __init__(self, flat_key: str, dot_path: str, original_error: TypeError):
        self.flat_key = flat_key
        self.dot_path = dot_path
        self.original_error = original_error
        super().__init__(
            f"Cannot set '{flat_key}' at '{dot_path}': {original_error}"
        )


def rehydrate(
    request_body: dict,
    flat_data: dict[str, str],
    missing: list[MissingField],
) -> dict:
    """Merge flat elicitation responses back into nested UPS structure.

    Uses the ``missing`` list as the flat_key -> dot_path mapping.
    Skips empty/None values. Does not overwrite existing non-empty values.
    Returns a new deep copy — does not mutate the input.

    Raises RehydrationError if a structural conflict prevents setting a value.
    """
    flat_to_dot = {mf.flat_key: mf.dot_path for mf in missing}
    result = copy.deepcopy(request_body)

    for flat_key, value in flat_data.items():
        if value is None or value == "":
            continue
        dot_path = flat_to_dot.get(flat_key)
        if dot_path is None:
            continue
        if not _field_exists(result, dot_path):
            try:
                _set_field(result, dot_path, value)
            except TypeError as exc:
                raise RehydrationError(flat_key, dot_path, exc) from exc

    return result


# ---------------------------------------------------------------------------
# Elicitation capability check
# ---------------------------------------------------------------------------

def check_form_elicitation(ctx: Context | None) -> bool:
    """Check if the connected client supports form-mode elicitation."""
    if ctx is None:
        return False
    try:
        params = ctx.request_context.session.client_params
        if params is None:
            return False
        caps = params.capabilities
        if caps.elicitation is None:
            return False
        # Form supported if .form is explicitly present
        if caps.elicitation.form is not None:
            return True
        # Backward compat: empty elicitation object (neither form nor url set)
        if caps.elicitation.url is None:
            return True
        # Only url is set — form not supported
        return False
    except AttributeError:
        return False


# ---------------------------------------------------------------------------
# Centralized elicit-and-rehydrate flow
# ---------------------------------------------------------------------------

def _missing_payload(fields: list[MissingField]) -> list[dict[str, str]]:
    """Build structured missing-field payload for ToolError JSON."""
    return [
        {"dot_path": mf.dot_path, "flat_key": mf.flat_key, "prompt": mf.prompt}
        for mf in fields
    ]


async def elicit_and_rehydrate(
    ctx: Context | None,
    body: dict,
    missing: list[MissingField],
    find_missing_fn: Callable[[dict], list[MissingField]],
    tool_label: str,
    canonicalize_fn: Callable[[dict], dict] | None = None,
    max_retries: int = 3,
) -> dict:
    """Centralized elicitation flow with retry on validation errors.

    1. Separate structural (non-elicitable) fields -> raise STRUCTURAL_FIELDS_REQUIRED
    2. Check form elicitation support -> raise ELICITATION_UNSUPPORTED
    3. Loop up to max_retries:
       a. Build schema -> call ctx.elicit()
       b. On accept: normalize -> validate -> if errors, retry with error context
       c. On valid: rehydrate -> re-run find_missing_fn
          -> if still missing (elicitable), retry with remaining fields
          -> if still missing (structural), raise immediately
          -> if complete, return updated body
       d. On decline/cancel: raise immediately
    4. After max_retries exhausted: raise ELICITATION_MAX_RETRIES

    Returns the updated body dict on success.
    """
    structural = [mf for mf in missing if not mf.elicitable]
    elicitable = [mf for mf in missing if mf.elicitable]

    if structural:
        raise ToolError(json.dumps({
            "code": "STRUCTURAL_FIELDS_REQUIRED",
            "message": (
                f"Missing {len(structural)} structural field(s) that must be "
                "added directly to request_body (cannot be elicited via form)"
            ),
            "reason": "structural",
            "missing": _missing_payload(structural),
        }))

    if not check_form_elicitation(ctx):
        raise ToolError(json.dumps({
            "code": "ELICITATION_UNSUPPORTED",
            "message": (
                f"Missing {len(elicitable)} required field(s) and client "
                "does not support form elicitation"
            ),
            "reason": "unsupported",
            "missing": _missing_payload(elicitable),
        }))

    schema = build_elicitation_schema(elicitable)
    base_message = f"Missing {len(elicitable)} required field(s) for {tool_label}."
    current_message = base_message

    for attempt in range(max_retries):
        try:
            result = await ctx.elicit(message=current_message, schema=schema)
        except ToolError:
            raise
        except Exception as exc:
            raise ToolError(json.dumps({
                "code": "ELICITATION_FAILED",
                "message": f"Elicitation request failed: {exc}",
                "reason": "transport_error",
                "missing": _missing_payload(elicitable),
            }))

        if isinstance(result, AcceptedElicitation):
            normalized = normalize_elicited_values(result.data.model_dump())
            validation_errors = validate_elicited_values(normalized, elicitable)

            if validation_errors:
                error_text = "\n".join(f"- {err}" for err in validation_errors)
                current_message = (
                    f"Please correct the following:\n{error_text}"
                    f"\n\n{base_message}"
                )
                continue

            try:
                if canonicalize_fn is not None:
                    body = canonicalize_fn(body)
                updated = rehydrate(body, normalized, elicitable)
            except RehydrationError as exc:
                raise ToolError(json.dumps({
                    "code": "ELICITATION_INVALID_RESPONSE",
                    "message": f"Elicited data conflicts with request structure: {exc}",
                    "reason": "rehydration_error",
                    "missing": _missing_payload(elicitable),
                }))

            still_missing = find_missing_fn(updated)
            if not still_missing:
                return updated

            still_structural = [mf for mf in still_missing if not mf.elicitable]
            still_elicitable = [mf for mf in still_missing if mf.elicitable]

            if still_structural:
                raise ToolError(json.dumps({
                    "code": "STRUCTURAL_FIELDS_REQUIRED",
                    "message": (
                        f"Missing {len(still_structural)} structural field(s) "
                        "that must be added directly to request_body"
                    ),
                    "reason": "structural",
                    "missing": _missing_payload(still_structural),
                }))

            elicitable = still_elicitable
            schema = build_elicitation_schema(elicitable)
            body = updated
            error_text = "\n".join(f"- {mf.prompt}" for mf in still_elicitable)
            base_message = (
                f"Missing {len(still_elicitable)} required field(s) for {tool_label}."
            )
            current_message = (
                f"Still missing after elicitation:\n{error_text}\n\n{base_message}"
            )
            continue

        elif isinstance(result, DeclinedElicitation):
            raise ToolError(json.dumps({
                "code": "ELICITATION_DECLINED",
                "message": f"User declined to provide missing {tool_label} fields",
                "reason": "declined",
                "missing": _missing_payload(elicitable),
            }))

        else:  # CancelledElicitation
            raise ToolError(json.dumps({
                "code": "ELICITATION_CANCELLED",
                "message": f"User cancelled {tool_label} field elicitation",
                "reason": "cancelled",
                "missing": _missing_payload(elicitable),
            }))

    raise ToolError(json.dumps({
        "code": "ELICITATION_MAX_RETRIES",
        "message": (
            f"Maximum elicitation retries ({max_retries}) exceeded for {tool_label}"
        ),
        "reason": "max_retries",
        "missing": _missing_payload(elicitable),
    }))
