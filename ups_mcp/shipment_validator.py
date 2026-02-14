"""Shipment preflight validation, elicitation schema generation, and rehydration.

Pure functions — no MCP/protocol dependencies. All functions are stateless
and safe to test in isolation.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field, create_model


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MissingField:
    """A required field that is absent from the request body.

    Carries optional type metadata so that ``build_elicitation_schema`` can
    produce richer JSON Schema types (enums, numbers, defaults, constraints).
    """
    dot_path: str   # e.g. "ShipmentRequest.Shipment.Shipper.Name"
    flat_key: str   # e.g. "shipper_name"
    prompt: str     # e.g. "Shipper name"
    type_hint: type = str
    enum_values: tuple[str, ...] | None = None
    enum_titles: tuple[str, ...] | None = None
    default: Any = None
    constraints: tuple[tuple[str, Any], ...] | None = None


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
# Required field rules — unconditional (non-package, non-conditional)
# ---------------------------------------------------------------------------

UNCONDITIONAL_RULES: list[FieldRule] = [
    FieldRule("ShipmentRequest.Request.RequestOption", "request_option", "Request option"),
    FieldRule("ShipmentRequest.Shipment.Shipper.Name", "shipper_name", "Shipper name"),
    FieldRule("ShipmentRequest.Shipment.Shipper.ShipperNumber", "shipper_number", "UPS account number"),
    FieldRule("ShipmentRequest.Shipment.Shipper.Address.AddressLine[0]", "shipper_address_line_1", "Shipper street address"),
    FieldRule("ShipmentRequest.Shipment.Shipper.Address.City", "shipper_city", "Shipper city"),
    FieldRule(
        "ShipmentRequest.Shipment.Shipper.Address.CountryCode",
        "shipper_country_code", "Shipper country code",
        constraints=(("maxLength", 2), ("pattern", "^[A-Z]{2}$")),
    ),
    FieldRule("ShipmentRequest.Shipment.ShipTo.Name", "ship_to_name", "Recipient name"),
    FieldRule("ShipmentRequest.Shipment.ShipTo.Address.AddressLine[0]", "ship_to_address_line_1", "Recipient street address"),
    FieldRule("ShipmentRequest.Shipment.ShipTo.Address.City", "ship_to_city", "Recipient city"),
    FieldRule(
        "ShipmentRequest.Shipment.ShipTo.Address.CountryCode",
        "ship_to_country_code", "Recipient country code",
        constraints=(("maxLength", 2), ("pattern", "^[A-Z]{2}$")),
    ),
    FieldRule(
        "ShipmentRequest.Shipment.Service.Code", "service_code",
        "UPS service type",
        enum_values=("01", "02", "03", "12", "13", "14", "59", "65"),
        enum_titles=(
            "Next Day Air", "2nd Day Air", "Ground", "3 Day Select",
            "Next Day Air Saver", "Next Day Air Early", "2nd Day Air A.M.",
            "UPS Saver",
        ),
        default="03",
    ),
]


# ---------------------------------------------------------------------------
# Required field rules — payment
#
# Charge type is always required. Payer account is conditional on which
# billing object is present (BillShipper, BillReceiver, BillThirdParty).
# If no billing object is present, we default to requiring BillShipper.
# ---------------------------------------------------------------------------

PAYMENT_CHARGE_TYPE_RULE: FieldRule = FieldRule(
    "ShipmentRequest.Shipment.PaymentInformation.ShipmentCharge[0].Type",
    "payment_charge_type",
    "Shipment charge type",
    enum_values=("01", "02"),
    enum_titles=("Transportation", "Duties and Taxes"),
    default="01",
)

# Maps billing object key -> FieldRule for the account number within that object.
# find_missing_fields checks which billing object is present and validates accordingly.
PAYMENT_PAYER_RULES: dict[str, FieldRule] = {
    "BillShipper": FieldRule(
        "ShipmentRequest.Shipment.PaymentInformation.ShipmentCharge[0].BillShipper.AccountNumber",
        "payment_account_number",
        "Billing account number",
    ),
    "BillReceiver": FieldRule(
        "ShipmentRequest.Shipment.PaymentInformation.ShipmentCharge[0].BillReceiver.AccountNumber",
        "payment_account_number",
        "Billing account number",
    ),
    "BillThirdParty": FieldRule(
        "ShipmentRequest.Shipment.PaymentInformation.ShipmentCharge[0].BillThirdParty.AccountNumber",
        "payment_account_number",
        "Billing account number",
    ),
}


# ---------------------------------------------------------------------------
# Required field rules — per-package (sub-paths relative to each Package element)
# ---------------------------------------------------------------------------

PACKAGE_RULES: list[FieldRule] = [
    FieldRule(
        "Packaging.Code", "packaging_code", "Packaging type code",
        enum_values=("02", "01", "03", "04", "21", "24", "25"),
        enum_titles=(
            "Customer Supplied Package", "UPS Letter", "Tube",
            "PAK", "UPS Express Box", "UPS 25KG Box", "UPS 10KG Box",
        ),
        default="02",
    ),
    FieldRule(
        "PackageWeight.UnitOfMeasurement.Code", "weight_unit",
        "Weight unit",
        enum_values=("LBS", "KGS"),
        default="LBS",
    ),
    FieldRule(
        "PackageWeight.Weight", "weight", "Package weight",
        type_hint=float,
        constraints=(("gt", 0),),
    ),
]


# ---------------------------------------------------------------------------
# Required field rules — conditional by country
# Sub-paths relative to each address (Shipper.Address or ShipTo.Address).
#
# v1 scope: Only US/CA/PR are enforced. Other countries may require postal
# codes or province codes, but UPS API will catch those. A broader postal
# requirement strategy is planned for v2.
# ---------------------------------------------------------------------------

COUNTRY_CONDITIONAL_RULES: dict[tuple[str, ...], list[FieldRule]] = {
    ("US", "CA", "PR"): [
        FieldRule(
            "StateProvinceCode", "state", "State/province code",
            constraints=(("maxLength", 2), ("pattern", "^[A-Z]{2}$")),
        ),
        FieldRule("PostalCode", "postal_code", "Postal code"),
    ],
}


# ---------------------------------------------------------------------------
# 3-tier defaults
# ---------------------------------------------------------------------------

BUILT_IN_DEFAULTS: dict[str, str] = {
    "ShipmentRequest.Request.RequestOption": "nonvalidate",
    "ShipmentRequest.Shipment.PaymentInformation.ShipmentCharge[0].Type": "01",
}

ENV_DEFAULTS: dict[str, str] = {
    # key = dot-path, value = env-var name to read from env_config
    "ShipmentRequest.Shipment.Shipper.ShipperNumber": "UPS_ACCOUNT_NUMBER",
    # NOTE: BillShipper.AccountNumber is NOT in ENV_DEFAULTS. It is applied
    # conditionally in apply_defaults() only when no payer object
    # (BillShipper/BillReceiver/BillThirdParty) is present, to avoid
    # injecting BillShipper into BillReceiver/BillThirdParty flows.
}

# Billing payer keys to check — if any of these exist in the first
# ShipmentCharge, the caller has chosen a payer and we must not inject
# BillShipper.AccountNumber from env.
_PAYER_OBJECT_KEYS = ("BillShipper", "BillReceiver", "BillThirdParty")


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
# 3-tier defaults application
# ---------------------------------------------------------------------------

def _has_payer_object(request_body: dict) -> bool:
    """Check if any billing payer object exists in the first ShipmentCharge."""
    charge = (
        request_body
        .get("ShipmentRequest", {})
        .get("Shipment", {})
        .get("PaymentInformation", {})
        .get("ShipmentCharge", [{}])
    )
    first_charge = charge[0] if isinstance(charge, list) and charge else (
        charge if isinstance(charge, dict) else {}
    )
    return any(key in first_charge for key in _PAYER_OBJECT_KEYS)


def apply_defaults(request_body: dict, env_config: dict[str, str]) -> dict:
    """Apply 3-tier defaults: built-in -> env -> caller body (highest priority).

    BillShipper.AccountNumber env default is only applied when no payer
    object (BillShipper/BillReceiver/BillThirdParty) exists in the request,
    to avoid overriding the caller's intended billing flow.

    Returns a new dict — does not mutate the input.
    """
    result = copy.deepcopy(request_body)

    # Built-in defaults (lowest priority)
    for dot_path, value in BUILT_IN_DEFAULTS.items():
        if not _field_exists(result, dot_path):
            _set_field(result, dot_path, value)

    # Env defaults (middle priority)
    for dot_path, env_var_name in ENV_DEFAULTS.items():
        env_value = env_config.get(env_var_name, "")
        if env_value and not _field_exists(result, dot_path):
            _set_field(result, dot_path, env_value)

    # Conditional env default: BillShipper.AccountNumber
    # Only inject when NO payer object exists in the request.
    bill_shipper_path = "ShipmentRequest.Shipment.PaymentInformation.ShipmentCharge[0].BillShipper.AccountNumber"
    account_number = env_config.get("UPS_ACCOUNT_NUMBER", "")
    if account_number and not _has_payer_object(result) and not _field_exists(result, bill_shipper_path):
        _set_field(result, bill_shipper_path, account_number)

    return result


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class AmbiguousPayerError(Exception):
    """Raised when multiple billing payer objects exist in the same ShipmentCharge."""
    def __init__(self, payer_keys: list[str]):
        self.payer_keys = payer_keys
        super().__init__(
            f"Ambiguous payer: multiple billing objects present ({', '.join(payer_keys)}). "
            f"Only one of BillShipper, BillReceiver, BillThirdParty is allowed per charge."
        )


# ---------------------------------------------------------------------------
# Body canonicalization
# ---------------------------------------------------------------------------

def _normalize_list_field(container: dict, key: str) -> None:
    """Normalize a field in container from dict -> [dict], preserving lists.

    Non-dict list elements are coerced to {} to prevent confusing downstream
    errors (e.g. a string element where _field_exists expects a dict).

    Mutates container in place.
    """
    if key not in container:
        return
    value = container[key]
    if isinstance(value, dict):
        container[key] = [value]
    elif isinstance(value, list):
        if not value:
            container[key] = [{}]
        else:
            container[key] = [el if isinstance(el, dict) else {} for el in value]
    else:
        container[key] = [{}]


def canonicalize_body(request_body: dict) -> dict:
    """Return a deep copy of request_body with Package and ShipmentCharge
    normalized to list form.

    This is the single normalization entry point. All validation,
    rehydration, and UPS API calls should operate on the canonical form.
    """
    result = copy.deepcopy(request_body)

    # Validate structural anchors so callers receive a predictable TypeError
    # instead of leaking AttributeError from chained .get() on non-dict nodes.
    if not isinstance(result, dict):
        raise TypeError(
            f"Expected dict at request body root, got {type(result).__name__}"
        )

    shipment_request = result.get("ShipmentRequest")
    if shipment_request is None:
        return result
    if not isinstance(shipment_request, dict):
        raise TypeError(
            f"Expected dict at 'ShipmentRequest', got {type(shipment_request).__name__}"
        )

    shipment = shipment_request.get("Shipment")
    if shipment is None:
        return result
    if not isinstance(shipment, dict):
        raise TypeError(
            f"Expected dict at 'ShipmentRequest.Shipment', got {type(shipment).__name__}"
        )

    _normalize_list_field(shipment, "Package")

    payment = shipment.get("PaymentInformation")
    if payment is None:
        return result
    if not isinstance(payment, dict):
        raise TypeError(
            "Expected dict at 'ShipmentRequest.Shipment.PaymentInformation', "
            f"got {type(payment).__name__}"
        )

    _normalize_list_field(payment, "ShipmentCharge")
    return result


# ---------------------------------------------------------------------------
# Preflight validation
# ---------------------------------------------------------------------------

def _get_packages(request_body: dict) -> list[dict]:
    """Extract the Package list from a (preferably canonical) body.

    If Package is missing, returns [{}] for index-0 validation.
    """
    shipment = request_body.get("ShipmentRequest", {}).get("Shipment", {})
    packages = shipment.get("Package")
    if packages is None:
        return [{}]
    if isinstance(packages, list):
        return packages if packages else [{}]
    if isinstance(packages, dict):
        return [packages]
    return [{}]


def _missing_from_rule(
    rule: FieldRule,
    dot_path: str | None = None,
    flat_key: str | None = None,
    prompt: str | None = None,
) -> MissingField:
    """Create a MissingField from a FieldRule, propagating type metadata.

    Optional overrides for dot_path/flat_key/prompt allow customization
    (e.g. per-package indexing) without losing the rule's type information.
    """
    return MissingField(
        dot_path=dot_path or rule.dot_path,
        flat_key=flat_key or rule.flat_key,
        prompt=prompt or rule.prompt,
        type_hint=rule.type_hint,
        enum_values=rule.enum_values,
        enum_titles=rule.enum_titles,
        default=rule.default,
        constraints=rule.constraints,
    )


def find_missing_fields(request_body: dict) -> list[MissingField]:
    """Check required fields and return those that are missing.

    Checks unconditional rules, payment rules, per-package rules,
    and country-conditional rules.

    Body is canonicalized first (Package + ShipmentCharge normalized to
    list form) so that all _field_exists calls with [0] paths work correctly
    regardless of whether the caller provided dicts or lists.
    """
    # Canonicalize once — all subsequent _field_exists calls use this copy.
    body = canonicalize_body(request_body)
    missing: list[MissingField] = []

    # Unconditional non-package fields
    for rule in UNCONDITIONAL_RULES:
        if not _field_exists(body, rule.dot_path):
            missing.append(_missing_from_rule(rule))

    # Payment: charge type is always required
    if not _field_exists(body, PAYMENT_CHARGE_TYPE_RULE.dot_path):
        missing.append(_missing_from_rule(PAYMENT_CHARGE_TYPE_RULE))

    # Payment: payer account is conditional on which billing object is present.
    # Body is canonical so ShipmentCharge is always a list here.
    first_charge = (
        body
        .get("ShipmentRequest", {})
        .get("Shipment", {})
        .get("PaymentInformation", {})
        .get("ShipmentCharge", [{}])
    )
    first_charge = first_charge[0] if first_charge else {}

    # Detect ambiguous payer: multiple billing objects in the same charge
    present_payers = [k for k in PAYMENT_PAYER_RULES if k in first_charge]
    if len(present_payers) > 1:
        raise AmbiguousPayerError(present_payers)

    payer_found = False
    for payer_key, rule in PAYMENT_PAYER_RULES.items():
        if payer_key in first_charge:
            payer_found = True
            if not _field_exists(body, rule.dot_path):
                missing.append(_missing_from_rule(rule))
            break
    if not payer_found:
        # No billing object present — require BillShipper.AccountNumber
        default_rule = PAYMENT_PAYER_RULES["BillShipper"]
        if not _field_exists(body, default_rule.dot_path):
            missing.append(_missing_from_rule(default_rule))

    # Per-package fields — body is canonical so Package is always a list
    packages = _get_packages(body)
    for i, pkg in enumerate(packages):
        n = i + 1  # 1-indexed for user-facing flat keys
        for rule in PACKAGE_RULES:
            full_dot_path = f"ShipmentRequest.Shipment.Package[{i}].{rule.dot_path}"
            flat_key = f"package_{n}_{rule.flat_key}"
            prompt = f"Package {n}: {rule.prompt}" if len(packages) > 1 else rule.prompt
            if not _field_exists(pkg, rule.dot_path):
                missing.append(_missing_from_rule(
                    rule, dot_path=full_dot_path, flat_key=flat_key, prompt=prompt,
                ))

    # Country-conditional fields
    shipment = body.get("ShipmentRequest", {}).get("Shipment", {})
    for role, prefix in [("Shipper", "shipper"), ("ShipTo", "ship_to")]:
        address = shipment.get(role, {}).get("Address", {})
        if not isinstance(address, dict):
            continue
        country = str(address.get("CountryCode", "")).strip().upper()
        for countries, rules in COUNTRY_CONDITIONAL_RULES.items():
            if country in countries:
                for rule in rules:
                    full_dot_path = f"ShipmentRequest.Shipment.{role}.Address.{rule.dot_path}"
                    flat_key = f"{prefix}_{rule.flat_key}"
                    prompt = f"{'Shipper' if role == 'Shipper' else 'Recipient'} {rule.prompt.lower()}"
                    if not _field_exists(address, rule.dot_path):
                        missing.append(_missing_from_rule(
                            rule, dot_path=full_dot_path, flat_key=flat_key, prompt=prompt,
                        ))

    return missing


# ---------------------------------------------------------------------------
# Elicitation schema generation
# ---------------------------------------------------------------------------

# Pydantic Field() natively supports these constraint keys.
# Everything else goes into json_schema_extra for the JSON Schema output.
_PYDANTIC_NATIVE_CONSTRAINTS: frozenset[str] = frozenset({
    "gt", "ge", "lt", "le", "multiple_of", "strict",
    "min_length", "max_length", "pattern",
})


def build_elicitation_schema(missing: list[MissingField]) -> type[BaseModel]:
    """Create a dynamic flat Pydantic model from missing field metadata.

    Uses MissingField type information to produce richer schema types:
    - ``enum_values`` with ``enum_titles`` → ``Literal`` (renders as oneOf)
    - ``enum_values`` without titles → ``Literal`` (renders as enum)
    - ``type_hint == float`` → ``float``
    - ``type_hint == int`` → ``int``
    - ``type_hint == bool`` → ``bool``
    - default → ``str``

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
    return create_model("MissingShipmentFields", **field_definitions)


