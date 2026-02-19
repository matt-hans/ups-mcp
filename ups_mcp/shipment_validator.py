"""Shipment preflight validation, elicitation schema generation, and rehydration.

Pure functions — no MCP/protocol dependencies. All functions are stateless
and safe to test in isolation.
"""

from __future__ import annotations

import copy
from typing import Any

from .elicitation import FieldRule, MissingField, _missing_from_rule, _field_exists, _set_field, ArrayFieldRule, expand_array_fields
from .constants import (
    INTERNATIONAL_FORM_TYPES,
    FORMS_REQUIRING_PRODUCTS,
    FORMS_REQUIRING_CURRENCY,
    REASON_FOR_EXPORT_VALUES,
)


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
# International validation constants
# ---------------------------------------------------------------------------

EU_COUNTRIES: frozenset[str] = frozenset({
    "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR",
    "DE", "GR", "HU", "IE", "IT", "LV", "LT", "LU", "MT", "NL",
    "PL", "PT", "RO", "SK", "SI", "ES", "SE",
})

INTERNATIONAL_DESCRIPTION_RULE: FieldRule = FieldRule(
    "ShipmentRequest.Shipment.Description",
    "shipment_description",
    "Description of goods (required for international)",
    constraints=(("maxLength", 50),),
)

INTERNATIONAL_SHIPPER_CONTACT_RULES: list[FieldRule] = [
    FieldRule(
        "ShipmentRequest.Shipment.Shipper.AttentionName",
        "shipper_attention_name",
        "Shipper attention name",
        constraints=(("maxLength", 35),),
    ),
    FieldRule(
        "ShipmentRequest.Shipment.Shipper.Phone.Number",
        "shipper_phone",
        "Shipper phone number",
        constraints=(("maxLength", 15),),
    ),
]

SHIP_TO_CONTACT_RULES: list[FieldRule] = [
    FieldRule(
        "ShipmentRequest.Shipment.ShipTo.AttentionName",
        "ship_to_attention_name",
        "Recipient attention name",
        constraints=(("maxLength", 35),),
    ),
    FieldRule(
        "ShipmentRequest.Shipment.ShipTo.Phone.Number",
        "ship_to_phone",
        "Recipient phone number",
        constraints=(("maxLength", 15),),
    ),
]

INVOICE_LINE_TOTAL_RULES: list[FieldRule] = [
    FieldRule(
        "ShipmentRequest.Shipment.InvoiceLineTotal.CurrencyCode",
        "invoice_currency_code",
        "Invoice currency code (e.g. USD)",
        constraints=(("maxLength", 3), ("pattern", "^[A-Z]{3}$")),
    ),
    FieldRule(
        "ShipmentRequest.Shipment.InvoiceLineTotal.MonetaryValue",
        "invoice_monetary_value",
        "Invoice total monetary value",
        constraints=(("maxLength", 11), ("pattern", r"^\d+(\.\d{1,2})?$")),
    ),
]


# ---------------------------------------------------------------------------
# International Forms field rules
# ---------------------------------------------------------------------------

INTL_FORMS_FORM_TYPE_RULE: FieldRule = FieldRule(
    "ShipmentRequest.Shipment.ShipmentServiceOptions.InternationalForms.FormType",
    "intl_forms_form_type",
    "International form type",
    enum_values=tuple(INTERNATIONAL_FORM_TYPES.keys()),
    enum_titles=tuple(INTERNATIONAL_FORM_TYPES.values()),
)

INTL_FORMS_CURRENCY_CODE_RULE: FieldRule = FieldRule(
    "ShipmentRequest.Shipment.ShipmentServiceOptions.InternationalForms.CurrencyCode",
    "intl_forms_currency_code",
    "Currency code for international forms (e.g. USD, EUR, GBP)",
    constraints=(("maxLength", 3), ("pattern", "^[A-Z]{3}$")),
)

INTL_FORMS_REASON_FOR_EXPORT_RULE: FieldRule = FieldRule(
    "ShipmentRequest.Shipment.ShipmentServiceOptions.InternationalForms.ReasonForExport",
    "intl_forms_reason_for_export",
    "Reason for export",
    enum_values=REASON_FOR_EXPORT_VALUES,
    enum_titles=("Sale", "Gift", "Sample", "Return", "Repair", "Intercompany Data"),
)

INTL_FORMS_INVOICE_NUMBER_RULE: FieldRule = FieldRule(
    "ShipmentRequest.Shipment.ShipmentServiceOptions.InternationalForms.InvoiceNumber",
    "intl_forms_invoice_number",
    "Commercial invoice number",
    constraints=(("maxLength", 35),),
)

