# ShipAgent Hosted-v1 UPS MCP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the opt-in ShipAgent hosted-v1 UPS boundary contract while preserving raw UPS MCP behavior by default.

**Architecture:** Keep hosted contract shaping in a pure `ups_mcp/shipagent_normalization.py` module with no MCP runtime dependency. Keep `ups_mcp/server.py` as the boundary that validates `response_format`, owns hosted correlation ids, catches hosted failures, and delegates existing raw execution to internal helpers. Hosted mode must be deterministic and must not use MCP elicitation; missing hosted fields return safe validation envelopes. Hosted rate/create execution uses an explicit non-eliciting branch (`allow_elicitation=False`) that raises a local validation `ToolError` before `elicit_and_rehydrate` can run. Hosted capability compatibility is expressed only by `contract_version` for this release; do not add a schema hash or separate schema version. Hosted capabilities stay a flat list for hosted-v1; retry behavior is documented and enforced by the no-retry guard instead of adding a structured `retry_policy` field. Invalid `response_format` values fail with a direct MCP `ToolError` before UPS calls or hosted safe-envelope handling, because no valid hosted boundary contract was selected. Hosted mode catches `ToolError`, normalization failures, and unexpected exceptions after a valid hosted-v1 selection, returning hosted-safe envelopes; raw mode keeps current propagation behavior. Hosted public error categories are limited to `auth`, `rate_limit`, `validation`, `service_unavailable`, `transport`, `unknown`, and `normalization`; non-auth, non-rate-limit carrier 4xx responses map to validation and are not retryable. Do not add domain-specific public categories such as address or customs. Hosted success envelopes use camelCase field names and must include the boundary correlation id as `correlationId`; error envelopes keep the closed `error.correlation_id` field and never echo `idempotencyKey`, even for hosted create failures after a valid key was supplied. When callers omit `trans_id`, hosted mode generates `corr_<32 lowercase hex chars>` and sends it to UPS as `trans_id`; caller-supplied `trans_id` values are stripped and preserved when they are free of ASCII control characters, with no hosted-v1 length limit. Caller-supplied `trans_id` values containing ASCII control characters return a hosted validation safe error before UPS, using a generated safe `corr_...` id in the error envelope. Hosted mode preserves printable caller-supplied `transaction_src` values and keeps the existing default of `ups-mcp`; values containing ASCII control characters return a hosted validation safe error before UPS. ShipAgent hosted infrastructure can pass `shipagent` explicitly if desired. Hosted rate quote and shop results must be self-contained: every returned `RatedShipment` must normalize with `serviceCode` and `totalCharges`; shop mode must not filter incomplete returned options into a partial success. If a hosted rate `RatedShipment` includes `NegotiatedRateCharges`, it must contain a complete `TotalCharge`; do not silently fall back to standard `TotalCharges` when negotiated pricing is malformed. Hosted address validation returns successful domain statuses, including `unsupported` for well-formed two-letter non-US/PR country codes that UPS address validation does not cover; blank or malformed `countryCode` is malformed input and returns a hosted validation safe error before UPS. Hosted success normalization requires UPS-derived string fields to be strings and rejects ASCII control characters instead of coercing, stripping, or returning log-hostile values. Hosted create-shipment success is a complete buy-label result and includes a supported create-shipment label format (`GIF`, `ZPL`, `EPL`, or `SPL`) and strict unwrapped base64 label content from UPS `GraphicImage`, while omitting unsafe label fields such as HTML or URL variants. If hosted create `ShipmentResults` includes `NegotiatedRateCharges`, it must contain a complete `TotalCharge`; do not silently fall back to `ShipmentCharges.TotalCharges` when negotiated pricing is malformed. Every returned UPS `PackageResults` item must include `TrackingNumber`, supported `ShippingLabel.ImageFormat.Code` after uppercasing, and strict unwrapped `ShippingLabel.GraphicImage` base64 with no whitespace or MIME line wrapping; otherwise hosted create returns `UPS_NORMALIZATION_ERROR` instead of a partial buy-label success. Keep top-level `trackingNumbers` for convenience, and include the matching `trackingNumber` inside each `labelData` entry so labels are self-contained. Hosted `idempotency_key` is stripped and must be non-empty, no more than 512 characters, and free of ASCII control characters before UPS is called. Hosted create also validates any caller-supplied `ShipmentRequest.Request.TransactionReference.CustomerContext` before UPS because hosted mode explicitly mutates or preserves that field: existing context must be a string, at most 512 characters, and free of ASCII control characters. Keep UPS operation routing in `ups_mcp/tools.py`, with only create-shipment idempotency metadata pass-through added before the HTTP call. Idempotency metadata is written to `CustomerContext`: set it when the context is missing/blank, append `; idempotency_key=<key>` when the combined value fits UPS's 512-character limit, and preserve the caller's existing context unchanged when it does not fit. Do not add a local idempotency replay cache, dedupe store, lock, or persistence layer; ShipAgent hosted infrastructure owns real tenant/request idempotency.

**Hosted address country handling:** Use `countryCode.strip().upper()` only for hosted boundary decisions: blank validation, two-letter ASCII shape validation, `US`/`PR` support, and non-US/PR `unsupported`. Do not add an ISO or UPS country allowlist for hosted-v1. A well-formed two-letter non-US/PR country code returns `unsupported` before validating the rest of the address fields. A blank or malformed country code returns hosted `UPS_VALIDATION_ERROR` before UPS. When hosted validation proceeds to UPS, pass the caller's original `countryCode` value through unchanged.

**Hosted address required fields:** For supported `US`/`PR` address validation, blank `addressLine1`, `politicalDivision1`, `politicalDivision2`, or `zipPrimary` returns a hosted `UPS_VALIDATION_ERROR` before UPS. Do not run this blank-field validation for well-formed two-letter unsupported countries. Raw mode keeps existing behavior.

**Hosted address candidate fields:** Hosted-v1 address candidates include address fields only: `addressLines`, `city`, `stateProvince`, `postalCode`, `postalCodeExtended`, and `countryCode`. Do not expose UPS `AddressClassification` or other candidate metadata in hosted-v1. Drop any UPS candidate that normalizes to no substantive hosted address fields; `countryCode` alone is not a usable candidate. Never emit an empty `{}` candidate. `valid` and `ambiguous` statuses require at least one surviving hosted address candidate with a substantive field; if all candidates are dropped, return `UPS_NORMALIZATION_ERROR`. `invalid` and `unknown` statuses must have an empty candidate list; if UPS returns candidate data for either status, return `UPS_NORMALIZATION_ERROR`. If UPS returns more than one known XAV status indicator, return `UPS_NORMALIZATION_ERROR` instead of choosing an arbitrary precedence.

**Hosted contract version handling:** Return `contract_version` only from `shipagent_capabilities`. Hosted rate, address, and create success envelopes do not include `contractVersion` or `contract_version`; `response_format="shipagent_v1"` and the capabilities tool establish the contract.

**Hosted field naming:** Hosted rate, address, and create success payload fields use camelCase (`correlationId`, `serviceCode`, `totalCharges`, `trackingNumbers`, `labelData`, `idempotencyKey`). Hosted error payloads keep the closed error object shape with Pythonic `correlation_id` inside `error`; do not add top-level `correlationId` or camelCase aliases to error envelopes.

**Hosted monetary fields:** Preserve UPS `MonetaryValue` formatting as a string without numeric coercion. Hosted rate and create `totalCharges.monetaryValue` must be a string; present numeric, boolean, object, or array monetary values are not coerced. Hosted `totalCharges.currencyCode` must be a string of exactly three uppercase ASCII letters after stripping; malformed currency codes return `UPS_NORMALIZATION_ERROR`.

**Hosted success string safety:** Present UPS-derived string fields that enter hosted success envelopes must be strings. Numeric, boolean, object, or array values are not coerced into strings. `None`/null is treated as missing and is handled by each field's required-or-optional rules. Strings are stripped for surrounding whitespace, but ASCII control characters are not stripped or passed through. If UPS returns newline, carriage return, tab, NUL, DEL, or any other ASCII control character in a hosted success string field, normalization returns `UPS_NORMALIZATION_ERROR`. This applies to fields such as service codes/descriptions, address candidate fields, shipment ids, tracking numbers, label format codes, label base64 content, and monetary strings.

**Tech Stack:** Python 3.12, FastMCP, `mcp.server.fastmcp.exceptions.ToolError`, `unittest`, `pytest`, package metadata via `importlib.metadata`.

---

All paths below are relative to repo root `/Users/matthewhans/Desktop/Programming/ups-mcp`.

## File Structure

- Create: `ups_mcp/shipagent_normalization.py`
  - Pure helpers for capabilities, hosted success mapping, normalization failures, and hosted-safe error envelopes.
  - No imports from `ups_mcp.server`, FastMCP, HTTP clients, validators, or elicitation code.
- Modify: `ups_mcp/server.py`
  - Add `shipagent_capabilities`.
  - Add `response_format` to `rate_shipment`, `validate_address`, and `create_shipment`.
  - Add `idempotency_key` to `create_shipment`.
  - Add small private helpers for response-format validation, hosted correlation ids, and raw-operation helper functions.
  - Hosted mode catches failures and returns hosted-safe envelopes without MCP elicitation; raw mode keeps current behavior.
- Modify: `ups_mcp/tools.py`
  - Add create-shipment metadata pass-through for the stripped hosted idempotency key.
  - Do not store, replay, dedupe, or suppress requests based on idempotency keys.
  - Do not add a retry loop.
- Create: `tests/test_shipagent_normalization.py`
  - Unit tests for pure normalization helpers, success `correlationId`, hosted create label content, and safe error envelopes.
- Create: `tests/test_shipagent_server_hosted.py`
  - Boundary tests for capabilities, raw defaults, hosted response formats, correlation ids, no hosted elicitation, safe errors, unsupported address countries as successful domain results, and idempotency preconditions.
- Modify: `tests/test_tool_mapping.py`
  - Unit tests for `ToolManager.create_shipment` idempotency metadata pass-through, no local dedupe, and no-retry behavior.
- Modify: `README.md`
  - Document hosted-v1 as an opt-in private ShipAgent carrier boundary.

## Implementation Tasks

### Task 1: ShipAgent Capabilities And Safe Error Primitives

**Files:**
- Create: `ups_mcp/shipagent_normalization.py`
- Create: `tests/test_shipagent_normalization.py`

- [ ] **Step 1: Write failing tests for capabilities and closed safe errors**

Create `tests/test_shipagent_normalization.py` with:

```python
import json
import unittest

from mcp.server.fastmcp.exceptions import ToolError

from ups_mcp.shipagent_normalization import (
    ShipAgentNormalizationError,
    build_shipagent_capabilities,
    to_normalization_error,
    to_safe_error,
)


class ShipAgentCapabilitiesAndErrorTests(unittest.TestCase):
    def test_build_shipagent_capabilities_returns_hosted_v1_metadata(self) -> None:
        result = build_shipagent_capabilities("1.1.0")

        self.assertEqual(
            set(result.keys()),
            {"contract_version", "server_version", "capabilities", "response_formats"},
        )
        self.assertEqual(result["contract_version"], "hosted-v1")
        self.assertEqual(result["server_version"], "1.1.0")
        self.assertNotIn("schema_hash", result)
        self.assertNotIn("schema_version", result)
        self.assertNotIn("retry_policy", result)
        self.assertIn("rate_quote", result["capabilities"])
        self.assertIn("rate_shop", result["capabilities"])
        self.assertIn("address_validation", result["capabilities"])
        self.assertIn("create_shipment", result["capabilities"])
        self.assertIn("idempotency_metadata_passthrough", result["capabilities"])
        self.assertIn("shipment_response_normalization", result["capabilities"])
        self.assertIn("safe_error_mapping", result["capabilities"])
        self.assertIn("mutating_retry_policy", result["capabilities"])
        self.assertEqual(result["response_formats"], ["raw", "shipagent_v1"])

    def test_to_normalization_error_is_closed_shape(self) -> None:
        result = to_normalization_error("corr_123")

        self.assertEqual(set(result.keys()), {"success", "error"})
        self.assertFalse(result["success"])
        self.assertEqual(
            set(result["error"].keys()),
            {"code", "category", "message", "retryable", "correlation_id"},
        )
        self.assertEqual(result["error"]["code"], "UPS_NORMALIZATION_ERROR")
        self.assertEqual(result["error"]["category"], "normalization")
        self.assertFalse(result["error"]["retryable"])
        self.assertEqual(result["error"]["correlation_id"], "corr_123")

    def test_to_safe_error_maps_http_and_local_failures_without_raw_details_or_codes(self) -> None:
        unsafe = ToolError(json.dumps({
            "status_code": 429,
            "code": "120001",
            "message": "raw UPS message with account 123456 and UPS code 120001",
            "details": {"request_body": {"client_secret": "secret", "ups_code": "120001"}},
        }))

        result = to_safe_error(unsafe, "corr_rate_limit")

        self.assertEqual(set(result.keys()), {"success", "error"})
        self.assertFalse(result["success"])
        self.assertEqual(
            set(result["error"].keys()),
            {"code", "category", "message", "retryable", "correlation_id"},
        )
        self.assertEqual(result["error"]["code"], "UPS_RATE_LIMIT_ERROR")
        self.assertEqual(result["error"]["category"], "rate_limit")
        self.assertTrue(result["error"]["retryable"])
        serialized = json.dumps(result)
        self.assertNotIn("raw UPS message", serialized)
        self.assertNotIn("request_body", serialized)
        self.assertNotIn("client_secret", serialized)
        self.assertNotIn("123456", serialized)
        self.assertNotIn("120001", serialized)
        self.assertNotIn("ups_code", serialized)

    def test_to_safe_error_maps_validation_transport_auth_service_and_unknown(self) -> None:
        cases = [
            (ToolError(json.dumps({"status_code": 401, "code": "401"})), "UPS_AUTH_ERROR", "auth", False),
            (ToolError(json.dumps({"status_code": 503, "code": "503"})), "UPS_SERVICE_UNAVAILABLE", "service_unavailable", True),
            (ToolError(json.dumps({"code": "REQUEST_ERROR"})), "UPS_TRANSPORT_ERROR", "transport", True),
            (ToolError(json.dumps({"code": "MALFORMED_REQUEST", "reason": "malformed_structure"})), "UPS_VALIDATION_ERROR", "validation", False),
            (ToolError(json.dumps({"status_code": 404, "code": "NOT_FOUND"})), "UPS_VALIDATION_ERROR", "validation", False),
            (ToolError(json.dumps({"status_code": 409, "code": "CONFLICT"})), "UPS_VALIDATION_ERROR", "validation", False),
            (ToolError(json.dumps({"status_code": 422, "code": "UNPROCESSABLE_ENTITY"})), "UPS_VALIDATION_ERROR", "validation", False),
            (ToolError("Invalid requestoption 'bad'. Allowed values: Rate, Shop")), "UPS_VALIDATION_ERROR", "validation", False),
            (RuntimeError("stack path /tmp/secret traceback token")), "UPS_UNKNOWN_ERROR", "unknown", False),
        ]

        for exc, expected_code, expected_category, expected_retryable in cases:
            with self.subTest(expected_code=expected_code):
                result = to_safe_error(exc, "corr_case")
                self.assertEqual(result["error"]["code"], expected_code)
                self.assertEqual(result["error"]["category"], expected_category)
                self.assertEqual(result["error"]["retryable"], expected_retryable)
                self.assertEqual(result["error"]["correlation_id"], "corr_case")
                self.assertNotIn("traceback", json.dumps(result).lower())
                self.assertNotIn("/tmp/secret", json.dumps(result))

    def test_to_safe_error_does_not_expose_domain_specific_error_categories(self) -> None:
        allowed_categories = {"auth", "rate_limit", "validation", "service_unavailable", "transport", "unknown"}
        cases = [
            ToolError(json.dumps({"code": "ADDRESS_NOT_FOUND", "reason": "xav candidate failed"})),
            ToolError(json.dumps({"code": "CUSTOMS_FORM_ERROR", "reason": "international invoice failed"})),
        ]

        for exc in cases:
            with self.subTest(exc=str(exc)):
                result = to_safe_error(exc, "corr_domain")
                self.assertIn(result["error"]["category"], allowed_categories)
                self.assertNotIn(result["error"]["category"], {"address", "customs"})
                self.assertNotIn(result["error"]["code"], {"UPS_ADDRESS_ERROR", "UPS_CUSTOMS_ERROR"})

    def test_normalization_error_type_is_public(self) -> None:
        with self.assertRaises(ShipAgentNormalizationError):
            raise ShipAgentNormalizationError("missing total charges")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
python3 -m pytest tests/test_shipagent_normalization.py::ShipAgentCapabilitiesAndErrorTests -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'ups_mcp.shipagent_normalization'`.

- [ ] **Step 3: Add the pure normalization module primitives**

Create `ups_mcp/shipagent_normalization.py` with:

```python
from __future__ import annotations

import base64
import binascii
import json
from typing import Any, Mapping


HOSTED_CONTRACT_VERSION = "hosted-v1"
HOSTED_RESPONSE_FORMAT = "shipagent_v1"
RAW_RESPONSE_FORMAT = "raw"

SHIPAGENT_CAPABILITIES = [
    "rate_quote",
    "rate_shop",
    "address_validation",
    "create_shipment",
    "idempotency_metadata_passthrough",
    "shipment_response_normalization",
    "safe_error_mapping",
    "mutating_retry_policy",
]

RESPONSE_FORMATS = [RAW_RESPONSE_FORMAT, HOSTED_RESPONSE_FORMAT]
SUPPORTED_CREATE_LABEL_FORMATS = {"GIF", "ZPL", "EPL", "SPL"}

_CATEGORY_TO_PUBLIC_ERROR = {
    "auth": ("UPS_AUTH_ERROR", "UPS authentication failed.", False),
    "rate_limit": ("UPS_RATE_LIMIT_ERROR", "UPS rate limit exceeded.", True),
    "validation": ("UPS_VALIDATION_ERROR", "The UPS request could not be validated.", False),
    "service_unavailable": ("UPS_SERVICE_UNAVAILABLE", "UPS service is temporarily unavailable.", True),
    "transport": ("UPS_TRANSPORT_ERROR", "UPS could not be reached.", True),
    "unknown": ("UPS_UNKNOWN_ERROR", "UPS could not complete the request.", False),
}


class ShipAgentNormalizationError(ValueError):
    """Raised when a successful UPS payload cannot satisfy hosted-v1."""


def build_shipagent_capabilities(server_version: str) -> dict[str, Any]:
    return {
        "contract_version": HOSTED_CONTRACT_VERSION,
        "server_version": server_version,
        "capabilities": list(SHIPAGENT_CAPABILITIES),
        "response_formats": list(RESPONSE_FORMATS),
    }


def to_normalization_error(correlation_id: str) -> dict[str, Any]:
    return {
        "success": False,
        "error": {
            "code": "UPS_NORMALIZATION_ERROR",
            "category": "normalization",
            "message": "UPS returned a response that could not be normalized.",
            "retryable": False,
            "correlation_id": correlation_id,
        },
    }


def to_safe_error(exc: BaseException, correlation_id: str) -> dict[str, Any]:
    category = _classify_exception(exc)
    code, message, retryable = _CATEGORY_TO_PUBLIC_ERROR[category]
    # Keep hosted-v1 closed: do not echo raw UPS codes, messages, or details.
    return {
        "success": False,
        "error": {
            "code": code,
            "category": category,
            "message": message,
            "retryable": retryable,
            "correlation_id": correlation_id,
        },
    }


def _classify_exception(exc: BaseException) -> str:
    payload = _parse_exception_payload(exc)
    status_code = _coerce_int(payload.get("status_code"))
    code = str(payload.get("code", "")).lower()
    reason = str(payload.get("reason", "")).lower()
    classifier = f"{code} {reason}"

    if status_code in {401, 403} or "auth" in classifier or "oauth" in classifier or "unauthorized" in classifier:
        return "auth"
    if status_code == 429 or "rate_limit" in classifier or "too_many" in classifier:
        return "rate_limit"
    if status_code is not None and 500 <= status_code <= 599:
        return "service_unavailable"
    if code == "request_error" or "timeout" in classifier or "network" in classifier:
        return "transport"
    if (
        (status_code is not None and 400 <= status_code <= 499)
        or "validation" in classifier
        or "malformed" in classifier
        or "missing" in classifier
        or "invalid_requestoption" in classifier
        or code in {
            "malformed_request",
            "elicitation_unsupported",
            "elicitation_declined",
            "elicitation_cancelled",
            "elicitation_failed",
            "elicitation_invalid_response",
            "elicitation_max_retries",
            "validation_error",
        }
    ):
        return "validation"

    raw_text = str(exc).lower()
    if "invalid requestoption" in raw_text or "request_body must be a json object" in raw_text:
        return "validation"
    return "unknown"


def _parse_exception_payload(exc: BaseException) -> dict[str, Any]:
    try:
        parsed = json.loads(str(exc))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _coerce_int(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _as_mapping(value: Any) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _clean_string(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ShipAgentNormalizationError("non-string hosted string field")
    raw = value
    if _has_ascii_control(raw):
        raise ShipAgentNormalizationError("control character in hosted string field")
    cleaned = raw.strip()
    return cleaned or None


def _has_ascii_control(value: str) -> bool:
    return any(ord(char) < 32 or ord(char) == 127 for char in value)
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
python3 -m pytest tests/test_shipagent_normalization.py::ShipAgentCapabilitiesAndErrorTests -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ups_mcp/shipagent_normalization.py tests/test_shipagent_normalization.py
git commit -m "feat: add shipagent hosted error primitives"
```

