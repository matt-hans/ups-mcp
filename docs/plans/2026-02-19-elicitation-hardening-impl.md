# Elicitation Hardening Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Harden the elicitation system with bug fixes, a retry loop for validation errors, and general-purpose array flattening so InternationalForms.Product can be elicited via flat forms.

**Architecture:** Three incremental layers applied to `elicitation.py` (core), `shipment_validator.py` / `rating_validator.py` (validators), and `server.py` (wiring). Each layer builds on the previous and is independently testable. TDD throughout — tests first, then implementation.

**Tech Stack:** Python 3.14, Pydantic V2, MCP SDK 1.26.0 (`mcp.server.fastmcp.Context`, `mcp.server.elicitation`), unittest/IsolatedAsyncioTestCase

**Design doc:** `docs/plans/2026-02-19-elicitation-hardening-design.md`

---

### Task 1: Bug fix — remove "strict" from Pydantic native constraints

**Files:**
- Modify: `ups_mcp/elicitation.py:193-196`
- Test: `tests/test_elicitation.py`

**Step 1: Write the failing test**

Add to `tests/test_elicitation.py` at the end of the file, before `if __name__`:

```python
class PydanticConstraintTests(unittest.TestCase):
    def test_strict_not_in_native_constraints(self) -> None:
        """'strict' should not be in _PYDANTIC_NATIVE_CONSTRAINTS as it
        causes schema generation crashes when dynamically applied."""
        from ups_mcp.elicitation import _PYDANTIC_NATIVE_CONSTRAINTS
        self.assertNotIn("strict", _PYDANTIC_NATIVE_CONSTRAINTS)

    def test_strict_constraint_goes_to_json_schema_extra(self) -> None:
        """If a FieldRule has constraints=(('strict', True),), it should
        end up in json_schema_extra, not as a native Pydantic Field kwarg."""
        mf = MissingField(
            "Root.Val", "val", "Value",
            type_hint=float,
            constraints=(("strict", True),),
        )
        Model = build_elicitation_schema([mf])
        schema = Model.model_json_schema()
        # 'strict' should be in the property's schema, not as a Pydantic native constraint
        prop = schema["properties"]["val"]
        self.assertIn("strict", prop)
        self.assertTrue(prop["strict"])
```

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_elicitation.py::PydanticConstraintTests -v`
Expected: FAIL — `"strict"` IS currently in `_PYDANTIC_NATIVE_CONSTRAINTS`

**Step 3: Implement the fix**

In `ups_mcp/elicitation.py:193-196`, change:
```python
_PYDANTIC_NATIVE_CONSTRAINTS: frozenset[str] = frozenset({
    "gt", "ge", "lt", "le", "multiple_of", "strict",
    "min_length", "max_length", "pattern",
})
```
to:
```python
_PYDANTIC_NATIVE_CONSTRAINTS: frozenset[str] = frozenset({
    "gt", "ge", "lt", "le", "multiple_of",
    "min_length", "max_length", "pattern",
})
```

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_elicitation.py::PydanticConstraintTests -v`
Expected: PASS

**Step 5: Run full test suite to check for regressions**

Run: `python3 -m pytest tests/ -v`
Expected: All existing tests still pass

**Step 6: Commit**

```bash
git add ups_mcp/elicitation.py tests/test_elicitation.py
git commit -m "fix: remove 'strict' from Pydantic native constraints to prevent schema crashes"
```

---

### Task 2: Bug fix — NaN/Infinity validation in weight fields

**Files:**
- Modify: `ups_mcp/elicitation.py:14` (add `import math`), `ups_mcp/elicitation.py:330-336`
- Test: `tests/test_elicitation.py`

**Step 1: Write the failing tests**

Add to `tests/test_elicitation.py`:

```python
class WeightValidationEdgeCaseTests(unittest.TestCase):
    def test_infinity_weight_rejected(self) -> None:
        missing = [MissingField("Root.Weight", "package_1_weight", "Package weight")]
        errors = validate_elicited_values({"package_1_weight": "inf"}, missing)
        self.assertEqual(len(errors), 1)
        self.assertIn("positive, finite", errors[0])

    def test_negative_infinity_weight_rejected(self) -> None:
        missing = [MissingField("Root.Weight", "package_1_weight", "Package weight")]
        errors = validate_elicited_values({"package_1_weight": "-inf"}, missing)
        self.assertEqual(len(errors), 1)
        self.assertIn("positive, finite", errors[0])

    def test_nan_weight_rejected(self) -> None:
        missing = [MissingField("Root.Weight", "package_1_weight", "Package weight")]
        errors = validate_elicited_values({"package_1_weight": "nan"}, missing)
        self.assertEqual(len(errors), 1)
        self.assertIn("positive, finite", errors[0])

    def test_valid_weight_still_passes(self) -> None:
        missing = [MissingField("Root.Weight", "package_1_weight", "Package weight")]
        errors = validate_elicited_values({"package_1_weight": "5.5"}, missing)
        self.assertEqual(errors, [])

    def test_zero_weight_rejected(self) -> None:
        missing = [MissingField("Root.Weight", "package_1_weight", "Package weight")]
        errors = validate_elicited_values({"package_1_weight": "0"}, missing)
        self.assertEqual(len(errors), 1)
        self.assertIn("positive, finite", errors[0])
```

**Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_elicitation.py::WeightValidationEdgeCaseTests -v`
Expected: `test_infinity_weight_rejected`, `test_negative_infinity_weight_rejected`, `test_nan_weight_rejected` FAIL (inf passes `w <= 0`, nan comparison is unpredictable). `test_valid_weight_still_passes` and `test_zero_weight_rejected` should already pass.

**Step 3: Implement the fix**

In `ups_mcp/elicitation.py`, add `import math` at the top (line 14, after `import json`):
```python
import math
```

Then change lines 330-336 from:
```python
        if _WEIGHT_VALUE_KEYS.match(key):
            try:
                w = float(value)
                if w <= 0:
                    errors.append(f"{label}: must be a positive number")
            except (ValueError, TypeError):
                errors.append(f"{label}: must be a number")
```
to:
```python
        if _WEIGHT_VALUE_KEYS.match(key):
            try:
                w = float(value)
                if not math.isfinite(w) or w <= 0:
                    errors.append(f"{label}: must be a positive, finite number")
            except (ValueError, TypeError):
                errors.append(f"{label}: must be a number")
