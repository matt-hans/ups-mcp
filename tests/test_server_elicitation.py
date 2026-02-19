"""Integration tests for create_shipment elicitation flow in server.py."""

import json
import unittest
from unittest.mock import AsyncMock, MagicMock

from mcp.server.elicitation import AcceptedElicitation, DeclinedElicitation, CancelledElicitation
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import (
    ClientCapabilities,
    ElicitationCapability,
    FormElicitationCapability,
    InitializeRequestParams,
    Implementation,
)
from pydantic import create_model

import ups_mcp.server as server
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

        Model = create_model("ElicitedData", shipper_name=(str, ...))
        accepted = AcceptedElicitation(data=Model(shipper_name="Elicited Corp"))

        ctx = self._make_ctx(form_supported=True, elicit_result=accepted)
        result = await server.create_shipment(request_body=body, ctx=ctx)
        self.assertIn("ShipmentResponse", result)
        ctx.elicit.assert_called_once()

    async def test_declined_raises_elicitation_declined(self) -> None:
        body = make_complete_body()
        del body["ShipmentRequest"]["Shipment"]["Shipper"]["Name"]
        declined = DeclinedElicitation()
        ctx = self._make_ctx(form_supported=True, elicit_result=declined)
        with self.assertRaises(ToolError) as cm:
            await server.create_shipment(request_body=body, ctx=ctx)
        payload = json.loads(str(cm.exception))
        self.assertEqual(payload["code"], "ELICITATION_DECLINED")

    async def test_cancelled_raises_elicitation_cancelled(self) -> None:
        body = make_complete_body()
        del body["ShipmentRequest"]["Shipment"]["Shipper"]["Name"]
        cancelled = CancelledElicitation()
        ctx = self._make_ctx(form_supported=True, elicit_result=cancelled)
        with self.assertRaises(ToolError) as cm:
            await server.create_shipment(request_body=body, ctx=ctx)
        payload = json.loads(str(cm.exception))
        self.assertEqual(payload["code"], "ELICITATION_CANCELLED")

    async def test_still_missing_after_accept_raises_incomplete(self) -> None:
        body = make_complete_body()
        del body["ShipmentRequest"]["Shipment"]["Shipper"]["Name"]
        del body["ShipmentRequest"]["Shipment"]["ShipTo"]["Name"]

        Model = create_model("ElicitedData", shipper_name=(str, ...))
        accepted = AcceptedElicitation(data=Model(shipper_name="Filled"))

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

    async def test_malformed_shipment_node_raises_structured_tool_error(self) -> None:
        """Malformed Shipment node should not leak AttributeError."""
        body = {
            "ShipmentRequest": {
                "Shipment": "not_a_dict",
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

        Model = create_model(
            "ElicitedData",
            shipper_name=(str, ...),
            shipper_address_line_1=(str, ...),
        )
        accepted = AcceptedElicitation(data=Model(
            shipper_name="Test",
            shipper_address_line_1="123 Main",
        ))

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

    async def test_validation_errors_raise_structured_tool_error(self) -> None:
        """Invalid elicited values (e.g. non-numeric weight) raise ELICITATION_INVALID_RESPONSE."""
        body = make_complete_body()
        del body["ShipmentRequest"]["Shipment"]["Package"][0]["PackageWeight"]["Weight"]

        Model = create_model("ElicitedData", package_1_weight=(str, ...))
        accepted = AcceptedElicitation(data=Model(package_1_weight="not_a_number"))

        ctx = self._make_ctx(form_supported=True, elicit_result=accepted)
        with self.assertRaises(ToolError) as cm:
            await server.create_shipment(request_body=body, ctx=ctx)
        payload = json.loads(str(cm.exception))
        self.assertEqual(payload["code"], "ELICITATION_INVALID_RESPONSE")
        self.assertEqual(payload["reason"], "validation_errors")

    async def test_elicitation_transport_failure_raises_structured_error(self) -> None:
        """If ctx.elicit() raises an unexpected exception, wrap as ELICITATION_FAILED."""
        body = make_complete_body()
        del body["ShipmentRequest"]["Shipment"]["Shipper"]["Name"]

        ctx = self._make_ctx(form_supported=True)
        ctx.elicit = AsyncMock(side_effect=RuntimeError("connection lost"))

        with self.assertRaises(ToolError) as cm:
            await server.create_shipment(request_body=body, ctx=ctx)
        payload = json.loads(str(cm.exception))
        self.assertEqual(payload["code"], "ELICITATION_FAILED")
        self.assertEqual(payload["reason"], "transport_error")
        self.assertIn("connection lost", payload["message"])


if __name__ == "__main__":
    unittest.main()
