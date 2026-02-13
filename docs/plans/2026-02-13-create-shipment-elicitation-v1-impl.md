# Create Shipment Elicitation v1 — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add preflight validation and MCP form-mode elicitation to `create_shipment` so missing required fields are either collected from the user via `ctx.elicit()` or reported in a structured `ToolError`.

**Architecture:** New pure-logic `shipment_validator.py` module handles rules, defaults, flatten/unflatten, and post-elicitation normalization. `server.py::create_shipment` orchestrates: apply defaults → preflight → elicit (if supported) or ToolError → normalize → ToolManager. `tools.py` is unchanged.

**Tech Stack:** Python 3.14, Pydantic v2 (dynamic models), MCP Python SDK v1.26.0 (`Context.elicit()`, `ElicitationCapability`), unittest/IsolatedAsyncioTestCase.

---

## Shared Test Fixtures

The following helper will be used across multiple test files. Define it in the first test task and import in subsequent ones.

```python
# tests/shipment_fixtures.py

def make_complete_body(
    shipper_country: str = "US",
    ship_to_country: str = "US",
    num_packages: int = 1,
) -> dict:
    """Return a minimal-but-complete ShipmentRequest body.

    Package is always returned as a list for internal consistency.
    """
    packages = []
    for _ in range(num_packages):
        packages.append({
            "Packaging": {"Code": "02"},
            "PackageWeight": {
                "UnitOfMeasurement": {"Code": "LBS"},
                "Weight": "5",
            },
        })
    body = {
        "ShipmentRequest": {
            "Request": {"RequestOption": "nonvalidate"},
            "Shipment": {
                "Shipper": {
                    "Name": "Test Shipper",
                    "ShipperNumber": "129D9Y",
                    "Address": {
                        "AddressLine": ["123 Main St"],
                        "City": "Timonium",
                        "StateProvinceCode": "MD",
                        "PostalCode": "21093",
                        "CountryCode": shipper_country,
                    },
                },
                "ShipTo": {
                    "Name": "Test Recipient",
                    "Address": {
                        "AddressLine": ["456 Oak Ave"],
                        "City": "New York",
                        "StateProvinceCode": "NY",
                        "PostalCode": "10001",
                        "CountryCode": ship_to_country,
                    },
                },
                "PaymentInformation": {
                    "ShipmentCharge": [{
                        "Type": "01",
                        "BillShipper": {"AccountNumber": "129D9Y"},
                    }],
                },
                "Service": {"Code": "03"},
                "Package": packages,
            },
        }
    }
    return body
```

---

### Task 1: Create data structures and field rules

**Files:**
- Create: `ups_mcp/shipment_validator.py`
- Create: `tests/__init__.py`
- Create: `tests/shipment_fixtures.py`
- Create: `tests/test_shipment_validator.py`

**Step 1: Create `tests/__init__.py`**

Write an empty `tests/__init__.py` so the `tests` directory is a proper Python package and `from tests.shipment_fixtures import ...` resolves correctly.

```python
# tests/__init__.py
```

**Step 2: Create the test fixture file**

Write `tests/shipment_fixtures.py` with the `make_complete_body()` function from the shared fixtures section above.

**Step 3: Write failing test for data structures**

Write `tests/test_shipment_validator.py`:

```python
import unittest

from ups_mcp.shipment_validator import (
    MissingField,
    FieldRule,
    UNCONDITIONAL_RULES,
    PACKAGE_RULES,
    PAYMENT_CHARGE_TYPE_RULE,
    PAYMENT_PAYER_RULES,
    COUNTRY_CONDITIONAL_RULES,
    BUILT_IN_DEFAULTS,
    ENV_DEFAULTS,
)


class DataStructureTests(unittest.TestCase):
    def test_missing_field_has_required_attrs(self) -> None:
        mf = MissingField(
            dot_path="ShipmentRequest.Shipment.Shipper.Name",
            flat_key="shipper_name",
            prompt="Shipper name",
        )
        self.assertEqual(mf.dot_path, "ShipmentRequest.Shipment.Shipper.Name")
        self.assertEqual(mf.flat_key, "shipper_name")
        self.assertEqual(mf.prompt, "Shipper name")

    def test_unconditional_rules_is_nonempty_list(self) -> None:
        self.assertIsInstance(UNCONDITIONAL_RULES, list)
        self.assertGreater(len(UNCONDITIONAL_RULES), 0)

    def test_package_rules_is_nonempty_list(self) -> None:
        self.assertIsInstance(PACKAGE_RULES, list)
        self.assertEqual(len(PACKAGE_RULES), 3)  # packaging code, weight unit, weight

    def test_payment_charge_type_rule_exists(self) -> None:
        self.assertIsInstance(PAYMENT_CHARGE_TYPE_RULE, FieldRule)
        self.assertEqual(PAYMENT_CHARGE_TYPE_RULE.flat_key, "payment_charge_type")

    def test_payment_payer_rules_has_bill_shipper(self) -> None:
        self.assertIn("BillShipper", PAYMENT_PAYER_RULES)
        rule = PAYMENT_PAYER_RULES["BillShipper"]
        self.assertEqual(rule.flat_key, "payment_account_number")

    def test_payment_payer_rules_has_bill_receiver(self) -> None:
        self.assertIn("BillReceiver", PAYMENT_PAYER_RULES)

    def test_payment_payer_rules_has_bill_third_party(self) -> None:
        self.assertIn("BillThirdParty", PAYMENT_PAYER_RULES)

    def test_country_conditional_rules_has_us_ca_pr(self) -> None:
        self.assertIn(("US", "CA", "PR"), COUNTRY_CONDITIONAL_RULES)

    def test_built_in_defaults_has_request_option(self) -> None:
        self.assertIn("ShipmentRequest.Request.RequestOption", BUILT_IN_DEFAULTS)
        self.assertEqual(
            BUILT_IN_DEFAULTS["ShipmentRequest.Request.RequestOption"],
            "nonvalidate",
        )

    def test_built_in_defaults_has_payment_charge_type(self) -> None:
        self.assertIn(
            "ShipmentRequest.Shipment.PaymentInformation.ShipmentCharge[0].Type",
            BUILT_IN_DEFAULTS,
        )

    def test_env_defaults_has_shipper_number(self) -> None:
        self.assertIn(
            "ShipmentRequest.Shipment.Shipper.ShipperNumber",
            ENV_DEFAULTS,
        )
        self.assertEqual(
            ENV_DEFAULTS["ShipmentRequest.Shipment.Shipper.ShipperNumber"],
            "UPS_ACCOUNT_NUMBER",
        )

    def test_env_defaults_does_not_have_bill_shipper_account(self) -> None:
        """BillShipper.AccountNumber is conditionally applied, not in ENV_DEFAULTS."""
        self.assertNotIn(
            "ShipmentRequest.Shipment.PaymentInformation.ShipmentCharge[0].BillShipper.AccountNumber",
            ENV_DEFAULTS,
        )


if __name__ == "__main__":
    unittest.main()
```

**Step 4: Run test to verify it fails**

Run: `python3 -m pytest tests/test_shipment_validator.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ups_mcp.shipment_validator'`

**Step 5: Implement shipment_validator.py with data structures**

Write `ups_mcp/shipment_validator.py`:

```python
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
```

**Step 6: Run test to verify it passes**

Run: `python3 -m pytest tests/test_shipment_validator.py -v`
Expected: All tests PASS

**Step 7: Commit**

```bash
git add ups_mcp/shipment_validator.py tests/__init__.py tests/shipment_fixtures.py tests/test_shipment_validator.py
git commit -m "feat: add shipment_validator data structures and field rules

Includes payment rules (charge type + billing account) and
tests/__init__.py for proper pytest import resolution."
```

---

### Task 2: Implement and test dict navigation helpers

**Files:**
- Modify: `ups_mcp/shipment_validator.py`
- Modify: `tests/test_shipment_validator.py`

**Step 1: Write failing tests for `_field_exists` and `_set_field`**

Append to `tests/test_shipment_validator.py`:

```python
from ups_mcp.shipment_validator import _field_exists, _set_field


class FieldExistsTests(unittest.TestCase):
    def test_simple_path(self) -> None:
        data = {"a": {"b": {"c": "value"}}}
        self.assertTrue(_field_exists(data, "a.b.c"))

    def test_missing_intermediate(self) -> None:
        data = {"a": {}}
        self.assertFalse(_field_exists(data, "a.b.c"))

    def test_missing_leaf(self) -> None:
        data = {"a": {"b": {}}}
        self.assertFalse(_field_exists(data, "a.b.c"))

    def test_empty_string_is_missing(self) -> None:
        data = {"a": {"b": ""}}
        self.assertFalse(_field_exists(data, "a.b"))

    def test_whitespace_only_is_missing(self) -> None:
        data = {"a": {"b": "   "}}
        self.assertFalse(_field_exists(data, "a.b"))

    def test_whitespace_with_tabs_is_missing(self) -> None:
        data = {"a": " \t\n "}
        self.assertFalse(_field_exists(data, "a"))

    def test_none_is_missing(self) -> None:
        data = {"a": None}
        self.assertFalse(_field_exists(data, "a"))

    def test_array_index(self) -> None:
        data = {"a": {"b": ["first", "second"]}}
        self.assertTrue(_field_exists(data, "a.b[0]"))
        self.assertTrue(_field_exists(data, "a.b[1]"))

    def test_array_index_out_of_bounds(self) -> None:
        data = {"a": {"b": ["only"]}}
        self.assertFalse(_field_exists(data, "a.b[1]"))

    def test_array_index_empty_list(self) -> None:
        data = {"a": {"b": []}}
        self.assertFalse(_field_exists(data, "a.b[0]"))

    def test_zero_value_is_present(self) -> None:
        data = {"a": 0}
        self.assertTrue(_field_exists(data, "a"))

    def test_false_value_is_present(self) -> None:
        data = {"a": False}
        self.assertTrue(_field_exists(data, "a"))


class SetFieldTests(unittest.TestCase):
    def test_simple_set(self) -> None:
        data: dict = {}
        _set_field(data, "a.b.c", "value")
        self.assertEqual(data, {"a": {"b": {"c": "value"}}})

    def test_set_array_index(self) -> None:
        data: dict = {}
        _set_field(data, "a.b[0]", "first")
        self.assertEqual(data, {"a": {"b": ["first"]}})

    def test_overwrites_leaf_value(self) -> None:
        data = {"a": {"b": "existing"}}
        _set_field(data, "a.b", "new")
        self.assertEqual(data["a"]["b"], "new")

    def test_creates_intermediate_dicts(self) -> None:
        data: dict = {}
        _set_field(data, "ShipmentRequest.Shipment.Shipper.Name", "Test")
        self.assertEqual(
            data["ShipmentRequest"]["Shipment"]["Shipper"]["Name"],
            "Test",
        )

    def test_raises_on_existing_non_dict_intermediate(self) -> None:
        """When an existing intermediate node is a string but we need a dict, raise."""
        data: dict = {"a": {"b": "was_a_string"}}
        with self.assertRaises(TypeError):
            _set_field(data, "a.b.c", "value")

    def test_raises_on_existing_non_list_intermediate(self) -> None:
        """When an existing intermediate should be a list but isn't, raise."""
        data: dict = {"a": {"b": "was_a_string"}}
        with self.assertRaises(TypeError):
            _set_field(data, "a.b[0]", "value")

    def test_preserves_existing_list_elements(self) -> None:
        data: dict = {"a": {"b": ["existing"]}}
        _set_field(data, "a.b[1]", "new")
        self.assertEqual(data["a"]["b"], ["existing", "new"])
```

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_shipment_validator.py::FieldExistsTests -v`
Expected: FAIL with `ImportError: cannot import name '_field_exists'`

**Step 3: Implement helpers**

Add to `ups_mcp/shipment_validator.py`:

```python
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
```

**Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_shipment_validator.py -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add ups_mcp/shipment_validator.py tests/test_shipment_validator.py
git commit -m "feat: add dict navigation helpers with whitespace and type safety

_field_exists treats whitespace-only strings as missing.
_set_field raises TypeError on existing incompatible intermediate
types instead of silently overwriting data."
```

---

### Task 3: Implement and test `apply_defaults`

**Files:**
- Modify: `ups_mcp/shipment_validator.py`
- Modify: `tests/test_shipment_validator.py`

**Step 1: Write failing tests**

Append to `tests/test_shipment_validator.py`:

```python
import copy
from tests.shipment_fixtures import make_complete_body
from ups_mcp.shipment_validator import apply_defaults


class ApplyDefaultsTests(unittest.TestCase):
    def test_empty_body_gets_builtin_defaults(self) -> None:
        result = apply_defaults({}, {})
        self.assertEqual(
            result["ShipmentRequest"]["Request"]["RequestOption"],
            "nonvalidate",
        )

    def test_empty_body_gets_payment_charge_type_default(self) -> None:
        result = apply_defaults({}, {})
        self.assertEqual(
            result["ShipmentRequest"]["Shipment"]["PaymentInformation"]["ShipmentCharge"][0]["Type"],
            "01",
        )

    def test_caller_value_overrides_builtin(self) -> None:
        body = {"ShipmentRequest": {"Request": {"RequestOption": "validate"}}}
        result = apply_defaults(body, {})
        self.assertEqual(
            result["ShipmentRequest"]["Request"]["RequestOption"],
            "validate",
        )

    def test_env_default_fills_shipper_number(self) -> None:
        body: dict = {"ShipmentRequest": {"Shipment": {"Shipper": {}}}}
        result = apply_defaults(body, {"UPS_ACCOUNT_NUMBER": "ABC123"})
        self.assertEqual(
            result["ShipmentRequest"]["Shipment"]["Shipper"]["ShipperNumber"],
            "ABC123",
        )

    def test_env_default_fills_bill_shipper_when_no_payer(self) -> None:
        """When no payer object exists, env default injects BillShipper.AccountNumber."""
        result = apply_defaults({}, {"UPS_ACCOUNT_NUMBER": "ABC123"})
        self.assertEqual(
            result["ShipmentRequest"]["Shipment"]["PaymentInformation"]["ShipmentCharge"][0]["BillShipper"]["AccountNumber"],
            "ABC123",
        )

    def test_env_default_skips_bill_shipper_when_bill_receiver_present(self) -> None:
        """When BillReceiver is present, env default must NOT inject BillShipper."""
        body = {
            "ShipmentRequest": {
                "Shipment": {
                    "PaymentInformation": {
                        "ShipmentCharge": [{"Type": "01", "BillReceiver": {"AccountNumber": "RCV456"}}]
                    }
                }
            }
        }
        result = apply_defaults(body, {"UPS_ACCOUNT_NUMBER": "ABC123"})
        first_charge = result["ShipmentRequest"]["Shipment"]["PaymentInformation"]["ShipmentCharge"][0]
        self.assertNotIn("BillShipper", first_charge)
        self.assertEqual(first_charge["BillReceiver"]["AccountNumber"], "RCV456")

    def test_env_default_skips_bill_shipper_when_bill_third_party_present(self) -> None:
        """When BillThirdParty is present, env default must NOT inject BillShipper."""
        body = {
            "ShipmentRequest": {
                "Shipment": {
                    "PaymentInformation": {
                        "ShipmentCharge": [{"Type": "01", "BillThirdParty": {"AccountNumber": "TRD789"}}]
                    }
                }
            }
        }
        result = apply_defaults(body, {"UPS_ACCOUNT_NUMBER": "ABC123"})
        first_charge = result["ShipmentRequest"]["Shipment"]["PaymentInformation"]["ShipmentCharge"][0]
        self.assertNotIn("BillShipper", first_charge)

    def test_env_default_fills_bill_shipper_when_bill_shipper_present_but_no_account(self) -> None:
        """When BillShipper exists but has no AccountNumber, env fills it."""
        body = {
            "ShipmentRequest": {
                "Shipment": {
                    "PaymentInformation": {
                        "ShipmentCharge": [{"Type": "01", "BillShipper": {}}]
                    }
                }
            }
        }
        result = apply_defaults(body, {"UPS_ACCOUNT_NUMBER": "ABC123"})
        # BillShipper is a payer object, but _has_payer_object returns True.
        # The conditional skips. BillShipper.AccountNumber stays empty.
        # This is correct — the caller explicitly chose BillShipper but
        # didn't provide the account. find_missing_fields will catch it.
        first_charge = result["ShipmentRequest"]["Shipment"]["PaymentInformation"]["ShipmentCharge"][0]
        self.assertNotIn("AccountNumber", first_charge.get("BillShipper", {}))

    def test_caller_value_overrides_env_default(self) -> None:
        body = {
            "ShipmentRequest": {
                "Shipment": {"Shipper": {"ShipperNumber": "CALLER_NUM"}}
            }
        }
        result = apply_defaults(body, {"UPS_ACCOUNT_NUMBER": "ENV_NUM"})
        self.assertEqual(
            result["ShipmentRequest"]["Shipment"]["Shipper"]["ShipperNumber"],
            "CALLER_NUM",
        )

    def test_empty_env_value_does_not_set(self) -> None:
        result = apply_defaults({}, {"UPS_ACCOUNT_NUMBER": ""})
        shipper = result.get("ShipmentRequest", {}).get("Shipment", {}).get("Shipper", {})
        self.assertNotIn("ShipperNumber", shipper)

    def test_does_not_mutate_input(self) -> None:
        body = {"ShipmentRequest": {"Request": {}}}
        original = copy.deepcopy(body)
        apply_defaults(body, {})
        self.assertEqual(body, original)
```

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_shipment_validator.py::ApplyDefaultsTests -v`
Expected: FAIL with `ImportError: cannot import name 'apply_defaults'`

**Step 3: Implement `apply_defaults`**

Add to `ups_mcp/shipment_validator.py`:

```python
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
```

**Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_shipment_validator.py -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add ups_mcp/shipment_validator.py tests/test_shipment_validator.py
git commit -m "feat: implement apply_defaults with 3-tier merge

Includes payment charge type (built-in) and conditional billing account (env, only when no payer object present)."
```

---

### Task 4: Implement and test `find_missing_fields` — unconditional + payment rules

**Files:**
- Modify: `ups_mcp/shipment_validator.py`
- Modify: `tests/test_shipment_validator.py`

**Step 1: Write failing tests**

Append to `tests/test_shipment_validator.py`:

```python
from ups_mcp.shipment_validator import find_missing_fields, MissingField, AmbiguousPayerError


class FindMissingFieldsUnconditionalTests(unittest.TestCase):
    def test_complete_body_returns_empty(self) -> None:
        body = make_complete_body()
        missing = find_missing_fields(body)
        self.assertEqual(missing, [])

    def test_empty_body_returns_all_fields(self) -> None:
        missing = find_missing_fields({})
        flat_keys = {mf.flat_key for mf in missing}
        self.assertIn("request_option", flat_keys)
        self.assertIn("shipper_name", flat_keys)
        self.assertIn("shipper_number", flat_keys)
        self.assertIn("shipper_address_line_1", flat_keys)
        self.assertIn("ship_to_name", flat_keys)
        self.assertIn("service_code", flat_keys)
        self.assertIn("package_1_packaging_code", flat_keys)
        self.assertIn("package_1_weight_unit", flat_keys)
        self.assertIn("package_1_weight", flat_keys)
        self.assertIn("payment_charge_type", flat_keys)
        self.assertIn("payment_account_number", flat_keys)

    def test_missing_shipper_name_detected(self) -> None:
        body = make_complete_body()
        del body["ShipmentRequest"]["Shipment"]["Shipper"]["Name"]
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertIn("shipper_name", flat_keys)

    def test_missing_ship_to_address_detected(self) -> None:
        body = make_complete_body()
        del body["ShipmentRequest"]["Shipment"]["ShipTo"]["Address"]["AddressLine"]
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertIn("ship_to_address_line_1", flat_keys)

    def test_missing_service_code_detected(self) -> None:
        body = make_complete_body()
        del body["ShipmentRequest"]["Shipment"]["Service"]
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertIn("service_code", flat_keys)

    def test_missing_payment_info_detected(self) -> None:
        body = make_complete_body()
        del body["ShipmentRequest"]["Shipment"]["PaymentInformation"]
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertIn("payment_charge_type", flat_keys)
        self.assertIn("payment_account_number", flat_keys)

    def test_bill_receiver_account_validated(self) -> None:
        """BillReceiver present but missing AccountNumber triggers validation."""
        body = make_complete_body()
        body["ShipmentRequest"]["Shipment"]["PaymentInformation"]["ShipmentCharge"] = [{
            "Type": "01",
            "BillReceiver": {},
        }]
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertIn("payment_account_number", flat_keys)
        # Dot path should point to BillReceiver, not BillShipper
        account_rule = [mf for mf in missing if mf.flat_key == "payment_account_number"]
        self.assertIn("BillReceiver", account_rule[0].dot_path)

    def test_bill_third_party_account_validated(self) -> None:
        """BillThirdParty present but missing AccountNumber triggers validation."""
        body = make_complete_body()
        body["ShipmentRequest"]["Shipment"]["PaymentInformation"]["ShipmentCharge"] = [{
            "Type": "01",
            "BillThirdParty": {},
        }]
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertIn("payment_account_number", flat_keys)
        account_rule = [mf for mf in missing if mf.flat_key == "payment_account_number"]
        self.assertIn("BillThirdParty", account_rule[0].dot_path)

    def test_bill_receiver_with_account_passes(self) -> None:
        """BillReceiver with AccountNumber present should not be flagged."""
        body = make_complete_body()
        body["ShipmentRequest"]["Shipment"]["PaymentInformation"]["ShipmentCharge"] = [{
            "Type": "01",
            "BillReceiver": {"AccountNumber": "RCV123"},
        }]
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertNotIn("payment_account_number", flat_keys)

    def test_no_billing_object_defaults_to_bill_shipper(self) -> None:
        """No billing object present defaults to requiring BillShipper.AccountNumber."""
        body = make_complete_body()
        body["ShipmentRequest"]["Shipment"]["PaymentInformation"]["ShipmentCharge"] = [{
            "Type": "01",
        }]
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertIn("payment_account_number", flat_keys)
        account_rule = [mf for mf in missing if mf.flat_key == "payment_account_number"]
        self.assertIn("BillShipper", account_rule[0].dot_path)

    def test_shipment_charge_as_dict_normalized(self) -> None:
        """ShipmentCharge as a dict (not list) should be normalized and validated."""
        body = make_complete_body()
        # Convert ShipmentCharge from list to dict
        body["ShipmentRequest"]["Shipment"]["PaymentInformation"]["ShipmentCharge"] = {
            "Type": "01",
            "BillShipper": {"AccountNumber": "129D9Y"},
        }
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertNotIn("payment_charge_type", flat_keys)
        self.assertNotIn("payment_account_number", flat_keys)

    def test_multiple_payer_objects_raises_ambiguous_error(self) -> None:
        """Multiple billing objects in the same ShipmentCharge raises AmbiguousPayerError."""
        body = make_complete_body()
        body["ShipmentRequest"]["Shipment"]["PaymentInformation"]["ShipmentCharge"] = [{
            "Type": "01",
            "BillShipper": {"AccountNumber": "ABC"},
            "BillReceiver": {"AccountNumber": "DEF"},
        }]
        with self.assertRaises(AmbiguousPayerError) as cm:
            find_missing_fields(body)
        self.assertIn("BillShipper", cm.exception.payer_keys)
        self.assertIn("BillReceiver", cm.exception.payer_keys)

    def test_three_payer_objects_raises_ambiguous_error(self) -> None:
        """All three billing objects present also raises AmbiguousPayerError."""
        body = make_complete_body()
        body["ShipmentRequest"]["Shipment"]["PaymentInformation"]["ShipmentCharge"] = [{
            "Type": "01",
            "BillShipper": {"AccountNumber": "A"},
            "BillReceiver": {"AccountNumber": "B"},
            "BillThirdParty": {"AccountNumber": "C"},
        }]
        with self.assertRaises(AmbiguousPayerError):
            find_missing_fields(body)

    def test_returns_missing_field_instances(self) -> None:
        body = make_complete_body()
        del body["ShipmentRequest"]["Shipment"]["Shipper"]["Name"]
        missing = find_missing_fields(body)
        shipper_name = [mf for mf in missing if mf.flat_key == "shipper_name"]
        self.assertEqual(len(shipper_name), 1)
        self.assertEqual(shipper_name[0].dot_path, "ShipmentRequest.Shipment.Shipper.Name")
        self.assertEqual(shipper_name[0].prompt, "Shipper name")

    def test_whitespace_value_treated_as_missing(self) -> None:
        body = make_complete_body()
        body["ShipmentRequest"]["Shipment"]["Shipper"]["Name"] = "   "
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertIn("shipper_name", flat_keys)
```

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_shipment_validator.py::FindMissingFieldsUnconditionalTests -v`
Expected: FAIL with `ImportError: cannot import name 'find_missing_fields'`

**Step 3: Implement `find_missing_fields`**

Add to `ups_mcp/shipment_validator.py`:

```python
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
    shipment = result.get("ShipmentRequest", {}).get("Shipment", {})
    _normalize_list_field(shipment, "Package")
    payment = shipment.get("PaymentInformation", {})
    _normalize_list_field(payment, "ShipmentCharge")
    return result


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
            missing.append(MissingField(rule.dot_path, rule.flat_key, rule.prompt))

    # Payment: charge type is always required
    if not _field_exists(body, PAYMENT_CHARGE_TYPE_RULE.dot_path):
        missing.append(MissingField(
            PAYMENT_CHARGE_TYPE_RULE.dot_path,
            PAYMENT_CHARGE_TYPE_RULE.flat_key,
            PAYMENT_CHARGE_TYPE_RULE.prompt,
        ))

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
                missing.append(MissingField(rule.dot_path, rule.flat_key, rule.prompt))
            break
    if not payer_found:
        # No billing object present — require BillShipper.AccountNumber
        default_rule = PAYMENT_PAYER_RULES["BillShipper"]
        if not _field_exists(body, default_rule.dot_path):
            missing.append(MissingField(
                default_rule.dot_path, default_rule.flat_key, default_rule.prompt,
            ))

    # Per-package fields — body is canonical so Package is always a list
    packages = _get_packages(body)
    for i, pkg in enumerate(packages):
        n = i + 1  # 1-indexed for user-facing flat keys
        for rule in PACKAGE_RULES:
            full_dot_path = f"ShipmentRequest.Shipment.Package[{i}].{rule.dot_path}"
            flat_key = f"package_{n}_{rule.flat_key}"
            prompt = f"Package {n}: {rule.prompt}" if len(packages) > 1 else rule.prompt
            if not _field_exists(pkg, rule.dot_path):
                missing.append(MissingField(full_dot_path, flat_key, prompt))

    # Country-conditional fields
    shipment = body.get("ShipmentRequest", {}).get("Shipment", {})
    for role, prefix in [("Shipper", "shipper"), ("ShipTo", "ship_to")]:
        address = shipment.get(role, {}).get("Address", {})
        country = str(address.get("CountryCode", "")).strip().upper()
        for countries, rules in COUNTRY_CONDITIONAL_RULES.items():
            if country in countries:
                for rule in rules:
                    full_dot_path = f"ShipmentRequest.Shipment.{role}.Address.{rule.dot_path}"
                    flat_key = f"{prefix}_{rule.flat_key}"
                    prompt = f"{'Shipper' if role == 'Shipper' else 'Recipient'} {rule.prompt.lower()}"
                    if not _field_exists(address, rule.dot_path):
                        missing.append(MissingField(full_dot_path, flat_key, prompt))

    return missing
```

**Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_shipment_validator.py -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add ups_mcp/shipment_validator.py tests/test_shipment_validator.py
git commit -m "feat: implement find_missing_fields with payment and package rules

Normalizes Package to list internally. Validates payment charge type
and billing account. Whitespace-only values treated as missing."
```

---

### Task 5: Test `find_missing_fields` — package edge cases

**Files:**
- Modify: `tests/test_shipment_validator.py`

**Step 1: Write tests for package handling edge cases**

Append to `tests/test_shipment_validator.py`:

```python
class FindMissingFieldsPackageTests(unittest.TestCase):
    def test_missing_package_key_emits_package_1_fields(self) -> None:
        body = make_complete_body()
        del body["ShipmentRequest"]["Shipment"]["Package"]
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertIn("package_1_packaging_code", flat_keys)
        self.assertIn("package_1_weight_unit", flat_keys)
        self.assertIn("package_1_weight", flat_keys)

    def test_empty_package_list_emits_package_1_fields(self) -> None:
        body = make_complete_body()
        body["ShipmentRequest"]["Shipment"]["Package"] = []
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertIn("package_1_weight", flat_keys)

    def test_single_dict_package_validates_as_index_0(self) -> None:
        """Package as a single dict (not list) is normalized and validated."""
        body = make_complete_body()
        # Convert Package from list to dict for this test
        pkg = body["ShipmentRequest"]["Shipment"]["Package"][0]
        body["ShipmentRequest"]["Shipment"]["Package"] = pkg
        self.assertIsInstance(body["ShipmentRequest"]["Shipment"]["Package"], dict)
        missing = find_missing_fields(body)
        pkg_missing = [mf for mf in missing if "package_" in mf.flat_key]
        self.assertEqual(pkg_missing, [])

    def test_multi_package_validates_each(self) -> None:
        body = make_complete_body(num_packages=2)
        body["ShipmentRequest"]["Shipment"]["Package"][1].pop("PackageWeight")
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertNotIn("package_1_weight", flat_keys)
        self.assertIn("package_2_weight", flat_keys)
        self.assertIn("package_2_weight_unit", flat_keys)

    def test_multi_package_prompts_include_index(self) -> None:
        body = make_complete_body(num_packages=2)
        body["ShipmentRequest"]["Shipment"]["Package"][0].pop("PackageWeight")
        missing = find_missing_fields(body)
        pkg1_weight = [mf for mf in missing if mf.flat_key == "package_1_weight"]
        self.assertEqual(len(pkg1_weight), 1)
        self.assertIn("Package 1", pkg1_weight[0].prompt)
```

**Step 2: Run tests**

Run: `python3 -m pytest tests/test_shipment_validator.py::FindMissingFieldsPackageTests -v`
Expected: All PASS

**Step 3: Commit**

```bash
git add tests/test_shipment_validator.py
git commit -m "test: add package edge case tests for find_missing_fields"
```

---

### Task 6: Test `find_missing_fields` — country-conditional rules

**Files:**
- Modify: `tests/test_shipment_validator.py`

**Step 1: Write tests for country-conditional behavior**

Append to `tests/test_shipment_validator.py`:

```python
class FindMissingFieldsCountryTests(unittest.TestCase):
    def test_us_address_requires_state_and_postal(self) -> None:
        body = make_complete_body(shipper_country="US")
        del body["ShipmentRequest"]["Shipment"]["Shipper"]["Address"]["StateProvinceCode"]
        del body["ShipmentRequest"]["Shipment"]["Shipper"]["Address"]["PostalCode"]
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertIn("shipper_state", flat_keys)
        self.assertIn("shipper_postal_code", flat_keys)

    def test_ca_address_requires_state_and_postal(self) -> None:
        body = make_complete_body(shipper_country="CA")
        del body["ShipmentRequest"]["Shipment"]["Shipper"]["Address"]["StateProvinceCode"]
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertIn("shipper_state", flat_keys)

    def test_pr_address_requires_state_and_postal(self) -> None:
        body = make_complete_body(ship_to_country="PR")
        del body["ShipmentRequest"]["Shipment"]["ShipTo"]["Address"]["PostalCode"]
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertIn("ship_to_postal_code", flat_keys)

    def test_gb_address_does_not_require_state(self) -> None:
        body = make_complete_body(shipper_country="GB")
        del body["ShipmentRequest"]["Shipment"]["Shipper"]["Address"]["StateProvinceCode"]
        del body["ShipmentRequest"]["Shipment"]["Shipper"]["Address"]["PostalCode"]
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertNotIn("shipper_state", flat_keys)
        self.assertNotIn("shipper_postal_code", flat_keys)

    def test_no_country_code_skips_conditional(self) -> None:
        body = make_complete_body()
        del body["ShipmentRequest"]["Shipment"]["Shipper"]["Address"]["CountryCode"]
        del body["ShipmentRequest"]["Shipment"]["Shipper"]["Address"]["StateProvinceCode"]
        del body["ShipmentRequest"]["Shipment"]["Shipper"]["Address"]["PostalCode"]
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertIn("shipper_country_code", flat_keys)
        self.assertNotIn("shipper_state", flat_keys)
        self.assertNotIn("shipper_postal_code", flat_keys)
```

**Step 2: Run tests**

Run: `python3 -m pytest tests/test_shipment_validator.py::FindMissingFieldsCountryTests -v`
Expected: All PASS

**Step 3: Commit**

```bash
git add tests/test_shipment_validator.py
git commit -m "test: add country-conditional tests for find_missing_fields"
```

---

### Task 7: Implement and test `build_elicitation_schema`

**Files:**
- Modify: `ups_mcp/shipment_validator.py`
- Modify: `tests/test_shipment_validator.py`

**Step 1: Write failing tests**

Append to `tests/test_shipment_validator.py`:

```python
from ups_mcp.shipment_validator import build_elicitation_schema
from pydantic import BaseModel


class BuildElicitationSchemaTests(unittest.TestCase):
    def test_schema_has_only_missing_fields(self) -> None:
        missing = [
            MissingField("a.b", "shipper_name", "Shipper name"),
            MissingField("c.d", "service_code", "Service code"),
        ]
        schema = build_elicitation_schema(missing)
        self.assertTrue(issubclass(schema, BaseModel))
        field_names = set(schema.model_fields.keys())
        self.assertEqual(field_names, {"shipper_name", "service_code"})

    def test_all_fields_are_str_type(self) -> None:
        missing = [
            MissingField("a.b", "shipper_name", "Shipper name"),
            MissingField("c.d", "package_1_weight", "Package weight"),
        ]
        schema = build_elicitation_schema(missing)
        for field_info in schema.model_fields.values():
            self.assertEqual(field_info.annotation, str)

    def test_field_descriptions_match_prompts(self) -> None:
        missing = [
            MissingField("a.b", "shipper_name", "Shipper name"),
        ]
        schema = build_elicitation_schema(missing)
        self.assertEqual(
            schema.model_fields["shipper_name"].description,
            "Shipper name",
        )

    def test_empty_missing_returns_valid_model(self) -> None:
        schema = build_elicitation_schema([])
        self.assertTrue(issubclass(schema, BaseModel))
        self.assertEqual(len(schema.model_fields), 0)
```

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_shipment_validator.py::BuildElicitationSchemaTests -v`
Expected: FAIL with `ImportError: cannot import name 'build_elicitation_schema'`

**Step 3: Implement `build_elicitation_schema`**

Add to `ups_mcp/shipment_validator.py`:

```python
def build_elicitation_schema(missing: list[MissingField]) -> type[BaseModel]:
    """Create a dynamic flat Pydantic model with one str field per missing field.

    All fields are required str types with descriptions from the MissingField prompts.
    This model is suitable for passing to ``ctx.elicit(schema=...)``.
    """
    field_definitions: dict[str, Any] = {}
    for mf in missing:
        field_definitions[mf.flat_key] = (str, Field(description=mf.prompt))
    return create_model("MissingShipmentFields", **field_definitions)
```

**Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_shipment_validator.py -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add ups_mcp/shipment_validator.py tests/test_shipment_validator.py
git commit -m "feat: implement build_elicitation_schema for dynamic Pydantic models"
```

---

### Task 8: Implement and test `normalize_elicited_values` and `rehydrate`

**Files:**
- Modify: `ups_mcp/shipment_validator.py`
- Modify: `tests/test_shipment_validator.py`

**Step 1: Write failing tests**

Append to `tests/test_shipment_validator.py`:

```python
from ups_mcp.shipment_validator import (
    normalize_elicited_values,
    rehydrate,
    canonicalize_body,
    RehydrationError,
)


class CanonicalizeBodyTests(unittest.TestCase):
    def test_package_dict_becomes_list(self) -> None:
        body = {"ShipmentRequest": {"Shipment": {"Package": {"Packaging": {"Code": "02"}}}}}
        result = canonicalize_body(body)
        pkg = result["ShipmentRequest"]["Shipment"]["Package"]
        self.assertIsInstance(pkg, list)
        self.assertEqual(len(pkg), 1)
        self.assertEqual(pkg[0]["Packaging"]["Code"], "02")

    def test_shipment_charge_dict_becomes_list(self) -> None:
        body = {
            "ShipmentRequest": {
                "Shipment": {
                    "PaymentInformation": {
                        "ShipmentCharge": {"Type": "01", "BillShipper": {"AccountNumber": "X"}}
                    }
                }
            }
        }
        result = canonicalize_body(body)
        sc = result["ShipmentRequest"]["Shipment"]["PaymentInformation"]["ShipmentCharge"]
        self.assertIsInstance(sc, list)
        self.assertEqual(sc[0]["Type"], "01")

    def test_already_lists_unchanged(self) -> None:
        body = make_complete_body()
        result = canonicalize_body(body)
        self.assertEqual(
            result["ShipmentRequest"]["Shipment"]["Package"],
            body["ShipmentRequest"]["Shipment"]["Package"],
        )

    def test_does_not_mutate_input(self) -> None:
        body = {"ShipmentRequest": {"Shipment": {"Package": {"Packaging": {"Code": "02"}}}}}
        original = copy.deepcopy(body)
        canonicalize_body(body)
        self.assertEqual(body, original)

    def test_missing_fields_tolerated(self) -> None:
        result = canonicalize_body({})
        self.assertEqual(result, {})

    def test_non_dict_list_elements_coerced_to_empty_dict(self) -> None:
        body = {
            "ShipmentRequest": {
                "Shipment": {
                    "Package": ["not_a_dict", 42, None],
                }
            }
        }
        result = canonicalize_body(body)
        pkgs = result["ShipmentRequest"]["Shipment"]["Package"]
        self.assertEqual(pkgs, [{}, {}, {}])

    def test_non_dict_shipment_charge_elements_coerced(self) -> None:
        body = {
            "ShipmentRequest": {
                "Shipment": {
                    "PaymentInformation": {
                        "ShipmentCharge": ["bad_element"],
                    }
                }
            }
        }
        result = canonicalize_body(body)
        charges = result["ShipmentRequest"]["Shipment"]["PaymentInformation"]["ShipmentCharge"]
        self.assertEqual(charges, [{}])

    def test_non_list_non_dict_package_becomes_empty_list(self) -> None:
        body = {"ShipmentRequest": {"Shipment": {"Package": "invalid"}}}
        result = canonicalize_body(body)
        self.assertEqual(result["ShipmentRequest"]["Shipment"]["Package"], [{}])


class NormalizeElicitedValuesTests(unittest.TestCase):
    def test_trims_whitespace(self) -> None:
        result = normalize_elicited_values({"shipper_name": "  Acme Corp  "})
        self.assertEqual(result["shipper_name"], "Acme Corp")

    def test_uppercases_country_codes(self) -> None:
        result = normalize_elicited_values({
            "shipper_country_code": "us",
            "ship_to_country_code": "ca",
        })
        self.assertEqual(result["shipper_country_code"], "US")
        self.assertEqual(result["ship_to_country_code"], "CA")

    def test_uppercases_state_codes(self) -> None:
        result = normalize_elicited_values({
            "shipper_state": "ny",
            "ship_to_state": "ca",
        })
        self.assertEqual(result["shipper_state"], "NY")
        self.assertEqual(result["ship_to_state"], "CA")

    def test_uppercases_weight_unit(self) -> None:
        result = normalize_elicited_values({"package_1_weight_unit": "lbs"})
        self.assertEqual(result["package_1_weight_unit"], "LBS")

    def test_strips_weight_value(self) -> None:
        result = normalize_elicited_values({"package_1_weight": " 5.0 "})
        self.assertEqual(result["package_1_weight"], "5.0")

    def test_preserves_other_values(self) -> None:
        result = normalize_elicited_values({"shipper_name": "Test Co"})
        self.assertEqual(result["shipper_name"], "Test Co")

    def test_removes_empty_values(self) -> None:
        result = normalize_elicited_values({
            "shipper_name": "Test",
            "service_code": "",
            "shipper_city": "   ",
        })
        self.assertIn("shipper_name", result)
        self.assertNotIn("service_code", result)
        self.assertNotIn("shipper_city", result)


class RehydrateTests(unittest.TestCase):
    def test_flat_data_creates_nested_structure(self) -> None:
        body: dict = {"ShipmentRequest": {"Shipment": {"Shipper": {}}}}
        missing = [
            MissingField(
                "ShipmentRequest.Shipment.Shipper.Name",
                "shipper_name",
                "Shipper name",
            ),
        ]
        result = rehydrate(body, {"shipper_name": "Acme Corp"}, missing)
        self.assertEqual(
            result["ShipmentRequest"]["Shipment"]["Shipper"]["Name"],
            "Acme Corp",
        )

    def test_address_line_becomes_array(self) -> None:
        body: dict = {"ShipmentRequest": {"Shipment": {"Shipper": {"Address": {}}}}}
        missing = [
            MissingField(
                "ShipmentRequest.Shipment.Shipper.Address.AddressLine[0]",
                "shipper_address_line_1",
                "Shipper street address",
            ),
        ]
        result = rehydrate(body, {"shipper_address_line_1": "123 Main St"}, missing)
        self.assertEqual(
            result["ShipmentRequest"]["Shipment"]["Shipper"]["Address"]["AddressLine"],
            ["123 Main St"],
        )

    def test_package_index_routes_correctly(self) -> None:
        body: dict = {
            "ShipmentRequest": {
                "Shipment": {"Package": [{"Packaging": {"Code": "02"}}, {}]}
            }
        }
        missing = [
            MissingField(
                "ShipmentRequest.Shipment.Package[1].PackageWeight.Weight",
                "package_2_weight",
                "Package 2: Package weight",
            ),
        ]
        result = rehydrate(body, {"package_2_weight": "10"}, missing)
        self.assertEqual(
            result["ShipmentRequest"]["Shipment"]["Package"][1]["PackageWeight"]["Weight"],
            "10",
        )

    def test_does_not_overwrite_existing(self) -> None:
        body = make_complete_body()
        original_name = body["ShipmentRequest"]["Shipment"]["Shipper"]["Name"]
        missing = [
            MissingField(
                "ShipmentRequest.Shipment.Shipper.Name",
                "shipper_name",
                "Shipper name",
            ),
        ]
        result = rehydrate(body, {"shipper_name": ""}, missing)
        self.assertEqual(
            result["ShipmentRequest"]["Shipment"]["Shipper"]["Name"],
            original_name,
        )

    def test_does_not_mutate_input(self) -> None:
        body: dict = {"ShipmentRequest": {"Shipment": {"Shipper": {}}}}
        original = copy.deepcopy(body)
        missing = [
            MissingField(
                "ShipmentRequest.Shipment.Shipper.Name",
                "shipper_name",
                "Shipper name",
            ),
        ]
        rehydrate(body, {"shipper_name": "Test"}, missing)
        self.assertEqual(body, original)

    def test_skips_unknown_flat_keys(self) -> None:
        body: dict = {"ShipmentRequest": {}}
        result = rehydrate(body, {"unknown_key": "value"}, [])
        self.assertEqual(result, {"ShipmentRequest": {}})

    def test_multi_package_rehydration(self) -> None:
        body: dict = {"ShipmentRequest": {"Shipment": {"Package": [{}, {}]}}}
        missing = [
            MissingField(
                "ShipmentRequest.Shipment.Package[0].PackageWeight.Weight",
                "package_1_weight",
                "Package weight",
            ),
            MissingField(
                "ShipmentRequest.Shipment.Package[1].PackageWeight.Weight",
                "package_2_weight",
                "Package 2: Package weight",
            ),
        ]
        result = rehydrate(
            body,
            {"package_1_weight": "5", "package_2_weight": "10"},
            missing,
        )
        self.assertEqual(
            result["ShipmentRequest"]["Shipment"]["Package"][0]["PackageWeight"]["Weight"],
            "5",
        )
        self.assertEqual(
            result["ShipmentRequest"]["Shipment"]["Package"][1]["PackageWeight"]["Weight"],
            "10",
        )

    def test_structural_conflict_raises_rehydration_error(self) -> None:
        """When _set_field hits a type conflict, RehydrationError is raised."""
        body: dict = {
            "ShipmentRequest": {
                "Shipment": {
                    "Shipper": {"Address": "not_a_dict"},
                }
            }
        }
        missing = [
            MissingField(
                "ShipmentRequest.Shipment.Shipper.Address.City",
                "shipper_city",
                "Shipper city",
            ),
        ]
        with self.assertRaises(RehydrationError) as cm:
            rehydrate(body, {"shipper_city": "NYC"}, missing)
        self.assertEqual(cm.exception.flat_key, "shipper_city")

    def test_normalizes_package_dict_to_list_during_rehydration(self) -> None:
        """If Package was a dict, rehydrate should still work via list normalization."""
        body: dict = {
            "ShipmentRequest": {"Shipment": {"Package": {"Packaging": {"Code": "02"}}}}
        }
        missing = [
            MissingField(
                "ShipmentRequest.Shipment.Package[0].PackageWeight.Weight",
                "package_1_weight",
                "Package weight",
            ),
        ]
        result = rehydrate(body, {"package_1_weight": "5"}, missing)
        pkg = result["ShipmentRequest"]["Shipment"]["Package"]
        self.assertIsInstance(pkg, list)
        self.assertEqual(pkg[0]["PackageWeight"]["Weight"], "5")
        # Original packaging preserved
        self.assertEqual(pkg[0]["Packaging"]["Code"], "02")
```

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_shipment_validator.py::NormalizeElicitedValuesTests -v`
Expected: FAIL with `ImportError: cannot import name 'normalize_elicited_values'`

**Step 3: Implement `normalize_elicited_values` and `rehydrate`**

Add to `ups_mcp/shipment_validator.py`:

```python
# Flat key patterns for normalization
_COUNTRY_CODE_KEYS = re.compile(r".*_country_code$")
_STATE_KEYS = re.compile(r".*_state$")
_WEIGHT_UNIT_KEYS = re.compile(r".*_weight_unit$")
_WEIGHT_KEYS = re.compile(r".*_weight$")


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


class AmbiguousPayerError(Exception):
    """Raised when multiple billing payer objects exist in the same ShipmentCharge."""
    def __init__(self, payer_keys: list[str]):
        self.payer_keys = payer_keys
        super().__init__(
            f"Ambiguous payer: multiple billing objects present ({', '.join(payer_keys)}). "
            f"Only one of BillShipper, BillReceiver, BillThirdParty is allowed per charge."
        )


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
        if not value:
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
```

**Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_shipment_validator.py -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add ups_mcp/shipment_validator.py tests/test_shipment_validator.py
git commit -m "feat: implement normalize_elicited_values and rehydrate

Post-elicitation normalization: trim, uppercase codes, remove empties.
Rehydrate normalizes Package dict to list for consistent structure."
```