### Task 2: Hosted Rate Normalization

**Files:**
- Modify: `ups_mcp/shipagent_normalization.py`
- Modify: `tests/test_shipagent_normalization.py`

- [ ] **Step 1: Add failing rate-normalization tests**

Append this test class to `tests/test_shipagent_normalization.py` before the `if __name__ == "__main__":` block:

```python
from ups_mcp.shipagent_normalization import normalize_rate_result


class ShipAgentRateNormalizationTests(unittest.TestCase):
    def test_rate_quote_requires_single_rated_shipment_and_uses_negotiated_total(self) -> None:
        raw = {
            "RateResponse": {
                "RatedShipment": {
                    "Service": {"Code": "03", "Description": "UPS Ground"},
                    "NegotiatedRateCharges": {
                        "TotalCharge": {"CurrencyCode": "USD", "MonetaryValue": "10.50"}
                    },
                    "TotalCharges": {"CurrencyCode": "USD", "MonetaryValue": "12.34"},
                }
            }
        }

        result = normalize_rate_result(raw, "rate", "corr_rate_quote")

        self.assertEqual(result, {
            "success": True,
            "correlationId": "corr_rate_quote",
            "serviceCode": "03",
            "serviceDescription": "UPS Ground",
            "totalCharges": {"monetaryValue": "10.50", "currencyCode": "USD"},
        })
        self.assertNotIn("correlation_id", result)
        self.assertNotIn("contractVersion", result)
        self.assertNotIn("contract_version", result)

    def test_rate_quote_rejects_multiple_rated_shipments(self) -> None:
        raw = {
            "RateResponse": {
                "RatedShipment": [
                    {
                        "Service": {"Code": "03"},
                        "TotalCharges": {"CurrencyCode": "USD", "MonetaryValue": "12.34"},
                    },
                    {
                        "Service": {"Code": "02"},
                        "TotalCharges": {"CurrencyCode": "USD", "MonetaryValue": "20.00"},
                    },
                ]
            }
        }

        with self.assertRaises(ShipAgentNormalizationError):
            normalize_rate_result(raw, "Rate", "corr_rate_multi_quote")

    def test_rate_quote_omits_service_description_when_ups_omits_it(self) -> None:
        raw = {
            "RateResponse": {
                "RatedShipment": {
                    "Service": {"Code": "03"},
                    "TotalCharges": {"CurrencyCode": "USD", "MonetaryValue": "12.34"},
                }
            }
        }

        result = normalize_rate_result(raw, "Ratetimeintransit", "corr_rate_no_description")

        self.assertEqual(result, {
            "success": True,
            "correlationId": "corr_rate_no_description",
            "serviceCode": "03",
            "totalCharges": {"monetaryValue": "12.34", "currencyCode": "USD"},
        })

    def test_rate_preserves_monetary_value_as_string_without_numeric_coercion(self) -> None:
        raw = {
            "RateResponse": {
                "RatedShipment": {
                    "Service": {"Code": "03"},
                    "TotalCharges": {"CurrencyCode": "USD", "MonetaryValue": "10.00"},
                }
            }
        }

        result = normalize_rate_result(raw, "Rate", "corr_rate_money")

        self.assertEqual(result["totalCharges"]["monetaryValue"], "10.00")
        self.assertIsInstance(result["totalCharges"]["monetaryValue"], str)

    def test_rate_rejects_malformed_currency_code(self) -> None:
        bad_currency_codes = ("usd", "US", "US1", "US$", "\u00d8SD", "", "   ")

        for currency_code in bad_currency_codes:
            with self.subTest(currency_code=currency_code):
                raw = {
                    "RateResponse": {
                        "RatedShipment": {
                            "Service": {"Code": "03"},
                            "TotalCharges": {
                                "CurrencyCode": currency_code,
                                "MonetaryValue": "12.34",
                            },
                        }
                    }
                }
                with self.assertRaises(ShipAgentNormalizationError):
                    normalize_rate_result(raw, "Rate", "corr_rate_bad_currency")

    def test_rate_rejects_ascii_control_characters_in_success_strings(self) -> None:
        cases = [
            {"Service": {"Code": "03\n"}, "TotalCharges": {"CurrencyCode": "USD", "MonetaryValue": "12.34"}},
            {"Service": {"Code": "03", "Description": "UPS\tGround"}, "TotalCharges": {"CurrencyCode": "USD", "MonetaryValue": "12.34"}},
            {"Service": {"Code": "03"}, "TotalCharges": {"CurrencyCode": "USD", "MonetaryValue": "12.34\x00"}},
            {"Service": {"Code": "03"}, "TotalCharges": {"CurrencyCode": f"US{chr(127)}", "MonetaryValue": "12.34"}},
        ]

        for rated_shipment in cases:
            with self.subTest(rated_shipment=rated_shipment):
                raw = {"RateResponse": {"RatedShipment": rated_shipment}}
                with self.assertRaises(ShipAgentNormalizationError):
                    normalize_rate_result(raw, "Rate", "corr_rate_control")

    def test_rate_rejects_non_string_success_fields(self) -> None:
        cases = [
            {"Service": {"Code": 3}, "TotalCharges": {"CurrencyCode": "USD", "MonetaryValue": "12.34"}},
            {"Service": {"Code": "03", "Description": True}, "TotalCharges": {"CurrencyCode": "USD", "MonetaryValue": "12.34"}},
            {"Service": {"Code": "03"}, "TotalCharges": {"CurrencyCode": "USD", "MonetaryValue": 12.34}},
            {"Service": {"Code": "03"}, "TotalCharges": {"CurrencyCode": ["USD"], "MonetaryValue": "12.34"}},
        ]

        for rated_shipment in cases:
            with self.subTest(rated_shipment=rated_shipment):
                raw = {"RateResponse": {"RatedShipment": rated_shipment}}
                with self.assertRaises(ShipAgentNormalizationError):
                    normalize_rate_result(raw, "Rate", "corr_rate_non_string")

    def test_rate_rejects_incomplete_negotiated_total_without_standard_fallback(self) -> None:
        complete_standard = {"CurrencyCode": "USD", "MonetaryValue": "12.34"}
        cases = [
            {"NegotiatedRateCharges": {"TotalCharge": {"CurrencyCode": "USD"}}},
            {"NegotiatedRateCharges": {"TotalCharge": {"MonetaryValue": "10.50"}}},
            {"NegotiatedRateCharges": {"TotalCharge": {}}},
            {"NegotiatedRateCharges": {}},
        ]

        for partial_negotiated in cases:
            with self.subTest(partial_negotiated=partial_negotiated):
                raw = {
                    "RateResponse": {
                        "RatedShipment": {
                            "Service": {"Code": "03"},
                            "TotalCharges": complete_standard,
                            **partial_negotiated,
                        }
                    }
                }
                with self.assertRaises(ShipAgentNormalizationError):
                    normalize_rate_result(raw, "Rate", "corr_rate_bad_negotiated")

    def test_rate_quote_requires_service_code(self) -> None:
        raw = {
            "RateResponse": {
                "RatedShipment": {
                    "Service": {"Description": "UPS Ground"},
                    "TotalCharges": {"CurrencyCode": "USD", "MonetaryValue": "12.34"},
                }
            }
        }

        with self.assertRaises(ShipAgentNormalizationError):
            normalize_rate_result(raw, "Rate", "corr_rate_missing_service")

    def test_rate_shop_returns_all_complete_options_and_uses_standard_total_when_negotiated_absent(self) -> None:
        raw = {
            "RateResponse": {
                "RatedShipment": [
                    {
                        "Service": {"Code": "03", "Description": "UPS Ground"},
                        "TotalCharges": {"CurrencyCode": "USD", "MonetaryValue": "12.34"},
                    },
                    {
                        "Service": {"Code": "02"},
                        "TotalCharges": {"CurrencyCode": "USD", "MonetaryValue": "20.00"},
                    },
                ]
            }
        }

        result = normalize_rate_result(raw, "SHOP", "corr_rate_shop")

        self.assertEqual(result, {
            "success": True,
            "correlationId": "corr_rate_shop",
            "ratedShipments": [
                {
                    "serviceCode": "03",
                    "serviceDescription": "UPS Ground",
                    "totalCharges": {"monetaryValue": "12.34", "currencyCode": "USD"},
                },
                {
                    "serviceCode": "02",
                    "totalCharges": {"monetaryValue": "20.00", "currencyCode": "USD"},
                }
            ],
        })

    def test_rate_shop_rejects_any_incomplete_returned_option(self) -> None:
        valid_option = {
            "Service": {"Code": "03"},
            "TotalCharges": {"CurrencyCode": "USD", "MonetaryValue": "12.34"},
        }
        cases = [
            [valid_option, {"Service": {"Code": ""}, "TotalCharges": {"CurrencyCode": "USD", "MonetaryValue": "1.00"}}],
            [valid_option, {"Service": {"Code": "02"}, "TotalCharges": {"CurrencyCode": "USD"}}],
            [valid_option, "not-a-shipment"],
        ]

        for rated_shipments in cases:
            with self.subTest(rated_shipments=rated_shipments):
                raw = {"RateResponse": {"RatedShipment": rated_shipments}}
                with self.assertRaises(ShipAgentNormalizationError):
                    normalize_rate_result(raw, "Shop", "corr_rate_partial_shop")

    def test_rate_shop_accepts_object_rated_shipment_shape(self) -> None:
        raw = {
            "RateResponse": {
                "RatedShipment": {
                    "Service": {"Code": "03"},
                    "TotalCharges": {"CurrencyCode": "USD", "MonetaryValue": "12.34"},
                }
            }
        }

        result = normalize_rate_result(raw, "Shoptimeintransit", "corr_rate_shop_object")

        self.assertEqual(result, {
            "success": True,
            "correlationId": "corr_rate_shop_object",
            "ratedShipments": [
                {
                    "serviceCode": "03",
                    "totalCharges": {"monetaryValue": "12.34", "currencyCode": "USD"},
                }
            ],
        })

    def test_rate_normalization_raises_when_required_hosted_fields_are_missing(self) -> None:
        cases = [
            {"RateResponse": {"RatedShipment": []}},
            {"RateResponse": {"RatedShipment": {"Service": {"Code": "03"}}}},
            {"RateResponse": {"RatedShipment": {"TotalCharges": {"CurrencyCode": "USD", "MonetaryValue": "1.00"}}}},
            {"RateResponse": {"RatedShipment": [{"Service": {"Code": ""}, "TotalCharges": {"CurrencyCode": "USD", "MonetaryValue": "1.00"}}]}},
        ]

        for raw in cases:
            with self.subTest(raw=raw):
                with self.assertRaises(ShipAgentNormalizationError):
                    normalize_rate_result(raw, "Shop", "corr_rate_missing")
```

- [ ] **Step 2: Run rate tests to verify they fail**

Run:

```bash
python3 -m pytest tests/test_shipagent_normalization.py::ShipAgentRateNormalizationTests -q
```

Expected: FAIL with `ImportError` for `normalize_rate_result`.

- [ ] **Step 3: Add rate normalization helpers**

Append this code to `ups_mcp/shipagent_normalization.py`:

```python
_RATE_QUOTE_OPTIONS = {"rate", "ratetimeintransit"}
_RATE_SHOP_OPTIONS = {"shop", "shoptimeintransit"}


def normalize_rate_result(
    raw: Mapping[str, Any],
    requestoption: str,
    correlation_id: str,
) -> dict[str, Any]:
    rate_response = _as_mapping(raw.get("RateResponse"))
    if rate_response is None:
        raise ShipAgentNormalizationError("missing RateResponse")

    rated_shipments = _rated_shipments(rate_response.get("RatedShipment"))
    option = str(requestoption).lower()

    if option in _RATE_QUOTE_OPTIONS:
        if not rated_shipments:
            raise ShipAgentNormalizationError("missing RatedShipment")
        if len(rated_shipments) != 1:
            raise ShipAgentNormalizationError("quote returned multiple RatedShipment values")
        normalized = _normalize_rate_shipment(rated_shipments[0], require_service_code=True)
        if normalized is None:
            raise ShipAgentNormalizationError("missing quote serviceCode or totalCharges")
        return {"success": True, "correlationId": correlation_id, **normalized}

    if option in _RATE_SHOP_OPTIONS:
        normalized_options = []
        for rated in rated_shipments:
            normalized = _normalize_rate_shipment(rated, require_service_code=True)
            if normalized is None:
                raise ShipAgentNormalizationError("missing shop serviceCode or totalCharges")
            normalized_options.append(normalized)
        if not normalized_options:
            raise ShipAgentNormalizationError("missing usable shop options")
        return {
            "success": True,
            "correlationId": correlation_id,
            "ratedShipments": normalized_options,
        }

    raise ShipAgentNormalizationError("unsupported rate request option")


def _rated_shipments(value: Any) -> list[Mapping[str, Any]]:
    shipments: list[Mapping[str, Any]] = []
    for item in _as_list(value):
        shipment = _as_mapping(item)
        if shipment is None:
            raise ShipAgentNormalizationError("invalid RatedShipment item")
        shipments.append(shipment)
    return shipments


def _normalize_rate_shipment(rated: Mapping[str, Any], *, require_service_code: bool) -> dict[str, Any] | None:
    total_charges = _extract_total_charge(
        rated,
        negotiated_path=("NegotiatedRateCharges", "TotalCharge"),
        standard_path=("TotalCharges",),
        require_complete_negotiated=True,
    )
    if total_charges is None:
        return None

    service = _as_mapping(rated.get("Service")) or {}
    service_code = _clean_string(service.get("Code"))
    if require_service_code and service_code is None:
        return None

    normalized: dict[str, Any] = {}
    if service_code is not None:
        normalized["serviceCode"] = service_code
    description = _clean_string(service.get("Description"))
    if description is not None:
        normalized["serviceDescription"] = description
    normalized["totalCharges"] = total_charges
    return normalized


def _extract_total_charge(
    container: Mapping[str, Any],
    *,
    negotiated_path: tuple[str, str],
    standard_path: tuple[str, ...],
    require_complete_negotiated: bool = False,
) -> dict[str, str] | None:
    if negotiated_path[0] in container:
        negotiated_parent = _as_mapping(container.get(negotiated_path[0]))
        if negotiated_parent is None:
            if require_complete_negotiated:
                raise ShipAgentNormalizationError("invalid negotiated charges")
            negotiated_parent = None
    else:
        negotiated_parent = None

    if negotiated_parent is not None:
        negotiated_charge = _as_mapping(negotiated_parent.get(negotiated_path[1]))
        normalized = _normalize_charge(negotiated_charge)
        if normalized is not None:
            return normalized
        if require_complete_negotiated:
            raise ShipAgentNormalizationError("missing negotiated totalCharges")

    current: Any = container
    for key in standard_path:
        mapping = _as_mapping(current)
        if mapping is None:
            return None
        current = mapping.get(key)
    return _normalize_charge(_as_mapping(current))


def _normalize_charge(charge: Mapping[str, Any] | None) -> dict[str, str] | None:
    if charge is None:
        return None
    currency_code = _clean_string(charge.get("CurrencyCode"))
    monetary_value = _clean_string(charge.get("MonetaryValue"))
    if currency_code is None or monetary_value is None:
        return None
    if not _is_currency_code(currency_code):
        return None
    # Preserve UPS monetary formatting as a string; callers can parse with Decimal.
    return {"monetaryValue": monetary_value, "currencyCode": currency_code}


def _is_currency_code(value: str) -> bool:
    return len(value) == 3 and all("A" <= char <= "Z" for char in value)
```

- [ ] **Step 4: Run focused normalization tests**

Run:

```bash
python3 -m pytest tests/test_shipagent_normalization.py::ShipAgentRateNormalizationTests -q
```

Expected: PASS.

- [ ] **Step 5: Run all current normalization tests**

Run:

```bash
python3 -m pytest tests/test_shipagent_normalization.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add ups_mcp/shipagent_normalization.py tests/test_shipagent_normalization.py
git commit -m "feat: normalize shipagent rate responses"
```

### Task 3: Hosted Address Validation Normalization

**Files:**
- Modify: `ups_mcp/shipagent_normalization.py`
- Modify: `tests/test_shipagent_normalization.py`

- [ ] **Step 1: Add failing address-normalization tests**

Append this import near the existing normalization import block:

```python
from ups_mcp.shipagent_normalization import normalize_address_result
```

Append this test class before the `if __name__ == "__main__":` block:

