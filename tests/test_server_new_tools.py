import unittest

import ups_mcp.server as server


class FakeToolManager:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def get_landed_cost_quote(self, **kwargs):  # noqa: ANN003
        self.calls.append(("get_landed_cost_quote", kwargs))
        return {"LandedCostResponse": {"shipment": {}}}

    def upload_paperless_document(self, **kwargs):  # noqa: ANN003
        self.calls.append(("upload_paperless_document", kwargs))
        return {"UploadResponse": {"FormsHistoryDocumentID": {}}}

    def push_document_to_shipment(self, **kwargs):  # noqa: ANN003
        self.calls.append(("push_document_to_shipment", kwargs))
        return {"PushToImageRepositoryResponse": {}}

    def delete_paperless_document(self, **kwargs):  # noqa: ANN003
        self.calls.append(("delete_paperless_document", kwargs))
        return {"DeleteResponse": {}}

    def find_locations(self, **kwargs):  # noqa: ANN003
        self.calls.append(("find_locations", kwargs))
        return {"LocatorResponse": {"SearchResults": {}}}

    def rate_pickup(self, **kwargs):  # noqa: ANN003
        self.calls.append(("rate_pickup", kwargs))
        return {"PickupRateResponse": {}}

    def schedule_pickup(self, **kwargs):  # noqa: ANN003
        self.calls.append(("schedule_pickup", kwargs))
        return {"PickupCreationResponse": {"PRN": "123"}}

    def cancel_pickup(self, **kwargs):  # noqa: ANN003
        self.calls.append(("cancel_pickup", kwargs))
        return {"PickupCancelResponse": {}}

    def get_pickup_status(self, **kwargs):  # noqa: ANN003
        self.calls.append(("get_pickup_status", kwargs))
        return {"PickupPendingStatusResponse": {}}

    def get_political_divisions(self, **kwargs):  # noqa: ANN003
        self.calls.append(("get_political_divisions", kwargs))
        return {"PoliticalDivision1List": []}

    def get_service_center_facilities(self, **kwargs):  # noqa: ANN003
        self.calls.append(("get_service_center_facilities", kwargs))
        return {"PickupGetServiceCenterFacilitiesResponse": {}}


class NewServerToolsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.original_tool_manager = server.tool_manager
        self.fake = FakeToolManager()
        server.tool_manager = self.fake

    def tearDown(self) -> None:
        server.tool_manager = self.original_tool_manager

    async def test_get_landed_cost_quote(self) -> None:
        resp = await server.get_landed_cost_quote(
            currency_code="USD", export_country_code="US", import_country_code="GB",
            commodities=[{"price": 10, "quantity": 1}],
        )
        self.assertIn("LandedCostResponse", resp)
        self.assertEqual(self.fake.calls[0][0], "get_landed_cost_quote")

    async def test_upload_paperless_document(self) -> None:
        resp = await server.upload_paperless_document(
            file_content_base64="dGVzdA==", file_name="inv.pdf",
            file_format="pdf", document_type="002",
        )
        self.assertIn("UploadResponse", resp)
        self.assertEqual(self.fake.calls[0][0], "upload_paperless_document")

    async def test_push_document_to_shipment(self) -> None:
        resp = await server.push_document_to_shipment(
            document_id="DOC123", shipment_identifier="1Z999AA10123456784",
        )
        self.assertIn("PushToImageRepositoryResponse", resp)
        self.assertEqual(self.fake.calls[0][0], "push_document_to_shipment")

    async def test_delete_paperless_document(self) -> None:
        resp = await server.delete_paperless_document(document_id="DOC456")
        self.assertIn("DeleteResponse", resp)
        self.assertEqual(self.fake.calls[0][0], "delete_paperless_document")

    async def test_find_locations(self) -> None:
        resp = await server.find_locations(
            location_type="access_point", address_line="123 Main St", city="Atlanta",
            state="GA", postal_code="30301", country_code="US",
        )
        self.assertIn("LocatorResponse", resp)
        self.assertEqual(self.fake.calls[0][0], "find_locations")

    async def test_rate_pickup(self) -> None:
        resp = await server.rate_pickup(
            pickup_type="oncall", address_line="123 Main", city="Atlanta",
            state="GA", postal_code="30301", country_code="US",
            pickup_date="20260301", ready_time="0900", close_time="1700",
        )
        self.assertIn("PickupRateResponse", resp)
        self.assertEqual(self.fake.calls[0][0], "rate_pickup")

    async def test_schedule_pickup(self) -> None:
        resp = await server.schedule_pickup(
            pickup_date="20260301", ready_time="0900", close_time="1700",
            address_line="123 Main", city="Atlanta", state="GA",
            postal_code="30301", country_code="US",
            contact_name="John", phone_number="5551234567",
        )
        self.assertIn("PickupCreationResponse", resp)
        self.assertEqual(self.fake.calls[0][0], "schedule_pickup")

    async def test_cancel_pickup(self) -> None:
        resp = await server.cancel_pickup(cancel_by="account")
        self.assertIn("PickupCancelResponse", resp)
        self.assertEqual(self.fake.calls[0][0], "cancel_pickup")

    async def test_get_pickup_status(self) -> None:
        resp = await server.get_pickup_status(pickup_type="oncall")
        self.assertIn("PickupPendingStatusResponse", resp)
        self.assertEqual(self.fake.calls[0][0], "get_pickup_status")

    async def test_get_political_divisions(self) -> None:
        resp = await server.get_political_divisions(country_code="US")
        self.assertIn("PoliticalDivision1List", resp)
        self.assertEqual(self.fake.calls[0][0], "get_political_divisions")

    async def test_get_service_center_facilities(self) -> None:
        resp = await server.get_service_center_facilities(
            city="Atlanta", state="GA", postal_code="30301", country_code="US",
        )
        self.assertIn("PickupGetServiceCenterFacilitiesResponse", resp)
        self.assertEqual(self.fake.calls[0][0], "get_service_center_facilities")

    async def test_empty_string_optional_params_converted_to_none(self) -> None:
        """Verify that empty strings for optional params are converted to None."""
        await server.get_landed_cost_quote(
            currency_code="USD", export_country_code="US", import_country_code="GB",
            commodities=[{"price": 10, "quantity": 1}],
            account_number="", trans_id="", transaction_src="ups-mcp",
        )
        kwargs = self.fake.calls[0][1]
        self.assertIsNone(kwargs["account_number"])
        self.assertIsNone(kwargs["trans_id"])


if __name__ == "__main__":
    unittest.main()