---

### Task 9: Implement and test `_check_form_elicitation`

**Files:**
- Modify: `ups_mcp/server.py`
- Create: `tests/test_server_elicitation.py`

**Step 1: Write failing tests**

Write `tests/test_server_elicitation.py`:

```python
import unittest
from unittest.mock import MagicMock

from mcp.server.fastmcp import Context
from mcp.types import (
    ClientCapabilities,
    ElicitationCapability,
    FormElicitationCapability,
    UrlElicitationCapability,
    InitializeRequestParams,
    Implementation,
)

import ups_mcp.server as server


class CheckFormElicitationTests(unittest.TestCase):
    def _make_ctx(
        self,
        elicitation: ElicitationCapability | None = None,
    ) -> MagicMock:
        """Build a mock Context with the given elicitation capability."""
        ctx = MagicMock()
        caps = ClientCapabilities(elicitation=elicitation)
        params = InitializeRequestParams(
            protocolVersion="2025-03-26",
            capabilities=caps,
            clientInfo=Implementation(name="test", version="1.0"),
        )
        ctx.request_context.session._client_params = params
        ctx.request_context.session.client_params = params
        return ctx

    def test_none_ctx_returns_false(self) -> None:
        self.assertFalse(server._check_form_elicitation(None))

    def test_no_elicitation_capability_returns_false(self) -> None:
        ctx = self._make_ctx(elicitation=None)
        self.assertFalse(server._check_form_elicitation(ctx))

    def test_form_capability_returns_true(self) -> None:
        ctx = self._make_ctx(
            elicitation=ElicitationCapability(form=FormElicitationCapability())
        )
        self.assertTrue(server._check_form_elicitation(ctx))

    def test_empty_elicitation_object_returns_true(self) -> None:
        ctx = self._make_ctx(elicitation=ElicitationCapability())
        self.assertTrue(server._check_form_elicitation(ctx))

    def test_url_only_returns_false(self) -> None:
        ctx = self._make_ctx(
            elicitation=ElicitationCapability(url=UrlElicitationCapability())
        )
        self.assertFalse(server._check_form_elicitation(ctx))

    def test_both_form_and_url_returns_true(self) -> None:
        ctx = self._make_ctx(
            elicitation=ElicitationCapability(
                form=FormElicitationCapability(),
                url=UrlElicitationCapability(),
            )
        )
        self.assertTrue(server._check_form_elicitation(ctx))

    def test_attribute_error_returns_false(self) -> None:
        """Integration safety: if ctx has unexpected shape, return False."""
        ctx = MagicMock()
        ctx.request_context.session.client_params = None
        self.assertFalse(server._check_form_elicitation(ctx))

    def test_with_real_capability_objects(self) -> None:
        """Integration-style: use real Pydantic objects, minimal mocking."""
        ctx = MagicMock(spec=Context)
        caps = ClientCapabilities(
            elicitation=ElicitationCapability(form=FormElicitationCapability())
        )
        params = InitializeRequestParams(
            protocolVersion="2025-03-26",
            capabilities=caps,
            clientInfo=Implementation(name="real-client", version="2.0"),
        )
        ctx.request_context.session.client_params = params
        self.assertTrue(server._check_form_elicitation(ctx))


if __name__ == "__main__":
    unittest.main()
```

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_server_elicitation.py -v`
Expected: FAIL with `AttributeError: module 'ups_mcp.server' has no attribute '_check_form_elicitation'`

**Step 3: Implement `_check_form_elicitation`**

Add to `ups_mcp/server.py`, after the imports and before the tool definitions:

```python
from mcp.server.fastmcp import Context


def _check_form_elicitation(ctx: Context | None) -> bool:
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
```

**Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_server_elicitation.py -v`
Expected: All 8 tests PASS

**Step 5: Commit**

```bash
git add ups_mcp/server.py tests/test_server_elicitation.py
git commit -m "feat: implement _check_form_elicitation capability check

Includes integration-style test with real Pydantic capability objects."
```

---

### Task 10: Wire up orchestration in server.py `create_shipment`

**Files:**
- Modify: `ups_mcp/server.py`

**Step 1: Write failing integration tests**

Append to `tests/test_server_elicitation.py`:

```python
import json
from unittest.mock import AsyncMock

from mcp.server.fastmcp.exceptions import ToolError

from tests.shipment_fixtures import make_complete_body


class _FakeToolManager:
    """Minimal fake ToolManager for elicitation integration tests.

    Defined locally to avoid cross-test coupling with test_server_tools.py.
    """
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def create_shipment(self, **kwargs):
        self.calls.append(("create_shipment", kwargs))
        return {"ShipmentResponse": {"ShipmentResults": {}}}


class CreateShipmentElicitationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.original_tool_manager = server.tool_manager
        self.fake_tool_manager = _FakeToolManager()
        server.tool_manager = self.fake_tool_manager

    def tearDown(self) -> None:
        server.tool_manager = self.original_tool_manager

    def _make_ctx(
        self,
        form_supported: bool = False,
        elicit_result: object | None = None,
    ) -> MagicMock:
        """Build a mock Context with optional form elicitation."""
        ctx = MagicMock()
        if form_supported:
            caps = ClientCapabilities(
                elicitation=ElicitationCapability(form=FormElicitationCapability())
            )
        else:
            caps = ClientCapabilities(elicitation=None)
        params = InitializeRequestParams(
            protocolVersion="2025-03-26",
            capabilities=caps,
            clientInfo=Implementation(name="test", version="1.0"),
        )
        ctx.request_context.session.client_params = params
        if elicit_result is not None:
            ctx.elicit = AsyncMock(return_value=elicit_result)
        return ctx

    async def test_complete_body_bypasses_elicitation(self) -> None:
        body = make_complete_body()
        result = await server.create_shipment(request_body=body)
        self.assertIn("ShipmentResponse", result)
        self.assertEqual(len(self.fake_tool_manager.calls), 1)

    async def test_defaults_fill_gaps_preventing_elicitation(self) -> None:
        body = make_complete_body()
        del body["ShipmentRequest"]["Request"]["RequestOption"]
        result = await server.create_shipment(request_body=body)
        self.assertIn("ShipmentResponse", result)
        call_args = self.fake_tool_manager.calls[0][1]
        self.assertEqual(
            call_args["request_body"]["ShipmentRequest"]["Request"]["RequestOption"],
            "nonvalidate",
        )

    async def test_no_ctx_raises_elicitation_unsupported(self) -> None:
        body: dict = {"ShipmentRequest": {}}
        with self.assertRaises(ToolError) as cm:
            await server.create_shipment(request_body=body)
        payload = json.loads(str(cm.exception))
        self.assertEqual(payload["code"], "ELICITATION_UNSUPPORTED")
        self.assertIn("missing", payload)
        self.assertIsInstance(payload["missing"], list)
        # Each item should have dot_path, flat_key, prompt
        for item in payload["missing"]:
            self.assertIn("dot_path", item)
            self.assertIn("flat_key", item)
            self.assertIn("prompt", item)

    async def test_no_elicitation_cap_raises_unsupported(self) -> None:
        body: dict = {"ShipmentRequest": {}}
        ctx = self._make_ctx(form_supported=False)
        with self.assertRaises(ToolError) as cm:
            await server.create_shipment(request_body=body, ctx=ctx)
        payload = json.loads(str(cm.exception))
        self.assertEqual(payload["code"], "ELICITATION_UNSUPPORTED")

    async def test_accepted_elicitation_calls_ups(self) -> None:
        body = make_complete_body()
        del body["ShipmentRequest"]["Shipment"]["Shipper"]["Name"]

        mock_data = MagicMock()
        mock_data.model_dump.return_value = {"shipper_name": "Elicited Corp"}
        accepted = MagicMock()
        accepted.action = "accept"
        accepted.data = mock_data

        ctx = self._make_ctx(form_supported=True, elicit_result=accepted)
        result = await server.create_shipment(request_body=body, ctx=ctx)
        self.assertIn("ShipmentResponse", result)
        ctx.elicit.assert_called_once()

    async def test_declined_raises_elicitation_declined(self) -> None:
        body = make_complete_body()
        del body["ShipmentRequest"]["Shipment"]["Shipper"]["Name"]
        declined = MagicMock()
        declined.action = "decline"
        ctx = self._make_ctx(form_supported=True, elicit_result=declined)
        with self.assertRaises(ToolError) as cm:
            await server.create_shipment(request_body=body, ctx=ctx)
        payload = json.loads(str(cm.exception))
        self.assertEqual(payload["code"], "ELICITATION_DECLINED")

    async def test_cancelled_raises_elicitation_cancelled(self) -> None:
        body = make_complete_body()
        del body["ShipmentRequest"]["Shipment"]["Shipper"]["Name"]
        cancelled = MagicMock()
        cancelled.action = "cancel"
        ctx = self._make_ctx(form_supported=True, elicit_result=cancelled)
        with self.assertRaises(ToolError) as cm:
            await server.create_shipment(request_body=body, ctx=ctx)
        payload = json.loads(str(cm.exception))
        self.assertEqual(payload["code"], "ELICITATION_CANCELLED")

    async def test_still_missing_after_accept_raises_incomplete(self) -> None:
        body = make_complete_body()
        del body["ShipmentRequest"]["Shipment"]["Shipper"]["Name"]
        del body["ShipmentRequest"]["Shipment"]["ShipTo"]["Name"]

        mock_data = MagicMock()
        mock_data.model_dump.return_value = {"shipper_name": "Filled"}
        accepted = MagicMock()
        accepted.action = "accept"
        accepted.data = mock_data

        ctx = self._make_ctx(form_supported=True, elicit_result=accepted)
        with self.assertRaises(ToolError) as cm:
            await server.create_shipment(request_body=body, ctx=ctx)
        payload = json.loads(str(cm.exception))
        self.assertEqual(payload["code"], "INCOMPLETE_SHIPMENT")

    async def test_malformed_body_raises_structured_tool_error(self) -> None:
        """Structural TypeError during apply_defaults wraps as MALFORMED_REQUEST."""
        body = {
            "ShipmentRequest": {
                "Request": "not_a_dict",  # Should be dict, _set_field will fail
            }
        }
        with self.assertRaises(ToolError) as cm:
            await server.create_shipment(request_body=body)
        payload = json.loads(str(cm.exception))
        self.assertEqual(payload["code"], "MALFORMED_REQUEST")
        self.assertEqual(payload["reason"], "malformed_structure")

    async def test_ambiguous_payer_raises_structured_tool_error(self) -> None:
        """Multiple billing objects in the same ShipmentCharge wraps as MALFORMED_REQUEST."""
        body = make_complete_body()
        body["ShipmentRequest"]["Shipment"]["PaymentInformation"]["ShipmentCharge"] = [{
            "Type": "01",
            "BillShipper": {"AccountNumber": "ABC"},
            "BillReceiver": {"AccountNumber": "DEF"},
        }]
        with self.assertRaises(ToolError) as cm:
            await server.create_shipment(request_body=body)
        payload = json.loads(str(cm.exception))
        self.assertEqual(payload["code"], "MALFORMED_REQUEST")
        self.assertEqual(payload["reason"], "ambiguous_payer")

    async def test_rehydration_error_raises_structured_tool_error(self) -> None:
        """When rehydrate hits a structural conflict, ToolError wraps it."""
        body = make_complete_body()
        del body["ShipmentRequest"]["Shipment"]["Shipper"]["Name"]
        # Corrupt the structure so rehydration will fail
        body["ShipmentRequest"]["Shipment"]["Shipper"]["Address"] = "not_a_dict"

        mock_data = MagicMock()
        mock_data.model_dump.return_value = {
            "shipper_name": "Test",
            "shipper_address_line_1": "123 Main",  # This will fail — Address is a string
        }
        accepted = MagicMock()
        accepted.action = "accept"
        accepted.data = mock_data

        # Missing fields will include shipper_name and shipper_address_line_1
        # because we deleted Name and corrupted Address
        ctx = self._make_ctx(form_supported=True, elicit_result=accepted)
        with self.assertRaises(ToolError) as cm:
            await server.create_shipment(request_body=body, ctx=ctx)
        payload = json.loads(str(cm.exception))
        self.assertEqual(payload["code"], "ELICITATION_INVALID_RESPONSE")
        self.assertEqual(payload["reason"], "rehydration_error")

    async def test_package_dict_canonicalized_to_list_before_ups_call(self) -> None:
        """A complete body with Package as dict should be canonicalized to list."""
        body = make_complete_body()
        # Convert Package from list to dict
        body["ShipmentRequest"]["Shipment"]["Package"] = (
            body["ShipmentRequest"]["Shipment"]["Package"][0]
        )
        self.assertIsInstance(body["ShipmentRequest"]["Shipment"]["Package"], dict)
        result = await server.create_shipment(request_body=body)
        self.assertIn("ShipmentResponse", result)
        # Verify the body sent to UPS has Package as list
        call_args = self.fake_tool_manager.calls[0][1]
        pkg = call_args["request_body"]["ShipmentRequest"]["Shipment"]["Package"]
        self.assertIsInstance(pkg, list)

    async def test_shipment_charge_dict_canonicalized_to_list_before_ups_call(self) -> None:
        """A complete body with ShipmentCharge as dict should be canonicalized to list."""
        body = make_complete_body()
        # Convert ShipmentCharge from list to dict
        body["ShipmentRequest"]["Shipment"]["PaymentInformation"]["ShipmentCharge"] = (
            body["ShipmentRequest"]["Shipment"]["PaymentInformation"]["ShipmentCharge"][0]
        )
        result = await server.create_shipment(request_body=body)
        self.assertIn("ShipmentResponse", result)
        call_args = self.fake_tool_manager.calls[0][1]
        sc = call_args["request_body"]["ShipmentRequest"]["Shipment"]["PaymentInformation"]["ShipmentCharge"]
        self.assertIsInstance(sc, list)

    async def test_error_payload_structured_missing_objects(self) -> None:
        """Error payload uses structured missing array, not split parallel structures."""
        body: dict = {"ShipmentRequest": {}}
        with self.assertRaises(ToolError) as cm:
            await server.create_shipment(request_body=body)
        payload = json.loads(str(cm.exception))
        self.assertIn("code", payload)
        self.assertIn("message", payload)
        self.assertIn("reason", payload)
        self.assertIn("missing", payload)
        self.assertIsInstance(payload["missing"], list)
        self.assertGreater(len(payload["missing"]), 0)
        first = payload["missing"][0]
        self.assertIn("dot_path", first)
        self.assertIn("flat_key", first)
        self.assertIn("prompt", first)
```

**Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_server_elicitation.py::CreateShipmentElicitationTests -v`
Expected: FAIL because `create_shipment` doesn't accept `ctx` parameter yet

**Step 3: Rewrite `create_shipment` in `server.py`**

Replace the existing `create_shipment` function in `ups_mcp/server.py` (lines 172-206) with:

```python
@mcp.tool()
async def create_shipment(
    request_body: dict[str, Any],
    version: str = "v2409",
    additionaladdressvalidation: str = "",
    trans_id: str = "",
    transaction_src: str = "ups-mcp",
    ctx: Context | None = None,
) -> dict[str, Any]:
    """
    Create a shipment using UPS Shipping API (`POST /shipments/{version}/ship`).

    If required fields are missing and the client supports form-mode elicitation,
    the server will prompt for the missing information. Otherwise, a structured
    ToolError is raised listing the missing fields.

    Args:
        request_body (dict): JSON object matching `SHIPRequestWrapper`.
            Minimum practical shape:
            - ShipmentRequest.Request
            - ShipmentRequest.Shipment.Shipper
            - ShipmentRequest.Shipment.ShipTo
            - ShipmentRequest.Shipment.Service
            - ShipmentRequest.Shipment.Package
            - ShipmentRequest.Shipment.PaymentInformation
        version (str): API version. Default `v2409`.
        additionaladdressvalidation (str): Optional query param (for example `city`).
        trans_id (str): Optional request id.
        transaction_src (str): Optional caller source name. Default `ups-mcp`.
        ctx: MCP Context (injected by FastMCP, not provided by callers).

    Returns:
        dict[str, Any]: Raw UPS API response payload. On error, raises ToolError.
    """
    from .shipment_validator import (
        apply_defaults,
        find_missing_fields,
        build_elicitation_schema,
        normalize_elicited_values,
        rehydrate,
        canonicalize_body,
        RehydrationError,
        AmbiguousPayerError,
    )

    # Helper: canonicalize and send to UPS
    def _send_to_ups(body):
        canonical = canonicalize_body(body)
        return _require_tool_manager().create_shipment(
            request_body=canonical,
            version=version,
            additionaladdressvalidation=additionaladdressvalidation or None,
            trans_id=trans_id or None,
            transaction_src=transaction_src,
        )

    # 1. Apply 3-tier defaults (may raise TypeError on malformed bodies)
    env_config = {"UPS_ACCOUNT_NUMBER": os.getenv("UPS_ACCOUNT_NUMBER", "")}
    try:
        merged_body = apply_defaults(request_body, env_config)
    except TypeError as exc:
        raise ToolError(json.dumps({
            "code": "MALFORMED_REQUEST",
            "message": f"Request body has structural conflicts: {exc}",
            "reason": "malformed_structure",
            "missing": [],
        }))

    # 2. Preflight: find missing required fields
    try:
        missing = find_missing_fields(merged_body)
    except AmbiguousPayerError as exc:
        raise ToolError(json.dumps({
            "code": "MALFORMED_REQUEST",
            "message": str(exc),
            "reason": "ambiguous_payer",
            "missing": [],
        }))

    # 3. Happy path — all fields present
    if not missing:
        return _send_to_ups(merged_body)

    # Helper: build structured missing payload
    def _missing_payload(fields):
        return [
            {"dot_path": mf.dot_path, "flat_key": mf.flat_key, "prompt": mf.prompt}
            for mf in fields
        ]

    # 4. Check form-mode elicitation support
    if _check_form_elicitation(ctx):
        schema = build_elicitation_schema(missing)
        result = await ctx.elicit(
            message=f"Missing {len(missing)} required field(s) for shipment creation.",
            schema=schema,
        )

        if result.action == "accept":
            normalized = normalize_elicited_values(result.data.model_dump())
            try:
                merged_body = rehydrate(merged_body, normalized, missing)
            except RehydrationError as exc:
                raise ToolError(json.dumps({
                    "code": "ELICITATION_INVALID_RESPONSE",
                    "message": f"Elicited data conflicts with request structure: {exc}",
                    "reason": "rehydration_error",
                    "missing": _missing_payload(missing),
                }))
            still_missing = find_missing_fields(merged_body)
            if still_missing:
                raise ToolError(json.dumps({
                    "code": "INCOMPLETE_SHIPMENT",
                    "message": "Still missing required fields after elicitation",
                    "reason": "still_missing",
                    "missing": _missing_payload(still_missing),
                }))
            return _send_to_ups(merged_body)

        elif result.action == "decline":
            raise ToolError(json.dumps({
                "code": "ELICITATION_DECLINED",
                "message": "User declined to provide missing shipment fields",
                "reason": "declined",
                "missing": _missing_payload(missing),
            }))

        else:  # cancel
            raise ToolError(json.dumps({
                "code": "ELICITATION_CANCELLED",
                "message": "User cancelled shipment field elicitation",
                "reason": "cancelled",
                "missing": _missing_payload(missing),
            }))

    # 5. No form elicitation — structured ToolError for agent fallback
    raise ToolError(json.dumps({
        "code": "ELICITATION_UNSUPPORTED",
        "message": f"Missing {len(missing)} required field(s) and client does not support form elicitation",
        "reason": "unsupported",
        "missing": _missing_payload(missing),
    }))
