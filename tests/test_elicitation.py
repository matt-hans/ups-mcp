"""Tests for the generic elicitation infrastructure module."""

import json
import unittest
from unittest.mock import AsyncMock, MagicMock

from mcp.server.elicitation import AcceptedElicitation, DeclinedElicitation, CancelledElicitation
from mcp.server.fastmcp import Context
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import (
    ClientCapabilities,
    ElicitationCapability,
    FormElicitationCapability,
    UrlElicitationCapability,
    InitializeRequestParams,
    Implementation,
)
from pydantic import create_model

from ups_mcp.elicitation import (
    FieldRule,
    MissingField,
    check_form_elicitation,
    elicit_and_rehydrate,
    build_elicitation_schema,
    normalize_elicited_values,
    validate_elicited_values,
    rehydrate,
    RehydrationError,
    _field_exists,
    _set_field,
    _missing_from_rule,
)


# ---------------------------------------------------------------------------
# check_form_elicitation tests
# ---------------------------------------------------------------------------

class CheckFormElicitationTests(unittest.TestCase):
    def _make_ctx(
        self,
        elicitation: ElicitationCapability | None = None,
    ) -> MagicMock:
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
        self.assertFalse(check_form_elicitation(None))

    def test_no_elicitation_capability_returns_false(self) -> None:
        ctx = self._make_ctx(elicitation=None)
        self.assertFalse(check_form_elicitation(ctx))

    def test_form_capability_returns_true(self) -> None:
        ctx = self._make_ctx(
            elicitation=ElicitationCapability(form=FormElicitationCapability())
        )
        self.assertTrue(check_form_elicitation(ctx))

    def test_empty_elicitation_object_returns_true(self) -> None:
        ctx = self._make_ctx(elicitation=ElicitationCapability())
        self.assertTrue(check_form_elicitation(ctx))

    def test_url_only_returns_false(self) -> None:
        ctx = self._make_ctx(
            elicitation=ElicitationCapability(url=UrlElicitationCapability())
        )
        self.assertFalse(check_form_elicitation(ctx))

    def test_both_form_and_url_returns_true(self) -> None:
        ctx = self._make_ctx(
            elicitation=ElicitationCapability(
                form=FormElicitationCapability(),
                url=UrlElicitationCapability(),
            )
        )
        self.assertTrue(check_form_elicitation(ctx))

    def test_attribute_error_returns_false(self) -> None:
        ctx = MagicMock()
        ctx.request_context.session.client_params = None
        self.assertFalse(check_form_elicitation(ctx))


# ---------------------------------------------------------------------------
# elicit_and_rehydrate tests
# ---------------------------------------------------------------------------

def _make_form_ctx(elicit_result=None, elicit_side_effect=None):
    """Build a mock Context with form elicitation support."""
    ctx = MagicMock()
    caps = ClientCapabilities(
        elicitation=ElicitationCapability(form=FormElicitationCapability())
    )
    params = InitializeRequestParams(
        protocolVersion="2025-03-26",
        capabilities=caps,
        clientInfo=Implementation(name="test", version="1.0"),
    )
    ctx.request_context.session.client_params = params
    if elicit_side_effect is not None:
        ctx.elicit = AsyncMock(side_effect=elicit_side_effect)
    elif elicit_result is not None:
        ctx.elicit = AsyncMock(return_value=elicit_result)
    return ctx


def _make_no_form_ctx():
    """Build a mock Context without form elicitation support."""
    ctx = MagicMock()
    caps = ClientCapabilities(elicitation=None)
    params = InitializeRequestParams(
        protocolVersion="2025-03-26",
        capabilities=caps,
        clientInfo=Implementation(name="test", version="1.0"),
    )
    ctx.request_context.session.client_params = params
    return ctx


def _simple_missing():
    """Return a single MissingField for testing."""
    return [MissingField(
        "Root.Name", "name", "Name",
    )]


def _make_accepted(data_dict):
    """Make a real AcceptedElicitation result for testing."""
    fields = {k: (type(v) if v is not None else str, ...) for k, v in data_dict.items()}
    Model = create_model("ElicitedData", **fields)
    instance = Model(**data_dict)
    return AcceptedElicitation(data=instance)


