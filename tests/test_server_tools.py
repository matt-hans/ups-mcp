import unittest

import ups_mcp.server as server


class FakeToolManager:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def track_package(self, **kwargs):  # noqa: ANN003
        self.calls.append(("track_package", kwargs))
        return {"ok": True, "operation": "track_package", "status_code": 200, "trans_id": "x", "request": {}, "data": {"tracking": "ok"}, "error": None}

    def validate_address(self, **kwargs):  # noqa: ANN003
        self.calls.append(("validate_address", kwargs))
        return {"ok": True, "operation": "validate_address", "status_code": 200, "trans_id": "x", "request": {}, "data": {"validation": "ok"}, "error": None}

    def rate_shipment(self, **kwargs):  # noqa: ANN003
        self.calls.append(("rate_shipment", kwargs))
        return {"ok": True, "operation": "rate_shipment", "status_code": 200, "trans_id": "x", "request": {}, "data": {}, "error": None}

    def create_shipment(self, **kwargs):  # noqa: ANN003
        self.calls.append(("create_shipment", kwargs))
        return {"ok": True, "operation": "create_shipment", "status_code": 200, "trans_id": "x", "request": {}, "data": {}, "error": None}

    def void_shipment(self, **kwargs):  # noqa: ANN003
        self.calls.append(("void_shipment", kwargs))
        return {"ok": True, "operation": "void_shipment", "status_code": 200, "trans_id": "x", "request": {}, "data": {}, "error": None}

    def recover_label(self, **kwargs):  # noqa: ANN003
        self.calls.append(("recover_label", kwargs))
        return {"ok": True, "operation": "recover_label", "status_code": 200, "trans_id": "x", "request": {}, "data": {}, "error": None}

    def get_time_in_transit(self, **kwargs):  # noqa: ANN003
        self.calls.append(("get_time_in_transit", kwargs))
        return {"ok": True, "operation": "get_time_in_transit", "status_code": 200, "trans_id": "x", "request": {}, "data": {}, "error": None}


class ServerToolsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.original_tool_manager = server.tool_manager
        self.fake_tool_manager = FakeToolManager()
        server.tool_manager = self.fake_tool_manager

    def tearDown(self) -> None:
        server.tool_manager = self.original_tool_manager

    async def test_legacy_tools_return_structured_envelope(self) -> None:
        track_response = await server.track_package(inquiryNumber="1Z999")
        validation_response = await server.validate_address(
            addressLine1="123 Main St",
            politicalDivision1="GA",
            politicalDivision2="Atlanta",
            zipPrimary="30301",
            countryCode="US",
        )

        self.assertIsInstance(track_response, dict)
        self.assertIsInstance(validation_response, dict)
        self.assertTrue(track_response["ok"])
        self.assertTrue(validation_response["ok"])
        self.assertEqual(track_response["operation"], "track_package")
        self.assertEqual(validation_response["operation"], "validate_address")

    async def test_new_tools_return_structured_envelope(self) -> None:
        rate_response = await server.rate_shipment(
            requestoption="Rate",
            request_body={"RateRequest": {}},
        )
        time_response = await server.get_time_in_transit(
            request_body={"originCountryCode": "US", "destinationCountryCode": "US"},
        )

        self.assertIsInstance(rate_response, dict)
        self.assertTrue(rate_response["ok"])
        self.assertEqual(rate_response["operation"], "rate_shipment")
        self.assertIsInstance(time_response, dict)
        self.assertTrue(time_response["ok"])
        self.assertEqual(time_response["operation"], "get_time_in_transit")


if __name__ == "__main__":
    unittest.main()