```python
class ShipAgentAddressNormalizationTests(unittest.TestCase):
    def test_address_valid_status_and_object_candidate_safe_fields(self) -> None:
        raw = {
            "XAVResponse": {
                "ValidAddressIndicator": "",
                "Candidate": {
                    "AddressKeyFormat": {
                        "AddressLine": "123 MAIN ST",
                        "PoliticalDivision2": "ATLANTA",
                        "PoliticalDivision1": "GA",
                        "PostcodePrimaryLow": "30301",
                        "PostcodeExtendedLow": "1234",
                        "CountryCode": "US",
                        "ConsigneeName": "Unsafe Name",
                        "AddressClassification": {"Code": "2", "Description": "Commercial"},
                    }
                },
            }
        }

        result = normalize_address_result(raw, "corr_address_valid")

        self.assertEqual(result, {
            "success": True,
            "correlationId": "corr_address_valid",
            "status": "valid",
            "candidates": [
                {
                    "addressLines": ["123 MAIN ST"],
                    "city": "ATLANTA",
                    "stateProvince": "GA",
                    "postalCode": "30301",
                    "postalCodeExtended": "1234",
                    "countryCode": "US",
                }
            ],
        })
        self.assertNotIn("correlation_id", result)
        self.assertNotIn("contractVersion", result)
        self.assertNotIn("contract_version", result)
        self.assertNotIn("Unsafe Name", json.dumps(result))
        self.assertNotIn("AddressClassification", json.dumps(result))
        self.assertNotIn("Commercial", json.dumps(result))

    def test_address_ambiguous_status_and_list_candidates(self) -> None:
        raw = {
            "XAVResponse": {
                "AmbiguousAddressIndicator": "",
                "Candidate": [
                    {"AddressKeyFormat": {"AddressLine": ["123 MAIN ST", "STE 1"], "CountryCode": "US"}},
                    {"AddressKeyFormat": {"ConsigneeName": "Unsafe Name", "AddressClassification": {"Code": "2"}}},
                    {"AddressLine": ["125 MAIN ST"], "PoliticalDivision1": "GA", "CountryCode": "US"},
                ],
            }
        }

        result = normalize_address_result(raw, "corr_address_ambiguous")

        self.assertEqual(result["status"], "ambiguous")
        self.assertEqual(result["correlationId"], "corr_address_ambiguous")
        self.assertEqual(result["candidates"], [
            {"addressLines": ["123 MAIN ST", "STE 1"], "countryCode": "US"},
            {"addressLines": ["125 MAIN ST"], "stateProvince": "GA", "countryCode": "US"},
        ])
        self.assertNotIn({}, result["candidates"])
        self.assertNotIn("AddressClassification", json.dumps(result))

    def test_address_rejects_ascii_control_characters_in_candidate_fields(self) -> None:
        cases = [
            {"AddressLine": "123\nMAIN ST", "CountryCode": "US"},
            {"PoliticalDivision2": "ATLANTA\t", "PostcodePrimaryLow": "30301", "CountryCode": "US"},
            {"PoliticalDivision1": f"G{chr(127)}A", "PostcodePrimaryLow": "30301", "CountryCode": "US"},
            {"PostcodePrimaryLow": "30301\x00", "CountryCode": "US"},
        ]

        for address_key_format in cases:
            with self.subTest(address_key_format=address_key_format):
                raw = {
                    "XAVResponse": {
                        "ValidAddressIndicator": "",
                        "Candidate": {"AddressKeyFormat": address_key_format},
                    }
                }
                with self.assertRaises(ShipAgentNormalizationError):
                    normalize_address_result(raw, "corr_address_control")

    def test_address_rejects_non_string_candidate_fields(self) -> None:
        cases = [
            {"AddressLine": 123, "CountryCode": "US"},
            {"PoliticalDivision2": True, "PostcodePrimaryLow": "30301", "CountryCode": "US"},
            {"PoliticalDivision1": ["GA"], "PostcodePrimaryLow": "30301", "CountryCode": "US"},
            {"PostcodePrimaryLow": {"zip": "30301"}, "CountryCode": "US"},
        ]

        for address_key_format in cases:
            with self.subTest(address_key_format=address_key_format):
                raw = {
                    "XAVResponse": {
                        "ValidAddressIndicator": "",
                        "Candidate": {"AddressKeyFormat": address_key_format},
                    }
                }
                with self.assertRaises(ShipAgentNormalizationError):
                    normalize_address_result(raw, "corr_address_non_string")

    def test_address_invalid_unknown_and_empty_candidate_results_are_successful_domain_results(self) -> None:
        invalid = normalize_address_result({"XAVResponse": {"NoCandidatesIndicator": ""}}, "corr_address_invalid")
        unknown = normalize_address_result(
            {"XAVResponse": {"Response": {"ResponseStatus": {"Code": "1"}}}},
            "corr_address_unknown",
        )

        self.assertEqual(invalid, {
            "success": True,
            "correlationId": "corr_address_invalid",
            "status": "invalid",
            "candidates": [],
        })
        self.assertEqual(unknown, {
            "success": True,
            "correlationId": "corr_address_unknown",
            "status": "unknown",
            "candidates": [],
        })

    def test_address_valid_and_ambiguous_require_at_least_one_hosted_candidate(self) -> None:
        cases = [
            {
                "XAVResponse": {
                    "ValidAddressIndicator": "",
                    "Candidate": {"AddressKeyFormat": {"AddressClassification": {"Code": "2"}}},
                }
            },
            {
                "XAVResponse": {
                    "AmbiguousAddressIndicator": "",
                    "Candidate": [{"AddressKeyFormat": {"ConsigneeName": "Unsafe Name"}}],
                }
            },
            {
                "XAVResponse": {
                    "ValidAddressIndicator": "",
                    "Candidate": {"AddressKeyFormat": {"CountryCode": "US"}},
                }
            },
            {
                "XAVResponse": {
                    "AmbiguousAddressIndicator": "",
                    "Candidate": [{"AddressKeyFormat": {"CountryCode": "US"}}],
                }
            },
        ]

        for raw in cases:
            with self.subTest(raw=raw):
                with self.assertRaises(ShipAgentNormalizationError):
                    normalize_address_result(raw, "corr_address_empty_candidates")

    def test_address_invalid_and_unknown_reject_candidate_data(self) -> None:
        cases = [
            {
                "XAVResponse": {
                    "NoCandidatesIndicator": "",
                    "Candidate": {
                        "AddressKeyFormat": {"AddressLine": "123 MAIN ST", "CountryCode": "US"}
                    },
                }
            },
            {
                "XAVResponse": {
                    "Response": {"ResponseStatus": {"Code": "1"}},
                    "Candidate": {
                        "AddressKeyFormat": {"AddressLine": "123 MAIN ST", "CountryCode": "US"}
                    },
                }
            },
            {
                "XAVResponse": {
                    "NoCandidatesIndicator": "",
                    "Candidate": {"AddressKeyFormat": {"CountryCode": "US"}},
                }
            },
            {
                "XAVResponse": {
                    "Response": {"ResponseStatus": {"Code": "1"}},
                    "Candidate": {"AddressKeyFormat": {"AddressClassification": {"Code": "2"}}},
                }
            },
        ]

        for raw in cases:
            with self.subTest(raw=raw):
                with self.assertRaises(ShipAgentNormalizationError):
                    normalize_address_result(raw, "corr_address_unexpected_candidates")

    def test_address_conflicting_status_indicators_raise_normalization_error(self) -> None:
        cases = [
            {"XAVResponse": {"ValidAddressIndicator": "", "NoCandidatesIndicator": ""}},
            {"XAVResponse": {"ValidAddressIndicator": "", "AmbiguousAddressIndicator": ""}},
            {"XAVResponse": {"AmbiguousAddressIndicator": "", "NoCandidatesIndicator": ""}},
        ]

        for raw in cases:
            with self.subTest(raw=raw):
                with self.assertRaises(ShipAgentNormalizationError):
                    normalize_address_result(raw, "corr_address_conflicting_status")

    def test_address_missing_xav_response_raises_normalization_error(self) -> None:
        for raw in ({}, {"XAVResponse": []}, {"AddressValidationResponse": {}}):
            with self.subTest(raw=raw):
                with self.assertRaises(ShipAgentNormalizationError):
                    normalize_address_result(raw, "corr_address_missing")
```

- [ ] **Step 2: Run address tests to verify they fail**

Run:

```bash
python3 -m pytest tests/test_shipagent_normalization.py::ShipAgentAddressNormalizationTests -q
```

Expected: FAIL with `ImportError` for `normalize_address_result`.

- [ ] **Step 3: Add address normalization code**

Append this code to `ups_mcp/shipagent_normalization.py`:

```python
def normalize_address_result(raw: Mapping[str, Any], correlation_id: str) -> dict[str, Any]:
    xav_response = _as_mapping(raw.get("XAVResponse"))
    if xav_response is None:
        raise ShipAgentNormalizationError("missing XAVResponse")

    status = _address_status(xav_response)
    has_raw_candidates = bool(_as_list(xav_response.get("Candidate")))
    if status in {"invalid", "unknown"} and has_raw_candidates:
        raise ShipAgentNormalizationError("unexpected address candidates")

    candidates = _normalize_address_candidates(xav_response.get("Candidate"))
    if status in {"valid", "ambiguous"} and not candidates:
        raise ShipAgentNormalizationError("missing address candidates")

    return {
        "success": True,
        "correlationId": correlation_id,
        "status": status,
        "candidates": candidates,
    }


def _address_status(xav_response: Mapping[str, Any]) -> str:
    indicators = {
        "ValidAddressIndicator": "valid",
        "AmbiguousAddressIndicator": "ambiguous",
        "NoCandidatesIndicator": "invalid",
    }
    matched = [status for indicator, status in indicators.items() if indicator in xav_response]
    if len(matched) > 1:
        raise ShipAgentNormalizationError("conflicting address status indicators")
    if matched:
        return matched[0]
    return "unknown"


def _normalize_address_candidates(candidate_value: Any) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for candidate in _as_list(candidate_value):
        candidate_mapping = _as_mapping(candidate)
        if candidate_mapping is None:
            continue
        address_key_format = _as_mapping(candidate_mapping.get("AddressKeyFormat")) or candidate_mapping
        normalized = _normalize_address_candidate(address_key_format)
        # Drop candidates that contain only metadata, countryCode, or unsupported fields.
        if _has_substantive_address_candidate_field(normalized):
            candidates.append(normalized)
    return candidates


def _normalize_address_candidate(address: Mapping[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    address_lines = _normalize_address_lines(address.get("AddressLine"))
    if address_lines:
        normalized["addressLines"] = address_lines
    # Hosted-v1 candidates intentionally include address fields only.
    field_map = {
        "PoliticalDivision2": "city",
        "PoliticalDivision1": "stateProvince",
        "PostcodePrimaryLow": "postalCode",
        "PostcodeExtendedLow": "postalCodeExtended",
        "CountryCode": "countryCode",
    }
    for ups_key, hosted_key in field_map.items():
        value = _clean_string(address.get(ups_key))
        if value is not None:
            normalized[hosted_key] = value
    return normalized


def _has_substantive_address_candidate_field(candidate: Mapping[str, Any]) -> bool:
    return any(
        key in candidate
        for key in ("addressLines", "city", "stateProvince", "postalCode", "postalCodeExtended")
    )


def _normalize_address_lines(value: Any) -> list[str]:
    lines: list[str] = []
    for item in _as_list(value):
        cleaned = _clean_string(item)
        if cleaned is not None:
            lines.append(cleaned)
    return lines
```

- [ ] **Step 4: Run focused address tests**

Run:

```bash
python3 -m pytest tests/test_shipagent_normalization.py::ShipAgentAddressNormalizationTests -q
```

Expected: PASS.

- [ ] **Step 5: Run all normalization tests**

Run:

```bash
python3 -m pytest tests/test_shipagent_normalization.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add ups_mcp/shipagent_normalization.py tests/test_shipagent_normalization.py
git commit -m "feat: normalize shipagent address responses"
```

### Task 4: Hosted Shipment Creation Normalization

**Files:**
- Modify: `ups_mcp/shipagent_normalization.py`
- Modify: `tests/test_shipagent_normalization.py`

- [ ] **Step 1: Add failing shipment-normalization tests**

Append this import near the existing normalization import block:

```python
from ups_mcp.shipagent_normalization import normalize_create_shipment_result
```

Append this test class before the `if __name__ == "__main__":` block:

```python
class ShipAgentShipmentNormalizationTests(unittest.TestCase):
    def test_create_shipment_extracts_safe_fields_label_base64_and_negotiated_total(self) -> None:
        raw = {
            "ShipmentResponse": {
                "ShipmentResults": {
                    "ShipmentIdentificationNumber": "1ZSHIP",
                    "NegotiatedRateCharges": {
                        "TotalCharge": {"CurrencyCode": "USD", "MonetaryValue": "15.00"}
                    },
                    "ShipmentCharges": {
                        "TotalCharges": {"CurrencyCode": "USD", "MonetaryValue": "20.00"}
                    },
                    "PackageResults": [
                        {
                            "TrackingNumber": "1ZTRACK1",
                            "ShippingLabel": {
                                "ImageFormat": {"Code": "zpl"},
                                "GraphicImage": "QkFTRTY0UERG",
                                "HTMLImage": "<html>unsafe</html>",
                                "URL": "https://unsafe.example/label",
                            },
                        }
                    ],
                    "BillingWeight": {"Weight": "5"},
                    "FRSShipmentData": {"Unsafe": True},
                }
            }
        }

        result = normalize_create_shipment_result(raw, "idem-123", "corr_create_safe")

        self.assertEqual(result, {
            "success": True,
            "correlationId": "corr_create_safe",
            "idempotencyKey": "idem-123",
            "shipmentIdentificationNumber": "1ZSHIP",
            "trackingNumbers": ["1ZTRACK1"],
            "totalCharges": {"monetaryValue": "15.00", "currencyCode": "USD"},
            "labelData": [
                {
                    "trackingNumber": "1ZTRACK1",
                    "format": "ZPL",
                    "encoding": "base64",
                    "contentBase64": "QkFTRTY0UERG",
                }
            ],
        })
        self.assertNotIn("correlation_id", result)
        self.assertNotIn("contractVersion", result)
        self.assertNotIn("contract_version", result)
        serialized = json.dumps(result)
        self.assertIn("contentBase64", serialized)
        self.assertIn("QkFTRTY0UERG", serialized)
        self.assertNotIn("HTMLImage", serialized)
        self.assertNotIn("URL", serialized)
        self.assertNotIn("BillingWeight", serialized)
        self.assertNotIn("FRSShipmentData", serialized)

    def test_create_shipment_accepts_object_package_results_and_uses_standard_total_when_negotiated_absent(self) -> None:
        raw = {
            "ShipmentResponse": {
                "ShipmentResults": {
                    "ShipmentIdentificationNumber": "1ZSHIP",
                    "ShipmentCharges": {
                        "TotalCharges": {"CurrencyCode": "USD", "MonetaryValue": "20.00"}
                    },
                    "PackageResults": {
                        "TrackingNumber": "1ZTRACK1",
                        "ShippingLabel": {
                            "ImageFormat": {"Code": "gif"},
                            "GraphicImage": "QkFTRTY0R0lG",
                        },
                    },
                }
            }
        }

        result = normalize_create_shipment_result(raw, "idem-456", "corr_create_object")

        self.assertEqual(result["correlationId"], "corr_create_object")
        self.assertEqual(result["trackingNumbers"], ["1ZTRACK1"])
        self.assertEqual(result["totalCharges"], {"monetaryValue": "20.00", "currencyCode": "USD"})
        self.assertIsInstance(result["totalCharges"]["monetaryValue"], str)
        self.assertEqual(result["labelData"], [
            {
                "trackingNumber": "1ZTRACK1",
                "format": "GIF",
                "encoding": "base64",
                "contentBase64": "QkFTRTY0R0lG",
            }
        ])

    def test_create_shipment_rejects_malformed_currency_code(self) -> None:
        valid_package = {
            "TrackingNumber": "1ZTRACK1",
            "ShippingLabel": {"ImageFormat": {"Code": "ZPL"}, "GraphicImage": "QkFTRTY0UERG"},
        }
        bad_currency_codes = ("usd", "US", "US1", "US$", "\u00d8SD", "", "   ")

        for currency_code in bad_currency_codes:
            with self.subTest(currency_code=currency_code):
                raw = {
                    "ShipmentResponse": {
                        "ShipmentResults": {
                            "ShipmentIdentificationNumber": "1ZSHIP",
                            "ShipmentCharges": {
                                "TotalCharges": {
                                    "CurrencyCode": currency_code,
                                    "MonetaryValue": "20.00",
                                }
                            },
                            "PackageResults": valid_package,
                        }
                    }
                }
                with self.assertRaises(ShipAgentNormalizationError):
                    normalize_create_shipment_result(raw, "idem-bad-currency", "corr_create_bad_currency")

    def test_create_shipment_rejects_ascii_control_characters_in_success_strings(self) -> None:
        valid_package = {
            "TrackingNumber": "1ZTRACK1",
            "ShippingLabel": {"ImageFormat": {"Code": "ZPL"}, "GraphicImage": "QkFTRTY0UERG"},
        }
        valid_results = {
            "ShipmentIdentificationNumber": "1ZSHIP",
            "ShipmentCharges": {"TotalCharges": {"CurrencyCode": "USD", "MonetaryValue": "20.00"}},
            "PackageResults": valid_package,
        }
        cases = [
            {**valid_results, "ShipmentIdentificationNumber": "1Z\nSHIP"},
            {**valid_results, "ShipmentCharges": {"TotalCharges": {"CurrencyCode": "USD", "MonetaryValue": "20.00\t"}}},
            {**valid_results, "PackageResults": {**valid_package, "TrackingNumber": "1Z\x00TRACK1"}},
            {**valid_results, "PackageResults": {**valid_package, "ShippingLabel": {"ImageFormat": {"Code": f"ZP{chr(127)}"}, "GraphicImage": "QkFTRTY0UERG"}}},
        ]

        for shipment_results in cases:
            with self.subTest(shipment_results=shipment_results):
                raw = {"ShipmentResponse": {"ShipmentResults": shipment_results}}
                with self.assertRaises(ShipAgentNormalizationError):
                    normalize_create_shipment_result(raw, "idem-control", "corr_create_control")

    def test_create_shipment_rejects_non_string_success_fields(self) -> None:
        valid_package = {
            "TrackingNumber": "1ZTRACK1",
            "ShippingLabel": {"ImageFormat": {"Code": "ZPL"}, "GraphicImage": "QkFTRTY0UERG"},
        }
        valid_results = {
            "ShipmentIdentificationNumber": "1ZSHIP",
            "ShipmentCharges": {"TotalCharges": {"CurrencyCode": "USD", "MonetaryValue": "20.00"}},
            "PackageResults": valid_package,
        }
        cases = [
            {**valid_results, "ShipmentIdentificationNumber": 123},
            {**valid_results, "ShipmentCharges": {"TotalCharges": {"CurrencyCode": "USD", "MonetaryValue": 20}}},
            {**valid_results, "PackageResults": {**valid_package, "TrackingNumber": True}},
            {**valid_results, "PackageResults": {**valid_package, "ShippingLabel": {"ImageFormat": {"Code": ["ZPL"]}, "GraphicImage": "QkFTRTY0UERG"}}},
            {**valid_results, "PackageResults": {**valid_package, "ShippingLabel": {"ImageFormat": {"Code": "ZPL"}, "GraphicImage": {"base64": "QkFTRTY0UERG"}}}},
        ]

        for shipment_results in cases:
            with self.subTest(shipment_results=shipment_results):
                raw = {"ShipmentResponse": {"ShipmentResults": shipment_results}}
                with self.assertRaises(ShipAgentNormalizationError):
                    normalize_create_shipment_result(raw, "idem-non-string", "corr_create_non_string")

    def test_create_shipment_rejects_incomplete_negotiated_total_without_standard_fallback(self) -> None:
        complete_standard = {"CurrencyCode": "USD", "MonetaryValue": "20.00"}
        valid_package = {
            "TrackingNumber": "1ZTRACK1",
            "ShippingLabel": {"ImageFormat": {"Code": "ZPL"}, "GraphicImage": "QkFTRTY0UERG"},
        }
        cases = [
            {"NegotiatedRateCharges": {"TotalCharge": {"CurrencyCode": "USD"}}},
            {"NegotiatedRateCharges": {"TotalCharge": {"MonetaryValue": "15.00"}}},
            {"NegotiatedRateCharges": {"TotalCharge": {}}},
            {"NegotiatedRateCharges": {}},
        ]

        for partial_negotiated in cases:
            with self.subTest(partial_negotiated=partial_negotiated):
                raw = {
                    "ShipmentResponse": {
                        "ShipmentResults": {
                            "ShipmentIdentificationNumber": "1ZSHIP",
                            "ShipmentCharges": {"TotalCharges": complete_standard},
                            "PackageResults": valid_package,
                            **partial_negotiated,
                        }
                    }
                }
                with self.assertRaises(ShipAgentNormalizationError):
                    normalize_create_shipment_result(raw, "idem-bad-negotiated", "corr_create_bad_negotiated")

    def test_create_shipment_label_data_includes_tracking_number_for_each_package(self) -> None:
        raw = {
            "ShipmentResponse": {
                "ShipmentResults": {
                    "ShipmentIdentificationNumber": "1ZSHIP",
                    "ShipmentCharges": {
                        "TotalCharges": {"CurrencyCode": "USD", "MonetaryValue": "20.00"}
                    },
                    "PackageResults": [
                        {
                            "TrackingNumber": "1ZTRACK1",
                            "ShippingLabel": {
                                "ImageFormat": {"Code": "zpl"},
                                "GraphicImage": "QkFTRTY0UERGMA==",
                            },
                        },
                        {
                            "TrackingNumber": "1ZTRACK2",
                            "ShippingLabel": {
                                "ImageFormat": {"Code": "gif"},
                                "GraphicImage": "QkFTRTY0R0lGMg==",
                            },
                        },
                    ],
                }
            }
        }

        result = normalize_create_shipment_result(raw, "idem-multi", "corr_multi")

        self.assertEqual(result["trackingNumbers"], ["1ZTRACK1", "1ZTRACK2"])
        self.assertEqual(result["labelData"], [
            {
                "trackingNumber": "1ZTRACK1",
                "format": "ZPL",
                "encoding": "base64",
                "contentBase64": "QkFTRTY0UERGMA==",
            },
            {
                "trackingNumber": "1ZTRACK2",
                "format": "GIF",
                "encoding": "base64",
                "contentBase64": "QkFTRTY0R0lGMg==",
            },
        ])

    def test_create_shipment_rejects_invalid_label_base64(self) -> None:
        bad_images = (
            "not-base64!",
            "QkFTRTY0 UERG",
            "QkFTRTY0\nUERG",
            " QkFTRTY0UERG",
            "QkFTRTY0UERG\n",
        )

        for graphic_image in bad_images:
            with self.subTest(graphic_image=repr(graphic_image)):
                raw = {
                    "ShipmentResponse": {
                        "ShipmentResults": {
                            "ShipmentIdentificationNumber": "1ZSHIP",
                            "ShipmentCharges": {
                                "TotalCharges": {"CurrencyCode": "USD", "MonetaryValue": "20.00"}
                            },
                            "PackageResults": {
                                "TrackingNumber": "1ZTRACK1",
                                "ShippingLabel": {
                                    "ImageFormat": {"Code": "ZPL"},
                                    "GraphicImage": graphic_image,
                                },
                            },
                        }
                    }
                }

                with self.assertRaises(ShipAgentNormalizationError):
                    normalize_create_shipment_result(raw, "idem-bad-label", "corr_create_bad_label")

    def test_create_shipment_rejects_unsupported_create_label_formats(self) -> None:
        unsupported_formats = ("PDF", "PNG", "HTML", "JPG")

        for format_code in unsupported_formats:
            with self.subTest(format_code=format_code):
                raw = {
                    "ShipmentResponse": {
                        "ShipmentResults": {
                            "ShipmentIdentificationNumber": "1ZSHIP",
                            "ShipmentCharges": {
                                "TotalCharges": {"CurrencyCode": "USD", "MonetaryValue": "20.00"}
                            },
                            "PackageResults": {
                                "TrackingNumber": "1ZTRACK1",
                                "ShippingLabel": {
                                    "ImageFormat": {"Code": format_code},
                                    "GraphicImage": "QkFTRTY0UERG",
                                },
                            },
                        }
                    }
                }

                with self.assertRaises(ShipAgentNormalizationError):
                    normalize_create_shipment_result(raw, "idem-bad-format", "corr_create_bad_format")

    def test_create_shipment_requires_required_hosted_fields(self) -> None:
        valid_package = {
            "TrackingNumber": "1ZTRACK1",
            "ShippingLabel": {"ImageFormat": {"Code": "ZPL"}, "GraphicImage": "QkFTRTY0UERG"},
        }
        valid_results = {
            "ShipmentIdentificationNumber": "1ZSHIP",
            "ShipmentCharges": {"TotalCharges": {"CurrencyCode": "USD", "MonetaryValue": "20.00"}},
            "PackageResults": valid_package,
        }
        cases = [
            {},
            {"ShipmentResponse": {"ShipmentResults": {}}},
            {"ShipmentResponse": {"ShipmentResults": {**valid_results, "ShipmentIdentificationNumber": ""}}},
            {"ShipmentResponse": {"ShipmentResults": {**valid_results, "ShipmentCharges": {}}}},
            {"ShipmentResponse": {"ShipmentResults": {**valid_results, "PackageResults": []}}},
            {"ShipmentResponse": {"ShipmentResults": {**valid_results, "PackageResults": {"ShippingLabel": {"ImageFormat": {"Code": "ZPL"}, "GraphicImage": "QkFTRTY0UERG"}}}}},
            {"ShipmentResponse": {"ShipmentResults": {**valid_results, "PackageResults": {"TrackingNumber": "1ZTRACK1", "ShippingLabel": {"GraphicImage": "QkFTRTY0UERG"}}}}},
            {"ShipmentResponse": {"ShipmentResults": {**valid_results, "PackageResults": {"TrackingNumber": "1ZTRACK1", "ShippingLabel": {"ImageFormat": {"Code": "ZPL"}}}}}},
            {"ShipmentResponse": {"ShipmentResults": {**valid_results, "PackageResults": [valid_package, {"ShippingLabel": {"ImageFormat": {"Code": "ZPL"}, "GraphicImage": "QkFTRTY0UERG"}}]}}},
            {"ShipmentResponse": {"ShipmentResults": {**valid_results, "PackageResults": [valid_package, {"TrackingNumber": "1ZTRACK2", "ShippingLabel": {"GraphicImage": "QkFTRTY0UERG"}}]}}},
            {"ShipmentResponse": {"ShipmentResults": {**valid_results, "PackageResults": [valid_package, {"TrackingNumber": "1ZTRACK2", "ShippingLabel": {"ImageFormat": {"Code": "ZPL"}}}]}}},
        ]

        for raw in cases:
            with self.subTest(raw=raw):
                with self.assertRaises(ShipAgentNormalizationError):
                    normalize_create_shipment_result(raw, "idem-required", "corr_create_missing")
```

