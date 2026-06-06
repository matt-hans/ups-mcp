import json
import unittest
from importlib import metadata
from unittest.mock import AsyncMock, MagicMock, patch

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


class _FakeToolManager:
    def __init__(
        self,
        *,
        rate_response: dict | None = None,
        rate_exception: BaseException | None = None,
    ) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.rate_response = rate_response or _rate_quote_response()
        self.rate_exception = rate_exception

    def rate_shipment(self, **kwargs):  # noqa: ANN003
        self.calls.append(("rate_shipment", kwargs))
        if self.rate_exception is not None:
            raise self.rate_exception
        return self.rate_response

    def validate_address(self, **kwargs):  # noqa: ANN003
        self.calls.append(("validate_address", kwargs))
        return {"XAVResponse": {"ValidAddressIndicator": ""}}

    def create_shipment(self, **kwargs):  # noqa: ANN003
        self.calls.append(("create_shipment", kwargs))
        return {"ShipmentResponse": {"ShipmentResults": {}}}


def _rate_quote_response(
    *,
    service_code: str = "03",
    service_description: str = "UPS Ground",
    monetary_value: str = "12.34",
    currency_code: str = "USD",
) -> dict:
    return {
        "RateResponse": {
            "RatedShipment": [
                {
                    "Service": {
                        "Code": service_code,
                        "Description": service_description,
                    },
                    "TotalCharges": {
                        "MonetaryValue": monetary_value,
                        "CurrencyCode": currency_code,
                    },
                }
            ]
        }
    }


def _rate_shop_response() -> dict:
    return {
        "RateResponse": {
            "RatedShipment": [
                {
                    "Service": {"Code": "03", "Description": "UPS Ground"},
                    "TotalCharges": {"MonetaryValue": "12.34", "CurrencyCode": "USD"},
                },
                {
                    "Service": {"Code": "02"},
                    "TotalCharges": {"MonetaryValue": "20.00", "CurrencyCode": "USD"},
                },
            ]
        }
    }


class ShipAgentHostedServerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.original_tool_manager = server.tool_manager
        self.fake_tool_manager = _FakeToolManager()
        server.tool_manager = self.fake_tool_manager

    def tearDown(self) -> None:
        server.tool_manager = self.original_tool_manager

    def _install_fake_tool_manager(self, fake: _FakeToolManager) -> _FakeToolManager:
        self.fake_tool_manager = fake
        server.tool_manager = fake
        return fake

    def _assert_corr_id(self, value: str) -> None:
        self.assertRegex(value, r"^corr_[0-9a-f]{32}$")

    def _assert_safe_validation(
        self,
        result: dict,
        *,
        correlation_id: str | None = None,
    ) -> None:
        self.assertEqual(set(result), {"success", "error"})
        self.assertIs(result["success"], False)
        error = result["error"]
        self.assertEqual(
            set(error),
            {"category", "code", "message", "correlation_id", "retryable"},
        )
        self.assertEqual(error["category"], "validation")
        self.assertEqual(error["code"], "UPS_VALIDATION_ERROR")
        self.assertEqual(error["message"], "UPS request validation failed.")
        self.assertIs(error["retryable"], False)
        if correlation_id is not None:
            self.assertEqual(error["correlation_id"], correlation_id)

    async def test_shipagent_capabilities_returns_metadata_without_tool_manager(self) -> None:
        server.tool_manager = None

        result = await server.shipagent_capabilities()

        self.assertEqual(result["contract_version"], "hosted-v1")
        self.assertEqual(result["server_version"], metadata.version("ups-mcp"))
        self.assertEqual(result["response_formats"], ["raw", "shipagent_v1"])
        self.assertIn("rate_quote", result["capabilities"])

    async def test_shipagent_capabilities_version_falls_back_to_unknown(self) -> None:
        with patch.object(server.metadata, "version", side_effect=RuntimeError("boom")):
            result = await server.shipagent_capabilities()

        self.assertEqual(result["server_version"], "unknown")

    async def test_shipagent_capabilities_is_registered_as_mcp_tool(self) -> None:
        tools = await server.mcp.list_tools()

        self.assertIn("shipagent_capabilities", {tool.name for tool in tools})

    async def test_rate_shipment_raw_default_preserves_raw_response_and_omitted_trans_id(self) -> None:
        raw_response = {"RateResponse": {"RatedShipment": []}}
        fake = self._install_fake_tool_manager(
            _FakeToolManager(rate_response=raw_response)
        )

        result = await server.rate_shipment(
            requestoption="Rate",
            request_body=make_complete_rate_body(),
        )

        self.assertIs(result, raw_response)
        self.assertEqual(fake.calls[0][1]["trans_id"], None)

    async def test_invalid_response_format_raises_direct_tool_error_before_ups(self) -> None:
        for response_format in ("xml", "ShipAgent_V1", "RAW", "shipagent-v1"):
            with self.subTest(response_format=response_format):
                fake = self._install_fake_tool_manager(_FakeToolManager())

                with self.assertRaises(ToolError) as cm:
                    await server.rate_shipment(
                        requestoption="Rate",
                        request_body=make_complete_rate_body(),
                        response_format=response_format,
                    )

                self.assertEqual(
                    json.loads(str(cm.exception)),
                    {
                        "code": "INVALID_RESPONSE_FORMAT",
                        "allowed": ["raw", "shipagent_v1"],
                    },
                )
                self.assertEqual(fake.calls, [])

    async def test_hosted_rate_rejects_trans_id_control_chars_before_ups(self) -> None:
        result = await server.rate_shipment(
            requestoption="Rate",
            request_body=make_complete_rate_body(),
            trans_id="bad\nid",
            response_format="shipagent_v1",
        )

        self._assert_safe_validation(
            result,
        )
        self._assert_corr_id(result["error"]["correlation_id"])
        self.assertEqual(self.fake_tool_manager.calls, [])

    async def test_hosted_quote_normalizes_and_passes_stripped_correlation_id_to_ups(self) -> None:
        fake = self._install_fake_tool_manager(
            _FakeToolManager(rate_response=_rate_quote_response())
        )

        result = await server.rate_shipment(
            requestoption="Rate",
            request_body=make_complete_rate_body(),
            trans_id=" corr_quote_123 ",
            response_format="shipagent_v1",
        )

        self.assertEqual(
            result,
            {
                "success": True,
                "correlationId": "corr_quote_123",
                "serviceCode": "03",
                "serviceDescription": "UPS Ground",
                "totalCharges": {"monetaryValue": "12.34", "currencyCode": "USD"},
            },
        )
        self.assertEqual(fake.calls[0][1]["trans_id"], "corr_quote_123")

    async def test_hosted_preserves_explicit_printable_transaction_src(self) -> None:
        fake = self._install_fake_tool_manager(_FakeToolManager())

        await server.rate_shipment(
            requestoption="Rate",
            request_body=make_complete_rate_body(),
            trans_id="corr_src_preserved",
            transaction_src="caller src=abc",
            response_format="shipagent_v1",
        )

        self.assertEqual(fake.calls[0][1]["transaction_src"], "caller src=abc")

    async def test_hosted_rejects_transaction_src_control_chars_before_ups(self) -> None:
        result = await server.rate_shipment(
            requestoption="Rate",
            request_body=make_complete_rate_body(),
            trans_id="corr_existing",
            transaction_src="bad\rsrc",
            response_format="shipagent_v1",
        )

        self._assert_safe_validation(
            result,
            correlation_id="corr_existing",
        )
        self.assertEqual(self.fake_tool_manager.calls, [])

    async def test_hosted_shop_normalizes_shop_result(self) -> None:
        self._install_fake_tool_manager(
            _FakeToolManager(rate_response=_rate_shop_response())
        )

        result = await server.rate_shipment(
            requestoption="Shop",
            request_body=make_complete_rate_body(),
            trans_id="corr_shop",
            response_format="shipagent_v1",
        )

        self.assertEqual(
            result,
            {
                "success": True,
                "correlationId": "corr_shop",
                "ratedShipments": [
                    {
                        "serviceCode": "03",
                        "serviceDescription": "UPS Ground",
                        "totalCharges": {"monetaryValue": "12.34", "currencyCode": "USD"},
                    },
                    {
                        "serviceCode": "02",
                        "totalCharges": {"monetaryValue": "20.00", "currencyCode": "USD"},
                    },
                ],
            },
        )

    async def test_hosted_tool_error_returns_safe_envelope_without_raw_details(self) -> None:
        exc = ToolError(
            json.dumps(
                {
                    "status_code": 400,
                    "code": "250003",
                    "message": "Invalid account secret-token",
                    "details": {"path": "/Users/matthewhans/Desktop/ups.py"},
                }
            )
        )
        self._install_fake_tool_manager(_FakeToolManager(rate_exception=exc))

        result = await server.rate_shipment(
            requestoption="Rate",
            request_body=make_complete_rate_body(),
            trans_id="corr_tool_error",
            response_format="shipagent_v1",
        )

        self._assert_safe_validation(result, correlation_id="corr_tool_error")
        serialized = json.dumps(result)
        self.assertNotIn("250003", serialized)
        self.assertNotIn("secret-token", serialized)
        self.assertNotIn("/Users/matthewhans/Desktop/ups.py", serialized)

    async def test_hosted_unexpected_exception_returns_unknown_safe_envelope(self) -> None:
        self._install_fake_tool_manager(
            _FakeToolManager(
                rate_exception=RuntimeError("connection timeout")
            )
        )

        result = await server.rate_shipment(
            requestoption="Rate",
            request_body=make_complete_rate_body(),
            trans_id="corr_unknown",
            response_format="shipagent_v1",
        )

        self.assertEqual(
            result,
            {
                "success": False,
                "error": {
                    "category": "unknown",
                    "code": "UPS_UNKNOWN_ERROR",
                    "message": "UPS request failed unexpectedly.",
                    "correlation_id": "corr_unknown",
                    "retryable": False,
                },
            },
        )
        self.assertNotIn("/Users/", json.dumps(result))
        self.assertNotIn("Traceback", json.dumps(result))
        self.assertNotIn("connection timeout", json.dumps(result))

    async def test_raw_mode_still_raises_tool_error(self) -> None:
        exc = ToolError(json.dumps({"status_code": 429, "message": "rate limit"}))
        self._install_fake_tool_manager(_FakeToolManager(rate_exception=exc))

        with self.assertRaises(ToolError) as cm:
            await server.rate_shipment(
                requestoption="Rate",
                request_body=make_complete_rate_body(),
            )

        self.assertIs(cm.exception, exc)

    async def test_hosted_normalization_failure_returns_normalization_safe_envelope(self) -> None:
        self._install_fake_tool_manager(
            _FakeToolManager(rate_response={"RateResponse": {"RatedShipment": []}})
        )

        result = await server.rate_shipment(
            requestoption="Rate",
            request_body=make_complete_rate_body(),
            trans_id="corr_bad_ups_payload",
            response_format="shipagent_v1",
        )

        self.assertEqual(
            result,
            {
                "success": False,
                "error": {
                    "category": "normalization",
                    "code": "UPS_NORMALIZATION_ERROR",
                    "message": "UPS response could not be normalized.",
                    "correlation_id": "corr_bad_ups_payload",
                    "retryable": False,
                },
            },
        )

    async def test_hosted_generates_correlation_id_when_trans_id_missing_and_passes_same_id(self) -> None:
        fake = self._install_fake_tool_manager(_FakeToolManager())

        result = await server.rate_shipment(
            requestoption="Rate",
            request_body=make_complete_rate_body(),
            response_format="shipagent_v1",
        )

        correlation_id = result["correlationId"]
        self._assert_corr_id(correlation_id)
        self.assertEqual(fake.calls[0][1]["trans_id"], correlation_id)

    async def test_hosted_does_not_elicit_missing_fields_or_call_ups(self) -> None:
        ctx = MagicMock()
        ctx.request_context.session.client_params = InitializeRequestParams(
            protocolVersion="2025-03-26",
            capabilities=ClientCapabilities(
                elicitation=ElicitationCapability(form=FormElicitationCapability())
            ),
            clientInfo=Implementation(name="test", version="1.0"),
        )
        ctx.elicit = AsyncMock()

        result = await server.rate_shipment(
            requestoption="Rate",
            request_body={"RateRequest": {}},
            trans_id="corr_missing",
            response_format="shipagent_v1",
            ctx=ctx,
        )

        self._assert_safe_validation(result, correlation_id="corr_missing")
        ctx.elicit.assert_not_awaited()
        self.assertEqual(self.fake_tool_manager.calls, [])


if __name__ == "__main__":
    unittest.main()