# ---------------------------------------------------------------------------
# Post-elicitation normalization
# ---------------------------------------------------------------------------

# Flat key patterns for normalization
_COUNTRY_CODE_KEYS = re.compile(r".*_country_code$")
_STATE_KEYS = re.compile(r".*_state$")
_WEIGHT_UNIT_KEYS = re.compile(r".*_weight_unit$")


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
        if _COUNTRY_CODE_KEYS.match(key) or _STATE_KEYS.match(key) or _WEIGHT_UNIT_KEYS.match(key):
            value = value.upper()
        result[key] = value
    return result


# ---------------------------------------------------------------------------
# Post-elicitation semantic validation
# ---------------------------------------------------------------------------

_WEIGHT_VALUE_KEYS = re.compile(r".*_weight$")
_TWO_ALPHA = re.compile(r"^[A-Z]{2}$")


def validate_elicited_values(
    flat_data: dict[str, str],
    missing: list[MissingField],
) -> list[str]:
    """Validate elicited values before rehydration.

    Returns a list of human-readable error messages (empty if all valid).
    Only validates fields that are present in flat_data and have a matching
    MissingField entry.
    """
    prompt_by_key = {mf.flat_key: mf.prompt for mf in missing}
    errors: list[str] = []

    for key, value in flat_data.items():
        label = prompt_by_key.get(key, key)

        if _WEIGHT_VALUE_KEYS.match(key):
            try:
                w = float(value)
                if w <= 0:
                    errors.append(f"{label}: must be a positive number")
            except (ValueError, TypeError):
                errors.append(f"{label}: must be a number")

        if _COUNTRY_CODE_KEYS.match(key) and not _TWO_ALPHA.match(value):
            errors.append(f"{label}: must be a 2-letter country code")

        if _STATE_KEYS.match(key) and not _TWO_ALPHA.match(value):
            errors.append(f"{label}: must be a 2-letter state/province code")

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
    Canonicalizes body (Package + ShipmentCharge to list) for consistent structure.
    Returns a new dict — does not mutate the input.

    Raises RehydrationError if a structural conflict prevents setting a value.
    """
    flat_to_dot = {mf.flat_key: mf.dot_path for mf in missing}
    result = canonicalize_body(request_body)

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