- [ ] **Step 2: Run shipment tests to verify they fail**

Run:

```bash
python3 -m pytest tests/test_shipagent_normalization.py::ShipAgentShipmentNormalizationTests -q
```

Expected: FAIL with `ImportError` for `normalize_create_shipment_result`.

- [ ] **Step 3: Add shipment normalization code**

Append this code to `ups_mcp/shipagent_normalization.py`:

```python
def normalize_create_shipment_result(
    raw: Mapping[str, Any],
    idempotency_key: str,
    correlation_id: str,
) -> dict[str, Any]:
    shipment_response = _as_mapping(raw.get("ShipmentResponse"))
    shipment_results = _as_mapping(shipment_response.get("ShipmentResults")) if shipment_response else None
    if shipment_results is None:
        raise ShipAgentNormalizationError("missing ShipmentResults")

    shipment_id = _clean_string(shipment_results.get("ShipmentIdentificationNumber"))
    if shipment_id is None:
        raise ShipAgentNormalizationError("missing ShipmentIdentificationNumber")

    total_charges = _extract_total_charge(
        shipment_results,
        negotiated_path=("NegotiatedRateCharges", "TotalCharge"),
        standard_path=("ShipmentCharges", "TotalCharges"),
        require_complete_negotiated=True,
    )
    if total_charges is None:
        raise ShipAgentNormalizationError("missing shipment totalCharges")

    tracking_numbers: list[str] = []
    label_data: list[dict[str, str]] = []
    for package_result in _shipment_package_results(shipment_results):
        tracking_number = _clean_string(package_result.get("TrackingNumber"))
        if tracking_number is None:
            raise ShipAgentNormalizationError("missing package TrackingNumber")
        tracking_numbers.append(tracking_number)
        label_data.append(_normalize_shipping_label(package_result.get("ShippingLabel"), tracking_number))

    if not tracking_numbers:
        raise ShipAgentNormalizationError("missing trackingNumbers")
    if not label_data:
        raise ShipAgentNormalizationError("missing labelData")

    return {
        "success": True,
        "correlationId": correlation_id,
        "idempotencyKey": idempotency_key,
        "shipmentIdentificationNumber": shipment_id,
        "trackingNumbers": tracking_numbers,
        "totalCharges": total_charges,
        "labelData": label_data,
    }


def _shipment_package_results(shipment_results: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    package_results: list[Mapping[str, Any]] = []
    for value in _as_list(shipment_results.get("PackageResults")):
        package_result = _as_mapping(value)
        if package_result is None:
            raise ShipAgentNormalizationError("invalid PackageResults item")
        package_results.append(package_result)
    if not package_results:
        raise ShipAgentNormalizationError("missing PackageResults")
    return package_results


def _normalize_shipping_label(value: Any, tracking_number: str) -> dict[str, str]:
    label = _as_mapping(value)
    if label is None:
        raise ShipAgentNormalizationError("missing ShippingLabel")
    image_format = _as_mapping(label.get("ImageFormat"))
    format_code = _clean_string(image_format.get("Code")) if image_format else None
    graphic_image = _clean_string(label.get("GraphicImage"))
    if format_code is None or graphic_image is None:
        raise ShipAgentNormalizationError("missing label format or GraphicImage")
    normalized_format = format_code.upper()
    if normalized_format not in SUPPORTED_CREATE_LABEL_FORMATS:
        raise ShipAgentNormalizationError("unsupported ShippingLabel.ImageFormat.Code")
    if not _is_base64(graphic_image):
        raise ShipAgentNormalizationError("invalid GraphicImage base64")
    return {
        "trackingNumber": tracking_number,
        "format": normalized_format,
        "encoding": "base64",
        "contentBase64": graphic_image,
    }


def _is_base64(value: str) -> bool:
    try:
        base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        return False
    return True
```

- [ ] **Step 4: Run focused shipment tests**

Run:

```bash
python3 -m pytest tests/test_shipagent_normalization.py::ShipAgentShipmentNormalizationTests -q
```

Expected: PASS.

- [ ] **Step 5: Run all normalization tests**

Run:

```bash
python3 -m pytest tests/test_shipagent_normalization.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add ups_mcp/shipagent_normalization.py tests/test_shipagent_normalization.py
git commit -m "feat: normalize shipagent shipment responses"
```

### Task 5: Capability Tool And Hosted Rate Boundary

**Files:**
- Modify: `ups_mcp/server.py`
- Create: `tests/test_shipagent_server_hosted.py`

- [ ] **Step 1: Write failing server tests for capabilities and hosted rate**

Create `tests/test_shipagent_server_hosted.py` with:

```python
import json
import unittest
from unittest import mock

from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import (
    ClientCapabilities,
    ElicitationCapability,
    FormElicitationCapability,
    Implementation,
    InitializeRequestParams,
)

import ups_mcp.server as server
from tests.rating_fixtures import make_complete_rate_body


class HostedFakeToolManager:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.rate_response: dict = {
            "RateResponse": {
                "RatedShipment": {
                    "Service": {"Code": "03", "Description": "UPS Ground"},
                    "TotalCharges": {"CurrencyCode": "USD", "MonetaryValue": "12.34"},
                }
            }
        }
        self.rate_exc: BaseException | None = None

    def rate_shipment(self, **kwargs):
        self.calls.append(("rate_shipment", kwargs))
        if self.rate_exc is not None:
            raise self.rate_exc
        return self.rate_response

    def validate_address(self, **kwargs):
        self.calls.append(("validate_address", kwargs))
        return {"XAVResponse": {"ValidAddressIndicator": ""}}

    def create_shipment(self, **kwargs):
        self.calls.append(("create_shipment", kwargs))
        return {"ShipmentResponse": {"ShipmentResults": {}}}


class ShipAgentHostedServerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.original_tool_manager = server.tool_manager
        self.fake_tool_manager = HostedFakeToolManager()
        server.tool_manager = self.fake_tool_manager

    def tearDown(self) -> None:
        server.tool_manager = self.original_tool_manager

    def _make_form_capable_ctx(self):
        ctx = mock.MagicMock()
        ctx.request_context.session.client_params = InitializeRequestParams(
            protocolVersion="2025-03-26",
            capabilities=ClientCapabilities(
                elicitation=ElicitationCapability(form=FormElicitationCapability())
            ),
            clientInfo=Implementation(name="test", version="1.0"),
        )
        ctx.elicit = mock.AsyncMock(side_effect=AssertionError("hosted mode must not elicit"))
        return ctx

    async def test_shipagent_capabilities_returns_metadata_without_tool_manager(self) -> None:
        server.tool_manager = None

        with mock.patch("ups_mcp.server.metadata.version", return_value="1.1.0"):
            result = await server.shipagent_capabilities()

        self.assertEqual(
            set(result.keys()),
            {"contract_version", "server_version", "capabilities", "response_formats"},
        )
        self.assertEqual(result["contract_version"], "hosted-v1")
        self.assertEqual(result["server_version"], "1.1.0")
        self.assertNotIn("schema_hash", result)
        self.assertNotIn("schema_version", result)
        self.assertNotIn("retry_policy", result)
        self.assertIn("shipagent_v1", result["response_formats"])
        self.assertIn("safe_error_mapping", result["capabilities"])

    async def test_shipagent_capabilities_falls_back_to_unknown_version(self) -> None:
        server.tool_manager = None

        with mock.patch("ups_mcp.server.metadata.version", side_effect=RuntimeError("metadata unavailable")):
            result = await server.shipagent_capabilities()

        self.assertEqual(result["server_version"], "unknown")

    async def test_shipagent_capabilities_is_registered_as_mcp_tool(self) -> None:
        tools = await server.mcp.list_tools()
        names = {tool.name for tool in tools}

        self.assertIn("shipagent_capabilities", names)

    async def test_rate_raw_is_default_and_preserves_raw_response(self) -> None:
        result = await server.rate_shipment(
            requestoption="Rate",
            request_body=make_complete_rate_body(),
        )

        self.assertIn("RateResponse", result)
        call_args = self.fake_tool_manager.calls[0][1]
        self.assertIsNone(call_args["trans_id"])

    async def test_rate_invalid_response_format_raises_tool_error(self) -> None:
        for invalid_format in ("xml", "ShipAgent_V1", "RAW", "shipagent-v1"):
            with self.subTest(response_format=invalid_format):
                with self.assertRaises(ToolError) as ctx:
                    await server.rate_shipment(
                        requestoption="Rate",
                        request_body=make_complete_rate_body(),
                        response_format=invalid_format,
                    )

                payload = json.loads(str(ctx.exception))
                self.assertEqual(payload["code"], "INVALID_RESPONSE_FORMAT")
                self.assertEqual(payload["allowed"], ["raw", "shipagent_v1"])
        self.assertEqual(len(self.fake_tool_manager.calls), 0)

    async def test_rate_hosted_rejects_trans_id_control_chars_before_ups(self) -> None:
        bad_ids = {
            "newline": "corr\nbad",
            "carriage_return": "corr\rbad",
            "tab": "corr\tbad",
            "nul": "corr\x00bad",
            "del": f"corr{chr(127)}bad",
        }

        for name, trans_id in bad_ids.items():
            with self.subTest(name=name):
                result = await server.rate_shipment(
                    requestoption="Rate",
                    request_body=make_complete_rate_body(),
                    response_format="shipagent_v1",
                    trans_id=trans_id,
                )

                self.assertFalse(result["success"])
                self.assertEqual(result["error"]["code"], "UPS_VALIDATION_ERROR")
                self.assertEqual(result["error"]["category"], "validation")
                self.assertRegex(result["error"]["correlation_id"], r"^corr_[0-9a-f]{32}$")
        self.assertEqual(self.fake_tool_manager.calls, [])

    async def test_rate_hosted_quote_normalizes_and_uses_boundary_correlation_id(self) -> None:
        result = await server.rate_shipment(
            requestoption="Rate",
            request_body=make_complete_rate_body(),
            response_format="shipagent_v1",
            trans_id=" supplied-trans ",
        )

        self.assertEqual(result, {
            "success": True,
            "correlationId": "supplied-trans",
            "serviceCode": "03",
            "serviceDescription": "UPS Ground",
            "totalCharges": {"monetaryValue": "12.34", "currencyCode": "USD"},
        })
        self.assertNotIn("contractVersion", result)
        self.assertNotIn("contract_version", result)
        call_args = self.fake_tool_manager.calls[0][1]
        self.assertEqual(call_args["trans_id"], "supplied-trans")
        self.assertEqual(call_args["transaction_src"], "ups-mcp")

    async def test_rate_hosted_preserves_explicit_transaction_src(self) -> None:
        await server.rate_shipment(
            requestoption="Rate",
            request_body=make_complete_rate_body(),
            response_format="shipagent_v1",
            trans_id="corr_src",
            transaction_src="shipagent",
        )

        call_args = self.fake_tool_manager.calls[0][1]
        self.assertEqual(call_args["transaction_src"], "shipagent")

    async def test_rate_hosted_rejects_transaction_src_control_chars_before_ups(self) -> None:
        bad_sources = {
            "newline": "ship\nagent",
            "carriage_return": "ship\ragent",
            "tab": "ship\tagent",
            "nul": "ship\x00agent",
            "del": f"ship{chr(127)}agent",
        }

        for name, transaction_src in bad_sources.items():
            with self.subTest(name=name):
                result = await server.rate_shipment(
                    requestoption="Rate",
                    request_body=make_complete_rate_body(),
                    response_format="shipagent_v1",
                    trans_id="corr_tx_src",
                    transaction_src=transaction_src,
                )

                self.assertFalse(result["success"])
                self.assertEqual(result["error"]["code"], "UPS_VALIDATION_ERROR")
                self.assertEqual(result["error"]["category"], "validation")
                self.assertEqual(result["error"]["correlation_id"], "corr_tx_src")
        self.assertEqual(self.fake_tool_manager.calls, [])

    async def test_rate_hosted_shop_normalizes_shop_result(self) -> None:
        self.fake_tool_manager.rate_response = {
            "RateResponse": {
                "RatedShipment": [
                    {
                        "Service": {"Code": "03"},
                        "TotalCharges": {"CurrencyCode": "USD", "MonetaryValue": "12.34"},
                    }
                ]
            }
        }

        result = await server.rate_shipment(
            requestoption="Shop",
            request_body=make_complete_rate_body(),
            response_format="shipagent_v1",
            trans_id="corr_shop",
        )

        self.assertEqual(result, {
            "success": True,
            "correlationId": "corr_shop",
            "ratedShipments": [
                {
                    "serviceCode": "03",
                    "totalCharges": {"monetaryValue": "12.34", "currencyCode": "USD"},
                }
            ],
        })

    async def test_rate_hosted_tool_error_returns_safe_envelope(self) -> None:
        self.fake_tool_manager.rate_exc = ToolError(json.dumps({
            "status_code": 400,
            "code": "VALIDATION_ERROR",
            "message": "unsafe request body",
            "details": {"request_body": {"access_token": "secret"}},
        }))

        result = await server.rate_shipment(
            requestoption="Rate",
            request_body=make_complete_rate_body(),
            response_format="shipagent_v1",
            trans_id="corr_error",
        )

        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], "UPS_VALIDATION_ERROR")
        self.assertEqual(result["error"]["category"], "validation")
        self.assertEqual(result["error"]["correlation_id"], "corr_error")
        self.assertNotIn("request_body", json.dumps(result))
        self.assertNotIn("access_token", json.dumps(result))

    async def test_rate_hosted_unexpected_exception_returns_unknown_safe_envelope(self) -> None:
        self.fake_tool_manager.rate_exc = RuntimeError("stack path /tmp/secret traceback token")

        result = await server.rate_shipment(
            requestoption="Rate",
            request_body=make_complete_rate_body(),
            response_format="shipagent_v1",
            trans_id="corr_unknown",
        )

        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], "UPS_UNKNOWN_ERROR")
        self.assertEqual(result["error"]["category"], "unknown")
        self.assertFalse(result["error"]["retryable"])
        self.assertEqual(result["error"]["correlation_id"], "corr_unknown")
        serialized = json.dumps(result).lower()
        self.assertNotIn("traceback", serialized)
        self.assertNotIn("/tmp/secret", serialized)

    async def test_rate_raw_mode_still_raises_tool_error(self) -> None:
        self.fake_tool_manager.rate_exc = ToolError(json.dumps({"status_code": 400, "code": "VALIDATION_ERROR"}))

        with self.assertRaises(ToolError):
            await server.rate_shipment(
                requestoption="Rate",
                request_body=make_complete_rate_body(),
            )

    async def test_rate_hosted_normalization_failure_returns_normalization_error(self) -> None:
        self.fake_tool_manager.rate_response = {"RateResponse": {"RatedShipment": []}}

        result = await server.rate_shipment(
            requestoption="Rate",
            request_body=make_complete_rate_body(),
            response_format="shipagent_v1",
            trans_id="corr_normalization",
        )

        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], "UPS_NORMALIZATION_ERROR")
        self.assertEqual(result["error"]["category"], "normalization")
        self.assertEqual(result["error"]["correlation_id"], "corr_normalization")

    async def test_rate_hosted_generates_correlation_id_when_trans_id_missing(self) -> None:
        result = await server.rate_shipment(
            requestoption="Rate",
            request_body=make_complete_rate_body(),
            response_format="shipagent_v1",
        )

        self.assertTrue(result["success"])
        call_args = self.fake_tool_manager.calls[0][1]
        self.assertRegex(call_args["trans_id"], r"^corr_[0-9a-f]{32}$")
        self.assertEqual(result["correlationId"], call_args["trans_id"])

    async def test_rate_hosted_does_not_elicit_missing_fields(self) -> None:
        ctx = self._make_form_capable_ctx()

        result = await server.rate_shipment(
            requestoption="Rate",
            request_body={"RateRequest": {}},
            response_format="shipagent_v1",
            trans_id="corr_no_rate_elicit",
            ctx=ctx,
        )

        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], "UPS_VALIDATION_ERROR")
        self.assertEqual(result["error"]["category"], "validation")
        self.assertEqual(result["error"]["correlation_id"], "corr_no_rate_elicit")
        ctx.elicit.assert_not_awaited()
        self.assertEqual(self.fake_tool_manager.calls, [])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run server hosted tests to verify they fail**

Run:

```bash
python3 -m pytest tests/test_shipagent_server_hosted.py::ShipAgentHostedServerTests -q
```

Expected: FAIL because `server.shipagent_capabilities` does not exist and `rate_shipment` does not accept `response_format`.

- [ ] **Step 3: Add server imports and private helpers**

Modify the top of `ups_mcp/server.py`:

```python
from typing import Any, Literal
from importlib import metadata
from mcp.server.fastmcp import FastMCP, Context
from mcp.server.fastmcp.exceptions import ToolError
from dotenv import load_dotenv
import json
import os
import sys
import uuid
from . import tools
from . import constants
from .openapi_registry import OpenAPISpecLoadError
from .shipagent_normalization import (
    HOSTED_RESPONSE_FORMAT,
    RAW_RESPONSE_FORMAT,
    ShipAgentNormalizationError,
    build_shipagent_capabilities,
    normalize_rate_result,
    to_normalization_error,
    to_safe_error,
)
```

Add these helpers after `_require_tool_manager()`:

```python
ResponseFormat = Literal["raw", "shipagent_v1"]
MAX_IDEMPOTENCY_KEY_LENGTH = 512
MAX_CUSTOMER_CONTEXT_LENGTH = 512


