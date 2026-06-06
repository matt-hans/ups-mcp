"""Pure ShipAgent hosted-v1 UPS boundary normalization helpers."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

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

_RATE_QUOTE_OPTIONS = {"rate", "ratetimeintransit"}
_RATE_SHOP_OPTIONS = {"shop", "shoptimeintransit"}

_CATEGORY_TO_PUBLIC_ERROR = {
    "auth": {
        "code": "UPS_AUTH_ERROR",
        "message": "UPS authentication failed.",
        "retryable": False,
    },
    "rate_limit": {
        "code": "UPS_RATE_LIMIT_ERROR",
        "message": "UPS rate limit exceeded.",
        "retryable": True,
    },
    "validation": {
        "code": "UPS_VALIDATION_ERROR",
        "message": "UPS request validation failed.",
        "retryable": False,
    },
    "service_unavailable": {
        "code": "UPS_SERVICE_UNAVAILABLE",
        "message": "UPS service is temporarily unavailable.",
        "retryable": True,
    },
    "transport": {
        "code": "UPS_TRANSPORT_ERROR",
        "message": "UPS transport request failed.",
        "retryable": True,
    },
    "unknown": {
        "code": "UPS_UNKNOWN_ERROR",
        "message": "UPS request failed unexpectedly.",
        "retryable": False,
    },
}

_VALIDATION_ERROR_CODES = {
    "BAD_REQUEST",
    "ELICITATION_CANCELLED",
    "ELICITATION_DECLINED",
    "ELICITATION_FAILED",
    "ELICITATION_INVALID_RESPONSE",
    "ELICITATION_MAX_RETRIES",
    "ELICITATION_UNSUPPORTED",
    "INVALID_REQUEST",
    "MALFORMED_REQUEST",
    "STRUCTURAL_FIELDS_REQUIRED",
    "VALIDATION_ERROR",
}

_HTTP_REASON_PHRASES = (
    "Bad Request",
    "Unauthorized",
    "Forbidden",
    "Request Timeout",
    "Too Many Requests",
    "Internal Server Error",
    "Bad Gateway",
    "Service Unavailable",
    "Gateway Timeout",
)


class ShipAgentNormalizationError(ValueError):
    """Raised when a UPS payload cannot satisfy the hosted-v1 contract."""


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
            "category": "normalization",
            "code": "UPS_NORMALIZATION_ERROR",
            "message": "UPS response could not be normalized.",
            "correlation_id": correlation_id,
            "retryable": False,
        },
    }


def to_safe_error(exc: BaseException, correlation_id: str) -> dict[str, Any]:
    category = _classify_exception(exc)
    if category == "normalization":
        return to_normalization_error(correlation_id)

    public_error = _CATEGORY_TO_PUBLIC_ERROR.get(category, _CATEGORY_TO_PUBLIC_ERROR["unknown"])
    return {
        "success": False,
        "error": {
            "category": category if category in _CATEGORY_TO_PUBLIC_ERROR else "unknown",
            "code": public_error["code"],
            "message": public_error["message"],
            "correlation_id": correlation_id,
            "retryable": public_error["retryable"],
        },
    }


def normalize_rate_result(raw: Mapping[str, Any], requestoption: str, correlation_id: str) -> dict[str, Any]:
    option = _required_hosted_string(requestoption, "requestoption").lower()
    if option not in _RATE_QUOTE_OPTIONS and option not in _RATE_SHOP_OPTIONS:
        raise ShipAgentNormalizationError("Unsupported rate request option.")
    normalized_correlation_id = _required_hosted_string(correlation_id, "correlationId")

    rated_shipments = _rated_shipments(
        _required_mapping(
            _required_mapping(raw, "RateResponse envelope").get("RateResponse"),
            "RateResponse",
        ).get("RatedShipment")
    )
    if not rated_shipments:
        raise ShipAgentNormalizationError("RateResponse.RatedShipment is required.")

    normalized_shipments: list[dict[str, Any]] = []
    for rated in rated_shipments:
        normalized_shipment = _normalize_rate_shipment(rated)
        if normalized_shipment is None:
            raise ShipAgentNormalizationError("RatedShipment is incomplete.")
        normalized_shipments.append(normalized_shipment)

    if option in _RATE_QUOTE_OPTIONS:
        if len(normalized_shipments) != 1:
            raise ShipAgentNormalizationError("Rate quote requires exactly one RatedShipment.")
        shipment = normalized_shipments[0]
        return {
            "success": True,
            "correlationId": normalized_correlation_id,
            **shipment,
        }

    return {
        "success": True,
        "correlationId": normalized_correlation_id,
        "ratedShipments": normalized_shipments,
    }


def _classify_exception(exc: BaseException) -> str:
    if isinstance(exc, ShipAgentNormalizationError):
        return "normalization"

    exception_text = str(exc)
    payload = _parse_exception_payload(exc)
    status_code = _coerce_http_status(
        payload.get("status_code")
        or payload.get("statusCode")
        or payload.get("status")
    )
    raw_code = _first_string(
        payload.get("code"),
        payload.get("error_code"),
        payload.get("errorCode"),
    )
    raw_message = _first_string(
        payload.get("message"),
        payload.get("error"),
        payload.get("detail"),
    )
    code = _clean_string(raw_code)
    message = _clean_string(raw_message)
    code_upper = (code or "").upper()
    code_status = _coerce_http_status(code)
    if status_code is None:
        status_code = code_status
    if status_code is None:
        status_code = _coerce_status_from_text(raw_message)
    if status_code is None and not payload:
        status_code = _coerce_status_from_text(exception_text)
    classifier_text = _classifier_text(raw_code, raw_message, exception_text if not payload else None)

    if status_code in {401, 403} or code_upper in {
        "AUTH_ERROR",
        "AUTHENTICATION_ERROR",
        "UNAUTHORIZED",
        "FORBIDDEN",
    }:
        return "auth"
    if status_code == 429 or code_upper in {"RATE_LIMIT", "RATE_LIMITED", "TOO_MANY_REQUESTS"}:
        return "rate_limit"
    if status_code == 408:
        return "transport"
    if status_code is not None and 400 <= status_code < 500:
        return "validation"
    if status_code is not None and status_code >= 500:
        return "service_unavailable"
    if code_upper in _VALIDATION_ERROR_CODES:
        return "validation"
    if _looks_like_validation_text(classifier_text):
        return "validation"
    if code_upper in {
        "REQUEST_ERROR",
        "REQUEST_TIMEOUT",
        "TRANSPORT_ERROR",
        "NETWORK_ERROR",
    }:
        return "transport"
    if "connection" in classifier_text or "timeout" in classifier_text or "network" in classifier_text:
        return "transport"
    return "unknown"


def _parse_exception_payload(exc: BaseException) -> dict[str, Any]:
    try:
        loaded = json.loads(str(exc))
    except (TypeError, ValueError):
        return {}
    return dict(loaded) if isinstance(loaded, Mapping) else {}


def _coerce_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        stripped = value.strip()
        if stripped:
            try:
                return int(stripped)
            except ValueError:
                return None
    return None


def _coerce_http_status(value: Any) -> int | None:
    if isinstance(value, str) and re.fullmatch(r"[1-5][0-9]{2}", value.strip()) is None:
        return None
    status = _coerce_int(value)
    if status is None or status < 100 or status > 599:
        return None
    return status


def _coerce_status_from_text(value: str | None) -> int | None:
    if value is None:
        return None
    match = re.search(
        r"\b(?:HTTPError|HTTP status|status(?: code)?)\D{0,20}([1-5][0-9]{2})\b",
        value,
        re.IGNORECASE,
    )
    if match:
        return int(match.group(1))

    match = re.search(
        r"\b([1-5][0-9]{2})\s+(?:Client|Server) Error\b",
        value,
        re.IGNORECASE,
    )
    if match:
        return int(match.group(1))

    reason_pattern = "|".join(re.escape(phrase) for phrase in _HTTP_REASON_PHRASES)
    match = re.search(rf"\b([1-5][0-9]{{2}})\s+(?:{reason_pattern})\b", value, re.IGNORECASE)
    return int(match.group(1)) if match else None


def _first_string(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str):
            return value
    return None


def _classifier_text(*values: str | None) -> str:
    return " ".join(value for value in values if value).lower()


def _looks_like_validation_text(value: str) -> bool:
    return any(
        re.search(pattern, value)
        for pattern in (
            r"\binvalid [a-z_]+",
            r"\ballowed values:",
            r"\bmust be (?:a |one of:|before\b)",
            r"\bis required\b",
            r"\brequires\b.*\bvia\b",
            r"\bmissing required key\b",
        )
    )


def _rated_shipments(value: Any) -> list[Mapping[str, Any]]:
    if value is None:
        return []
    if isinstance(value, Mapping):
        return [value]
    if isinstance(value, list):
        shipments: list[Mapping[str, Any]] = []
        for item in value:
            if not isinstance(item, Mapping):
                raise ShipAgentNormalizationError("RatedShipment entries must be objects.")
            shipments.append(item)
        return shipments
    raise ShipAgentNormalizationError("RatedShipment must be an object or list.")


def _normalize_rate_shipment(
    rated: Mapping[str, Any], *, require_service_code: bool = True
) -> dict[str, Any] | None:
    service = _optional_mapping(rated.get("Service"), "RatedShipment.Service")
    if service is None:
        return None
    service_code = _optional_hosted_string(service.get("Code"), "Service.Code")
    if require_service_code and service_code is None:
        return None

    total_charge = _extract_total_charge(rated)
    if total_charge is None:
        return None

    normalized: dict[str, Any] = {
        "totalCharges": total_charge,
    }
    if service_code is not None:
        normalized["serviceCode"] = service_code
    service_description = _optional_hosted_string(
        service.get("Description"), "Service.Description"
    )
    if service_description is not None:
        normalized["serviceDescription"] = service_description
    return normalized


def _extract_total_charge(rated: Mapping[str, Any]) -> dict[str, str] | None:
    if "NegotiatedRateCharges" in rated:
        negotiated = _required_mapping(
            rated.get("NegotiatedRateCharges"),
            "NegotiatedRateCharges",
        )
        return _normalize_charge(
            negotiated.get("TotalCharge"),
            "NegotiatedRateCharges.TotalCharge",
            require_complete=True,
        )
    return _normalize_charge(
        rated.get("TotalCharges"),
        "TotalCharges",
        require_complete=False,
    )


def _normalize_charge(
    value: Any, field_name: str, *, require_complete: bool
) -> dict[str, str] | None:
    if value is None:
        if require_complete:
            raise ShipAgentNormalizationError(f"{field_name} is required.")
        return None
    charge = _required_mapping(value, field_name)
    monetary_value = _optional_hosted_string(
        charge.get("MonetaryValue"), f"{field_name}.MonetaryValue"
    )
    currency_code = _optional_hosted_string(
        charge.get("CurrencyCode"), f"{field_name}.CurrencyCode"
    )
    if monetary_value is None or currency_code is None:
        if require_complete:
            raise ShipAgentNormalizationError(f"{field_name} is incomplete.")
        return None
    if not _is_currency_code(currency_code):
        raise ShipAgentNormalizationError(f"{field_name}.CurrencyCode is invalid.")
    return {"monetaryValue": monetary_value, "currencyCode": currency_code}


def _optional_mapping(value: Any, field_name: str) -> Mapping[str, Any] | None:
    if value is None:
        return None
    return _required_mapping(value, field_name)


def _required_mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ShipAgentNormalizationError(f"{field_name} must be an object.")
    return value


def _required_hosted_string(value: Any, field_name: str) -> str:
    normalized = _optional_hosted_string(value, field_name)
    if normalized is None:
        raise ShipAgentNormalizationError(f"{field_name} is required.")
    return normalized


def _optional_hosted_string(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ShipAgentNormalizationError(f"{field_name} must be a string.")
    if _has_ascii_control(value):
        raise ShipAgentNormalizationError(f"{field_name} contains ASCII control characters.")
    stripped = value.strip()
    if not stripped:
        return None
    return stripped


def _is_currency_code(value: str) -> bool:
    return re.fullmatch(r"[A-Z]{3}", value) is not None


def _as_mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _clean_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if not stripped or _has_ascii_control(stripped):
        return None
    return stripped


def _has_ascii_control(value: str) -> bool:
    return any(ord(char) < 32 or ord(char) == 127 for char in value)
