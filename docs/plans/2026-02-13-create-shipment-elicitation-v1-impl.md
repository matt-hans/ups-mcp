# Create Shipment Elicitation v1 — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add preflight validation and MCP form-mode elicitation to `create_shipment` so missing required fields are either collected from the user via `ctx.elicit()` or reported in a structured `ToolError`.

**Architecture:** New pure-logic `shipment_validator.py` module handles rules, defaults, flatten/unflatten. `server.py::create_shipment` orchestrates: apply defaults → preflight → elicit (if supported) or ToolError → ToolManager. `tools.py` is unchanged.

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
    """Return a minimal-but-complete ShipmentRequest body."""
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
                "Service": {"Code": "03"},
                "Package": packages if len(packages) > 1 else packages[0],
            },
        }
    }
    return body
```

---

### Task 1: Create data structures and field rules

**Files:**
- Create: `ups_mcp/shipment_validator.py`
- Create: `tests/shipment_fixtures.py`
- Create: `tests/test_shipment_validator.py`

**Step 1: Create the test fixture file**

Write `tests/shipment_fixtures.py` with the `make_complete_body()` function from the shared fixtures section above.

**Step 2: Write failing test for data structures**

Write `tests/test_shipment_validator.py`:

```python
import unittest

from ups_mcp.shipment_validator import (
    MissingField,
    UNCONDITIONAL_RULES,
    PACKAGE_RULES,
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

    def test_country_conditional_rules_has_us_ca_pr(self) -> None:
        self.assertIn(("US", "CA", "PR"), COUNTRY_CONDITIONAL_RULES)

    def test_built_in_defaults_has_request_option(self) -> None:
        self.assertIn("ShipmentRequest.Request.RequestOption", BUILT_IN_DEFAULTS)
        self.assertEqual(
            BUILT_IN_DEFAULTS["ShipmentRequest.Request.RequestOption"],
            "nonvalidate",
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


if __name__ == "__main__":
    unittest.main()
```

**Step 3: Run test to verify it fails**

Run: `python3 -m pytest tests/test_shipment_validator.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ups_mcp.shipment_validator'`

**Step 4: Implement shipment_validator.py with data structures**

Write `ups_mcp/shipment_validator.py`:

```python
"""Shipment preflight validation, elicitation schema generation, and rehydration.

Pure functions — no MCP/protocol dependencies. All functions are stateless
and safe to test in isolation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


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
}

ENV_DEFAULTS: dict[str, str] = {
    # key = dot-path, value = env-var name to read from env_config
    "ShipmentRequest.Shipment.Shipper.ShipperNumber": "UPS_ACCOUNT_NUMBER",
}
```

**Step 5: Run test to verify it passes**

Run: `python3 -m pytest tests/test_shipment_validator.py -v`
Expected: All 6 tests PASS

**Step 6: Commit**

```bash
git add ups_mcp/shipment_validator.py tests/shipment_fixtures.py tests/test_shipment_validator.py
git commit -m "feat: add shipment_validator data structures and field rules"
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

    def test_does_not_overwrite_existing(self) -> None:
        data = {"a": {"b": "existing"}}
        _set_field(data, "a.b", "new")
        # _set_field should overwrite — caller is responsible for checking
        self.assertEqual(data["a"]["b"], "new")

    def test_creates_intermediate_dicts(self) -> None:
        data: dict = {}
        _set_field(data, "ShipmentRequest.Shipment.Shipper.Name", "Test")
        self.assertEqual(
            data["ShipmentRequest"]["Shipment"]["Shipper"]["Name"],
            "Test",
        )
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
    """Check if a dot-path resolves to a non-empty value in a nested dict."""
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
    return current is not None and current != ""


def _set_field(data: dict, dot_path: str, value: Any) -> None:
    """Set a value at a dot-path, creating intermediate dicts/lists as needed."""
    segments = dot_path.split(".")
    current = data
    for segment in segments[:-1]:
        key, idx = _parse_path_segment(segment)
        if key not in current:
            current[key] = [] if idx is not None else {}
        target = current[key]
        if idx is not None:
            if not isinstance(target, list):
                current[key] = []
                target = current[key]
            while len(target) <= idx:
                target.append({})
            current = target[idx]
        else:
            current = target

    last_key, last_idx = _parse_path_segment(segments[-1])
    if last_idx is not None:
        if last_key not in current:
            current[last_key] = []
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
git commit -m "feat: add dict navigation helpers _field_exists and _set_field"
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
import copy


def apply_defaults(request_body: dict, env_config: dict[str, str]) -> dict:
    """Apply 3-tier defaults: built-in -> env -> caller body (highest priority).

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

    return result
```

**Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_shipment_validator.py -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add ups_mcp/shipment_validator.py tests/test_shipment_validator.py
git commit -m "feat: implement apply_defaults with 3-tier merge"
```

---

### Task 4: Implement and test `find_missing_fields` — unconditional rules

**Files:**
- Modify: `ups_mcp/shipment_validator.py`
- Modify: `tests/test_shipment_validator.py`

**Step 1: Write failing tests**

Append to `tests/test_shipment_validator.py`:

```python
from ups_mcp.shipment_validator import find_missing_fields, MissingField


class FindMissingFieldsUnconditionalTests(unittest.TestCase):
    def test_complete_body_returns_empty(self) -> None:
        body = make_complete_body()
        missing = find_missing_fields(body)
        self.assertEqual(missing, [])

    def test_empty_body_returns_all_fields(self) -> None:
        missing = find_missing_fields({})
        # Should include all unconditional + package_1 fields (no country-conditional
        # since no country code present)
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

    def test_returns_missing_field_instances(self) -> None:
        body = make_complete_body()
        del body["ShipmentRequest"]["Shipment"]["Shipper"]["Name"]
        missing = find_missing_fields(body)
        shipper_name = [mf for mf in missing if mf.flat_key == "shipper_name"]
        self.assertEqual(len(shipper_name), 1)
        self.assertEqual(shipper_name[0].dot_path, "ShipmentRequest.Shipment.Shipper.Name")
        self.assertEqual(shipper_name[0].prompt, "Shipper name")
```

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_shipment_validator.py::FindMissingFieldsUnconditionalTests -v`
Expected: FAIL with `ImportError: cannot import name 'find_missing_fields'`

**Step 3: Implement `find_missing_fields`**

Add to `ups_mcp/shipment_validator.py`:

```python
def _normalize_packages(request_body: dict) -> list[dict]:
    """Extract Package from body, normalize to a list of dicts."""
    shipment = request_body.get("ShipmentRequest", {}).get("Shipment", {})
    packages = shipment.get("Package")
    if packages is None:
        return [{}]
    if isinstance(packages, dict):
        return [packages]
    if isinstance(packages, list):
        return packages if packages else [{}]
    return [{}]


def find_missing_fields(request_body: dict) -> list[MissingField]:
    """Check required fields and return those that are missing.

    Checks unconditional rules, per-package rules, and country-conditional rules.
    """
    missing: list[MissingField] = []

    # Unconditional non-package fields
    for rule in UNCONDITIONAL_RULES:
        if not _field_exists(request_body, rule.dot_path):
            missing.append(MissingField(rule.dot_path, rule.flat_key, rule.prompt))

    # Per-package fields
    packages = _normalize_packages(request_body)
    for i, pkg in enumerate(packages):
        n = i + 1  # 1-indexed for user-facing flat keys
        for rule in PACKAGE_RULES:
            full_dot_path = f"ShipmentRequest.Shipment.Package[{i}].{rule.dot_path}"
            flat_key = f"package_{n}_{rule.flat_key}"
            prompt = f"Package {n}: {rule.prompt}" if len(packages) > 1 else rule.prompt
            if not _field_exists(pkg, rule.dot_path):
                missing.append(MissingField(full_dot_path, flat_key, prompt))

    # Country-conditional fields
    shipment = request_body.get("ShipmentRequest", {}).get("Shipment", {})
    for role, prefix in [("Shipper", "shipper"), ("ShipTo", "ship_to")]:
        address = shipment.get(role, {}).get("Address", {})
        country = str(address.get("CountryCode", "")).upper()
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
git commit -m "feat: implement find_missing_fields with unconditional rules"
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
        body = make_complete_body()
        # make_complete_body returns single package as dict (not list)
        self.assertIsInstance(body["ShipmentRequest"]["Shipment"]["Package"], dict)
        missing = find_missing_fields(body)
        # Should be complete — no package fields missing
        pkg_missing = [mf for mf in missing if "package_" in mf.flat_key]
        self.assertEqual(pkg_missing, [])

    def test_multi_package_validates_each(self) -> None:
        body = make_complete_body(num_packages=2)
        # Remove weight from package 2
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
Expected: All PASS (implementation already handles these cases)

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
        # Remove state — should NOT be flagged for GB
        del body["ShipmentRequest"]["Shipment"]["Shipper"]["Address"]["StateProvinceCode"]
        del body["ShipmentRequest"]["Shipment"]["Shipper"]["Address"]["PostalCode"]
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertNotIn("shipper_state", flat_keys)
        self.assertNotIn("shipper_postal_code", flat_keys)

    def test_no_country_code_skips_conditional(self) -> None:
        body = make_complete_body()
        del body["ShipmentRequest"]["Shipment"]["Shipper"]["Address"]["CountryCode"]
        # Remove state/postal — should NOT be flagged because country unknown
        del body["ShipmentRequest"]["Shipment"]["Shipper"]["Address"]["StateProvinceCode"]
        del body["ShipmentRequest"]["Shipment"]["Shipper"]["Address"]["PostalCode"]
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        # Country code itself should be missing (unconditional)
        self.assertIn("shipper_country_code", flat_keys)
        # But state/postal should NOT be flagged (no country → no conditional)
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
from pydantic import BaseModel, Field, create_model


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

### Task 8: Implement and test `rehydrate`

**Files:**
- Modify: `ups_mcp/shipment_validator.py`
- Modify: `tests/test_shipment_validator.py`

**Step 1: Write failing tests**

Append to `tests/test_shipment_validator.py`:

```python
from ups_mcp.shipment_validator import rehydrate


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
        # Rehydrate with empty value — should not clear existing
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
```

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_shipment_validator.py::RehydrateTests -v`
Expected: FAIL with `ImportError: cannot import name 'rehydrate'`

**Step 3: Implement `rehydrate`**

Add to `ups_mcp/shipment_validator.py`:

```python
def rehydrate(
    request_body: dict,
    flat_data: dict[str, str],
    missing: list[MissingField],
) -> dict:
    """Merge flat elicitation responses back into nested UPS structure.

    Uses the ``missing`` list as the flat_key → dot_path mapping.
    Skips empty/None values. Does not overwrite existing non-empty values.
    Returns a new dict — does not mutate the input.
    """
    flat_to_dot = {mf.flat_key: mf.dot_path for mf in missing}
    result = copy.deepcopy(request_body)

    for flat_key, value in flat_data.items():
        if not value:
            continue
        dot_path = flat_to_dot.get(flat_key)
        if dot_path is None:
            continue
        # Only set if not already present
        if not _field_exists(result, dot_path):
            _set_field(result, dot_path, value)

    return result
```

**Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_shipment_validator.py -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add ups_mcp/shipment_validator.py tests/test_shipment_validator.py
git commit -m "feat: implement rehydrate for flat-to-nested conversion"
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
        ctx.request_context.session.check_client_capability.side_effect = (
            lambda c: c.elicitation is not None and params.capabilities.elicitation is not None
        )
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
        # Backward compat: empty ElicitationCapability (neither form nor url set)
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
Expected: All 6 tests PASS

**Step 5: Commit**

```bash
git add ups_mcp/server.py tests/test_server_elicitation.py
git commit -m "feat: implement _check_form_elicitation capability check"
```

---

### Task 10: Wire up orchestration in server.py `create_shipment`

**Files:**
- Modify: `ups_mcp/server.py`

**Step 1: Write failing integration tests**

Append to `tests/test_server_elicitation.py`:

```python
import json
from unittest.mock import AsyncMock, patch

from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.elicitation import AcceptedElicitation, DeclinedElicitation, CancelledElicitation
from pydantic import BaseModel

from tests.shipment_fixtures import make_complete_body
from tests.test_server_tools import FakeToolManager


class CreateShipmentElicitationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.original_tool_manager = server.tool_manager
        self.fake_tool_manager = FakeToolManager()
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
        # ToolManager was called
        self.assertEqual(len(self.fake_tool_manager.calls), 1)

    async def test_defaults_fill_gaps_preventing_elicitation(self) -> None:
        body = make_complete_body()
        del body["ShipmentRequest"]["Request"]["RequestOption"]
        # RequestOption has a built-in default of "nonvalidate"
        result = await server.create_shipment(request_body=body)
        self.assertIn("ShipmentResponse", result)
        # Check that the default was applied
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
        self.assertIn("missing_fields", payload)
        self.assertIn("field_prompts", payload)

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

        # Create an AcceptedElicitation mock that has .action and .data
        mock_data = MagicMock()
        mock_data.model_dump.return_value = {"shipper_name": "Elicited Corp"}
        accepted = MagicMock()
        accepted.action = "accept"
        accepted.data = mock_data

        ctx = self._make_ctx(form_supported=True, elicit_result=accepted)
        result = await server.create_shipment(request_body=body, ctx=ctx)
        self.assertIn("ShipmentResponse", result)
        # Verify elicit was called
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

        # Accept but only provide one of two missing fields
        mock_data = MagicMock()
        mock_data.model_dump.return_value = {"shipper_name": "Filled"}
        # ship_to_name not provided
        accepted = MagicMock()
        accepted.action = "accept"
        accepted.data = mock_data

        ctx = self._make_ctx(form_supported=True, elicit_result=accepted)
        with self.assertRaises(ToolError) as cm:
            await server.create_shipment(request_body=body, ctx=ctx)
        payload = json.loads(str(cm.exception))
        self.assertEqual(payload["code"], "INCOMPLETE_SHIPMENT")

    async def test_toolerror_payload_has_required_fields(self) -> None:
        body: dict = {"ShipmentRequest": {}}
        with self.assertRaises(ToolError) as cm:
            await server.create_shipment(request_body=body)
        payload = json.loads(str(cm.exception))
        self.assertIn("code", payload)
        self.assertIn("message", payload)
        self.assertIn("reason", payload)
        self.assertIn("missing_fields", payload)
        self.assertIn("field_prompts", payload)
        self.assertIsInstance(payload["missing_fields"], list)
        self.assertIsInstance(payload["field_prompts"], dict)
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
        rehydrate,
    )

    # 1. Apply 3-tier defaults
    env_config = {"UPS_ACCOUNT_NUMBER": os.getenv("UPS_ACCOUNT_NUMBER", "")}
    merged_body = apply_defaults(request_body, env_config)

    # 2. Preflight: find missing required fields
    missing = find_missing_fields(merged_body)

    # 3. Happy path — all fields present
    if not missing:
        return _require_tool_manager().create_shipment(
            request_body=merged_body,
            version=version,
            additionaladdressvalidation=additionaladdressvalidation or None,
            trans_id=trans_id or None,
            transaction_src=transaction_src,
        )

    # 4. Check form-mode elicitation support
    if _check_form_elicitation(ctx):
        schema = build_elicitation_schema(missing)
        result = await ctx.elicit(
            message=f"Missing {len(missing)} required field(s) for shipment creation.",
            schema=schema,
        )

        if result.action == "accept":
            merged_body = rehydrate(merged_body, result.data.model_dump(), missing)
            still_missing = find_missing_fields(merged_body)
            if still_missing:
                raise ToolError(json.dumps({
                    "code": "INCOMPLETE_SHIPMENT",
                    "message": "Still missing required fields after elicitation",
                    "reason": "still_missing",
                    "missing_fields": [mf.dot_path for mf in still_missing],
                    "field_prompts": {mf.flat_key: mf.prompt for mf in still_missing},
                }))
            return _require_tool_manager().create_shipment(
                request_body=merged_body,
                version=version,
                additionaladdressvalidation=additionaladdressvalidation or None,
                trans_id=trans_id or None,
                transaction_src=transaction_src,
            )

        elif result.action == "decline":
            raise ToolError(json.dumps({
                "code": "ELICITATION_DECLINED",
                "message": "User declined to provide missing shipment fields",
                "reason": "declined",
                "missing_fields": [mf.dot_path for mf in missing],
                "field_prompts": {mf.flat_key: mf.prompt for mf in missing},
            }))

        else:  # cancel
            raise ToolError(json.dumps({
                "code": "ELICITATION_CANCELLED",
                "message": "User cancelled shipment field elicitation",
                "reason": "cancelled",
                "missing_fields": [mf.dot_path for mf in missing],
                "field_prompts": {mf.flat_key: mf.prompt for mf in missing},
            }))

    # 5. No form elicitation — structured ToolError for agent fallback
    raise ToolError(json.dumps({
        "code": "ELICITATION_UNSUPPORTED",
        "message": f"Missing {len(missing)} required field(s) and client does not support form elicitation",
        "reason": "unsupported",
        "missing_fields": [mf.dot_path for mf in missing],
        "field_prompts": {mf.flat_key: mf.prompt for mf in missing},
    }))
```

Also add `import json` to the top of `server.py` if not already present.

**Step 4: Run ALL tests to verify they pass**

Run: `python3 -m pytest tests/ -v`
Expected: All tests PASS (both new elicitation tests and existing server_tools tests)

**IMPORTANT:** The existing `test_server_tools.py::test_new_tools_return_raw_ups_response` may need updating if it calls `create_shipment` without a complete body. Check and fix if needed — the test currently passes `{"RateRequest": {}}` style bodies which may now trigger missing-fields detection. If so, update that test to use `make_complete_body()`.

**Step 5: Commit**

```bash
git add ups_mcp/server.py tests/test_server_elicitation.py
git commit -m "feat: wire up elicitation orchestration in create_shipment"
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

# Replace:
#   await server.create_shipment(request_body={"ShipmentRequest": {}})
# With:
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
| `ups_mcp/shipment_validator.py` | Create | Pure validation logic: rules, defaults, flatten/unflatten |
| `ups_mcp/server.py` | Modify | Add ctx param, orchestration, `_check_form_elicitation` |
| `tests/shipment_fixtures.py` | Create | Shared test fixture `make_complete_body()` |
| `tests/test_shipment_validator.py` | Create | Unit tests for validator module |
| `tests/test_server_elicitation.py` | Create | Integration tests for server orchestration |
| `tests/test_server_tools.py` | Modify | Update create_shipment calls if needed |
| `ups_mcp/tools.py` | None | Unchanged |

## Commit History (expected)

1. `feat: add shipment_validator data structures and field rules`
2. `feat: add dict navigation helpers _field_exists and _set_field`
3. `feat: implement apply_defaults with 3-tier merge`
4. `feat: implement find_missing_fields with unconditional rules`
5. `test: add package edge case tests for find_missing_fields`
6. `test: add country-conditional tests for find_missing_fields`
7. `feat: implement build_elicitation_schema for dynamic Pydantic models`
8. `feat: implement rehydrate for flat-to-nested conversion`
9. `feat: implement _check_form_elicitation capability check`
10. `feat: wire up elicitation orchestration in create_shipment`
11. `fix: update existing create_shipment tests for preflight validation` (if needed)