def _validate_response_format(response_format: str) -> None:
    if response_format not in {RAW_RESPONSE_FORMAT, HOSTED_RESPONSE_FORMAT}:
        raise ToolError(json.dumps({
            "code": "INVALID_RESPONSE_FORMAT",
            "message": "response_format must exactly match 'raw' or 'shipagent_v1'. Values are case-sensitive.",
            "allowed": [RAW_RESPONSE_FORMAT, HOSTED_RESPONSE_FORMAT],
        }))


def _has_ascii_control(value: str) -> bool:
    return any(ord(char) < 32 or ord(char) == 127 for char in value)


def _is_ascii_country_code(value: str) -> bool:
    return len(value) == 2 and all("A" <= char <= "Z" for char in value)


def _hosted_validation_error(correlation_id: str, reason: str) -> dict[str, Any]:
    return to_safe_error(
        ToolError(json.dumps({
            "code": "VALIDATION_ERROR",
            "reason": reason,
        })),
        correlation_id,
    )


def _hosted_correlation_id(trans_id: str) -> tuple[str, dict[str, Any] | None]:
    supplied = trans_id.strip()
    if supplied and _has_ascii_control(supplied):
        correlation_id = f"corr_{uuid.uuid4().hex}"
        return correlation_id, _hosted_validation_error(correlation_id, "trans_id_control_character")
    # Generated hosted ids are prefixed so they are distinguishable in UPS logs.
    return supplied or f"corr_{uuid.uuid4().hex}", None


def _hosted_transaction_src_error(transaction_src: str, correlation_id: str) -> dict[str, Any] | None:
    if _has_ascii_control(transaction_src):
        return _hosted_validation_error(correlation_id, "transaction_src_control_character")
    return None


def _validate_hosted_customer_context(request_body: dict[str, Any]) -> None:
    shipment_request = request_body.get("ShipmentRequest")
    request = shipment_request.get("Request") if isinstance(shipment_request, dict) else None
    transaction_reference = request.get("TransactionReference") if isinstance(request, dict) else None
    if not isinstance(transaction_reference, dict) or "CustomerContext" not in transaction_reference:
        return

    customer_context = transaction_reference.get("CustomerContext")
    if not isinstance(customer_context, str):
        raise ToolError(json.dumps({
            "code": "VALIDATION_ERROR",
            "reason": "customer_context_not_string",
        }))
    if len(customer_context) > MAX_CUSTOMER_CONTEXT_LENGTH:
        raise ToolError(json.dumps({
            "code": "VALIDATION_ERROR",
            "reason": "customer_context_too_long",
        }))
    if _has_ascii_control(customer_context):
        raise ToolError(json.dumps({
            "code": "VALIDATION_ERROR",
            "reason": "customer_context_control_character",
        }))


def _installed_server_version() -> str:
    try:
        return metadata.version("ups-mcp")
    except Exception:
        return "unknown"
```

- [ ] **Step 4: Add the capabilities tool**

Insert this function before `track_package`:

```python
@mcp.tool()
async def shipagent_capabilities() -> dict[str, Any]:
    """
    Return ShipAgent hosted-v1 readiness metadata.

    This read-only tool does not call UPS, require credentials, initialize
    ToolManager, or inspect tenant state.
    """
    return build_shipagent_capabilities(_installed_server_version())
```

- [ ] **Step 5: Extract the current rate implementation into an internal raw helper**

Replace the current `rate_shipment` body with this public wrapper plus internal helper. Preserve the existing docstring text and add the `response_format` argument description to it.

```python
@mcp.tool()
async def rate_shipment(
    requestoption: str,
    request_body: dict[str, Any],
    version: str = "v2409",
    additionalinfo: str = "",
    trans_id: str = "",
    transaction_src: str = "ups-mcp",
    response_format: ResponseFormat = "raw",
    ctx: Context | None = None,
) -> dict[str, Any]:
    """
    Rate or shop a shipment using UPS Rating API (`POST /rating/{version}/{requestoption}`).

    response_format defaults to "raw" for existing clients. Use
    "shipagent_v1" for hosted-v1 normalized responses and safe error envelopes.
    """
    _validate_response_format(response_format)
    if response_format == RAW_RESPONSE_FORMAT:
        return await _rate_shipment_execute(
            requestoption=requestoption,
            request_body=request_body,
            version=version,
            additionalinfo=additionalinfo,
            trans_id=trans_id or None,
            transaction_src=transaction_src,
            ctx=ctx,
            allow_elicitation=True,
        )

    correlation_id, correlation_error = _hosted_correlation_id(trans_id)
    if correlation_error is not None:
        return correlation_error
    transaction_src_error = _hosted_transaction_src_error(transaction_src, correlation_id)
    if transaction_src_error is not None:
        return transaction_src_error

    try:
        raw_result = await _rate_shipment_execute(
            requestoption=requestoption,
            request_body=request_body,
            version=version,
            additionalinfo=additionalinfo,
            trans_id=correlation_id,
            transaction_src=transaction_src,
            ctx=None,
            allow_elicitation=False,
        )
        return normalize_rate_result(raw_result, requestoption, correlation_id)
    except ShipAgentNormalizationError:
        return to_normalization_error(correlation_id)
    except ToolError as exc:
        return to_safe_error(exc, correlation_id)
    except Exception as exc:
        return to_safe_error(exc, correlation_id)


async def _rate_shipment_execute(
    *,
    requestoption: str,
    request_body: dict[str, Any],
    version: str,
    additionalinfo: str,
    trans_id: str | None,
    transaction_src: str,
    ctx: Context | None,
    allow_elicitation: bool,
) -> dict[str, Any]:
    from .rating_validator import (
        apply_rate_defaults,
        find_missing_rate_fields,
        canonicalize_rate_body,
        remap_packaging_for_rating,
    )
    from .elicitation import elicit_and_rehydrate
    from .shipment_validator import AmbiguousPayerError

    def _send_to_ups(body: dict[str, Any]) -> dict[str, Any]:
        canonical = canonicalize_rate_body(body)
        api_body = remap_packaging_for_rating(canonical)
        return _require_tool_manager().rate_shipment(
            requestoption=requestoption,
            request_body=api_body,
            version=version,
            additionalinfo=additionalinfo or None,
            trans_id=trans_id,
            transaction_src=transaction_src,
        )

    env_config = {"UPS_ACCOUNT_NUMBER": os.getenv("UPS_ACCOUNT_NUMBER", "")}
    try:
        canonical_input = canonicalize_rate_body(request_body)
        merged_body = apply_rate_defaults(canonical_input, env_config)
    except TypeError as exc:
        raise ToolError(json.dumps({
            "code": "MALFORMED_REQUEST",
            "message": f"Request body has structural conflicts: {exc}",
            "reason": "malformed_structure",
            "missing": [],
        }))

    try:
        find_fn = lambda body: find_missing_rate_fields(body, requestoption)
        missing = find_fn(merged_body)
    except AmbiguousPayerError as exc:
        raise ToolError(json.dumps({
            "code": "MALFORMED_REQUEST",
            "message": str(exc),
            "reason": "ambiguous_payer",
            "missing": [],
        }))

    if not missing:
        return _send_to_ups(merged_body)
    if not allow_elicitation:
        raise ToolError(json.dumps({
            "code": "VALIDATION_ERROR",
            "reason": "missing_rate_required_fields",
            "missing": [field.flat_key for field in missing],
        }))

    merged_body = await elicit_and_rehydrate(
        ctx, merged_body, missing,
        find_missing_fn=find_fn,
        tool_label="rate request",
        canonicalize_fn=canonicalize_rate_body,
    )
    return _send_to_ups(merged_body)
```

- [ ] **Step 6: Run focused hosted rate tests**

Run:

```bash
python3 -m pytest tests/test_shipagent_server_hosted.py::ShipAgentHostedServerTests -q
```

Expected: PASS for capability and rate tests in this file. If later address/create tests have already been added by another worker, run the listed individual tests for this task only.

- [ ] **Step 7: Run existing rate server tests for raw compatibility**

Run:

```bash
python3 -m pytest tests/test_server_rate_elicitation.py tests/test_server_tools.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add ups_mcp/server.py tests/test_shipagent_server_hosted.py
git commit -m "feat: add shipagent capabilities and hosted rate boundary"
```

### Task 6: Hosted Address Boundary

**Files:**
- Modify: `ups_mcp/server.py`
- Modify: `tests/test_shipagent_server_hosted.py`

- [ ] **Step 1: Add failing hosted address boundary tests**

Append these tests to `ShipAgentHostedServerTests` in `tests/test_shipagent_server_hosted.py`:

```python
    async def test_validate_address_raw_is_default(self) -> None:
        result = await server.validate_address(
            addressLine1="123 Main St",
            politicalDivision1="GA",
            politicalDivision2="Atlanta",
            zipPrimary="30301",
            countryCode="US",
        )

        self.assertIn("XAVResponse", result)
        call_args = self.fake_tool_manager.calls[0][1]
        self.assertIsNone(call_args["trans_id"])

    async def test_validate_address_invalid_response_format_raises_tool_error(self) -> None:
        for invalid_format in ("xml", "ShipAgent_V1", "RAW", "shipagent-v1"):
            with self.subTest(response_format=invalid_format):
                with self.assertRaises(ToolError) as ctx:
                    await server.validate_address(
                        addressLine1="123 Main St",
                        politicalDivision1="GA",
                        politicalDivision2="Atlanta",
                        zipPrimary="30301",
                        countryCode="US",
                        response_format=invalid_format,
                    )

                payload = json.loads(str(ctx.exception))
                self.assertEqual(payload["code"], "INVALID_RESPONSE_FORMAT")
                self.assertEqual(payload["allowed"], ["raw", "shipagent_v1"])

    async def test_validate_address_hosted_rejects_trans_id_control_chars_before_ups(self) -> None:
        result = await server.validate_address(
            addressLine1="123 Main St",
            politicalDivision1="GA",
            politicalDivision2="Atlanta",
            zipPrimary="30301",
            countryCode="US",
            response_format="shipagent_v1",
            trans_id="corr\nbad",
        )

        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], "UPS_VALIDATION_ERROR")
        self.assertEqual(result["error"]["category"], "validation")
        self.assertRegex(result["error"]["correlation_id"], r"^corr_[0-9a-f]{32}$")
        self.assertEqual(self.fake_tool_manager.calls, [])

    async def test_validate_address_hosted_unsupported_country_precedes_blank_address_fields(self) -> None:
        result = await server.validate_address(
            addressLine1="",
            politicalDivision1="",
            politicalDivision2="London",
            zipPrimary="",
            countryCode="GB",
            response_format="shipagent_v1",
            trans_id="corr_address",
        )

        self.assertEqual(result, {
            "success": True,
            "correlationId": "corr_address",
            "status": "unsupported",
            "candidates": [],
        })
        self.assertNotIn("error", result)
        self.assertEqual(self.fake_tool_manager.calls, [])

    async def test_validate_address_hosted_blank_country_returns_validation_error_before_ups(self) -> None:
        for country_code in ("", "   "):
            with self.subTest(countryCode=country_code):
                result = await server.validate_address(
                    addressLine1="123 Main St",
                    politicalDivision1="GA",
                    politicalDivision2="Atlanta",
                    zipPrimary="30301",
                    countryCode=country_code,
                    response_format="shipagent_v1",
                    trans_id="corr_blank_country",
                )

                self.assertFalse(result["success"])
                self.assertEqual(result["error"]["code"], "UPS_VALIDATION_ERROR")
                self.assertEqual(result["error"]["category"], "validation")
                self.assertEqual(result["error"]["correlation_id"], "corr_blank_country")
        self.assertEqual(self.fake_tool_manager.calls, [])

    async def test_validate_address_hosted_malformed_country_returns_validation_error_before_ups(self) -> None:
        for country_code in ("USA", "U1", "U-", "\u00e9S"):
            with self.subTest(countryCode=country_code):
                result = await server.validate_address(
                    addressLine1="123 Main St",
                    politicalDivision1="GA",
                    politicalDivision2="Atlanta",
                    zipPrimary="30301",
                    countryCode=country_code,
                    response_format="shipagent_v1",
                    trans_id="corr_bad_country",
                )

                self.assertFalse(result["success"])
                self.assertEqual(result["error"]["code"], "UPS_VALIDATION_ERROR")
                self.assertEqual(result["error"]["category"], "validation")
                self.assertEqual(result["error"]["correlation_id"], "corr_bad_country")
        self.assertEqual(self.fake_tool_manager.calls, [])

    async def test_validate_address_hosted_blank_required_fields_return_validation_error_before_ups(self) -> None:
        valid_args = {
            "addressLine1": "123 Main St",
            "politicalDivision1": "GA",
            "politicalDivision2": "Atlanta",
            "zipPrimary": "30301",
            "countryCode": "US",
        }

        for field in ("addressLine1", "politicalDivision1", "politicalDivision2", "zipPrimary"):
            for blank_value in ("", "   "):
                with self.subTest(field=field, blank_value=repr(blank_value)):
                    args = {**valid_args, field: blank_value}
                    result = await server.validate_address(
                        **args,
                        response_format="shipagent_v1",
                        trans_id="corr_blank_address_field",
                    )

                    self.assertFalse(result["success"])
                    self.assertEqual(result["error"]["code"], "UPS_VALIDATION_ERROR")
                    self.assertEqual(result["error"]["category"], "validation")
                    self.assertEqual(result["error"]["correlation_id"], "corr_blank_address_field")
        self.assertEqual(self.fake_tool_manager.calls, [])

    async def test_validate_address_hosted_normalizes_us_result(self) -> None:
        self.fake_tool_manager.validate_address_response = {
            "XAVResponse": {
                "ValidAddressIndicator": "",
                "Candidate": {
                    "AddressKeyFormat": {
                        "AddressLine": ["123 MAIN ST"],
                        "PoliticalDivision2": "ATLANTA",
                        "PoliticalDivision1": "GA",
                        "PostcodePrimaryLow": "30301",
                        "CountryCode": "US",
                    }
                },
            }
        }

        result = await server.validate_address(
            addressLine1="123 Main St",
            politicalDivision1="GA",
            politicalDivision2="Atlanta",
            zipPrimary="30301",
            countryCode="us",
            response_format="shipagent_v1",
            trans_id="corr_address_valid",
        )

        self.assertEqual(result["status"], "valid")
        self.assertEqual(result["correlationId"], "corr_address_valid")
        self.assertNotIn("contractVersion", result)
        self.assertNotIn("contract_version", result)
        self.assertEqual(result["candidates"][0]["postalCode"], "30301")
        call_args = self.fake_tool_manager.calls[0][1]
        self.assertEqual(call_args["countryCode"], "us")
        self.assertEqual(call_args["trans_id"], "corr_address_valid")
        self.assertEqual(call_args["transaction_src"], "ups-mcp")

    async def test_validate_address_hosted_preserves_explicit_transaction_src(self) -> None:
        await server.validate_address(
            addressLine1="123 Main St",
            politicalDivision1="GA",
            politicalDivision2="Atlanta",
            zipPrimary="30301",
            countryCode="US",
            response_format="shipagent_v1",
            trans_id="corr_address_src",
            transaction_src="shipagent",
        )

        call_args = self.fake_tool_manager.calls[0][1]
        self.assertEqual(call_args["transaction_src"], "shipagent")

    async def test_validate_address_hosted_rejects_transaction_src_control_chars_before_ups(self) -> None:
        result = await server.validate_address(
            addressLine1="123 Main St",
            politicalDivision1="GA",
            politicalDivision2="Atlanta",
            zipPrimary="30301",
            countryCode="US",
            response_format="shipagent_v1",
            trans_id="corr_address_tx_src",
            transaction_src="ship\nagent",
        )

        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], "UPS_VALIDATION_ERROR")
        self.assertEqual(result["error"]["category"], "validation")
        self.assertEqual(result["error"]["correlation_id"], "corr_address_tx_src")
        self.assertEqual(self.fake_tool_manager.calls, [])

    async def test_validate_address_hosted_generates_correlation_id_when_trans_id_missing(self) -> None:
        result = await server.validate_address(
            addressLine1="123 Main St",
            politicalDivision1="GA",
            politicalDivision2="Atlanta",
            zipPrimary="30301",
            countryCode="US",
            response_format="shipagent_v1",
        )

        self.assertTrue(result["success"])
        call_args = self.fake_tool_manager.calls[0][1]
        self.assertRegex(call_args["trans_id"], r"^corr_[0-9a-f]{32}$")
        self.assertEqual(result["correlationId"], call_args["trans_id"])

    async def test_validate_address_hosted_safe_error_and_normalization_error(self) -> None:
        self.fake_tool_manager.validate_address_exc = ToolError(json.dumps({"status_code": 503, "code": "503"}))

        result = await server.validate_address(
            addressLine1="123 Main St",
            politicalDivision1="GA",
            politicalDivision2="Atlanta",
            zipPrimary="30301",
            countryCode="US",
            response_format="shipagent_v1",
            trans_id="corr_address_error",
        )

        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], "UPS_SERVICE_UNAVAILABLE")
        self.assertEqual(result["error"]["correlation_id"], "corr_address_error")

        self.fake_tool_manager.validate_address_exc = RuntimeError("stack path /tmp/address traceback token")
        unknown = await server.validate_address(
            addressLine1="123 Main St",
            politicalDivision1="GA",
            politicalDivision2="Atlanta",
            zipPrimary="30301",
            countryCode="US",
            response_format="shipagent_v1",
            trans_id="corr_address_unknown",
        )
        self.assertFalse(unknown["success"])
        self.assertEqual(unknown["error"]["code"], "UPS_UNKNOWN_ERROR")
        self.assertEqual(unknown["error"]["category"], "unknown")
        self.assertFalse(unknown["error"]["retryable"])
        self.assertEqual(unknown["error"]["correlation_id"], "corr_address_unknown")
        serialized = json.dumps(unknown).lower()
        self.assertNotIn("traceback", serialized)
        self.assertNotIn("/tmp/address", serialized)

        self.fake_tool_manager.validate_address_exc = None
        self.fake_tool_manager.validate_address_response = {"bad": "shape"}
        normalized = await server.validate_address(
            addressLine1="123 Main St",
            politicalDivision1="GA",
            politicalDivision2="Atlanta",
            zipPrimary="30301",
            countryCode="US",
            response_format="shipagent_v1",
            trans_id="corr_address_norm",
        )
        self.assertFalse(normalized["success"])
        self.assertEqual(normalized["error"]["code"], "UPS_NORMALIZATION_ERROR")
        self.assertEqual(normalized["error"]["category"], "normalization")

    async def test_create_shipment_hosted_does_not_elicit_missing_fields(self) -> None:
        ctx = self._make_form_capable_ctx()

        result = await server.create_shipment(
            request_body={"ShipmentRequest": {}},
            response_format="shipagent_v1",
            idempotency_key="idem-no-elicit",
            trans_id="corr_no_create_elicit",
            ctx=ctx,
        )

        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], "UPS_VALIDATION_ERROR")
        self.assertEqual(result["error"]["category"], "validation")
        self.assertEqual(result["error"]["correlation_id"], "corr_no_create_elicit")
        ctx.elicit.assert_not_awaited()
        self.assertEqual(self.fake_tool_manager.calls, [])