INTL_FORMS_INVOICE_DATE_RULE: FieldRule = FieldRule(
    "ShipmentRequest.Shipment.ShipmentServiceOptions.InternationalForms.InvoiceDate",
    "intl_forms_invoice_date",
    "Invoice date (YYYYMMDD format)",
    constraints=(("maxLength", 8), ("pattern", r"^\d{8}$")),
)

# ---------------------------------------------------------------------------
# International Forms — Product array rules (elicitable via flat forms)
# ---------------------------------------------------------------------------

PRODUCT_ITEM_RULES: tuple[FieldRule, ...] = (
    FieldRule("Description", "description", "Product description",
              constraints=(("maxLength", 35),)),
    FieldRule("Unit.Number", "quantity", "Quantity",
              type_hint=int, constraints=(("gt", 0),)),
    FieldRule("Unit.Value", "value", "Unit value ($)",
              type_hint=float, constraints=(("gt", 0),)),
    FieldRule("Unit.UnitOfMeasurement.Code", "unit_code", "Unit of measure",
              enum_values=("PCS", "BOX", "DZ", "EA", "KG", "LB", "PR"),
              enum_titles=("Pieces", "Box", "Dozen", "Each", "Kilogram", "Pound", "Pair"),
              default="PCS"),
    FieldRule("OriginCountryCode", "origin_country", "Country of origin",
              constraints=(("maxLength", 2), ("pattern", "^[A-Z]{2}$"))),
)

PRODUCT_ARRAY_RULE: ArrayFieldRule = ArrayFieldRule(
    array_dot_path="ShipmentRequest.Shipment.ShipmentServiceOptions.InternationalForms.Product",
    item_prefix="product",
    item_rules=PRODUCT_ITEM_RULES,
)

# ---------------------------------------------------------------------------
# International Forms — SoldTo (invoice recipient) rules
# Required for Invoice (01) and USMCA (04) forms.
# ---------------------------------------------------------------------------

SOLD_TO_RULES: list[FieldRule] = [
    FieldRule(
        "ShipmentRequest.Shipment.ShipmentServiceOptions.InternationalForms.Contacts.SoldTo.Name",
        "sold_to_name", "Sold-to party name",
        constraints=(("maxLength", 35),),
    ),
    FieldRule(
        "ShipmentRequest.Shipment.ShipmentServiceOptions.InternationalForms.Contacts.SoldTo.AttentionName",
        "sold_to_attention_name", "Sold-to attention name",
        constraints=(("maxLength", 35),),
    ),
    FieldRule(
        "ShipmentRequest.Shipment.ShipmentServiceOptions.InternationalForms.Contacts.SoldTo.Phone.Number",
        "sold_to_phone", "Sold-to phone number",
        constraints=(("maxLength", 15),),
    ),
    FieldRule(
        "ShipmentRequest.Shipment.ShipmentServiceOptions.InternationalForms.Contacts.SoldTo.Address.AddressLine",
        "sold_to_address_line", "Sold-to street address",
    ),
    FieldRule(
        "ShipmentRequest.Shipment.ShipmentServiceOptions.InternationalForms.Contacts.SoldTo.Address.City",
        "sold_to_city", "Sold-to city",
    ),
    FieldRule(
        "ShipmentRequest.Shipment.ShipmentServiceOptions.InternationalForms.Contacts.SoldTo.Address.CountryCode",
        "sold_to_country_code", "Sold-to country code",
        constraints=(("maxLength", 2), ("pattern", "^[A-Z]{2}$")),
    ),
]


# ---------------------------------------------------------------------------
# International Forms helpers
# ---------------------------------------------------------------------------

def _get_intl_forms(shipment: dict) -> dict | None:
    """Extract InternationalForms from ShipmentServiceOptions, or None."""
    sso = shipment.get("ShipmentServiceOptions")
    if not isinstance(sso, dict):
        return None
    forms = sso.get("InternationalForms")
    return forms if isinstance(forms, dict) else None


