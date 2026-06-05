import json
import unittest

from mcp.server.fastmcp.exceptions import ToolError

from ups_mcp.shipagent_normalization import (
    ShipAgentNormalizationError,
    build_shipagent_capabilities,
    to_normalization_error,
    to_safe_error,
)


class ShipAgentCapabilitiesAndErrorTests(unittest.TestCase):
    def test_build_shipagent_capabilities_returns_hosted_v1_contract(self) -> None:
        capabilities = build_shipagent_capabilities("1.1.0")

        self.assertEqual(
            set(capabilities),
            {
                "contract_version",
                "server_version",
                "capabilities",
                "response_formats",
            },
        )
        self.assertEqual(capabilities["contract_version"], "hosted-v1")
        self.assertEqual(capabilities["server_version"], "1.1.0")
        self.assertEqual(
            capabilities["capabilities"],
            [
                "rate_quote",
                "rate_shop",
                "address_validation",
                "create_shipment",
                "idempotency_metadata_passthrough",
                "shipment_response_normalization",
                "safe_error_mapping",
                "mutating_retry_policy",
            ],
        )
        self.assertEqual(capabilities["response_formats"], ["raw", "shipagent_v1"])
        self.assertNotIn("schema_hash", capabilities)
        self.assertNotIn("schema_version", capabilities)
        self.assertNotIn("retry_policy", capabilities)

    def test_to_normalization_error_returns_closed_safe_error(self) -> None:
        error = to_normalization_error("corr_123")

        self.assertEqual(
            error,
            {
                "success": False,
                "error": {
                    "category": "normalization",
                    "code": "UPS_NORMALIZATION_ERROR",
                    "message": "UPS response could not be normalized.",
                    "correlation_id": "corr_123",
                    "retryable": False,
                },
            },
        )
        self.assertTrue(issubclass(ShipAgentNormalizationError, ValueError))

    def test_to_safe_error_maps_public_categories(self) -> None:
        cases = [
            (
                ToolError(json.dumps({"status_code": 401, "code": "250003", "message": "invalid token"})),
                {
                    "category": "auth",
                    "code": "UPS_AUTH_ERROR",
                    "message": "UPS authentication failed.",
                    "retryable": False,
                },
            ),
            (
                ToolError(json.dumps({"code": "429", "message": "too many requests"})),
                {
                    "category": "rate_limit",
                    "code": "UPS_RATE_LIMIT_ERROR",
                    "message": "UPS rate limit exceeded.",
                    "retryable": True,
                },
            ),
            (
                ToolError(json.dumps({"status_code": 400, "code": "120100", "message": "bad address"})),
                {
                    "category": "validation",
                    "code": "UPS_VALIDATION_ERROR",
                    "message": "UPS request validation failed.",
                    "retryable": False,
                },
            ),
            (
                ToolError(json.dumps({"status_code": 503, "code": "503", "message": "maintenance"})),
                {
                    "category": "service_unavailable",
                    "code": "UPS_SERVICE_UNAVAILABLE",
                    "message": "UPS service is temporarily unavailable.",
                    "retryable": True,
                },
            ),
            (
                ToolError(json.dumps({"code": "REQUEST_ERROR", "message": "connection reset"})),
                {
                    "category": "transport",
                    "code": "UPS_TRANSPORT_ERROR",
                    "message": "UPS transport request failed.",
                    "retryable": True,
                },
            ),
            (
                RuntimeError("stack trace with local path /tmp/ups.py"),
                {
                    "category": "unknown",
                    "code": "UPS_UNKNOWN_ERROR",
                    "message": "UPS request failed unexpectedly.",
                    "retryable": False,
                },
            ),
        ]

        for exc, expected in cases:
            with self.subTest(expected["category"]):
                error = to_safe_error(exc, "corr_map")

                self.assertEqual(set(error), {"success", "error"})
                self.assertIs(error["success"], False)
                self.assertEqual(
                    error["error"],
                    {
                        **expected,
                        "correlation_id": "corr_map",
                    },
                )

    def test_to_safe_error_does_not_leak_raw_ups_details(self) -> None:
        exc = ToolError(
            json.dumps(
                {
                    "status_code": 400,
                    "code": "250003",
                    "message": "Invalid account 1Z999AA10123456784 using secret-token",
                    "details": {
                        "request_body": {"shipper": {"account_number": "ABC123456"}},
                        "debug": "Traceback in /Users/matthewhans/Desktop/ups.py",
                    },
                },
            ),
        )

        error = to_safe_error(exc, "corr_safe")

        self.assertEqual(
            error,
            {
                "success": False,
                "error": {
                    "category": "validation",
                    "code": "UPS_VALIDATION_ERROR",
                    "message": "UPS request validation failed.",
                    "correlation_id": "corr_safe",
                    "retryable": False,
                },
            },
        )
        serialized = json.dumps(error)
        for leaked_fragment in (
            "250003",
            "1Z999AA10123456784",
            "secret-token",
            "ABC123456",
            "request_body",
            "/Users/matthewhans/Desktop/ups.py",
            "Traceback",
        ):
            self.assertNotIn(leaked_fragment, serialized)

    def test_to_safe_error_does_not_expose_domain_specific_categories_or_codes(self) -> None:
        cases = [
            {
                "status_code": 400,
                "code": "ADDRESS_VALIDATION_FAILED",
                "message": "address line is invalid",
            },
            {
                "status_code": 422,
                "code": "CUSTOMS_INVOICE_MISSING",
                "message": "customs form is missing",
            },
        ]

        for payload in cases:
            with self.subTest(payload["code"]):
                error = to_safe_error(ToolError(json.dumps(payload)), "corr_domain")

                self.assertEqual(set(error), {"success", "error"})
                self.assertIs(error["success"], False)
                self.assertEqual(error["error"]["category"], "validation")
                self.assertEqual(error["error"]["code"], "UPS_VALIDATION_ERROR")
                serialized = json.dumps(error).lower()
                self.assertNotIn("address", serialized)
                self.assertNotIn("customs", serialized)


if __name__ == "__main__":
    unittest.main()