```

Update `HostedFakeToolManager` in the same file:

```python
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.rate_response: dict = {
            "RateResponse": {
                "RatedShipment": {
                    "Service": {"Code": "03", "Description": "UPS Ground"},
                    "TotalCharges": {"CurrencyCode": "USD", "MonetaryValue": "12.34"},
                }
            }
        }
        self.rate_exc: BaseException | None = None
        self.validate_address_response: dict = {
            "XAVResponse": {
                "ValidAddressIndicator": "",
                "Candidate": {
                    "AddressKeyFormat": {
                        "AddressLine": "123 MAIN ST",
                        "PoliticalDivision2": "ATLANTA",
                        "PoliticalDivision1": "GA",
                        "PostcodePrimaryLow": "30301",
                        "CountryCode": "US",
                    }
                },
            }
        }
        self.validate_address_exc: BaseException | None = None
```

Replace `validate_address` in `HostedFakeToolManager` with:

```python
    def validate_address(self, **kwargs):
        self.calls.append(("validate_address", kwargs))
        if self.validate_address_exc is not None:
            raise self.validate_address_exc
        return self.validate_address_response
```

- [ ] **Step 2: Run hosted address tests to verify they fail**

Run:

```bash
python3 -m pytest tests/test_shipagent_server_hosted.py::ShipAgentHostedServerTests -q
```

Expected: FAIL because `validate_address` does not accept `response_format`.

- [ ] **Step 3: Import address normalization in `server.py`**

Add `normalize_address_result` to the existing import from `.shipagent_normalization`:

```python
from .shipagent_normalization import (
    HOSTED_RESPONSE_FORMAT,
    RAW_RESPONSE_FORMAT,
    ShipAgentNormalizationError,
    build_shipagent_capabilities,
    normalize_address_result,
    normalize_rate_result,
    to_normalization_error,
    to_safe_error,
)
```

- [ ] **Step 4: Replace `validate_address` with hosted wrapper and raw helper**

Replace the current `validate_address` function with:

```python
@mcp.tool()
async def validate_address(
    addressLine1: str,
    politicalDivision1: str,
    politicalDivision2: str,
    zipPrimary: str,
    countryCode: str,
    addressLine2: str = "",
    urbanization: str = "",
    zipExtended: str = "",
    trans_id: str = "",
    transaction_src: str = "ups-mcp",
    response_format: ResponseFormat = "raw",
) -> dict[str, Any]:
    """
    Checks addresses against the United States Postal Service database of valid
    addresses in the U.S. and Puerto Rico.

    response_format defaults to "raw" for existing clients. Use
    "shipagent_v1" for hosted-v1 normalized responses and safe error envelopes.
    """
    _validate_response_format(response_format)
    if response_format == RAW_RESPONSE_FORMAT:
        return _validate_address_raw(
            addressLine1=addressLine1,
            addressLine2=addressLine2,
            politicalDivision1=politicalDivision1,
            politicalDivision2=politicalDivision2,
            zipPrimary=zipPrimary,
            zipExtended=zipExtended,
            urbanization=urbanization,
            countryCode=countryCode,
            trans_id=trans_id or None,
            transaction_src=transaction_src,
        )

    correlation_id, correlation_error = _hosted_correlation_id(trans_id)
    if correlation_error is not None:
        return correlation_error
    transaction_src_error = _hosted_transaction_src_error(transaction_src, correlation_id)
    if transaction_src_error is not None:
        return transaction_src_error

    # Use normalized country only for boundary decisions; pass caller countryCode to UPS unchanged.
    hosted_country_code = countryCode.strip().upper()
    if not hosted_country_code:
        return to_safe_error(
            ToolError(json.dumps({
                "code": "VALIDATION_ERROR",
                "reason": "missing_country_code",
            })),
            correlation_id,
        )
    if not _is_ascii_country_code(hosted_country_code):
        return _hosted_validation_error(correlation_id, "invalid_country_code")
    if hosted_country_code not in {"US", "PR"}:
        return {
            "success": True,
            "correlationId": correlation_id,
            "status": "unsupported",
            "candidates": [],
        }

    # Required address fields matter only when hosted mode would call UPS.
    required_fields = {
        "addressLine1": addressLine1,
        "politicalDivision1": politicalDivision1,
        "politicalDivision2": politicalDivision2,
        "zipPrimary": zipPrimary,
    }
    missing_fields = [name for name, value in required_fields.items() if not value.strip()]
    if missing_fields:
        return _hosted_validation_error(correlation_id, "missing_address_required_fields")

    try:
        raw_result = _validate_address_raw(
            addressLine1=addressLine1,
            addressLine2=addressLine2,
            politicalDivision1=politicalDivision1,
            politicalDivision2=politicalDivision2,
            zipPrimary=zipPrimary,
            zipExtended=zipExtended,
            urbanization=urbanization,
            countryCode=countryCode,
            trans_id=correlation_id,
            transaction_src=transaction_src,
        )
        return normalize_address_result(raw_result, correlation_id)
    except ShipAgentNormalizationError:
        return to_normalization_error(correlation_id)
    except ToolError as exc:
        return to_safe_error(exc, correlation_id)
    except Exception as exc:
        return to_safe_error(exc, correlation_id)


def _validate_address_raw(
    *,
    addressLine1: str,
    addressLine2: str,
    politicalDivision1: str,
    politicalDivision2: str,
    zipPrimary: str,
    zipExtended: str,
    urbanization: str,
    countryCode: str,
    trans_id: str | None,
    transaction_src: str,
) -> dict[str, Any]:
    return _require_tool_manager().validate_address(
        addressLine1=addressLine1,
        addressLine2=addressLine2,
        politicalDivision1=politicalDivision1,
        politicalDivision2=politicalDivision2,
        zipPrimary=zipPrimary,
        zipExtended=zipExtended,
        urbanization=urbanization,
        countryCode=countryCode,
        trans_id=trans_id,
        transaction_src=transaction_src,
    )
```

- [ ] **Step 5: Run focused hosted server tests**

Run:

```bash
python3 -m pytest tests/test_shipagent_server_hosted.py::ShipAgentHostedServerTests -q
```

Expected: PASS for capability, rate, and address tests in this file. If create-shipment tests have already been added by another worker, run the listed address tests directly.

- [ ] **Step 6: Run existing server tests for raw compatibility**

Run:

```bash
python3 -m pytest tests/test_server_tools.py tests/test_server_config.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add ups_mcp/server.py tests/test_shipagent_server_hosted.py
git commit -m "feat: add hosted address boundary"
```

### Task 7: Hosted Create Shipment Boundary

**Files:**
- Modify: `ups_mcp/server.py`
- Modify: `tests/test_shipagent_server_hosted.py`

- [ ] **Step 1: Add failing hosted create-shipment tests**

Append this import to `tests/test_shipagent_server_hosted.py`:

```python
from tests.shipment_fixtures import make_complete_body
```

Update `HostedFakeToolManager.__init__`:

```python
        self.create_shipment_response: dict = {
            "ShipmentResponse": {
                "ShipmentResults": {
                    "ShipmentIdentificationNumber": "1ZSHIP",
                    "ShipmentCharges": {
                        "TotalCharges": {"CurrencyCode": "USD", "MonetaryValue": "20.00"}
                    },
                    "PackageResults": {
                        "TrackingNumber": "1ZTRACK1",
                        "ShippingLabel": {
                            "ImageFormat": {"Code": "ZPL"},
                            "GraphicImage": "QkFTRTY0UERG",
                        },
                    },
                }
            }
        }
        self.create_shipment_exc: BaseException | None = None
```

Replace `create_shipment` in `HostedFakeToolManager` with:

```python
    def create_shipment(self, **kwargs):
        self.calls.append(("create_shipment", kwargs))
        if self.create_shipment_exc is not None:
            raise self.create_shipment_exc
        return self.create_shipment_response
```

Append these tests to `ShipAgentHostedServerTests`:

```python
    async def test_create_shipment_raw_is_default_and_does_not_require_idempotency_key(self) -> None:
        result = await server.create_shipment(request_body=make_complete_body())

        self.assertIn("ShipmentResponse", result)
        call_args = self.fake_tool_manager.calls[0][1]
        self.assertIsNone(call_args["trans_id"])
        self.assertIsNone(call_args.get("idempotency_key"))

    async def test_create_shipment_invalid_response_format_raises_tool_error(self) -> None:
        for invalid_format in ("xml", "ShipAgent_V1", "RAW", "shipagent-v1"):
            with self.subTest(response_format=invalid_format):
                with self.assertRaises(ToolError) as ctx:
                    await server.create_shipment(
                        request_body=make_complete_body(),
                        response_format=invalid_format,
                    )

                payload = json.loads(str(ctx.exception))
                self.assertEqual(payload["code"], "INVALID_RESPONSE_FORMAT")
                self.assertEqual(payload["allowed"], ["raw", "shipagent_v1"])
        self.assertEqual(self.fake_tool_manager.calls, [])

    async def test_create_shipment_hosted_rejects_trans_id_control_chars_before_ups(self) -> None:
        result = await server.create_shipment(
            request_body=make_complete_body(),
            response_format="shipagent_v1",
            idempotency_key="idem-valid",
            trans_id="corr\nbad",
        )

        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], "UPS_VALIDATION_ERROR")
        self.assertEqual(result["error"]["category"], "validation")
        self.assertRegex(result["error"]["correlation_id"], r"^corr_[0-9a-f]{32}$")
        self.assertEqual(self.fake_tool_manager.calls, [])

    async def test_create_shipment_hosted_rejects_transaction_src_control_chars_before_ups(self) -> None:
        result = await server.create_shipment(
            request_body=make_complete_body(),
            response_format="shipagent_v1",
            idempotency_key="idem-valid",
            trans_id="corr_create_tx_src",
            transaction_src="ship\nagent",
        )

        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], "UPS_VALIDATION_ERROR")
        self.assertEqual(result["error"]["category"], "validation")
        self.assertEqual(result["error"]["correlation_id"], "corr_create_tx_src")
        self.assertEqual(self.fake_tool_manager.calls, [])

    async def test_create_shipment_hosted_requires_non_empty_idempotency_key_before_ups(self) -> None:
        for key in ("", "   "):
            with self.subTest(key=repr(key)):
                result = await server.create_shipment(
                    request_body=make_complete_body(),
                    response_format="shipagent_v1",
                    idempotency_key=key,
                    trans_id="corr_missing_key",
                )

                self.assertFalse(result["success"])
                self.assertEqual(result["error"]["code"], "UPS_VALIDATION_ERROR")
                self.assertEqual(result["error"]["category"], "validation")
                self.assertEqual(result["error"]["correlation_id"], "corr_missing_key")
        self.assertEqual(self.fake_tool_manager.calls, [])

    async def test_create_shipment_hosted_rejects_idempotency_key_over_512_chars_before_ups(self) -> None:
        result = await server.create_shipment(
            request_body=make_complete_body(),
            response_format="shipagent_v1",
            idempotency_key="k" * 513,
            trans_id="corr_long_key",
        )

        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], "UPS_VALIDATION_ERROR")
        self.assertEqual(result["error"]["category"], "validation")
        self.assertEqual(result["error"]["correlation_id"], "corr_long_key")
        self.assertEqual(self.fake_tool_manager.calls, [])

    async def test_create_shipment_hosted_rejects_idempotency_key_control_chars_before_ups(self) -> None:
        bad_keys = {
            "newline": "idem\nkey",
            "carriage_return": "idem\rkey",
            "tab": "idem\tkey",
            "nul": "idem\x00key",
            "del": f"idem{chr(127)}key",
        }

        for name, key in bad_keys.items():
            with self.subTest(name=name):
                result = await server.create_shipment(
                    request_body=make_complete_body(),
                    response_format="shipagent_v1",
                    idempotency_key=key,
                    trans_id="corr_control_key",
                )

                self.assertFalse(result["success"])
                self.assertEqual(result["error"]["code"], "UPS_VALIDATION_ERROR")
                self.assertEqual(result["error"]["category"], "validation")
                self.assertEqual(result["error"]["correlation_id"], "corr_control_key")
        self.assertEqual(self.fake_tool_manager.calls, [])

    async def test_create_shipment_hosted_rejects_existing_customer_context_over_512_chars_before_ups(self) -> None:
        body = make_complete_body()
        body["ShipmentRequest"]["Request"]["TransactionReference"] = {
            "CustomerContext": "x" * 513,
        }

        result = await server.create_shipment(
            request_body=body,
            response_format="shipagent_v1",
            idempotency_key="idem-valid",
            trans_id="corr_long_context",
        )

        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], "UPS_VALIDATION_ERROR")
        self.assertEqual(result["error"]["category"], "validation")
        self.assertEqual(result["error"]["correlation_id"], "corr_long_context")
        self.assertEqual(self.fake_tool_manager.calls, [])

    async def test_create_shipment_hosted_rejects_non_string_customer_context_before_ups(self) -> None:
        bad_contexts = (None, 123, True, {}, [])

        for customer_context in bad_contexts:
            with self.subTest(customer_context=repr(customer_context)):
                body = make_complete_body()
                body["ShipmentRequest"]["Request"]["TransactionReference"] = {
                    "CustomerContext": customer_context,
                }

                result = await server.create_shipment(
                    request_body=body,
                    response_format="shipagent_v1",
                    idempotency_key="idem-valid",
                    trans_id="corr_non_string_context",
                )

                self.assertFalse(result["success"])
                self.assertEqual(result["error"]["code"], "UPS_VALIDATION_ERROR")
                self.assertEqual(result["error"]["category"], "validation")
                self.assertEqual(result["error"]["correlation_id"], "corr_non_string_context")
        self.assertEqual(self.fake_tool_manager.calls, [])

    async def test_create_shipment_hosted_rejects_existing_customer_context_control_chars_before_ups(self) -> None:
        bad_contexts = {
            "newline": "caller\ncontext",
            "carriage_return": "caller\rcontext",
            "tab": "caller\tcontext",
            "nul": "caller\x00context",
            "del": f"caller{chr(127)}context",
        }

        for name, customer_context in bad_contexts.items():
            with self.subTest(name=name):
                body = make_complete_body()
                body["ShipmentRequest"]["Request"]["TransactionReference"] = {
                    "CustomerContext": customer_context,
                }

                result = await server.create_shipment(
                    request_body=body,
                    response_format="shipagent_v1",
                    idempotency_key="idem-valid",
                    trans_id="corr_bad_context",
                )

                self.assertFalse(result["success"])
                self.assertEqual(result["error"]["code"], "UPS_VALIDATION_ERROR")
                self.assertEqual(result["error"]["category"], "validation")
                self.assertEqual(result["error"]["correlation_id"], "corr_bad_context")
        self.assertEqual(self.fake_tool_manager.calls, [])

    async def test_create_shipment_hosted_normalizes_and_echoes_stripped_idempotency_key(self) -> None:
        result = await server.create_shipment(
            request_body=make_complete_body(),
            response_format="shipagent_v1",
            idempotency_key=" idem-create-1 ",
            trans_id=" corr_create ",
        )

        self.assertEqual(result, {
            "success": True,
            "correlationId": "corr_create",
            "idempotencyKey": "idem-create-1",
            "shipmentIdentificationNumber": "1ZSHIP",
            "trackingNumbers": ["1ZTRACK1"],
            "totalCharges": {"monetaryValue": "20.00", "currencyCode": "USD"},
            "labelData": [
                {
                    "trackingNumber": "1ZTRACK1",
                    "format": "ZPL",
                    "encoding": "base64",
                    "contentBase64": "QkFTRTY0UERG",
                }
            ],
        })
        self.assertNotIn("contractVersion", result)
        self.assertNotIn("contract_version", result)
        call_args = self.fake_tool_manager.calls[0][1]
        self.assertEqual(call_args["trans_id"], "corr_create")
        self.assertEqual(call_args["idempotency_key"], "idem-create-1")
        self.assertEqual(call_args["transaction_src"], "ups-mcp")

    async def test_create_shipment_hosted_preserves_explicit_transaction_src(self) -> None:
        await server.create_shipment(
            request_body=make_complete_body(),
            response_format="shipagent_v1",
            idempotency_key="idem-src",
            trans_id="corr_create_src",
            transaction_src="shipagent",
        )

        call_args = self.fake_tool_manager.calls[0][1]
        self.assertEqual(call_args["transaction_src"], "shipagent")

    async def test_create_shipment_hosted_generates_correlation_id_when_trans_id_missing(self) -> None:
        result = await server.create_shipment(
            request_body=make_complete_body(),
            response_format="shipagent_v1",
            idempotency_key="idem-generated-corr",
        )

        self.assertTrue(result["success"])
        call_args = self.fake_tool_manager.calls[0][1]
        self.assertRegex(call_args["trans_id"], r"^corr_[0-9a-f]{32}$")
        self.assertEqual(result["correlationId"], call_args["trans_id"])

    async def test_create_shipment_hosted_safe_error_and_normalization_error(self) -> None:
        self.fake_tool_manager.create_shipment_exc = ToolError(json.dumps({"status_code": 401, "code": "401"}))

        result = await server.create_shipment(
            request_body=make_complete_body(),
            response_format="shipagent_v1",
            idempotency_key="idem-error",
            trans_id="corr_create_error",
        )

        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], "UPS_AUTH_ERROR")
        self.assertEqual(result["error"]["correlation_id"], "corr_create_error")
        self.assertNotIn("idempotencyKey", result)

        self.fake_tool_manager.create_shipment_exc = RuntimeError("stack path /tmp/create traceback token")
        unknown = await server.create_shipment(
            request_body=make_complete_body(),
            response_format="shipagent_v1",
            idempotency_key="idem-unknown",
            trans_id="corr_create_unknown",
        )
        self.assertFalse(unknown["success"])
        self.assertEqual(unknown["error"]["code"], "UPS_UNKNOWN_ERROR")
        self.assertEqual(unknown["error"]["category"], "unknown")
        self.assertFalse(unknown["error"]["retryable"])
        self.assertEqual(unknown["error"]["correlation_id"], "corr_create_unknown")
        self.assertNotIn("idempotencyKey", unknown)
        serialized = json.dumps(unknown).lower()
        self.assertNotIn("traceback", serialized)
        self.assertNotIn("/tmp/create", serialized)

        self.fake_tool_manager.create_shipment_exc = None
        self.fake_tool_manager.create_shipment_response = {"ShipmentResponse": {"ShipmentResults": {}}}
        normalized = await server.create_shipment(
            request_body=make_complete_body(),
            response_format="shipagent_v1",
            idempotency_key="idem-normalization",
            trans_id="corr_create_norm",
        )
        self.assertFalse(normalized["success"])
        self.assertEqual(normalized["error"]["code"], "UPS_NORMALIZATION_ERROR")
        self.assertEqual(normalized["error"]["category"], "normalization")
        self.assertNotIn("idempotencyKey", normalized)