```

**Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_elicitation.py::WeightValidationEdgeCaseTests -v`
Expected: All PASS

**Step 5: Run full test suite**

Run: `python3 -m pytest tests/ -v`
Expected: All pass. Note: the existing `test_validation_errors_raise_invalid_response` test uses `"not_a_number"` which hits the `ValueError` path — this still works.

**Step 6: Commit**

```bash
git add ups_mcp/elicitation.py tests/test_elicitation.py
git commit -m "fix: reject NaN and Infinity in weight validation with math.isfinite()"
```

---

### Task 3: Bug fix — tighten ReturnService check in both validators

**Files:**
- Modify: `ups_mcp/shipment_validator.py:596-605`
- Modify: `ups_mcp/rating_validator.py:449-450`
- Test: `tests/test_shipment_validator.py`
- Test: `tests/test_rating_validator.py`

**Step 1: Write failing tests for shipment_validator**

Add to `tests/test_shipment_validator.py`. First, add `find_missing_fields` and `canonicalize_body` to the imports from `ups_mcp.shipment_validator` (if not already imported). Then add:

```python
from ups_mcp.shipment_validator import find_missing_fields, canonicalize_body, apply_defaults


class ReturnServiceCheckTests(unittest.TestCase):
    """ReturnService must be a dict with a non-empty Code to be treated as a return."""

    def _make_us_to_ca_body(self, return_service=None) -> dict:
        """Build a minimal US->CA body to trigger InvoiceLineTotal check."""
        body = {
            "ShipmentRequest": {
                "Request": {"RequestOption": "nonvalidate"},
                "Shipment": {
                    "Shipper": {
                        "Name": "Test",
                        "ShipperNumber": "129D9Y",
                        "Address": {"AddressLine": ["123 Main"], "City": "New York",
                                    "StateProvinceCode": "NY", "PostalCode": "10001",
                                    "CountryCode": "US"},
                        "AttentionName": "Attn", "Phone": {"Number": "1234567890"},
                    },
                    "ShipTo": {
                        "Name": "Recip",
                        "Address": {"AddressLine": ["456 Elm"], "City": "Toronto",
                                    "StateProvinceCode": "ON", "PostalCode": "M5V 2T6",
                                    "CountryCode": "CA"},
                        "AttentionName": "Recip Attn", "Phone": {"Number": "9876543210"},
                    },
                    "Service": {"Code": "07"},
                    "Description": "Test goods",
                    "Package": [{"Packaging": {"Code": "02"},
                                 "PackageWeight": {"UnitOfMeasurement": {"Code": "LBS"},
                                                   "Weight": "5"}}],
                    "PaymentInformation": {
                        "ShipmentCharge": [{"Type": "01",
                                            "BillShipper": {"AccountNumber": "129D9Y"}}],
                    },
                    "ShipmentServiceOptions": {
                        "InternationalForms": {
                            "FormType": "01", "CurrencyCode": "USD",
                            "ReasonForExport": "SALE", "InvoiceNumber": "INV-1",
                            "InvoiceDate": "20260219",
                            "Product": [{"Description": "Widget",
                                         "Unit": {"Number": "1", "Value": "100",
                                                  "UnitOfMeasurement": {"Code": "PCS"}},
                                         "OriginCountryCode": "US"}],
                        },
                    },
                },
            },
        }
        if return_service is not None:
            body["ShipmentRequest"]["Shipment"]["ReturnService"] = return_service
        return body

    def test_valid_return_service_suppresses_invoice_line_total(self) -> None:
        body = self._make_us_to_ca_body(return_service={"Code": "8"})
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertNotIn("invoice_currency_code", flat_keys)
        self.assertNotIn("invoice_monetary_value", flat_keys)

    def test_empty_string_return_service_requires_invoice(self) -> None:
        body = self._make_us_to_ca_body(return_service="")
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertIn("invoice_currency_code", flat_keys)

    def test_empty_dict_return_service_requires_invoice(self) -> None:
        body = self._make_us_to_ca_body(return_service={})
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertIn("invoice_currency_code", flat_keys)

    def test_dict_with_empty_code_requires_invoice(self) -> None:
        body = self._make_us_to_ca_body(return_service={"Code": ""})
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertIn("invoice_currency_code", flat_keys)

    def test_no_return_service_requires_invoice(self) -> None:
        body = self._make_us_to_ca_body(return_service=None)
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertIn("invoice_currency_code", flat_keys)
```

**Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_shipment_validator.py::ReturnServiceCheckTests -v`
Expected: `test_empty_string_return_service_requires_invoice` and `test_empty_dict_return_service_requires_invoice` and `test_dict_with_empty_code_requires_invoice` FAIL (currently treated as returns because `is not None` is True for `""`, `{}`, `{"Code": ""}`)

**Step 3: Implement the fix in shipment_validator**

In `ups_mcp/shipment_validator.py`, find the `is_return` line (around line 605) inside `find_missing_fields()`. Remove the old TODO comment and change:

```python
    # TODO: tighten to isinstance(dict) + Code check. Current permissive
    # guard is the safer baseline for forward/return classification.
    is_return = shipment.get("ReturnService") is not None
```
to:
```python
    rs = shipment.get("ReturnService")
    is_return = isinstance(rs, dict) and bool(rs.get("Code"))
```

**Step 4: Implement the fix in rating_validator**

In `ups_mcp/rating_validator.py`, find the `is_return` line (around line 450) and change:
```python
    is_return = shipment.get("ReturnService") is not None
```
to:
```python
    rs = shipment.get("ReturnService")
    is_return = isinstance(rs, dict) and bool(rs.get("Code"))
```

**Step 5: Run tests**

Run: `python3 -m pytest tests/test_shipment_validator.py::ReturnServiceCheckTests -v`
Expected: All PASS

**Step 6: Run full suite**

Run: `python3 -m pytest tests/ -v`
Expected: All pass

**Step 7: Commit**

```bash
git add ups_mcp/shipment_validator.py ups_mcp/rating_validator.py tests/test_shipment_validator.py
git commit -m "fix: tighten ReturnService check to require dict with non-empty Code"
```

---

### Task 4: Bug fix — isinstance pattern matching + defensive schema build

**Files:**
- Modify: `ups_mcp/elicitation.py:20-22` (imports), `ups_mcp/elicitation.py:449-556` (elicit_and_rehydrate)
- Test: `tests/test_elicitation.py`

**Step 1: Write failing tests**

The existing tests use mock objects with `.action = "accept"` etc. We need to verify that the code works with real `AcceptedElicitation`, `DeclinedElicitation`, `CancelledElicitation` instances. Add to `tests/test_elicitation.py`:

```python
from mcp.server.elicitation import AcceptedElicitation, DeclinedElicitation, CancelledElicitation
from pydantic import create_model


