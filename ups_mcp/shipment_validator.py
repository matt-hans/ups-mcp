"""Shipment preflight validation, elicitation schema generation, and rehydration.

Pure functions — no MCP/protocol dependencies. All functions are stateless
and safe to test in isolation.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field, create_model


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MissingField:
    """A required field that is absent from the request body."""
    dot_path: str   # e.g. "ShipmentRequest.Shipment.Shipper.Name"
    flat_key: str   # e.g. "shipper_name"
    prompt: str     # e.g. "Shipper name"


@dataclass(frozen=True)
class FieldRule:
    """A rule for a required field — either a full dot-path or a sub-path for packages."""
    dot_path: str
    flat_key: str
    prompt: str


# ---------------------------------------------------------------------------
# Required field rules — unconditional (non-package, non-conditional)
# ---------------------------------------------------------------------------

UNCONDITIONAL_RULES: list[FieldRule] = [
    FieldRule("ShipmentRequest.Request.RequestOption", "request_option", "Request option"),
    FieldRule("ShipmentRequest.Shipment.Shipper.Name", "shipper_name", "Shipper name"),
    FieldRule("ShipmentRequest.Shipment.Shipper.ShipperNumber", "shipper_number", "UPS account number"),
    FieldRule("ShipmentRequest.Shipment.Shipper.Address.AddressLine[0]", "shipper_address_line_1", "Shipper street address"),
    FieldRule("ShipmentRequest.Shipment.Shipper.Address.City", "shipper_city", "Shipper city"),
    FieldRule("ShipmentRequest.Shipment.Shipper.Address.CountryCode", "shipper_country_code", "Shipper country code"),
    FieldRule("ShipmentRequest.Shipment.ShipTo.Name", "ship_to_name", "Recipient name"),
    FieldRule("ShipmentRequest.Shipment.ShipTo.Address.AddressLine[0]", "ship_to_address_line_1", "Recipient street address"),
    FieldRule("ShipmentRequest.Shipment.ShipTo.Address.City", "ship_to_city", "Recipient city"),
    FieldRule("ShipmentRequest.Shipment.ShipTo.Address.CountryCode", "ship_to_country_code", "Recipient country code"),
    FieldRule("ShipmentRequest.Shipment.Service.Code", "service_code", "UPS service code (e.g. '03' for Ground)"),
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
    "Shipment charge type (01=Transportation, 02=Duties and Taxes)",
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
    FieldRule("Packaging.Code", "packaging_code", "Packaging type code"),
    FieldRule("PackageWeight.UnitOfMeasurement.Code", "weight_unit", "Weight unit (LBS or KGS)"),
    FieldRule("PackageWeight.Weight", "weight", "Package weight"),
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
        FieldRule("StateProvinceCode", "state", "State/province code"),
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