```

- [ ] **Step 2: Run hosted create-shipment tests to verify they fail**

Run:

```bash
python3 -m pytest tests/test_shipagent_server_hosted.py::ShipAgentHostedServerTests -q
```

Expected: FAIL because `create_shipment` does not accept `response_format` or `idempotency_key`.

- [ ] **Step 3: Import shipment normalization in `server.py`**

Add `normalize_create_shipment_result` to the existing import from `.shipagent_normalization`:

```python
from .shipagent_normalization import (
    HOSTED_RESPONSE_FORMAT,
    RAW_RESPONSE_FORMAT,
    ShipAgentNormalizationError,
    build_shipagent_capabilities,
    normalize_address_result,
    normalize_create_shipment_result,
    normalize_rate_result,
    to_normalization_error,
    to_safe_error,
)
```

- [ ] **Step 4: Replace `create_shipment` with hosted wrapper and raw helper**

Replace the current `create_shipment` function with this public wrapper and internal raw helper. Preserve the existing detailed docstring sections and add the `response_format` and `idempotency_key` argument descriptions to it.

```python
@mcp.tool()
async def create_shipment(
    request_body: dict[str, Any],
    version: str = "v2409",
    additionaladdressvalidation: str = "",
    trans_id: str = "",
    transaction_src: str = "ups-mcp",
    response_format: ResponseFormat = "raw",
    idempotency_key: str = "",
    ctx: Context | None = None,
) -> dict[str, Any]:
    """
    Create a shipment using UPS Shipping API (`POST /shipments/{version}/ship`).

    response_format defaults to "raw" for existing clients. Use
    "shipagent_v1" for hosted-v1 normalized responses and safe error envelopes.
    Hosted create shipment requires a non-empty idempotency_key of at most
    512 characters and no ASCII control characters before UPS is called.
    """
    _validate_response_format(response_format)
    if response_format == RAW_RESPONSE_FORMAT:
        return await _create_shipment_execute(
            request_body=request_body,
            version=version,
            additionaladdressvalidation=additionaladdressvalidation,
            trans_id=trans_id or None,
            transaction_src=transaction_src,
            idempotency_key=None,
            ctx=ctx,
            allow_elicitation=True,
        )

    correlation_id, correlation_error = _hosted_correlation_id(trans_id)
    if correlation_error is not None:
        return correlation_error
    transaction_src_error = _hosted_transaction_src_error(transaction_src, correlation_id)
    if transaction_src_error is not None:
        return transaction_src_error

    hosted_idempotency_key = idempotency_key.strip()
    if not hosted_idempotency_key:
        return to_safe_error(
            ToolError(json.dumps({
                "code": "VALIDATION_ERROR",
                "reason": "missing_idempotency_key",
            })),
            correlation_id,
        )
    if len(hosted_idempotency_key) > MAX_IDEMPOTENCY_KEY_LENGTH:
        return to_safe_error(
            ToolError(json.dumps({
                "code": "VALIDATION_ERROR",
                "reason": "idempotency_key_too_long",
            })),
            correlation_id,
        )
    if _has_ascii_control(hosted_idempotency_key):
        return to_safe_error(
            ToolError(json.dumps({
                "code": "VALIDATION_ERROR",
                "reason": "idempotency_key_control_character",
            })),
            correlation_id,
        )

    try:
        raw_result = await _create_shipment_execute(
            request_body=request_body,
            version=version,
            additionaladdressvalidation=additionaladdressvalidation,
            trans_id=correlation_id,
            transaction_src=transaction_src,
            idempotency_key=hosted_idempotency_key,
            ctx=None,
            allow_elicitation=False,
        )
        return normalize_create_shipment_result(raw_result, hosted_idempotency_key, correlation_id)
    except ShipAgentNormalizationError:
        return to_normalization_error(correlation_id)
    except ToolError as exc:
        return to_safe_error(exc, correlation_id)
    except Exception as exc:
        return to_safe_error(exc, correlation_id)


async def _create_shipment_execute(
    *,
    request_body: dict[str, Any],
    version: str,
    additionaladdressvalidation: str,
    trans_id: str | None,
    transaction_src: str,
    idempotency_key: str | None,
    ctx: Context | None,
    allow_elicitation: bool,
) -> dict[str, Any]:
    from .shipment_validator import (
        apply_defaults,
        find_missing_fields,
        canonicalize_body,
        AmbiguousPayerError,
        PRODUCT_ARRAY_RULE,
    )
    from .elicitation import elicit_and_rehydrate

    def _send_to_ups(body: dict[str, Any]) -> dict[str, Any]:
        canonical = canonicalize_body(body)
        if idempotency_key is not None:
            _validate_hosted_customer_context(canonical)
        return _require_tool_manager().create_shipment(
            request_body=canonical,
            version=version,
            additionaladdressvalidation=additionaladdressvalidation or None,
            trans_id=trans_id,
            transaction_src=transaction_src,
            idempotency_key=idempotency_key,
        )

    env_config = {"UPS_ACCOUNT_NUMBER": os.getenv("UPS_ACCOUNT_NUMBER", "")}
    try:
        canonical_input = canonicalize_body(request_body)
        merged_body = apply_defaults(canonical_input, env_config)
    except TypeError as exc:
        raise ToolError(json.dumps({
            "code": "MALFORMED_REQUEST",
            "message": f"Request body has structural conflicts: {exc}",
            "reason": "malformed_structure",
            "missing": [],
        }))

    try:
        missing = find_missing_fields(merged_body)
    except AmbiguousPayerError as exc:
        raise ToolError(json.dumps({
            "code": "MALFORMED_REQUEST",
            "message": str(exc),
            "reason": "ambiguous_payer",
            "missing": [],
        }))

    if not missing:
        return _send_to_ups(merged_body)
    if not allow_elicitation:
        raise ToolError(json.dumps({
            "code": "VALIDATION_ERROR",
            "reason": "missing_shipment_required_fields",
            "missing": [field.flat_key for field in missing],
        }))

    merged_body = await elicit_and_rehydrate(
        ctx, merged_body, missing,
        find_missing_fn=find_missing_fields,
        tool_label="shipment creation",
        canonicalize_fn=canonicalize_body,
        array_rules=[PRODUCT_ARRAY_RULE],
    )
    return _send_to_ups(merged_body)
```

- [ ] **Step 5: Run focused hosted server tests**

Run:

```bash
python3 -m pytest tests/test_shipagent_server_hosted.py::ShipAgentHostedServerTests -q
```

Expected: PASS for server hosted tests after Task 8 adds `ToolManager.create_shipment(idempotency_key=...)`. Before Task 8, the tests that enter `_create_shipment_execute` with complete hosted request bodies fail with `TypeError: create_shipment() got an unexpected keyword argument 'idempotency_key'`.

- [ ] **Step 6: Run existing create-shipment server tests after Task 8**

Run:

```bash
python3 -m pytest tests/test_server_elicitation.py tests/test_server_tools.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit after Task 8 has made the tool-manager signature compatible**

```bash
git add ups_mcp/server.py tests/test_shipagent_server_hosted.py
git commit -m "feat: add hosted shipment boundary"
```

### Task 8: Create-Shipment Idempotency Metadata Pass-Through

**Files:**
- Modify: `ups_mcp/tools.py`
- Modify: `tests/test_tool_mapping.py`

- [ ] **Step 1: Add failing ToolManager tests for metadata pass-through and no local dedupe**

Add this import to `tests/test_tool_mapping.py`:

```python
import copy
```

Append these tests to `ToolMappingTests`:

```python
    def test_create_shipment_sets_missing_customer_context_to_idempotency_key(self) -> None:
        body = {"ShipmentRequest": {"Request": {}, "Shipment": {}}}

        self.manager.create_shipment(
            request_body=body,
            idempotency_key=" idem-123 ",
        )

        sent_body = self.fake_http_client.calls[0]["kwargs"]["json_body"]
        context = sent_body["ShipmentRequest"]["Request"]["TransactionReference"]["CustomerContext"]
        self.assertEqual(context, "idem-123")
        self.assertNotIn("TransactionReference", body["ShipmentRequest"]["Request"])

    def test_create_shipment_sets_empty_customer_context_to_idempotency_key(self) -> None:
        body = {
            "ShipmentRequest": {
                "Request": {"TransactionReference": {"CustomerContext": "  "}},
                "Shipment": {},
            }
        }

        self.manager.create_shipment(request_body=body, idempotency_key="idem-empty")

        sent_body = self.fake_http_client.calls[0]["kwargs"]["json_body"]
        context = sent_body["ShipmentRequest"]["Request"]["TransactionReference"]["CustomerContext"]
        self.assertEqual(context, "idem-empty")

    def test_create_shipment_appends_idempotency_key_when_context_has_room(self) -> None:
        body = {
            "ShipmentRequest": {
                "Request": {"TransactionReference": {"CustomerContext": "caller-context"}},
                "Shipment": {},
            }
        }

        self.manager.create_shipment(request_body=body, idempotency_key="idem-append")

        sent_body = self.fake_http_client.calls[0]["kwargs"]["json_body"]
        context = sent_body["ShipmentRequest"]["Request"]["TransactionReference"]["CustomerContext"]
        self.assertEqual(context, "caller-context; idempotency_key=idem-append")

    def test_create_shipment_preserves_existing_context_when_append_exceeds_512_chars(self) -> None:
        existing = "x" * 500
        body = {
            "ShipmentRequest": {
                "Request": {"TransactionReference": {"CustomerContext": existing}},
                "Shipment": {},
            }
        }

        self.manager.create_shipment(request_body=body, idempotency_key="idem-too-long")

        sent_body = self.fake_http_client.calls[0]["kwargs"]["json_body"]
        context = sent_body["ShipmentRequest"]["Request"]["TransactionReference"]["CustomerContext"]
        self.assertEqual(context, existing)
        self.assertEqual(len(context), 500)

    def test_create_shipment_without_idempotency_key_leaves_request_body_unchanged(self) -> None:
        body = {
            "ShipmentRequest": {
                "Request": {"TransactionReference": {"CustomerContext": "caller-context"}},
                "Shipment": {},
            }
        }
        original = copy.deepcopy(body)

        self.manager.create_shipment(request_body=body)

        sent_body = self.fake_http_client.calls[0]["kwargs"]["json_body"]
        self.assertEqual(sent_body, original)
        self.assertEqual(body, original)

    def test_create_shipment_same_idempotency_key_is_not_deduped_locally(self) -> None:
        body = {"ShipmentRequest": {"Request": {}, "Shipment": {}}}

        first = self.manager.create_shipment(request_body=body, idempotency_key="idem-repeat")
        second = self.manager.create_shipment(request_body=body, idempotency_key="idem-repeat")

        self.assertEqual(first, {"mock": True})
        self.assertEqual(second, {"mock": True})
        self.assertEqual(len(self.fake_http_client.calls), 2)
        contexts = [
            call["kwargs"]["json_body"]["ShipmentRequest"]["Request"]["TransactionReference"]["CustomerContext"]
            for call in self.fake_http_client.calls
        ]
        self.assertEqual(contexts, ["idem-repeat", "idem-repeat"])
```

- [ ] **Step 2: Run ToolManager tests to verify they fail**

Run:

```bash
python3 -m pytest tests/test_tool_mapping.py::ToolMappingTests -q
```

Expected: FAIL because `ToolManager.create_shipment()` does not accept `idempotency_key`.

- [ ] **Step 3: Add `copy` import and metadata helper in `tools.py`**

Modify the imports at the top of `ups_mcp/tools.py`:

```python
from __future__ import annotations

import copy
import uuid
from typing import Any
```

Add this helper before `class ToolManager`:

```python
def _with_idempotency_customer_context(
    request_body: dict[str, Any],
    idempotency_key: str | None,
) -> dict[str, Any]:
    """Copy request_body and add idempotency metadata without overwriting caller context."""
    key = idempotency_key.strip() if idempotency_key else ""
    if not key:
        return copy.deepcopy(request_body)

    result = copy.deepcopy(request_body)
    shipment_request = result.setdefault("ShipmentRequest", {})
    request = shipment_request.setdefault("Request", {})
    transaction_reference = request.setdefault("TransactionReference", {})
    existing_value = transaction_reference.get("CustomerContext")
    existing_context = str(existing_value) if existing_value is not None else ""

    if not existing_context.strip():
        transaction_reference["CustomerContext"] = key
        return result

    appended = f"{existing_context}; idempotency_key={key}"
    if len(appended) <= 512:
        transaction_reference["CustomerContext"] = appended
    return result
```

- [ ] **Step 4: Add the optional idempotency parameter to `ToolManager.create_shipment`**

Replace `ToolManager.create_shipment` with:

```python
    def create_shipment(
        self,
        request_body: dict[str, Any],
        version: str = "v2409",
        additionaladdressvalidation: str | None = None,
        trans_id: str | None = None,
        transaction_src: str = "ups-mcp",
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        if not isinstance(request_body, dict):
            raise ToolError("request_body must be a JSON object")
        request_body_with_metadata = _with_idempotency_customer_context(request_body, idempotency_key)
        return self._execute_operation(
            operation_id=SHIPMENT_OPERATION_ID,
            operation_name="create_shipment",
            path_params={"version": version},
            query_params={"additionaladdressvalidation": additionaladdressvalidation},
            request_body=request_body_with_metadata,
            trans_id=trans_id,
            transaction_src=transaction_src,
        )
```

- [ ] **Step 5: Run ToolManager tests**

Run:

```bash
python3 -m pytest tests/test_tool_mapping.py::ToolMappingTests -q
```

Expected: PASS.

- [ ] **Step 6: Run hosted server tests and existing create-shipment tests**

Run:

```bash
python3 -m pytest tests/test_shipagent_server_hosted.py tests/test_server_elicitation.py tests/test_server_tools.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add ups_mcp/tools.py tests/test_tool_mapping.py
git commit -m "feat: pass hosted idempotency metadata to shipment requests"
```

### Task 9: No Generic Retry For Mutating Create Shipment

**Files:**
- Modify: `tests/test_tool_mapping.py`

- [ ] **Step 1: Add failing no-retry guard test**

Add this helper class below `FakeHTTPClient` in `tests/test_tool_mapping.py`:

```python
class FailingHTTPClient:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def call_operation(self, operation, **kwargs):  # noqa: ANN001
        self.calls.append({"operation": operation, "kwargs": kwargs})
        raise ToolError(json.dumps({"status_code": 503, "code": "503"}))
```

Add this import at the top if `json` is not already imported:

```python
import json
```

Append this test to `ToolMappingTests`:

```python
    def test_create_shipment_does_not_retry_after_http_error(self) -> None:
        failing_http_client = FailingHTTPClient()
        self.manager.http_client = failing_http_client

        with self.assertRaises(ToolError):
            self.manager.create_shipment(
                request_body={"ShipmentRequest": {"Request": {}, "Shipment": {}}},
                idempotency_key="idem-no-retry",
            )

        self.assertEqual(len(failing_http_client.calls), 1)
        self.assertEqual(failing_http_client.calls[0]["operation"].operation_id, "Shipment")
```

- [ ] **Step 2: Run the no-retry test**