class TypedElicitationResultTests(unittest.IsolatedAsyncioTestCase):
    """Verify elicit_and_rehydrate works with real typed result classes."""

    async def test_accept_with_real_accepted_elicitation(self) -> None:
        """AcceptedElicitation instance with .data as a real Pydantic model."""
        Model = create_model("TestModel", name=(str, ...))
        data_instance = Model(name="Test Corp")
        accepted = AcceptedElicitation(data=data_instance)
        ctx = _make_form_ctx(elicit_result=accepted)
        missing = _simple_missing()

        result = await elicit_and_rehydrate(
            ctx, {"Root": {}}, missing,
            find_missing_fn=lambda b: [],
            tool_label="test",
        )
        self.assertEqual(result["Root"]["Name"], "Test Corp")

    async def test_decline_with_real_declined_elicitation(self) -> None:
        declined = DeclinedElicitation()
        ctx = _make_form_ctx(elicit_result=declined)

        with self.assertRaises(ToolError) as cm:
            await elicit_and_rehydrate(
                ctx, {"Root": {}}, _simple_missing(),
                find_missing_fn=lambda b: [],
                tool_label="test",
            )
        payload = json.loads(str(cm.exception))
        self.assertEqual(payload["code"], "ELICITATION_DECLINED")

    async def test_cancel_with_real_cancelled_elicitation(self) -> None:
        cancelled = CancelledElicitation()
        ctx = _make_form_ctx(elicit_result=cancelled)

        with self.assertRaises(ToolError) as cm:
            await elicit_and_rehydrate(
                ctx, {"Root": {}}, _simple_missing(),
                find_missing_fn=lambda b: [],
                tool_label="test",
            )
        payload = json.loads(str(cm.exception))
        self.assertEqual(payload["code"], "ELICITATION_CANCELLED")


class DefensiveSchemaTests(unittest.IsolatedAsyncioTestCase):
    """Schema should be built from elicitable fields only, not all missing."""

    async def test_schema_excludes_structural_fields(self) -> None:
        """When structural+scalar fields are both missing, structural triggers
        STRUCTURAL_FIELDS_REQUIRED, so schema build never happens. But if we
        ever pass 'missing' (instead of 'elicitable') to build_elicitation_schema,
        structural fields with prompts as complex text would cause problems.
        This test verifies the schema is built from the filtered list."""
        # We can't easily test this directly since structural fields raise before
        # schema build. Instead verify: when only elicitable fields exist,
        # the schema IS built correctly.
        accepted = _make_accepted({"name": "Test"})
        ctx = _make_form_ctx(elicit_result=accepted)
        missing = [MissingField("Root.Name", "name", "Name")]

        result = await elicit_and_rehydrate(
            ctx, {"Root": {}}, missing,
            find_missing_fn=lambda b: [],
            tool_label="test",
        )
        # Verify the schema was called with the correct field
        call_kwargs = ctx.elicit.call_args
        schema = call_kwargs.kwargs.get("schema")
        if schema is None and call_kwargs.args:
            # Might be positional
            schema = call_kwargs.args[1] if len(call_kwargs.args) > 1 else call_kwargs.kwargs.get("schema")
        self.assertIsNotNone(schema)
        self.assertIn("name", schema.model_fields)