class ElicitAndRehydrateTests(unittest.IsolatedAsyncioTestCase):

    async def test_no_form_support_raises_unsupported(self) -> None:
        ctx = _make_no_form_ctx()
        missing = _simple_missing()
        with self.assertRaises(ToolError) as cm:
            await elicit_and_rehydrate(
                ctx, {"Root": {}}, missing,
                find_missing_fn=lambda b: [],
                tool_label="test",
            )
        payload = json.loads(str(cm.exception))
        self.assertEqual(payload["code"], "ELICITATION_UNSUPPORTED")

    async def test_none_ctx_raises_unsupported(self) -> None:
        missing = _simple_missing()
        with self.assertRaises(ToolError) as cm:
            await elicit_and_rehydrate(
                None, {"Root": {}}, missing,
                find_missing_fn=lambda b: [],
                tool_label="test",
            )
        payload = json.loads(str(cm.exception))
        self.assertEqual(payload["code"], "ELICITATION_UNSUPPORTED")

    async def test_accept_rehydrates_and_returns(self) -> None:
        accepted = _make_accepted({"name": "Test Corp"})
        ctx = _make_form_ctx(elicit_result=accepted)
        missing = _simple_missing()
        body = {"Root": {}}

        result = await elicit_and_rehydrate(
            ctx, body, missing,
            find_missing_fn=lambda b: [],
            tool_label="test",
        )
        self.assertEqual(result["Root"]["Name"], "Test Corp")
        ctx.elicit.assert_called_once()

    async def test_decline_raises_declined(self) -> None:
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

    async def test_cancel_raises_cancelled(self) -> None:
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

    async def test_transport_error_raises_elicitation_failed(self) -> None:
        ctx = _make_form_ctx(elicit_side_effect=RuntimeError("connection lost"))

        with self.assertRaises(ToolError) as cm:
            await elicit_and_rehydrate(
                ctx, {"Root": {}}, _simple_missing(),
                find_missing_fn=lambda b: [],
                tool_label="test",
            )
        payload = json.loads(str(cm.exception))
        self.assertEqual(payload["code"], "ELICITATION_FAILED")
        self.assertIn("connection lost", payload["message"])

    async def test_tool_error_from_elicit_reraises(self) -> None:
        """ToolError from ctx.elicit() should be re-raised as-is."""
        original_error = ToolError("original error")
        ctx = _make_form_ctx(elicit_side_effect=original_error)

        with self.assertRaises(ToolError) as cm:
            await elicit_and_rehydrate(
                ctx, {"Root": {}}, _simple_missing(),
                find_missing_fn=lambda b: [],
                tool_label="test",
            )
        self.assertEqual(str(cm.exception), "original error")

    async def test_still_missing_exhausts_retries(self) -> None:
        """Persistently missing fields after rehydration exhaust retries."""
        accepted = _make_accepted({"name": "Test"})
        ctx = _make_form_ctx(elicit_result=accepted)
        missing = _simple_missing()

        # find_missing_fn always returns something
        still_missing = [MissingField("Root.Other", "other", "Other field")]

        with self.assertRaises(ToolError) as cm:
            await elicit_and_rehydrate(
                ctx, {"Root": {}}, missing,
                find_missing_fn=lambda b: still_missing,
                tool_label="test",
            )
        payload = json.loads(str(cm.exception))
        self.assertEqual(payload["code"], "ELICITATION_MAX_RETRIES")

    async def test_validation_errors_exhaust_retries(self) -> None:
        """Persistent invalid elicited values exhaust retries."""
        missing = [MissingField("Root.Weight", "package_1_weight", "Package weight")]
        accepted = _make_accepted({"package_1_weight": "not_a_number"})
        ctx = _make_form_ctx(elicit_result=accepted)

        with self.assertRaises(ToolError) as cm:
            await elicit_and_rehydrate(
                ctx, {"Root": {}}, missing,
                find_missing_fn=lambda b: [],
                tool_label="test",
            )
        payload = json.loads(str(cm.exception))
        self.assertEqual(payload["code"], "ELICITATION_MAX_RETRIES")

    async def test_rehydration_error_raises_invalid_response(self) -> None:
        """Structural conflict during rehydration raises ELICITATION_INVALID_RESPONSE."""
        missing = [MissingField("Root.Sub.Name", "name", "Name")]
        accepted = _make_accepted({"name": "Test"})
        ctx = _make_form_ctx(elicit_result=accepted)
        # Root.Sub is a string, not a dict — rehydration will fail
        body = {"Root": {"Sub": "not_a_dict"}}

        with self.assertRaises(ToolError) as cm:
            await elicit_and_rehydrate(
                ctx, body, missing,
                find_missing_fn=lambda b: [],
                tool_label="test",
            )
        payload = json.loads(str(cm.exception))
        self.assertEqual(payload["code"], "ELICITATION_INVALID_RESPONSE")
        self.assertEqual(payload["reason"], "rehydration_error")

    async def test_canonicalize_fn_called_before_rehydrate(self) -> None:
        """When canonicalize_fn is provided, it's called on body before rehydration."""
        calls = []

        def mock_canonicalize(body):
            calls.append("canonicalize")
            # Add a marker to verify it was called
            result = dict(body)
            result["_canonicalized"] = True
            return result

        accepted = _make_accepted({"name": "Test"})
        ctx = _make_form_ctx(elicit_result=accepted)
        missing = _simple_missing()

        result = await elicit_and_rehydrate(
            ctx, {"Root": {}}, missing,
            find_missing_fn=lambda b: [],
            tool_label="test",
            canonicalize_fn=mock_canonicalize,
        )
        self.assertEqual(calls, ["canonicalize"])
        self.assertTrue(result.get("_canonicalized"))

    async def test_canonicalize_fn_none_works(self) -> None:
        """When canonicalize_fn is None, body is used as-is for rehydration."""
        accepted = _make_accepted({"name": "Test"})
        ctx = _make_form_ctx(elicit_result=accepted)
        missing = _simple_missing()

        result = await elicit_and_rehydrate(
            ctx, {"Root": {}}, missing,
            find_missing_fn=lambda b: [],
            tool_label="test",
            canonicalize_fn=None,
        )
        self.assertEqual(result["Root"]["Name"], "Test")

    async def test_does_not_mutate_input_body(self) -> None:
        """The original body dict should not be mutated."""
        accepted = _make_accepted({"name": "Test"})
        ctx = _make_form_ctx(elicit_result=accepted)
        missing = _simple_missing()
        body = {"Root": {}}

        await elicit_and_rehydrate(
            ctx, body, missing,
            find_missing_fn=lambda b: [],
            tool_label="test",
        )
        self.assertEqual(body, {"Root": {}})

    async def test_tool_label_in_elicit_message(self) -> None:
        """The tool_label should appear in the elicitation message."""
        accepted = _make_accepted({"name": "Test"})
        ctx = _make_form_ctx(elicit_result=accepted)
        missing = _simple_missing()

        await elicit_and_rehydrate(
            ctx, {"Root": {}}, missing,
            find_missing_fn=lambda b: [],
            tool_label="rate request",
        )
        call_kwargs = ctx.elicit.call_args
        self.assertIn("rate request", call_kwargs.kwargs.get("message", call_kwargs.args[0] if call_kwargs.args else ""))

    async def test_missing_payload_structure(self) -> None:
        """Error payloads should contain structured missing field info."""
        ctx = _make_no_form_ctx()
        missing = [
            MissingField("A.B", "field_a", "Field A"),
            MissingField("C.D", "field_c", "Field C"),
        ]
        with self.assertRaises(ToolError) as cm:
            await elicit_and_rehydrate(
                ctx, {}, missing,
                find_missing_fn=lambda b: [],
                tool_label="test",
            )
        payload = json.loads(str(cm.exception))
        self.assertEqual(len(payload["missing"]), 2)
        self.assertEqual(payload["missing"][0]["dot_path"], "A.B")
        self.assertEqual(payload["missing"][0]["flat_key"], "field_a")
        self.assertEqual(payload["missing"][0]["prompt"], "Field A")


