import unittest

import ups_mcp.server as server


class FakeToolManager:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def track_package(self, **kwargs):  # noqa: ANN003
        self.calls.append(("track_package", kwargs))
        return {"trackResponse": {"shipment": [{"package": [{"status": "delivered"}]}]}}

    def validate_address(self, **kwargs):  # noqa: ANN003
        self.calls.append(("validate_address", kwargs))
        return {"XAVResponse": {"ValidAddressIndicator": ""}}

    def rate_shipment(self, **kwargs):  # noqa: ANN003
        self.calls.append(("rate_shipment", kwargs))
        return {"RateResponse": {"RatedShipment": []}}

    def create_shipment(self, **kwargs):  # noqa: ANN003
        self.calls.append(("create_shipment", kwargs))
        return {"ShipmentResponse": {"ShipmentResults": {}}}

    def void_shipment(self, **kwargs):  # noqa: ANN003
        self.calls.append(("void_shipment", kwargs))
        return {"VoidShipmentResponse": {"SummaryResult": {}}}

    def recover_label(self, **kwargs):  # noqa: ANN003
        self.calls.append(("recover_label", kwargs))
        return {"LabelRecoveryResponse": {"LabelResults": {}}}

    def get_time_in_transit(self, **kwargs):  # noqa: ANN003
        self.calls.append(("get_time_in_transit", kwargs))
        return {"emsResponse": {"services": []}}


class ServerToolsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.original_tool_manager = server.tool_manager
        self.fake_tool_manager = FakeToolManager()
        server.tool_manager = self.fake_tool_manager

    def tearDown(self) -> None:
        server.tool_manager = self.original_tool_manager

    async def test_legacy_tools_return_raw_ups_response(self) -> None:
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
        self.assertIn("trackResponse", track_response)
        self.assertIn("XAVResponse", validation_response)

    async def test_new_tools_return_raw_ups_response(self) -> None:
        from tests.rating_fixtures import make_complete_rate_body
        rate_response = await server.rate_shipment(
            requestoption="Rate",
            request_body=make_complete_rate_body(),
        )
        time_response = await server.get_time_in_transit(
            request_body={"originCountryCode": "US", "destinationCountryCode": "US"},
        )

        self.assertIsInstance(rate_response, dict)
        self.assertIn("RateResponse", rate_response)
        self.assertIsInstance(time_response, dict)
        self.assertIn("emsResponse", time_response)

    async def test_no_envelope_keys_in_responses(self) -> None:
        track_response = await server.track_package(inquiryNumber="1Z999")

        self.assertNotIn("ok", track_response)
        self.assertNotIn("operation", track_response)
        self.assertNotIn("status_code", track_response)
        self.assertNotIn("data", track_response)
        self.assertNotIn("error", track_response)


if __name__ == "__main__":
    unittest.main()
