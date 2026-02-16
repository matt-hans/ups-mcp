"""Rating preflight validation, defaults, and canonicalization.

Mirrors the shipment_validator pattern for RateRequest bodies. Reuses
shared sub-path rules (PACKAGE_RULES, PAYMENT_*, COUNTRY_CONDITIONAL_RULES)
from shipment_validator with RateRequest.* root path prefix.

Pure functions — no MCP/protocol dependencies.
"""

from __future__ import annotations

import copy
from typing import Any

from .elicitation import (
    FieldRule,
    MissingField,
    _missing_from_rule,
    _field_exists,
    _set_field,
)
from .shipment_validator import (
    PACKAGE_RULES,
    PAYMENT_CHARGE_TYPE_RULE as _SHIP_PAYMENT_CHARGE_TYPE_RULE,
    PAYMENT_PAYER_RULES as _SHIP_PAYMENT_PAYER_RULES,
    COUNTRY_CONDITIONAL_RULES,
    EU_COUNTRIES,
    AmbiguousPayerError,
    _PAYER_OBJECT_KEYS,
    _normalize_list_field,
)


# ---------------------------------------------------------------------------
# Rating-specific unconditional rules
# ---------------------------------------------------------------------------

RATE_UNCONDITIONAL_RULES: list[FieldRule] = [
    FieldRule("RateRequest.Shipment.Shipper.Name", "shipper_name", "Shipper name"),
    FieldRule("RateRequest.Shipment.Shipper.ShipperNumber", "shipper_number", "UPS account number"),
    FieldRule("RateRequest.Shipment.Shipper.Address.AddressLine[0]", "shipper_address_line_1", "Shipper street address"),
    FieldRule("RateRequest.Shipment.Shipper.Address.City", "shipper_city", "Shipper city"),
    FieldRule(
        "RateRequest.Shipment.Shipper.Address.CountryCode",
        "shipper_country_code", "Shipper country code",
        constraints=(("maxLength", 2), ("pattern", "^[A-Z]{2}$")),
    ),
    FieldRule("RateRequest.Shipment.ShipTo.Name", "ship_to_name", "Recipient name"),
    FieldRule("RateRequest.Shipment.ShipTo.Address.AddressLine[0]", "ship_to_address_line_1", "Recipient street address"),
    FieldRule("RateRequest.Shipment.ShipTo.Address.City", "ship_to_city", "Recipient city"),
    FieldRule(
        "RateRequest.Shipment.ShipTo.Address.CountryCode",
        "ship_to_country_code", "Recipient country code",
        constraints=(("maxLength", 2), ("pattern", "^[A-Z]{2}$")),
    ),
]

# Service.Code is conditional — NOT required when requestoption is Shop/Shoptimeintransit
RATE_SERVICE_CODE_RULE: FieldRule = FieldRule(
    "RateRequest.Shipment.Service.Code", "service_code",
    "UPS service type",
    enum_values=(
        "01", "02", "03", "07", "08", "11", "12", "13", "14",
        "17", "54", "59", "65", "72", "74",
    ),
    enum_titles=(
        "Next Day Air", "2nd Day Air", "Ground",
        "Express", "Expedited", "UPS Standard",
        "3 Day Select", "Next Day Air Saver", "Next Day Air Early",
        "Worldwide Economy DDU", "Express Plus", "2nd Day Air A.M.",
        "UPS Saver", "Worldwide Economy DDP", "UPS Express 12:00",
    ),
)


# ---------------------------------------------------------------------------
# Rating-specific payment rules (RateRequest.* root paths)
# ---------------------------------------------------------------------------

RATE_PAYMENT_CHARGE_TYPE_RULE: FieldRule = FieldRule(
    "RateRequest.Shipment.PaymentInformation.ShipmentCharge[0].Type",
    "payment_charge_type",
    "Shipment charge type",
    enum_values=("01", "02"),
    enum_titles=("Transportation", "Duties and Taxes"),
    default="01",
)

RATE_PAYMENT_PAYER_RULES: dict[str, FieldRule] = {
    "BillShipper": FieldRule(
        "RateRequest.Shipment.PaymentInformation.ShipmentCharge[0].BillShipper.AccountNumber",
        "payment_account_number",
        "Billing account number",
    ),
    "BillReceiver": FieldRule(
        "RateRequest.Shipment.PaymentInformation.ShipmentCharge[0].BillReceiver.AccountNumber",
        "payment_account_number",
        "Billing account number",
    ),
    "BillThirdParty": FieldRule(
        "RateRequest.Shipment.PaymentInformation.ShipmentCharge[0].BillThirdParty.AccountNumber",
        "payment_account_number",
        "Billing account number",
    ),
}