# ---------------------------------------------------------------------------
# build_elicitation_schema model_name parameter test
# ---------------------------------------------------------------------------

class BuildElicitationSchemaModelNameTests(unittest.TestCase):
    def test_default_model_name(self) -> None:
        schema = build_elicitation_schema([])
        self.assertEqual(schema.__name__, "MissingFields")

    def test_custom_model_name(self) -> None:
        schema = build_elicitation_schema([], model_name="MissingRateFields")
        self.assertEqual(schema.__name__, "MissingRateFields")


# ---------------------------------------------------------------------------
# Structural (non-elicitable) MissingField tests
# ---------------------------------------------------------------------------

class StructuralFieldTests(unittest.IsolatedAsyncioTestCase):
    """Structural MissingFields (elicitable=False) must trigger an immediate
    error instead of entering the flat-form elicitation flow."""

    async def test_structural_field_raises_before_elicitation(self) -> None:
        """Non-elicitable field raises STRUCTURAL_FIELDS_REQUIRED."""
        ctx = _make_form_ctx()
        missing = [MissingField(
            "Root.Container",
            "container_required",
            "Container is required. Build it in request_body.",
            elicitable=False,
        )]

        with self.assertRaises(ToolError) as cm:
            await elicit_and_rehydrate(
                ctx, {"Root": {}}, missing,
                find_missing_fn=lambda b: [],
                tool_label="test",
            )
        payload = json.loads(str(cm.exception))
        self.assertEqual(payload["code"], "STRUCTURAL_FIELDS_REQUIRED")
        self.assertEqual(payload["reason"], "structural")
        self.assertEqual(len(payload["missing"]), 1)
        self.assertIn("Container is required", payload["missing"][0]["prompt"])

    async def test_structural_field_not_sent_to_elicit(self) -> None:
        """ctx.elicit() should never be called when structural fields exist."""
        ctx = _make_form_ctx()
        missing = [MissingField(
            "Root.Big", "big_thing", "Build this complex thing.",
            elicitable=False,
        )]
        with self.assertRaises(ToolError):
            await elicit_and_rehydrate(
                ctx, {"Root": {}}, missing,
                find_missing_fn=lambda b: [],
                tool_label="test",
            )
        ctx.elicit.assert_not_called()

    async def test_mixed_structural_and_scalar_raises_structural(self) -> None:
        """When both structural and scalar fields are missing, structural wins."""
        ctx = _make_form_ctx()
        missing = [
            MissingField("Root.Name", "name", "Name"),
            MissingField("Root.Container", "container", "Build this.", elicitable=False),
        ]
        with self.assertRaises(ToolError) as cm:
            await elicit_and_rehydrate(
                ctx, {"Root": {}}, missing,
                find_missing_fn=lambda b: [],
                tool_label="test",
            )
        payload = json.loads(str(cm.exception))
        self.assertEqual(payload["code"], "STRUCTURAL_FIELDS_REQUIRED")
        # Only the structural field is reported
        self.assertEqual(len(payload["missing"]), 1)
        self.assertEqual(payload["missing"][0]["flat_key"], "container")

    async def test_elicitable_true_by_default(self) -> None:
        """MissingField defaults to elicitable=True."""
        mf = MissingField("A.B", "ab", "AB field")
        self.assertTrue(mf.elicitable)