def _get_form_types(intl_forms: dict) -> list[str]:
    """Extract FormType codes as a normalized list of strings."""
    ft = intl_forms.get("FormType")
    if isinstance(ft, str):
        return [ft]
    if isinstance(ft, list):
        return [str(f).strip() for f in ft if f]
    return []


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

    # ----- International validation -----

    # Determine effective origin: ShipFrom takes precedence over Shipper (spec line 5238)
    # Guard against non-dict nodes (e.g. Shipper="not_a_dict") to avoid AttributeError.
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
        for rule in INTERNATIONAL_SHIPPER_CONTACT_RULES:
            if not _field_exists(body, rule.dot_path):
                missing.append(_missing_from_rule(rule))

    # ShipTo contact rules (international OR service "14")
    if is_international or service_code == "14":
        for rule in SHIP_TO_CONTACT_RULES:
            if not _field_exists(body, rule.dot_path):
                missing.append(_missing_from_rule(rule))

    # Shipment Description with UPS Letter and EU+Standard exemptions
    if is_international:
        packages = _get_packages(body)
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
            and not _field_exists(body, INTERNATIONAL_DESCRIPTION_RULE.dot_path)
        ):
            missing.append(_missing_from_rule(INTERNATIONAL_DESCRIPTION_RULE))

    rs = shipment.get("ReturnService")
    is_return = isinstance(rs, dict) and bool(rs.get("Code"))
    if (
        effective_origin == "US"
        and ship_to_country in ("CA", "PR")
        and not is_return
    ):
        for rule in INVOICE_LINE_TOTAL_RULES:
            if not _field_exists(body, rule.dot_path):
                missing.append(_missing_from_rule(rule))

    # ----- InternationalForms validation -----

    if is_international:
        intl_forms = _get_intl_forms(shipment)

        # InternationalForms presence check (with exemptions)
        if (
            not all_ups_letter
            and not eu_to_eu_standard
            and intl_forms is None
        ):
            missing.append(MissingField(
                dot_path="ShipmentRequest.Shipment.ShipmentServiceOptions.InternationalForms",
                flat_key="intl_forms_required",
                prompt=(
                    "International shipments require InternationalForms. "
                    "Add ShipmentServiceOptions.InternationalForms to request_body with at least: "
                    "FormType (e.g. '01' for Invoice), CurrencyCode, ReasonForExport, "
                    "and a Product array. Example structure: "
                    '{"ShipmentServiceOptions": {"InternationalForms": {'
                    '"FormType": "01", "CurrencyCode": "USD", '
                    '"ReasonForExport": "SALE", "InvoiceNumber": "INV-001", '
                    '"InvoiceDate": "20260216", '
                    '"Product": [{"Description": "Electronics", '
                    '"Unit": {"Number": "1", "Value": "100", '
                    '"UnitOfMeasurement": {"Code": "PCS"}}, '
                    '"CommodityCode": "8471.30", "OriginCountryCode": "US"}]}}}'
                ),
                elicitable=False,
            ))

        # Sub-field checks when InternationalForms IS present
        if intl_forms is not None:
            form_types = _get_form_types(intl_forms)

            # FormType missing
            if not form_types:
                missing.append(_missing_from_rule(INTL_FORMS_FORM_TYPE_RULE))

            # Product array: expand into indexed elicitable fields
            if form_types and any(ft in FORMS_REQUIRING_PRODUCTS for ft in form_types):
                missing.extend(expand_array_fields(PRODUCT_ARRAY_RULE, body))

            # CurrencyCode missing for forms that require it (01, 05)
            if form_types and any(ft in FORMS_REQUIRING_CURRENCY for ft in form_types):
                if not _field_exists(intl_forms, "CurrencyCode"):
                    missing.append(_missing_from_rule(INTL_FORMS_CURRENCY_CODE_RULE))

            # Invoice-specific fields (form type 01)
            if "01" in form_types:
                if not _field_exists(intl_forms, "ReasonForExport"):
                    missing.append(_missing_from_rule(INTL_FORMS_REASON_FOR_EXPORT_RULE))
                if not _field_exists(intl_forms, "InvoiceNumber"):
                    missing.append(_missing_from_rule(INTL_FORMS_INVOICE_NUMBER_RULE))
                # InvoiceDate not required for returns
                if not is_return and not _field_exists(intl_forms, "InvoiceDate"):
                    missing.append(_missing_from_rule(INTL_FORMS_INVOICE_DATE_RULE))

            # SoldTo required for Invoice (01) and USMCA (04)
            if any(ft in ("01", "04") for ft in form_types):
                for rule in SOLD_TO_RULES:
                    if not _field_exists(body, rule.dot_path):
                        missing.append(_missing_from_rule(rule))

    # ----- Duties & Taxes payment check -----

    if is_international:
        charges = (
            body
            .get("ShipmentRequest", {})
            .get("Shipment", {})
            .get("PaymentInformation", {})
            .get("ShipmentCharge", [])
        )
        if isinstance(charges, list) and len(charges) >= 2:
            second_charge = charges[1] if isinstance(charges[1], dict) else {}
            if str(second_charge.get("Type", "")).strip() == "02":
                has_payer = any(
                    key in second_charge
                    for key in ("BillShipper", "BillReceiver", "BillThirdParty")
                )
                if not has_payer:
                    missing.append(MissingField(
                        dot_path="ShipmentRequest.Shipment.PaymentInformation.ShipmentCharge[1]",
                        flat_key="duties_payer_required",
                        prompt=(
                            "Duties and Taxes charge (ShipmentCharge[1] Type '02') requires a payer. "
                            "Add BillShipper, BillReceiver, or BillThirdParty with AccountNumber."
                        ),
                        elicitable=False,
                    ))

    return missing