```

**Step 2: Run tests to verify behavior**

Run: `python3 -m pytest tests/test_elicitation.py::TypedElicitationResultTests -v`
Expected: These may pass with the current string-matching code since `AcceptedElicitation` has `.action = "accept"` and `.data`. But the real point is they confirm the typed objects work. Run them first to establish baseline.

**Step 3: Implement isinstance matching + defensive schema build**

In `ups_mcp/elicitation.py`, add the import (after line 22):
```python
from mcp.server.elicitation import (
    AcceptedElicitation,
    DeclinedElicitation,
    CancelledElicitation,
)
```

Then replace the `elicit_and_rehydrate` function body (lines 449-556) with this updated version. Key changes:
- Line 495: `build_elicitation_schema(missing)` → `build_elicitation_schema(elicitable)`
- Line 498: message uses `len(elicitable)` instead of `len(missing)`
- Lines 511-556: Replace string matching with isinstance checks

```python
async def elicit_and_rehydrate(
    ctx: Context | None,
    body: dict,
    missing: list[MissingField],
    find_missing_fn: Callable[[dict], list[MissingField]],
    tool_label: str,
    canonicalize_fn: Callable[[dict], dict] | None = None,
) -> dict:
    """Centralized elicitation flow: check support, elicit, validate, rehydrate.

    1. Check form elicitation support -> raise ELICITATION_UNSUPPORTED if not
    2. Build schema -> call ctx.elicit() -> handle transport errors
    3. On accept: normalize -> validate -> rehydrate -> re-run find_missing_fn
       -> raise if still missing
    4. On decline/cancel: raise appropriate ToolError

    The ``canonicalize_fn`` is called before rehydration (for body normalization).
    Passed as ``None`` for tools that don't need it.

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
            "message": f"Missing {len(elicitable)} required field(s) and client does not support form elicitation",
            "reason": "unsupported",
            "missing": _missing_payload(elicitable),
        }))

    schema = build_elicitation_schema(elicitable)
    try:
        result = await ctx.elicit(
            message=f"Missing {len(elicitable)} required field(s) for {tool_label}.",
            schema=schema,
        )
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
            raise ToolError(json.dumps({
                "code": "ELICITATION_INVALID_RESPONSE",
                "message": "; ".join(validation_errors),
                "reason": "validation_errors",
                "missing": _missing_payload(elicitable),
            }))
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
        if still_missing:
            raise ToolError(json.dumps({
                "code": "INCOMPLETE_SHIPMENT",
                "message": "Still missing required fields after elicitation",
                "reason": "still_missing",
                "missing": _missing_payload(still_missing),
            }))
        return updated

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
```

**Step 4: Run all tests**

Run: `python3 -m pytest tests/ -v`
Expected: All pass including new and existing tests

**Step 5: Commit**

```bash
git add ups_mcp/elicitation.py tests/test_elicitation.py
git commit -m "fix: adopt isinstance pattern matching and defensive schema build for elicitation"
```

---

### Task 5: Retry loop — tests first

**Files:**
- Test: `tests/test_elicitation.py`

**Step 1: Write failing tests for retry behavior**

Add to `tests/test_elicitation.py`:

```python
class RetryLoopTests(unittest.IsolatedAsyncioTestCase):
    """Elicitation should retry on validation errors instead of terminating."""

    async def test_validation_error_retries_then_succeeds(self) -> None:
        """First attempt has bad weight, second attempt is valid."""
        missing = [MissingField("Root.Weight", "package_1_weight", "Package weight")]

        bad_result = _make_accepted({"package_1_weight": "not_a_number"})
        good_result = _make_accepted({"package_1_weight": "5.0"})
        ctx = _make_form_ctx(elicit_side_effect=[bad_result, good_result])

        result = await elicit_and_rehydrate(
            ctx, {"Root": {}}, missing,
            find_missing_fn=lambda b: [],
            tool_label="test",
        )
        self.assertEqual(result["Root"]["Weight"], "5.0")
        self.assertEqual(ctx.elicit.call_count, 2)

    async def test_retry_message_contains_errors(self) -> None:
        """Second elicit call should have error context in the message."""
        missing = [MissingField("Root.Weight", "package_1_weight", "Package weight")]

        bad_result = _make_accepted({"package_1_weight": "-1"})
        good_result = _make_accepted({"package_1_weight": "5.0"})
        ctx = _make_form_ctx(elicit_side_effect=[bad_result, good_result])

        await elicit_and_rehydrate(
            ctx, {"Root": {}}, missing,
            find_missing_fn=lambda b: [],
            tool_label="test",
        )
        # Check the second call's message contains error context
        second_call = ctx.elicit.call_args_list[1]
        msg = second_call.kwargs.get("message", second_call.args[0] if second_call.args else "")
        self.assertIn("correct the following", msg.lower())
        self.assertIn("positive", msg.lower())

    async def test_max_retries_exceeded_raises(self) -> None:
        """After max_retries validation failures, raise ELICITATION_MAX_RETRIES."""
        missing = [MissingField("Root.Weight", "package_1_weight", "Package weight")]

        bad_result = _make_accepted({"package_1_weight": "not_a_number"})
        ctx = _make_form_ctx(elicit_side_effect=[bad_result, bad_result, bad_result])

        with self.assertRaises(ToolError) as cm:
            await elicit_and_rehydrate(
                ctx, {"Root": {}}, missing,
                find_missing_fn=lambda b: [],
                tool_label="test",
                max_retries=3,
            )
        payload = json.loads(str(cm.exception))
        self.assertEqual(payload["code"], "ELICITATION_MAX_RETRIES")
        self.assertEqual(ctx.elicit.call_count, 3)

    async def test_decline_on_retry_raises_immediately(self) -> None:
        """If user declines on retry, raise immediately (no more retries)."""
        missing = [MissingField("Root.Weight", "package_1_weight", "Package weight")]

        bad_result = _make_accepted({"package_1_weight": "not_a_number"})
        declined = MagicMock()
        declined.action = "decline"
        ctx = _make_form_ctx(elicit_side_effect=[bad_result, declined])

        with self.assertRaises(ToolError) as cm:
            await elicit_and_rehydrate(
                ctx, {"Root": {}}, missing,
                find_missing_fn=lambda b: [],
                tool_label="test",
            )
        payload = json.loads(str(cm.exception))
        self.assertEqual(payload["code"], "ELICITATION_DECLINED")

    async def test_still_missing_retries_with_remaining_fields(self) -> None:
        """If rehydration succeeds but fields still missing, retry with those."""
        missing = [
            MissingField("Root.Name", "name", "Name"),
            MissingField("Root.City", "city", "City"),
        ]

        # First attempt: provides name but find_missing returns city still needed
        first_result = _make_accepted({"name": "Test", "city": ""})
        # Second attempt: provides city
        second_result = _make_accepted({"city": "NYC"})

        call_count = [0]
        def find_fn(b):
            call_count[0] += 1
            if call_count[0] == 1:
                # After first rehydration, city is still missing
                return [MissingField("Root.City", "city", "City")]
            return []

        ctx = _make_form_ctx(elicit_side_effect=[first_result, second_result])

        result = await elicit_and_rehydrate(
            ctx, {"Root": {}}, missing,
            find_missing_fn=find_fn,
            tool_label="test",
        )
        self.assertEqual(result["Root"]["Name"], "Test")
        self.assertEqual(result["Root"]["City"], "NYC")

    async def test_first_attempt_success_no_retry(self) -> None:
        """Valid first attempt returns immediately (backward compat)."""
        accepted = _make_accepted({"name": "Test Corp"})
        ctx = _make_form_ctx(elicit_result=accepted)
        missing = _simple_missing()

        result = await elicit_and_rehydrate(
            ctx, {"Root": {}}, missing,
            find_missing_fn=lambda b: [],
            tool_label="test",
        )
        self.assertEqual(result["Root"]["Name"], "Test Corp")
        self.assertEqual(ctx.elicit.call_count, 1)
```

**Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_elicitation.py::RetryLoopTests -v`
Expected: FAIL — `max_retries` parameter doesn't exist yet, validation errors currently raise immediately

**Step 3: Commit test-only**

```bash
git add tests/test_elicitation.py
git commit -m "test: add retry loop tests for elicitation (red phase)"
```

---

### Task 6: Retry loop — implementation

**Files:**
- Modify: `ups_mcp/elicitation.py:449-556` (replace `elicit_and_rehydrate`)

**Step 1: Implement retry loop**

Replace the entire `elicit_and_rehydrate` function in `ups_mcp/elicitation.py` with:

```python
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
```

**Step 2: Run retry tests**

Run: `python3 -m pytest tests/test_elicitation.py::RetryLoopTests -v`
Expected: All PASS

**Step 3: Run full suite**

Run: `python3 -m pytest tests/ -v`
Expected: All pass including all existing tests (backward compatible)

**Step 4: Commit**

```bash
git add ups_mcp/elicitation.py
git commit -m "feat: add retry loop to elicit_and_rehydrate for validation error recovery"
```

---

### Task 7: Array flattening — data structures and helpers

**Files:**
- Modify: `ups_mcp/elicitation.py` (add ArrayFieldRule, _get_existing_array, expand_array_fields, reconstruct_array)
- Test: `tests/test_elicitation.py`

**Step 1: Write failing tests**

Add to `tests/test_elicitation.py`:

```python
from ups_mcp.elicitation import ArrayFieldRule, expand_array_fields, reconstruct_array


class ArrayFieldRuleTests(unittest.TestCase):
    """Tests for the ArrayFieldRule data structure and helper functions."""

    def _make_product_rule(self) -> ArrayFieldRule:
        return ArrayFieldRule(
            array_dot_path="Root.Items.Product",
            item_prefix="product",
            count_key="product_count",
            count_prompt="How many products?",
            item_rules=(
                FieldRule("Description", "description", "Product description"),
                FieldRule("Value", "value", "Unit value", type_hint=float),
            ),
            max_items=5,
            default_count=1,
        )

    def test_expand_empty_data_generates_default_count_fields(self) -> None:
        rule = self._make_product_rule()
        missing = expand_array_fields(rule, {"Root": {"Items": {}}})
        # default_count=1, 2 rules per item = 2 fields
        self.assertEqual(len(missing), 2)
        self.assertEqual(missing[0].flat_key, "product_1_description")
        self.assertEqual(missing[0].dot_path, "Root.Items.Product[0].Description")
        self.assertEqual(missing[0].prompt, "Item 1: Product description")
        self.assertEqual(missing[1].flat_key, "product_1_value")

    def test_expand_existing_items_generates_per_item_fields(self) -> None:
        rule = self._make_product_rule()
        data = {"Root": {"Items": {"Product": [
            {"Description": "Widget"},  # Value missing
            {},                         # Both missing
        ]}}}
        missing = expand_array_fields(rule, data)
        flat_keys = {mf.flat_key for mf in missing}
        # Item 1: only value missing (description exists)
        self.assertNotIn("product_1_description", flat_keys)
        self.assertIn("product_1_value", flat_keys)
        # Item 2: both missing
        self.assertIn("product_2_description", flat_keys)
        self.assertIn("product_2_value", flat_keys)

    def test_expand_respects_max_items(self) -> None:
        rule = self._make_product_rule()  # max_items=5
        data = {"Root": {"Items": {"Product": [{} for _ in range(10)]}}}
        missing = expand_array_fields(rule, data)
        # Should cap at 5 items * 2 rules = 10 max fields
        item_indices = {int(mf.flat_key.split("_")[1]) for mf in missing}
        self.assertTrue(max(item_indices) <= 5)

    def test_expand_with_explicit_count(self) -> None:
        rule = self._make_product_rule()
        missing = expand_array_fields(rule, {"Root": {"Items": {}}}, start_count=3)
        item_indices = {int(mf.flat_key.split("_")[1]) for mf in missing}
        self.assertEqual(item_indices, {1, 2, 3})

    def test_expand_single_dict_product_treated_as_list(self) -> None:
        rule = self._make_product_rule()
        data = {"Root": {"Items": {"Product": {"Description": "Widget"}}}}
        missing = expand_array_fields(rule, data)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertNotIn("product_1_description", flat_keys)
        self.assertIn("product_1_value", flat_keys)

    def test_reconstruct_builds_nested_array(self) -> None:
        rule = self._make_product_rule()
        flat_data = {
            "product_1_description": "Widget",
            "product_1_value": "100.00",
            "product_2_description": "Gadget",
            "product_2_value": "50.00",
        }
        items = reconstruct_array(flat_data, rule, count=2)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["Description"], "Widget")
        self.assertEqual(items[0]["Value"], "100.00")
        self.assertEqual(items[1]["Description"], "Gadget")

    def test_reconstruct_skips_empty_items(self) -> None:
        rule = self._make_product_rule()
        flat_data = {
            "product_1_description": "Widget",
            "product_1_value": "100.00",
            # product_2 has no data
        }
        items = reconstruct_array(flat_data, rule, count=2)
        self.assertEqual(len(items), 1)  # only non-empty items

    def test_reconstruct_handles_nested_dot_paths(self) -> None:
        rule = ArrayFieldRule(
            array_dot_path="Root.Product",
            item_prefix="prod",
            count_key="prod_count",
            count_prompt="How many?",
            item_rules=(
                FieldRule("Unit.Value", "unit_value", "Value"),
                FieldRule("Unit.Code", "unit_code", "Code"),
            ),
        )
        flat_data = {"prod_1_unit_value": "100", "prod_1_unit_code": "PCS"}
        items = reconstruct_array(flat_data, rule, count=1)
        self.assertEqual(items[0]["Unit"]["Value"], "100")
        self.assertEqual(items[0]["Unit"]["Code"], "PCS")
```

**Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_elicitation.py::ArrayFieldRuleTests -v`
Expected: ImportError — `ArrayFieldRule`, `expand_array_fields`, `reconstruct_array` don't exist yet

**Step 3: Implement the data structures and functions**

In `ups_mcp/elicitation.py`, add after the `FieldRule` class (around line 67):

```python
@dataclass(frozen=True)
class ArrayFieldRule:
    """Declares an array of structured items elicitable via flat forms.

    The system flattens each item's sub-fields into indexed scalar keys
    (e.g. product_1_description, product_1_value) and reconstructs the
    nested array during rehydration.
    """
    array_dot_path: str
    item_prefix: str
    count_key: str
    count_prompt: str
    item_rules: tuple[FieldRule, ...]
    max_items: int = 10
    default_count: int = 1
```

Add after the `_missing_from_rule` function (around line 184), the helper functions:

```python
def _get_existing_array(data: dict, dot_path: str) -> list[dict]:
    """Navigate to dot_path and return the existing array items.

    Returns [] if the path doesn't exist or isn't a list/dict.
    A single dict is normalized to [dict].
    """
    current: Any = data
    for segment in dot_path.split("."):
        key, idx = _parse_path_segment(segment)
        if not isinstance(current, dict) or key not in current:
            return []
        current = current[key]
        if idx is not None:
            if not isinstance(current, list) or len(current) <= idx:
                return []
            current = current[idx]
    if isinstance(current, dict):
        return [current]
    if isinstance(current, list):
        return [item if isinstance(item, dict) else {} for item in current]
    return []


def expand_array_fields(
    rule: ArrayFieldRule,
    data: dict,
    start_count: int | None = None,
) -> list[MissingField]:
    """Expand an ArrayFieldRule into indexed MissingFields for each item.

    Inspects existing data at array_dot_path to determine item count.
    For each item, checks which sub-fields are missing and generates
    indexed MissingFields with flat keys like product_1_description.
    """
    existing = _get_existing_array(data, rule.array_dot_path)
    count = start_count if start_count is not None else max(len(existing), rule.default_count)
    count = min(count, rule.max_items)

    missing: list[MissingField] = []
    for i in range(count):
        n = i + 1
        item_data = existing[i] if i < len(existing) else {}
        for sub_rule in rule.item_rules:
            if not _field_exists(item_data, sub_rule.dot_path):
                missing.append(_missing_from_rule(
                    sub_rule,
                    dot_path=f"{rule.array_dot_path}[{i}].{sub_rule.dot_path}",
                    flat_key=f"{rule.item_prefix}_{n}_{sub_rule.flat_key}",
                    prompt=f"Item {n}: {sub_rule.prompt}",
                ))
    return missing


def reconstruct_array(
    flat_data: dict[str, str],
    rule: ArrayFieldRule,
    count: int,
) -> list[dict]:
    """Reconstruct a nested array from flat indexed elicitation values.

    Matches keys like product_1_description, product_1_value and builds
    nested dicts using _set_field for each item's sub-rules.
    """
    items: list[dict] = []
    for i in range(count):
        n = i + 1
        item: dict = {}
        for sub_rule in rule.item_rules:
            flat_key = f"{rule.item_prefix}_{n}_{sub_rule.flat_key}"
            value = flat_data.get(flat_key)
            if value is not None and value != "":
                _set_field(item, sub_rule.dot_path, value)
        if item:
            items.append(item)
    return items
```

**Step 4: Run tests**

Run: `python3 -m pytest tests/test_elicitation.py::ArrayFieldRuleTests -v`
Expected: All PASS

**Step 5: Run full suite**

Run: `python3 -m pytest tests/ -v`
Expected: All pass

**Step 6: Commit**

```bash
git add ups_mcp/elicitation.py tests/test_elicitation.py
git commit -m "feat: add ArrayFieldRule, expand_array_fields, and reconstruct_array for flat array elicitation"
```

---

### Task 8: Array flattening — integrate into elicit_and_rehydrate

**Files:**
- Modify: `ups_mcp/elicitation.py` (add `array_rules` param to `elicit_and_rehydrate`)
- Test: `tests/test_elicitation.py`

**Step 1: Write failing test**

Add to `tests/test_elicitation.py`:

```python
class ArrayElicitationIntegrationTests(unittest.IsolatedAsyncioTestCase):
    """Integration: array fields flow through the full elicitation pipeline."""

    def _make_rule(self) -> ArrayFieldRule:
        return ArrayFieldRule(
            array_dot_path="Root.Items.Product",
            item_prefix="product",
            count_key="product_count",
            count_prompt="How many?",
            item_rules=(
                FieldRule("Description", "description", "Product description"),
                FieldRule("Value", "value", "Unit value", type_hint=float),
            ),
        )

    async def test_array_fields_elicited_and_reconstructed(self) -> None:
        """Array fields should be collected via flat form and reconstructed."""
        rule = self._make_rule()
        # Missing: both scalar and array fields
        missing = [
            MissingField("Root.Name", "name", "Name"),
            # Array fields generated by expand_array_fields:
            MissingField("Root.Items.Product[0].Description",
                         "product_1_description", "Item 1: Product description"),
            MissingField("Root.Items.Product[0].Value",
                         "product_1_value", "Item 1: Unit value", type_hint=float),
        ]

        accepted = _make_accepted({
            "name": "Test",
            "product_1_description": "Widget",
            "product_1_value": "100",
        })
        ctx = _make_form_ctx(elicit_result=accepted)

        result = await elicit_and_rehydrate(
            ctx, {"Root": {"Items": {}}}, missing,
            find_missing_fn=lambda b: [],
            tool_label="test",
            array_rules=[rule],
        )
        self.assertEqual(result["Root"]["Name"], "Test")
        products = result["Root"]["Items"]["Product"]
        self.assertEqual(len(products), 1)
        self.assertEqual(products[0]["Description"], "Widget")
        self.assertEqual(products[0]["Value"], "100")

    async def test_array_rules_none_backward_compat(self) -> None:
        """When array_rules is None, behavior is unchanged (backward compat)."""
        accepted = _make_accepted({"name": "Test Corp"})
        ctx = _make_form_ctx(elicit_result=accepted)
        missing = _simple_missing()

        result = await elicit_and_rehydrate(
            ctx, {"Root": {}}, missing,
            find_missing_fn=lambda b: [],
            tool_label="test",
            array_rules=None,
        )
        self.assertEqual(result["Root"]["Name"], "Test Corp")
```

**Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_elicitation.py::ArrayElicitationIntegrationTests -v`
Expected: FAIL — `array_rules` parameter doesn't exist yet

**Step 3: Implement array_rules integration**

In `ups_mcp/elicitation.py`, update the `elicit_and_rehydrate` signature to add the parameter:

```python
async def elicit_and_rehydrate(
    ctx: Context | None,
    body: dict,
    missing: list[MissingField],
    find_missing_fn: Callable[[dict], list[MissingField]],
    tool_label: str,
    canonicalize_fn: Callable[[dict], dict] | None = None,
    max_retries: int = 3,
    array_rules: list[ArrayFieldRule] | None = None,
) -> dict:
```

Then inside the `AcceptedElicitation` branch, after the successful `rehydrate()` call and before the `still_missing = find_missing_fn(updated)` line, add array reconstruction:

```python
            # Reconstruct arrays from flat indexed values
            if array_rules:
                for arr_rule in array_rules:
                    existing = _get_existing_array(updated, arr_rule.array_dot_path)
                    # Determine how many items were in the flat data
                    max_n = 0
                    for key in normalized:
                        if key.startswith(f"{arr_rule.item_prefix}_"):
                            parts = key.split("_")
                            if len(parts) >= 2 and parts[1].isdigit():
                                max_n = max(max_n, int(parts[1]))
                    if max_n > 0:
                        items = reconstruct_array(normalized, arr_rule, count=max_n)
                        if items:
                            # Merge with existing items: reconstructed items
                            # fill in missing sub-fields of existing items
                            merged_items = []
                            for idx, item in enumerate(items):
                                if idx < len(existing):
                                    # Merge: existing values take precedence
                                    merged = copy.deepcopy(existing[idx])
                                    for k, v in item.items():
                                        if k not in merged or merged[k] in (None, ""):
                                            merged[k] = v
                                        elif isinstance(merged[k], dict) and isinstance(v, dict):
                                            for sk, sv in v.items():
                                                if sk not in merged[k] or merged[k][sk] in (None, ""):
                                                    merged[k][sk] = sv
                                    merged_items.append(merged)
                                else:
                                    merged_items.append(item)
                            _set_field(updated, arr_rule.array_dot_path, merged_items)
```

**Step 4: Run tests**

Run: `python3 -m pytest tests/test_elicitation.py::ArrayElicitationIntegrationTests -v`
Expected: All PASS

**Step 5: Run full suite**

Run: `python3 -m pytest tests/ -v`
Expected: All pass

**Step 6: Commit**

```bash
git add ups_mcp/elicitation.py tests/test_elicitation.py
git commit -m "feat: integrate array_rules into elicit_and_rehydrate for array reconstruction"
```

---

### Task 9: Wire Product array into shipment_validator

**Files:**
- Modify: `ups_mcp/shipment_validator.py` (add PRODUCT_ITEM_RULES, PRODUCT_ARRAY_RULE, replace elicitable=False Product)
- Test: `tests/test_shipment_validator.py`

**Step 1: Write failing tests**

Add to `tests/test_shipment_validator.py`. First add imports:

```python
from ups_mcp.shipment_validator import (
    find_missing_fields,
    PRODUCT_ITEM_RULES,
    PRODUCT_ARRAY_RULE,
)
from ups_mcp.elicitation import ArrayFieldRule
```

Then add the test class:

```python
class ProductArrayRuleTests(unittest.TestCase):
    """Product array should generate elicitable indexed fields instead of
    a structural STRUCTURAL_FIELDS_REQUIRED error."""

    def test_product_array_rule_exists(self) -> None:
        self.assertIsInstance(PRODUCT_ARRAY_RULE, ArrayFieldRule)
        self.assertEqual(PRODUCT_ARRAY_RULE.item_prefix, "product")

    def test_product_item_rules_has_required_fields(self) -> None:
        flat_keys = {r.flat_key for r in PRODUCT_ITEM_RULES}
        self.assertIn("description", flat_keys)
        self.assertIn("quantity", flat_keys)
        self.assertIn("value", flat_keys)
        self.assertIn("unit_code", flat_keys)
        self.assertIn("origin_country", flat_keys)

    def test_international_missing_product_generates_indexed_fields(self) -> None:
        """When InternationalForms has no Product, generate product_1_* fields."""
        body = {
            "ShipmentRequest": {
                "Request": {"RequestOption": "nonvalidate"},
                "Shipment": {
                    "Shipper": {
                        "Name": "Test", "ShipperNumber": "129D9Y",
                        "Address": {"AddressLine": ["123 Main"], "City": "NYC",
                                    "StateProvinceCode": "NY", "PostalCode": "10001",
                                    "CountryCode": "US"},
                        "AttentionName": "Attn", "Phone": {"Number": "1234567890"},
                    },
                    "ShipTo": {
                        "Name": "Recip",
                        "Address": {"AddressLine": ["456 Elm"], "City": "London",
                                    "CountryCode": "GB"},
                        "AttentionName": "Recip", "Phone": {"Number": "4412345678"},
                    },
                    "Service": {"Code": "07"},
                    "Description": "Test goods",
                    "Package": [{"Packaging": {"Code": "02"},
                                 "PackageWeight": {"UnitOfMeasurement": {"Code": "LBS"},
                                                   "Weight": "5"}}],
                    "PaymentInformation": {
                        "ShipmentCharge": [{"Type": "01",
                                            "BillShipper": {"AccountNumber": "129D9Y"}}],
                    },
                    "ShipmentServiceOptions": {
                        "InternationalForms": {
                            "FormType": "01", "CurrencyCode": "USD",
                            "ReasonForExport": "SALE", "InvoiceNumber": "INV-1",
                            "InvoiceDate": "20260219",
                            # Product is missing!
                        },
                    },
                },
            },
        }
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        # Should have product_1_* indexed fields, NOT intl_forms_product_required
        self.assertNotIn("intl_forms_product_required", flat_keys)
        self.assertIn("product_1_description", flat_keys)
        self.assertIn("product_1_value", flat_keys)
        self.assertIn("product_1_origin_country", flat_keys)
        # All should be elicitable
        product_fields = [mf for mf in missing if mf.flat_key.startswith("product_")]
        for mf in product_fields:
            self.assertTrue(mf.elicitable, f"{mf.flat_key} should be elicitable")

    def test_existing_product_only_elicits_missing_subfields(self) -> None:
        """When Product[0] has Description, only elicit the missing sub-fields."""
        body = {
            "ShipmentRequest": {
                "Request": {"RequestOption": "nonvalidate"},
                "Shipment": {
                    "Shipper": {
                        "Name": "Test", "ShipperNumber": "129D9Y",
                        "Address": {"AddressLine": ["123 Main"], "City": "NYC",
                                    "StateProvinceCode": "NY", "PostalCode": "10001",
                                    "CountryCode": "US"},
                        "AttentionName": "Attn", "Phone": {"Number": "1234567890"},
                    },
                    "ShipTo": {
                        "Name": "Recip",
                        "Address": {"AddressLine": ["456 Elm"], "City": "London",
                                    "CountryCode": "GB"},
                        "AttentionName": "Recip", "Phone": {"Number": "4412345678"},
                    },
                    "Service": {"Code": "07"},
                    "Description": "Test goods",
                    "Package": [{"Packaging": {"Code": "02"},
                                 "PackageWeight": {"UnitOfMeasurement": {"Code": "LBS"},
                                                   "Weight": "5"}}],
                    "PaymentInformation": {
                        "ShipmentCharge": [{"Type": "01",
                                            "BillShipper": {"AccountNumber": "129D9Y"}}],
                    },
                    "ShipmentServiceOptions": {
                        "InternationalForms": {
                            "FormType": "01", "CurrencyCode": "USD",
                            "ReasonForExport": "SALE", "InvoiceNumber": "INV-1",
                            "InvoiceDate": "20260219",
                            "Product": [{"Description": "Widget",
                                         "OriginCountryCode": "US"}],
                        },
                    },
                },
            },
        }
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        # Description and OriginCountryCode are present — should NOT be missing
        self.assertNotIn("product_1_description", flat_keys)
        self.assertNotIn("product_1_origin_country", flat_keys)
        # Unit.Number, Unit.Value, Unit.UnitOfMeasurement.Code ARE missing
        self.assertIn("product_1_quantity", flat_keys)
        self.assertIn("product_1_value", flat_keys)
        self.assertIn("product_1_unit_code", flat_keys)
```

**Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_shipment_validator.py::ProductArrayRuleTests -v`
Expected: ImportError — `PRODUCT_ITEM_RULES` and `PRODUCT_ARRAY_RULE` don't exist

**Step 3: Implement Product rules and wire into find_missing_fields**

In `ups_mcp/shipment_validator.py`, add the import at the top (after the existing elicitation imports):

```python
from .elicitation import FieldRule, MissingField, _missing_from_rule, _field_exists, _set_field, ArrayFieldRule, expand_array_fields
```

Add the Product rules after the `INTL_FORMS_INVOICE_DATE_RULE` (around line 250):

```python
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
    count_key="product_count",
    count_prompt="How many different products in this shipment?",
    item_rules=PRODUCT_ITEM_RULES,
)
```

Then in `find_missing_fields()`, replace the `elicitable=False` Product block (lines ~654-674). Change this:

```python
            # Product[] missing for forms that require it
            if form_types and any(ft in FORMS_REQUIRING_PRODUCTS for ft in form_types):
                products = intl_forms.get("Product")
                has_products = (
                    isinstance(products, list) and len(products) > 0
                ) or isinstance(products, dict)
                if not has_products:
                    missing.append(MissingField(
                        dot_path="ShipmentRequest.Shipment.ShipmentServiceOptions.InternationalForms.Product",
                        flat_key="intl_forms_product_required",
                        prompt=(
                            "This form type requires a Product array. Add Product to InternationalForms "
                            "with at least: Description, Unit (Number, Value, UnitOfMeasurement.Code), "
                            "OriginCountryCode. Example: "
                            '"Product": [{"Description": "Electronics", '
                            '"Unit": {"Number": "1", "Value": "100", '
                            '"UnitOfMeasurement": {"Code": "PCS"}}, '
                            '"CommodityCode": "8471.30", "OriginCountryCode": "US"}]'
                        ),
                        elicitable=False,
                    ))
```

To this:

```python
            # Product array: expand into indexed elicitable fields
            if form_types and any(ft in FORMS_REQUIRING_PRODUCTS for ft in form_types):
                missing.extend(expand_array_fields(PRODUCT_ARRAY_RULE, body))
```

**Step 4: Run tests**

Run: `python3 -m pytest tests/test_shipment_validator.py::ProductArrayRuleTests -v`
Expected: All PASS

**Step 5: Run full suite (look for regressions in existing shipment tests)**

Run: `python3 -m pytest tests/ -v`
Expected: All pass. Note: existing tests that checked for `intl_forms_product_required` may need updating if they exist. Check for failures and fix as needed.

**Step 6: Commit**

```bash
git add ups_mcp/shipment_validator.py tests/test_shipment_validator.py
git commit -m "feat: replace structural Product error with elicitable indexed array fields"
```

---

### Task 10: Wire array_rules into server.py for create_shipment

**Files:**
- Modify: `ups_mcp/server.py` (add array_rules import and pass to elicit_and_rehydrate)
- Test: `tests/test_server_elicitation.py` (if exists — verify integration)

**Step 1: Update server.py**

In `ups_mcp/server.py`, inside the `create_shipment` function, update the import block (around line 342-348) to also import `PRODUCT_ARRAY_RULE`:

```python
    from .shipment_validator import (
        apply_defaults,
        find_missing_fields,
        canonicalize_body,
        AmbiguousPayerError,
        PRODUCT_ARRAY_RULE,
    )
```

Then update the `elicit_and_rehydrate` call (around line 390-396) to pass `array_rules`:

```python
    merged_body = await elicit_and_rehydrate(
        ctx, merged_body, missing,
        find_missing_fn=find_missing_fields,
        tool_label="shipment creation",
        canonicalize_fn=canonicalize_body,
        array_rules=[PRODUCT_ARRAY_RULE],
    )
```

**Step 2: Run full test suite**

Run: `python3 -m pytest tests/ -v`
Expected: All pass

**Step 3: Commit**

```bash
git add ups_mcp/server.py
git commit -m "feat: pass PRODUCT_ARRAY_RULE to elicit_and_rehydrate in create_shipment"
```

---

### Task 11: Final verification and cleanup

**Files:**
- All modified files

**Step 1: Run full test suite**

Run: `python3 -m pytest tests/ -v`
Expected: All pass

**Step 2: Verify no regressions in existing server tests**

Run: `python3 -m pytest tests/test_server_elicitation.py tests/test_server_rate_elicitation.py -v`
Expected: All pass

**Step 3: Quick smoke test of imports**

Run: `python3 -c "from ups_mcp.elicitation import ArrayFieldRule, expand_array_fields, reconstruct_array, elicit_and_rehydrate; print('OK')"`
Expected: `OK`

Run: `python3 -c "from ups_mcp.shipment_validator import PRODUCT_ARRAY_RULE, PRODUCT_ITEM_RULES; print('OK')"`
Expected: `OK`

**Step 4: Commit any cleanup**

If any cleanup was needed, commit it. Otherwise skip.

**Step 5: Final commit (if any remaining changes)**

```bash
git status
# If clean, done. Otherwise:
git add -A && git commit -m "chore: final cleanup for elicitation hardening"
```