# ---------------------------------------------------------------------------
# Rating-specific international rules
# ---------------------------------------------------------------------------

RATE_INTL_DESCRIPTION_RULE: FieldRule = FieldRule(
    "RateRequest.Shipment.Description", "shipment_description",
    "Description of goods (required for international)",
    constraints=(("maxLength", 50),),
)

RATE_INTL_SHIPPER_CONTACT_RULES: list[FieldRule] = [
    FieldRule(
        "RateRequest.Shipment.Shipper.AttentionName",
        "shipper_attention_name",
        "Shipper attention name",
        constraints=(("maxLength", 35),),
    ),
    FieldRule(
        "RateRequest.Shipment.Shipper.Phone.Number",
        "shipper_phone",
        "Shipper phone number",
        constraints=(("maxLength", 15),),
    ),
]

RATE_SHIP_TO_CONTACT_RULES: list[FieldRule] = [
    FieldRule(
        "RateRequest.Shipment.ShipTo.AttentionName",
        "ship_to_attention_name",
        "Recipient attention name",
        constraints=(("maxLength", 35),),
    ),
    FieldRule(
        "RateRequest.Shipment.ShipTo.Phone.Number",
        "ship_to_phone",
        "Recipient phone number",
        constraints=(("maxLength", 15),),
    ),
]

RATE_INVOICE_LINE_TOTAL_RULES: list[FieldRule] = [
    FieldRule(
        "RateRequest.Shipment.InvoiceLineTotal.CurrencyCode",
        "invoice_currency_code",
        "Invoice currency code (e.g. USD)",
        constraints=(("maxLength", 3), ("pattern", "^[A-Z]{3}$")),
    ),
    FieldRule(
        "RateRequest.Shipment.InvoiceLineTotal.MonetaryValue",
        "invoice_monetary_value",
        "Invoice total monetary value",
        constraints=(("maxLength", 11), ("pattern", r"^\d+(\.\d{1,2})?$")),
    ),
]


# ---------------------------------------------------------------------------
# Rating-specific 3-tier defaults
# ---------------------------------------------------------------------------

RATE_BUILT_IN_DEFAULTS: dict[str, str] = {
    "RateRequest.Shipment.PaymentInformation.ShipmentCharge[0].Type": "01",
}

RATE_ENV_DEFAULTS: dict[str, str] = {
    "RateRequest.Shipment.Shipper.ShipperNumber": "UPS_ACCOUNT_NUMBER",
}


# ---------------------------------------------------------------------------
# Body canonicalization
# ---------------------------------------------------------------------------

def canonicalize_rate_body(request_body: dict) -> dict:
    """Return a deep copy of request_body with Package and ShipmentCharge
    normalized to list form for RateRequest bodies.
    """
    result = copy.deepcopy(request_body)

    if not isinstance(result, dict):
        raise TypeError(
            f"Expected dict at request body root, got {type(result).__name__}"
        )

    rate_request = result.get("RateRequest")
    if rate_request is None:
        return result
    if not isinstance(rate_request, dict):
        raise TypeError(
            f"Expected dict at 'RateRequest', got {type(rate_request).__name__}"
        )

    shipment = rate_request.get("Shipment")
    if shipment is None:
        return result
    if not isinstance(shipment, dict):
        raise TypeError(
            f"Expected dict at 'RateRequest.Shipment', got {type(shipment).__name__}"
        )

    _normalize_list_field(shipment, "Package")

    payment = shipment.get("PaymentInformation")
    if payment is None:
        return result
    if not isinstance(payment, dict):
        raise TypeError(
            "Expected dict at 'RateRequest.Shipment.PaymentInformation', "
            f"got {type(payment).__name__}"
        )

    _normalize_list_field(payment, "ShipmentCharge")
    return result