# ---------------------------------------------------------------------------
# Currency code normalization & validation tests
# ---------------------------------------------------------------------------

class CurrencyCodeNormalizationTests(unittest.TestCase):
    def test_currency_code_uppercased(self) -> None:
        result = normalize_elicited_values({"intl_forms_currency_code": "usd"})
        self.assertEqual(result["intl_forms_currency_code"], "USD")

    def test_currency_code_already_upper(self) -> None:
        result = normalize_elicited_values({"intl_forms_currency_code": "EUR"})
        self.assertEqual(result["intl_forms_currency_code"], "EUR")

    def test_invoice_currency_code_uppercased(self) -> None:
        result = normalize_elicited_values({"invoice_currency_code": "gbp"})
        self.assertEqual(result["invoice_currency_code"], "GBP")


class CurrencyCodeValidationTests(unittest.TestCase):
    def test_valid_currency_code(self) -> None:
        missing = [MissingField("A.CurrencyCode", "intl_forms_currency_code", "Currency")]
        errors = validate_elicited_values({"intl_forms_currency_code": "USD"}, missing)
        self.assertEqual(errors, [])

    def test_invalid_currency_code_too_short(self) -> None:
        missing = [MissingField("A.CurrencyCode", "intl_forms_currency_code", "Currency")]
        errors = validate_elicited_values({"intl_forms_currency_code": "US"}, missing)
        self.assertEqual(len(errors), 1)
        self.assertIn("3-letter currency code", errors[0])

    def test_invalid_currency_code_numeric(self) -> None:
        missing = [MissingField("A.CurrencyCode", "intl_forms_currency_code", "Currency")]
        errors = validate_elicited_values({"intl_forms_currency_code": "123"}, missing)
        self.assertEqual(len(errors), 1)
        self.assertIn("3-letter currency code", errors[0])

    def test_invalid_currency_code_too_long(self) -> None:
        missing = [MissingField("A.CurrencyCode", "intl_forms_currency_code", "Currency")]
        errors = validate_elicited_values({"intl_forms_currency_code": "USDD"}, missing)
        self.assertEqual(len(errors), 1)


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
        declined = DeclinedElicitation()
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


from ups_mcp.elicitation import ArrayFieldRule, expand_array_fields, reconstruct_array


class ArrayElicitationIntegrationTests(unittest.IsolatedAsyncioTestCase):
    """Integration: array fields flow through the full elicitation pipeline."""

    def _make_rule(self) -> ArrayFieldRule:
        return ArrayFieldRule(
            array_dot_path="Root.Items.Product",
            item_prefix="product",
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


class ArrayFieldRuleTests(unittest.TestCase):
    """Tests for the ArrayFieldRule data structure and helper functions."""

    def _make_product_rule(self) -> ArrayFieldRule:
        return ArrayFieldRule(
            array_dot_path="Root.Items.Product",
            item_prefix="product",
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
            item_rules=(
                FieldRule("Unit.Value", "unit_value", "Value"),
                FieldRule("Unit.Code", "unit_code", "Code"),
            ),
        )
        flat_data = {"prod_1_unit_value": "100", "prod_1_unit_code": "PCS"}
        items = reconstruct_array(flat_data, rule, count=1)
        self.assertEqual(items[0]["Unit"]["Value"], "100")
        self.assertEqual(items[0]["Unit"]["Code"], "PCS")


if __name__ == "__main__":
    unittest.main()