```

Also add `import json` to the top of `server.py` if not already present.

**Step 4: Run ALL tests to verify they pass**

Run: `python3 -m pytest tests/ -v`
Expected: All tests PASS (both new elicitation tests and existing server_tools tests)

**IMPORTANT:** The existing `test_server_tools.py` may call `create_shipment` without a complete body. If those tests fail, update them in the next task.

**Step 5: Commit**

```bash
git add ups_mcp/server.py tests/test_server_elicitation.py
git commit -m "feat: wire up elicitation orchestration in create_shipment

Structured error payload uses 'missing' array with full field objects.
Post-elicitation normalization applied before rehydration."
```

---

### Task 11: Verify existing tests still pass and final cleanup

**Files:**
- Possibly modify: `tests/test_server_tools.py` (if create_shipment call needs a complete body)

**Step 1: Run the full test suite**

Run: `python3 -m pytest tests/ -v`

**Step 2: Fix any broken existing tests**

If `test_server_tools.py` tests for `create_shipment` fail because they now go through the preflight validation path, update them to pass a complete body:

```python
# In test_server_tools.py, update the create_shipment call:
from tests.shipment_fixtures import make_complete_body

# Replace any bare create_shipment calls with:
#   await server.create_shipment(request_body=make_complete_body())
```

**Step 3: Run full test suite again**

Run: `python3 -m pytest tests/ -v`
Expected: All tests PASS

**Step 4: Commit if changes were needed**

```bash
git add tests/test_server_tools.py
git commit -m "fix: update existing create_shipment tests for preflight validation"
```

---

## Summary of Files

| File | Action | Purpose |
|------|--------|---------|
| `ups_mcp/shipment_validator.py` | Create | Pure validation: rules, defaults, flatten/unflatten, normalization |
| `ups_mcp/server.py` | Modify | Add ctx param, orchestration, `_check_form_elicitation` |
| `tests/__init__.py` | Create | Make tests a proper package for imports |
| `tests/shipment_fixtures.py` | Create | Shared test fixture `make_complete_body()` |
| `tests/test_shipment_validator.py` | Create | Unit tests for validator module |
| `tests/test_server_elicitation.py` | Create | Integration tests for server orchestration |
| `tests/test_server_tools.py` | Modify | Update create_shipment calls if needed |
| `ups_mcp/tools.py` | None | Unchanged |

## Review Findings Addressed

### Round 1

| Finding | Severity | Resolution |
|---------|----------|------------|
| Import path risk (`from tests.` without `__init__.py`) | P0 | Added `tests/__init__.py` in Task 1 |
| Missing PaymentInformation rules | P0 | Added payment rules + built-in/env defaults for charge type + billing account (superseded by round 2 P0 conditional payment fix) |
| Package dict vs list instability | P1 | `_ensure_package_list()` normalizes to list in `rehydrate()` and `_normalize_packages()` in `find_missing_fields()` |
| Whitespace-only values bypass detection | P1 | `_field_exists()` strips and rejects whitespace-only strings |
| `_set_field` overwrite of incompatible types | P1 | Originally added coercion; superseded by round 2 P1 — now raises `TypeError` instead |
| Error payload split structures | P1 | Replaced `missing_fields`/`field_prompts` with single `missing` array of `{dot_path, flat_key, prompt}` objects |
| No post-elicitation normalization | P1 | Added `normalize_elicited_values()`: trim, uppercase codes, remove empties |
| Mock-heavy capability tests | P2 | Added `test_with_real_capability_objects` and `test_attribute_error_returns_false` |

### Round 2

| Finding | Severity | Resolution |
|---------|----------|------------|
| Payment validation too rigid (rejects BillReceiver/BillThirdParty) | P0 | Replaced static `PAYMENT_RULES` with `PAYMENT_CHARGE_TYPE_RULE` (always required) + `PAYMENT_PAYER_RULES` dict (conditional on which billing object is present). `find_missing_fields` checks BillShipper/BillReceiver/BillThirdParty in order; defaults to BillShipper if none present. Tests cover all payer types. |
| `_set_field` allows destructive coercion of existing structures | P1 | Changed to only create intermediates when node is missing. Raises `TypeError` when an existing node has an incompatible type instead of silently overwriting. Tests updated to assert `TypeError`. |
| Package shape not canonicalized before UPS call | P1 | Added `_send_to_ups()` helper in server orchestration that calls `_ensure_package_list()` before every `_require_tool_manager().create_shipment()` call. Test `test_package_dict_canonicalized_to_list_before_ups_call` verifies. |
| Country-conditional rules narrow scope | P1 | Added v1 scope comment to `COUNTRY_CONDITIONAL_RULES` documenting that only US/CA/PR are enforced, broader strategy planned for v2. Acceptable for v1. |
| Test coupling (FakeToolManager import from test_server_tools) | P2 | Defined local `_FakeToolManager` in `test_server_elicitation.py` with only `create_shipment` method. No cross-test imports. |

### Round 3

| Finding | Severity | Resolution |
|---------|----------|------------|
| Payment env default overrides intended payer flow | P0 | Removed `BillShipper.AccountNumber` from `ENV_DEFAULTS`. Added `_has_payer_object()` helper. `apply_defaults()` only injects BillShipper.AccountNumber when no payer object (BillShipper/BillReceiver/BillThirdParty) exists. 4 new tests cover all payer scenarios. |
| `FieldRule` not imported in Task 1 test | P1 | Added `FieldRule` to test imports. |
| ShipmentCharge shape not normalized | P1 | Added dict→list normalization in `find_missing_fields()` payer detection and in `_has_payer_object()`. Test `test_shipment_charge_as_dict_normalized` verifies. |
| TypeError from `_set_field` surfaces as non-structured error | P1 | Added `RehydrationError` exception. `rehydrate()` catches `TypeError` and wraps as `RehydrationError`. Server catches `RehydrationError` and wraps as `ToolError` with code `ELICITATION_INVALID_RESPONSE`. Tests at both levels. |
| Task 2 commit message says "coercion" but impl raises TypeError | P2 | Updated commit message to say "raises TypeError on existing incompatible intermediate types". |

### Round 4

| Finding | Severity | Resolution |
|---------|----------|------------|
| ShipmentCharge dict normalization broken — `_field_exists` runs on un-normalized body | P0 | Replaced fragmented normalization (`_ensure_package_list`, local charge normalization) with unified `canonicalize_body()` that normalizes both Package and ShipmentCharge to list form. `find_missing_fields` canonicalizes first, then all `_field_exists` calls operate on canonical body where `[0]` paths resolve correctly. |
| Structural TypeError leaks before elicitation | P1 | Wrapped `apply_defaults()` call in server.py with `try/except TypeError` → structured `ToolError` with code `MALFORMED_REQUEST`. Test verifies. |
| ShipmentCharge not canonicalized before UPS call | P1 | `_send_to_ups()` now calls `canonicalize_body()` (not just `_ensure_package_list`), normalizing both Package and ShipmentCharge. Test `test_shipment_charge_dict_canonicalized_to_list_before_ups_call` verifies. |

### Round 5

| Finding | Severity | Resolution |
|---------|----------|------------|
| Multiple payer objects in same ShipmentCharge silently picks first | P1 | Added `AmbiguousPayerError` exception. `find_missing_fields` detects when multiple billing objects (BillShipper, BillReceiver, BillThirdParty) are present in the same ShipmentCharge and raises it. Server wraps as `ToolError` with code `MALFORMED_REQUEST` and reason `ambiguous_payer`. Tests at validator and server levels. |
| Non-dict list elements not hardened in `_normalize_list_field` | P2 | `_normalize_list_field` now coerces non-dict elements to `{}`. Non-list/non-dict values for the field are also replaced with `[{}]`. Tests verify all edge cases. |
| Task 3 commit message references "billing account number (env)" but it's now conditional | P2 | Updated commit message to say "conditional billing account (env, only when no payer object present)". |

## Commit History (expected)

1. `feat: add shipment_validator data structures and field rules`
2. `feat: add dict navigation helpers with whitespace and type safety`
3. `feat: implement apply_defaults with 3-tier merge`
4. `feat: implement find_missing_fields with payment and package rules`
5. `test: add package edge case tests for find_missing_fields`
6. `test: add country-conditional tests for find_missing_fields`
7. `feat: implement build_elicitation_schema for dynamic Pydantic models`
8. `feat: implement normalize_elicited_values and rehydrate`
9. `feat: implement _check_form_elicitation capability check`
10. `feat: wire up elicitation orchestration in create_shipment`
11. `fix: update existing create_shipment tests for preflight validation` (if needed)