def remap_packaging_for_rating(body: dict) -> dict:
    """Rename Packaging → PackagingType in each package for the Rating API.

    The UPS Rating API uses ``PackagingType`` while the Shipping API uses
    ``Packaging``.  The MCP validator normalises to ``Packaging`` for both,
    so this remap is applied **after** validation, before the HTTP call.

    Returns a deep copy — the input dict is never mutated.
    """
    result = copy.deepcopy(body)
    packages = (
        result.get("RateRequest", {})
        .get("Shipment", {})
        .get("Package", [])
    )
    if isinstance(packages, dict):
        packages = [packages]
    for pkg in packages:
        if "Packaging" in pkg:
            pkg["PackagingType"] = pkg.pop("Packaging")
    return result


# ---------------------------------------------------------------------------
# 3-tier defaults application
# ---------------------------------------------------------------------------

def _has_rate_payer_object(request_body: dict) -> bool:
    """Check if any billing payer object exists in the first ShipmentCharge."""
    charge = (
        request_body
        .get("RateRequest", {})
        .get("Shipment", {})
        .get("PaymentInformation", {})
        .get("ShipmentCharge", [{}])
    )
    first_charge = charge[0] if isinstance(charge, list) and charge else (
        charge if isinstance(charge, dict) else {}
    )
    return any(key in first_charge for key in _PAYER_OBJECT_KEYS)


def apply_rate_defaults(request_body: dict, env_config: dict[str, str]) -> dict:
    """Apply 3-tier defaults for RateRequest bodies.

    Returns a new dict — does not mutate the input.
    """
    result = copy.deepcopy(request_body)

    # Built-in defaults (lowest priority)
    for dot_path, value in RATE_BUILT_IN_DEFAULTS.items():
        if not _field_exists(result, dot_path):
            _set_field(result, dot_path, value)

    # Env defaults (middle priority)
    for dot_path, env_var_name in RATE_ENV_DEFAULTS.items():
        env_value = env_config.get(env_var_name, "")
        if env_value and not _field_exists(result, dot_path):
            _set_field(result, dot_path, env_value)

    # Conditional env default: BillShipper.AccountNumber
    bill_shipper_path = "RateRequest.Shipment.PaymentInformation.ShipmentCharge[0].BillShipper.AccountNumber"
    account_number = env_config.get("UPS_ACCOUNT_NUMBER", "")
    if account_number and not _has_rate_payer_object(result) and not _field_exists(result, bill_shipper_path):
        _set_field(result, bill_shipper_path, account_number)

    return result


# ---------------------------------------------------------------------------
# Preflight validation
# ---------------------------------------------------------------------------

def _get_rate_packages(request_body: dict) -> list[dict]:
    """Extract the Package list from a (preferably canonical) RateRequest body."""
    shipment = request_body.get("RateRequest", {}).get("Shipment", {})
    packages = shipment.get("Package")
    if packages is None:
        return [{}]
    if isinstance(packages, list):
        return packages if packages else [{}]
    if isinstance(packages, dict):
        return [packages]
    return [{}]