Run:

```bash
python3 -m pytest tests/test_tool_mapping.py::ToolMappingTests::test_create_shipment_does_not_retry_after_http_error -q
```

Expected: PASS if Task 8 did not add retry behavior. If it fails with more than one HTTP call, remove the retry loop from `ToolManager.create_shipment` or `_execute_operation`.

- [ ] **Step 3: Run ToolManager tests**

Run:

```bash
python3 -m pytest tests/test_tool_mapping.py -q
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/test_tool_mapping.py
git commit -m "test: guard shipment creation against retries"
```

### Task 10: README Hosted-v1 Documentation

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add hosted-v1 documentation**

Insert this section after the "Response Format" section in `README.md`:

````markdown
### ShipAgent Hosted-v1 Boundary

`ups-mcp` can also serve as ShipAgent's private UPS carrier integration boundary. This is not the public ShipAgent marketplace MCP app; hosted marketplace transport, service-to-service authentication, tenant storage, and per-tenant UPS credential handoff are owned by ShipAgent hosted infrastructure.

Existing clients keep the default raw behavior. `rate_shipment`, `validate_address`, and `create_shipment` return raw UPS dictionaries unless callers explicitly pass:

```json
{"response_format": "shipagent_v1"}
```

`response_format` values are strict and case-sensitive. Only `"raw"` and `"shipagent_v1"` are accepted. Invalid values raise a direct MCP `ToolError` before UPS is called; they do not return a hosted safe envelope because no valid hosted boundary contract was selected.

Hosted mode is deterministic and never prompts through MCP elicitation. For hosted rate/create requests, if required fields are still missing after defaults are applied, the server returns a hosted `UPS_VALIDATION_ERROR` before calling UPS.

Hosted mode does not override `transaction_src`; it preserves printable caller-supplied values and defaults to `ups-mcp`. Values containing ASCII control characters such as newline, carriage return, tab, NUL, or DEL return a hosted `UPS_VALIDATION_ERROR` before UPS is called. ShipAgent hosted infrastructure can pass `transaction_src: "shipagent"` explicitly when it wants that UPS transaction source.

The read-only `shipagent_capabilities` tool returns hosted-v1 readiness metadata without calling UPS or requiring UPS credentials:

```json
{
  "contract_version": "hosted-v1",
  "server_version": "1.1.0",
  "capabilities": [
    "rate_quote",
    "rate_shop",
    "address_validation",
    "create_shipment",
    "idempotency_metadata_passthrough",
    "shipment_response_normalization",
    "safe_error_mapping",
    "mutating_retry_policy"
  ],
  "response_formats": ["raw", "shipagent_v1"]
}
```

`contract_version` is the compatibility signal for this release. The capabilities response intentionally does not include a schema hash or separate schema version; incompatible hosted response-shape changes should bump `contract_version`.

Capabilities are intentionally flat for hosted-v1. `mutating_retry_policy` signals that mutating create-shipment calls are not retried by this package, but the response does not include a structured `retry_policy` field until ShipAgent needs machine-readable retry metadata.

In hosted mode, successful responses are normalized to the hosted-v1 contract and use camelCase fields. Success envelopes include a top-level `correlationId` matching the hosted boundary id sent to UPS as `trans_id`. Hosted success envelopes do not repeat `contractVersion` or `contract_version`; use `shipagent_capabilities` for contract version discovery.

```json
{
  "success": true,
  "correlationId": "corr_123",
  "serviceCode": "03",
  "totalCharges": {
    "monetaryValue": "12.34",
    "currencyCode": "USD"
  }
}
```

When callers omit `trans_id`, hosted mode generates a correlation id shaped as `corr_<32 lowercase hex characters>`. When callers provide `trans_id`, the value is stripped and preserved if it does not contain ASCII control characters. Hosted-v1 does not impose a `trans_id` length limit. Caller-supplied `trans_id` values containing ASCII control characters return a hosted `UPS_VALIDATION_ERROR` before UPS is called; that error envelope uses a generated safe `corr_...` id instead of echoing the invalid value.

Failures return a safe result envelope instead of raising raw UPS details. Error envelopes keep the closed error object shape and include the same correlation id as `error.correlation_id`; they do not add top-level `correlationId` or camelCase aliases. Error envelopes use a closed public taxonomy: `code`, `category`, `message`, `retryable`, and `correlation_id`. Hosted-v1 public categories are `auth`, `rate_limit`, `validation`, `service_unavailable`, `transport`, `unknown`, and `normalization`; domain outcomes such as address validity are represented by successful hosted results instead of domain-specific error categories. Non-auth, non-rate-limit carrier 4xx responses map to `UPS_VALIDATION_ERROR` with `retryable: false`. Error envelopes do not include raw UPS error codes, raw UPS messages, request bodies, credentials, response details, or create-shipment `idempotencyKey`; use `correlation_id` for internal debugging.

Unexpected hosted exceptions are also converted to safe envelopes with `code: "UPS_UNKNOWN_ERROR"`, `category: "unknown"`, and `retryable: false`. Raw mode keeps existing exception behavior.

```json
{
  "success": false,
  "error": {
    "code": "UPS_VALIDATION_ERROR",
    "category": "validation",
    "message": "The UPS request could not be validated.",
    "retryable": false,
    "correlation_id": "corr_123"
  }
}
```

Hosted `rate_shipment` quote and shop successes require `serviceCode` and `totalCharges`. `serviceDescription` is included only when UPS provides it. Quote mode requires exactly one returned `RatedShipment`; multiple returned options are a normalization error and callers should use `Shop` for multi-option responses. A successful UPS rate payload without a usable service code returns `UPS_NORMALIZATION_ERROR`. Shop mode does not filter incomplete returned options; if any returned `RatedShipment` lacks `serviceCode` or `totalCharges`, hosted mode returns `UPS_NORMALIZATION_ERROR`. If UPS includes `NegotiatedRateCharges`, hosted rate normalization requires a complete `NegotiatedRateCharges.TotalCharge` and returns `UPS_NORMALIZATION_ERROR` instead of falling back to standard `TotalCharges` when negotiated pricing is malformed. Present UPS-derived success string fields must be strings; non-string values or strings containing ASCII control characters return `UPS_NORMALIZATION_ERROR` instead of being coerced, stripped, or passed through.

Hosted monetary amounts use UPS string formatting: `totalCharges.monetaryValue` is a string, not a JSON number. ShipAgent pricing code should parse it with `Decimal` or equivalent when arithmetic is needed. Hosted `totalCharges.currencyCode` must be exactly three uppercase ASCII letters; malformed currency codes return `UPS_NORMALIZATION_ERROR`.

Hosted `validate_address` returns successful domain statuses: `valid`, `ambiguous`, `invalid`, `unknown`, or `unsupported`. Hosted mode strips and uppercases `countryCode` only for boundary decisions, validates that it is exactly two ASCII letters, and does not maintain an ISO or UPS country allowlist. `unsupported` is returned without calling UPS when a well-formed two-letter `countryCode` is outside `US` or `PR`, because UPS address validation only covers the U.S. and Puerto Rico in this boundary. Unsupported country detection happens before required address field validation. Blank or malformed `countryCode` is malformed input and returns a hosted `UPS_VALIDATION_ERROR` before UPS is called. For supported `US`/`PR` validation, blank `addressLine1`, `politicalDivision1`, `politicalDivision2`, or `zipPrimary` also returns a hosted `UPS_VALIDATION_ERROR` before UPS. Hosted candidates contain address fields only and intentionally omit UPS `AddressClassification` and other candidate metadata. Candidates that normalize to no substantive hosted address fields are omitted; `countryCode` alone is not usable candidate data, and hosted-v1 never emits empty `{}` candidates. `valid` and `ambiguous` responses require at least one surviving hosted candidate with `addressLines`, `city`, `stateProvince`, `postalCode`, or `postalCodeExtended` and otherwise return `UPS_NORMALIZATION_ERROR`; `invalid` and `unknown` responses must return an empty candidate list and candidate data under either status returns `UPS_NORMALIZATION_ERROR`. If UPS returns multiple known XAV status indicators, hosted address normalization returns `UPS_NORMALIZATION_ERROR` instead of choosing a status by precedence. Present UPS-derived candidate fields must be strings; non-string values or strings containing ASCII control characters return `UPS_NORMALIZATION_ERROR`. Supported address validation calls pass the caller's original `countryCode` value through to UPS unchanged. Raw mode keeps existing address-validation behavior.

Hosted `create_shipment` success includes top-level `trackingNumbers` and `labelData` entries with `trackingNumber`, `format`, `encoding: "base64"`, and `contentBase64` from UPS `ShippingLabel.GraphicImage`. Every returned UPS `PackageResults` item must include `TrackingNumber`, a supported create-shipment `ShippingLabel.ImageFormat.Code` (`GIF`, `ZPL`, `EPL`, or `SPL` after uppercasing), and strict unwrapped base64 `ShippingLabel.GraphicImage`; otherwise hosted create returns `UPS_NORMALIZATION_ERROR` instead of a partial buy-label success. Hosted create validates `GraphicImage` with `base64.b64decode(..., validate=True)`, rejects whitespace and MIME line wrapping, and preserves the original UPS string as `contentBase64` when valid. Present UPS-derived shipment ids, tracking numbers, label format codes, label base64 content, and monetary strings must be strings; non-string values or strings containing ASCII control characters return `UPS_NORMALIZATION_ERROR`. `PDF` appears in UPS label-recovery responses, not create-shipment `ShippingLabel`, and `PNG` is not currently supported by the local create-shipment schema. If UPS includes `NegotiatedRateCharges`, hosted create normalization requires a complete `NegotiatedRateCharges.TotalCharge` and returns `UPS_NORMALIZATION_ERROR` instead of falling back to `ShipmentCharges.TotalCharges` when negotiated pricing is malformed. The hosted contract intentionally omits label `HTMLImage`, label URLs, and unrelated raw shipment metadata; use `recover_label` only when a label must be retrieved again later.

Hosted `create_shipment` requires a non-empty `idempotency_key` of at most 512 characters after stripping whitespace. Keys containing ASCII control characters such as newline, carriage return, tab, NUL, or DEL are invalid. Missing, over-limit, or control-character keys return a hosted validation safe error before UPS is called. The stripped key is echoed as `idempotencyKey` only on hosted create success and passed to UPS shipment transaction metadata in `ShipmentRequest.Request.TransactionReference.CustomerContext`; hosted create errors do not echo `idempotencyKey`. Hosted mode also validates an existing caller-supplied `CustomerContext` before UPS because this boundary explicitly mutates or preserves that field: existing context must be a string, at most 512 characters, and contain no ASCII control characters. Missing `CustomerContext` is allowed and hosted mode will set it from the idempotency key; explicit non-string values such as `null`, numbers, booleans, arrays, or objects return hosted `UPS_VALIDATION_ERROR` before UPS. If `CustomerContext` is missing or blank, the key is used as the context. If caller context already exists, `; idempotency_key=<key>` is appended only when the combined value fits UPS's 512-character limit. If appending would exceed the limit, the caller's existing context is preserved unchanged. This is metadata pass-through for ShipAgent retry coordination, not a claim of carrier-level idempotent shipment creation. `ups-mcp` does not store idempotency keys, maintain a replay cache, dedupe repeat calls, or suppress a UPS request when the same key appears again; ShipAgent hosted infrastructure owns tenant/request idempotency.
````

- [ ] **Step 2: Update tool argument bullets**

In the `rate_shipment`, `validate_address`, and `create_shipment` entries under "Available Tools", add these bullets:

```markdown
    - `response_format` (str, optional, default `raw`): exact case-sensitive value `raw` or `shipagent_v1`
```

For `create_shipment`, also add:

```markdown
    - `idempotency_key` (str, required only when `response_format=shipagent_v1`): deterministic ShipAgent request key, 1-512 characters after stripping whitespace, with no ASCII control characters, echoed in hosted responses and passed as metadata only
```

- [ ] **Step 3: Run documentation grep checks**

Run:

```bash
rg -n "shipagent_capabilities|shipagent_v1|trans_id|transaction_src|idempotency_key|private UPS carrier integration boundary|service-to-service authentication" README.md
```

Expected: output includes all five searched terms.

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: document shipagent hosted v1 contract"
```

### Task 11: Full Verification

**Files:**
- No planned source edits.

- [ ] **Step 1: Run the full test suite**

Run:

```bash
python3 -m pytest -q
```

Expected: PASS.

- [ ] **Step 2: Confirm hosted additions are the only intended source changes**

Run:

```bash
git status --short
git diff --stat
```

Expected: modified or added files are limited to:

```text
README.md
ups_mcp/server.py
ups_mcp/shipagent_normalization.py
ups_mcp/tools.py
tests/test_shipagent_normalization.py
tests/test_shipagent_server_hosted.py
tests/test_tool_mapping.py
```

Pre-existing working tree changes outside this list should be left intact and not reverted.

- [ ] **Step 3: Run public contract smoke checks in Python**

Run:

```bash
python3 - <<'PY'
import asyncio
import json
import ups_mcp.server as server

async def main():
    caps = await server.shipagent_capabilities()
    assert caps["contract_version"] == "hosted-v1"
    assert "shipagent_v1" in caps["response_formats"]
    tools = await server.mcp.list_tools()
    assert "shipagent_capabilities" in {tool.name for tool in tools}
    print(json.dumps({
        "contract_version": caps["contract_version"],
        "has_shipagent_v1": "shipagent_v1" in caps["response_formats"],
        "registered": True,
    }, sort_keys=True))

asyncio.run(main())
PY
```

Expected:

```json
{"contract_version": "hosted-v1", "has_shipagent_v1": true, "registered": true}
```

- [ ] **Step 4: Final commit if verification required changes**

If verification required source or test fixes, commit the fixes:

```bash
git add README.md ups_mcp/server.py ups_mcp/shipagent_normalization.py ups_mcp/tools.py tests/test_shipagent_normalization.py tests/test_shipagent_server_hosted.py tests/test_tool_mapping.py
git commit -m "test: verify shipagent hosted v1 contract"
```

If no files changed during verification, skip this commit.

## Self-Review

- Spec coverage:
  - Capability tool: Task 5.
  - Capabilities use `contract_version` only, with no schema hash/version fields: Tasks 1 and 5.
  - Hosted rate/address/create success envelopes do not include `contractVersion` or `contract_version`: Tasks 2, 3, 4, 5, 6, and 7.
  - Capabilities stay flat with no structured `retry_policy` field: Tasks 1, 5, and 9.
  - Raw default behavior: Tasks 5, 6, and 7.
  - Hosted success normalization for rate, address, and shipment creation: Tasks 2, 3, 4, 5, 6, and 7.
  - Hosted success payloads use camelCase fields while hosted errors keep the closed `error.correlation_id` shape with no camelCase aliases: Tasks 1, 2, 3, 4, 5, 6, and 7.
  - Strict case-sensitive `response_format` validation for only `raw` and `shipagent_v1`: Tasks 5, 6, and 7.
  - Invalid `response_format` raises direct MCP `ToolError` and never calls UPS or returns a hosted safe envelope: Tasks 5, 6, and 7.
  - Hosted public error categories stay operational and exclude address/customs domain categories: Tasks 1, 5, 6, and 7.
  - Hosted rate quote requires exactly one returned `RatedShipment`; quote/shop successes require `serviceCode` and `totalCharges` for every returned `RatedShipment`; `serviceDescription` is optional; shop mode does not filter partial options; and malformed negotiated rate charges do not fall back to standard totals: Task 2.
  - Hosted monetary values preserve UPS string formatting, are not coerced to numbers, and require three-uppercase-ASCII-letter currency codes: Tasks 2 and 4.
  - Hosted success normalization requires UPS-derived success string fields to be strings and rejects ASCII control characters instead of coercing, stripping, or returning them: Tasks 1, 2, 3, and 4.
  - Hosted safe errors and closed envelope shape, including non-auth/rate-limit carrier 4xx mapping to non-retryable validation errors: Tasks 1, 5, 6, and 7.
  - Hosted safe errors expose only public `UPS_*` codes and never raw UPS codes/messages/details or create-shipment `idempotencyKey`: Tasks 1 and 7.
  - Hosted unexpected exceptions return `UPS_UNKNOWN_ERROR` safe envelopes while raw mode still propagates: Tasks 1, 5, 6, and 7.
  - Hosted success `correlationId` and error `error.correlation_id` fields: Tasks 2, 3, 4, 5, 6, and 7.
  - Generated hosted correlation ids use `corr_<32 lowercase hex chars>`; supplied printable `trans_id` is stripped and preserved with no v1 length limit, while ASCII-control-character `trans_id` values return validation errors before UPS: Tasks 5, 6, and 7.
  - Hosted mode preserves printable caller `transaction_src`, defaults to `ups-mcp`, and rejects ASCII-control-character values before UPS: Tasks 5, 6, and 7.
  - Hosted no-elicitation determinism via explicit non-eliciting rate/create execution branches: Tasks 5 and 7.
  - Hosted address validation uses stripped/uppercased `countryCode` only for boundary decisions, rejects blank or malformed non-two-letter ASCII country codes before UPS, and returns success status `unsupported` for well-formed non-US/PR codes before required address field validation without calling UPS: Task 6.
  - Hosted supported-country address validation rejects blank `addressLine1`, `politicalDivision1`, `politicalDivision2`, or `zipPrimary` before UPS while raw mode keeps existing behavior: Task 6.
  - Hosted address boundary uses normalized `countryCode` only for support decisions and passes the caller's original `countryCode` through to UPS: Task 6.
  - Hosted address candidates stay address-field-only, omit UPS `AddressClassification`, drop candidates that normalize to no substantive hosted address fields, reject `countryCode`-only candidates, require at least one surviving candidate for `valid`/`ambiguous`, require empty candidates for `invalid`/`unknown`, and reject conflicting XAV status indicators: Task 3.
  - Hosted create-shipment success includes only supported create label formats (`GIF`, `ZPL`, `EPL`, `SPL`), strict unwrapped base64 label content with no whitespace, self-contained per-label `trackingNumber`, complete tracking/label data for every package, and no fallback to standard shipment totals when negotiated charges are malformed, while stripping HTML/URL label fields: Tasks 4 and 7.
  - Hosted create-shipment idempotency precondition, 512-character max, ASCII-control-character rejection, success-only echo, and no `idempotencyKey` on error envelopes: Task 7.
  - Hosted create-shipment validates existing caller-supplied `CustomerContext` type, max length, and ASCII-control-character constraints before UPS because hosted mode mutates or preserves that field: Task 7.
  - UPS `CustomerContext` metadata pass-through appends when it fits and preserves existing context when it does not: Task 8.
  - No local idempotency replay cache or dedupe store: Task 8.
  - No mutating retry loop: Task 9.
  - Documentation: Task 10.
  - Full suite verification: Task 11.
- Placeholder scan:
  - The plan avoids forbidden placeholder tokens and vague implementation instructions.
- Type consistency:
  - Public hosted helpers are `build_shipagent_capabilities`, `normalize_rate_result`, `normalize_address_result`, `normalize_create_shipment_result`, `to_normalization_error`, and `to_safe_error`.
  - Success normalizers accept the server-owned `correlation_id` and include it as top-level hosted-v1 `correlationId`.
  - Server `response_format` uses `ResponseFormat = Literal["raw", "shipagent_v1"]`.
  - Tool-manager metadata pass-through uses `idempotency_key: str | None = None`.
