import unittest

from ups_mcp.tools import ToolManager


class CapturingHTTPClient:
    def __init__(self, response: dict | None = None) -> None:
        self.calls: list[dict] = []
        self.response = response or {
            "ok": True,
            "operation": "x",
            "status_code": 200,
            "trans_id": "t",
            "request": {},
            "data": {},
            "error": None,
        }

    def call_operation(self, operation, **kwargs):  # noqa: ANN001
        self.calls.append({"operation": operation, "kwargs": kwargs})
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

        self.assertTrue(response["ok"])
        self.assertEqual(len(fake_client.calls), 1)
        call = fake_client.calls[0]
        self.assertEqual(call["kwargs"]["operation_name"], "track_package")
        self.assertEqual(call["kwargs"]["path_params"]["inquiryNum"], "1Z999AA10123456784")
        self.assertTrue(call["kwargs"]["query_params"]["returnMilestones"])

    def test_validate_address_uses_shared_http_client(self) -> None:
        fake_client = CapturingHTTPClient()
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

        self.assertTrue(response["ok"])
        self.assertEqual(len(fake_client.calls), 1)
        call = fake_client.calls[0]
        payload = call["kwargs"]["json_body"]
        self.assertEqual(call["kwargs"]["operation_name"], "validate_address")
        self.assertEqual(payload["XAVRequest"]["AddressKeyFormat"]["AddressLine"], ["123 Main St", "Apt 1"])
        self.assertEqual(payload["XAVRequest"]["AddressKeyFormat"]["PostcodeExtendedLow"], "1234")

    def test_legacy_tools_propagate_error_envelope(self) -> None:
        fake_error = {
            "ok": False,
            "operation": "track_package",
            "status_code": 429,
            "trans_id": "t",
            "request": {},
            "data": None,
            "error": {"code": "429", "message": "Rate limit exceeded", "details": {"x": 1}},
        }
        fake_client = CapturingHTTPClient(response=fake_error)
        self.manager.http_client = fake_client

        response = self.manager.track_package(
            inquiryNum="1Z999AA10123456784",
            locale="en_US",
            returnSignature=False,
            returnMilestones=False,
            returnPOD=False,
        )
        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], "429")


if __name__ == "__main__":
    unittest.main()