def find_missing_rate_fields(
    request_body: dict,
    request_option: str = "Rate",
) -> list[MissingField]:
    """Check required fields for a RateRequest body and return those that are missing.

    Args:
        request_body: The RateRequest body (preferably canonical).
        request_option: The requestoption path param. When "Shop" or
            "Shoptimeintransit", Service.Code is not required (UPS returns
            all service rates).
    """
    body = canonicalize_rate_body(request_body)
    missing: list[MissingField] = []

    # Unconditional rules
    for rule in RATE_UNCONDITIONAL_RULES:
        if not _field_exists(body, rule.dot_path):
            missing.append(_missing_from_rule(rule))

    # Service.Code — conditional on requestoption
    is_shop = request_option.lower() in ("shop", "shoptimeintransit")
    if not is_shop:
        if not _field_exists(body, RATE_SERVICE_CODE_RULE.dot_path):
            missing.append(_missing_from_rule(RATE_SERVICE_CODE_RULE))

    # Payment: charge type is always required
    if not _field_exists(body, RATE_PAYMENT_CHARGE_TYPE_RULE.dot_path):
        missing.append(_missing_from_rule(RATE_PAYMENT_CHARGE_TYPE_RULE))

    # Payment: payer account conditional on billing object
    first_charge = (
        body
        .get("RateRequest", {})
        .get("Shipment", {})
        .get("PaymentInformation", {})
        .get("ShipmentCharge", [{}])
    )
    first_charge = first_charge[0] if first_charge else {}

    present_payers = [k for k in RATE_PAYMENT_PAYER_RULES if k in first_charge]
    if len(present_payers) > 1:
        raise AmbiguousPayerError(present_payers)

    payer_found = False
    for payer_key, rule in RATE_PAYMENT_PAYER_RULES.items():
        if payer_key in first_charge:
            payer_found = True
            if not _field_exists(body, rule.dot_path):
                missing.append(_missing_from_rule(rule))
            break
    if not payer_found:
        default_rule = RATE_PAYMENT_PAYER_RULES["BillShipper"]
        if not _field_exists(body, default_rule.dot_path):
            missing.append(_missing_from_rule(default_rule))

    # Per-package fields
    packages = _get_rate_packages(body)
    for i, pkg in enumerate(packages):
        n = i + 1
        for rule in PACKAGE_RULES:
            full_dot_path = f"RateRequest.Shipment.Package[{i}].{rule.dot_path}"
            flat_key = f"package_{n}_{rule.flat_key}"
            prompt = f"Package {n}: {rule.prompt}" if len(packages) > 1 else rule.prompt
            if not _field_exists(pkg, rule.dot_path):
                missing.append(_missing_from_rule(
                    rule, dot_path=full_dot_path, flat_key=flat_key, prompt=prompt,
                ))

    # Country-conditional fields
    shipment = body.get("RateRequest", {}).get("Shipment", {})
    for role, prefix in [("Shipper", "shipper"), ("ShipTo", "ship_to")]:
        address = shipment.get(role, {}).get("Address", {})
        if not isinstance(address, dict):
            continue
        country = str(address.get("CountryCode", "")).strip().upper()
        for countries, rules in COUNTRY_CONDITIONAL_RULES.items():
            if country in countries:
                for rule in rules:
                    full_dot_path = f"RateRequest.Shipment.{role}.Address.{rule.dot_path}"
                    flat_key = f"{prefix}_{rule.flat_key}"
                    prompt = f"{'Shipper' if role == 'Shipper' else 'Recipient'} {rule.prompt.lower()}"
                    if not _field_exists(address, rule.dot_path):
                        missing.append(_missing_from_rule(
                            rule, dot_path=full_dot_path, flat_key=flat_key, prompt=prompt,
                        ))

    # ----- International validation -----

    def _safe_country(obj: Any) -> str:
        if not isinstance(obj, dict):
            return ""
        addr = obj.get("Address", {})
        if not isinstance(addr, dict):
            return ""
        return str(addr.get("CountryCode", "")).strip().upper()

    ship_from_country = _safe_country(shipment.get("ShipFrom"))
    effective_origin = ship_from_country or _safe_country(shipment.get("Shipper"))
    ship_to_country = _safe_country(shipment.get("ShipTo"))
    _service = shipment.get("Service", {})
    service_code = str(
        (_service.get("Code", "")) if isinstance(_service, dict) else ""
    ).strip()
    is_international = (
        effective_origin and ship_to_country
        and effective_origin != ship_to_country
    )

    # Shipper contact rules (international only)
    if is_international:
        for rule in RATE_INTL_SHIPPER_CONTACT_RULES:
            if not _field_exists(body, rule.dot_path):
                missing.append(_missing_from_rule(rule))

    # ShipTo contact rules (international OR service "14")
    if is_international or service_code == "14":
        for rule in RATE_SHIP_TO_CONTACT_RULES:
            if not _field_exists(body, rule.dot_path):
                missing.append(_missing_from_rule(rule))

    # Shipment Description with UPS Letter and EU+Standard exemptions
    if is_international:
        packages = _get_rate_packages(body)
        all_ups_letter = all(
            str(pkg.get("Packaging", {}).get("Code", "")).strip() == "01"
            for pkg in packages
        ) if packages else False
        eu_to_eu_standard = (
            effective_origin in EU_COUNTRIES
            and ship_to_country in EU_COUNTRIES
            and service_code == "11"
        )
        if (
            not all_ups_letter
            and not eu_to_eu_standard
            and not _field_exists(body, RATE_INTL_DESCRIPTION_RULE.dot_path)
        ):
            missing.append(_missing_from_rule(RATE_INTL_DESCRIPTION_RULE))

    # InvoiceLineTotal for forward US→CA/PR
    is_return = shipment.get("ReturnService") is not None
    if (
        effective_origin == "US"
        and ship_to_country in ("CA", "PR")
        and not is_return
    ):
        for rule in RATE_INVOICE_LINE_TOTAL_RULES:
            if not _field_exists(body, rule.dot_path):
                missing.append(_missing_from_rule(rule))

    return missing
