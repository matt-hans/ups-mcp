import unittest

from mcp.server.fastmcp.exceptions import ToolError

from ups_mcp.tools import ToolManager


class CapturingHTTPClient:
    def __init__(self, response: dict | None = None, raise_error: ToolError | None = None) -> None:
        self.calls: list[dict] = []
        self.response = response or {"trackResponse": {"shipment": []}}
        self.raise_error = raise_error

    def call_operation(self, operation, **kwargs):  # noqa: ANN001
        self.calls.append({"operation": operation, "kwargs": kwargs})
        if self.raise_error:
            raise self.raise_error
        return self.response


class LegacyToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = ToolManager(
            base_url="https://example.test",
            client_id="client-id",
            client_secret="client-secret",
        )

    def test_track_package_uses_shared_http_client(self) -> None:
        fake_client = CapturingHTTPClient()
        self.manager.http_client = fake_client

        response = self.manager.track_package(
            inquiryNum="1Z999AA10123456784",
            locale="en_US",
            returnSignature=False,
            returnMilestones=True,
            returnPOD=False,
        )

        self.assertIn("trackResponse", response)
        self.assertEqual(len(fake_client.calls), 1)
        call = fake_client.calls[0]
        self.assertEqual(call["kwargs"]["operation_name"], "track_package")
        self.assertEqual(call["kwargs"]["path_params"]["inquiryNum"], "1Z999AA10123456784")
        self.assertTrue(call["kwargs"]["query_params"]["returnMilestones"])

    def test_validate_address_uses_shared_http_client(self) -> None:
        fake_client = CapturingHTTPClient(response={"XAVResponse": {"ValidAddressIndicator": ""}})
        self.manager.http_client = fake_client

        response = self.manager.validate_address(
            addressLine1="123 Main St",
            addressLine2="Apt 1",
            politicalDivision1="GA",
            politicalDivision2="Atlanta",
            zipPrimary="30301",
            zipExtended="1234",
            urbanization="",
            countryCode="US",
        )

        self.assertIn("XAVResponse", response)
        self.assertEqual(len(fake_client.calls), 1)
        call = fake_client.calls[0]
        payload = call["kwargs"]["json_body"]
        self.assertEqual(call["kwargs"]["operation_name"], "validate_address")
        self.assertEqual(payload["XAVRequest"]["AddressKeyFormat"]["AddressLine"], ["123 Main St", "Apt 1"])
        self.assertEqual(payload["XAVRequest"]["AddressKeyFormat"]["PostcodeExtendedLow"], "1234")

    def test_legacy_tools_propagate_tool_error(self) -> None:
        fake_client = CapturingHTTPClient(
            raise_error=ToolError('{"status_code": 429, "code": "429", "message": "Rate limit exceeded"}'),
        )
        self.manager.http_client = fake_client

        with self.assertRaises(ToolError) as ctx:
            self.manager.track_package(
                inquiryNum="1Z999AA10123456784",
                locale="en_US",
                returnSignature=False,
                returnMilestones=False,
                returnPOD=False,
            )
        self.assertIn("Rate limit exceeded", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
