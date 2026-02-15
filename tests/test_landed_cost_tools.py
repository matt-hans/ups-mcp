import unittest

from mcp.server.fastmcp.exceptions import ToolError

from ups_mcp.tools import ToolManager


class FakeHTTPClient:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def call_operation(self, operation, **kwargs):  # noqa: ANN001
        self.calls.append({"operation": operation, "kwargs": kwargs})
        return {"LandedCostResponse": {"shipment": {}}}


class LandedCostToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = ToolManager(
            base_url="https://example.test",
            client_id="cid",
            client_secret="csec",
            account_number="ACCT123",
        )
        self.fake = FakeHTTPClient()
        self.manager.http_client = self.fake

    # --- Unit tests ---

    def test_routes_to_landed_cost_operation(self) -> None:
        self.manager.get_landed_cost_quote(
            currency_code="USD",
            export_country_code="US",
            import_country_code="GB",
            commodities=[{"hs_code": "6109.10", "price": 25.00, "quantity": 10}],
        )
        call = self.fake.calls[0]
        self.assertEqual(call["operation"].operation_id, "LandedCost")
        self.assertEqual(call["kwargs"]["path_params"]["version"], "v1")

    def test_injects_account_number_header(self) -> None:
        self.manager.get_landed_cost_quote(
            currency_code="USD",
            export_country_code="US",
            import_country_code="GB",
            commodities=[{"price": 10, "quantity": 1}],
        )
        headers = self.fake.calls[0]["kwargs"]["additional_headers"]
        self.assertEqual(headers["AccountNumber"], "ACCT123")

    def test_explicit_account_overrides_default(self) -> None:
        self.manager.get_landed_cost_quote(
            currency_code="USD",
            export_country_code="US",
            import_country_code="CA",
            commodities=[{"price": 10, "quantity": 1}],
            account_number="OVERRIDE999",
        )
        self.assertEqual(self.fake.calls[0]["kwargs"]["additional_headers"]["AccountNumber"], "OVERRIDE999")

    def test_no_account_omits_header(self) -> None:
        self.manager.account_number = None
        self.manager.get_landed_cost_quote(
            currency_code="USD",
            export_country_code="US",
            import_country_code="GB",
            commodities=[{"price": 10, "quantity": 1}],
        )
        self.assertIsNone(self.fake.calls[0]["kwargs"].get("additional_headers"))

    def test_multiple_commodities_with_weight(self) -> None:
        self.manager.get_landed_cost_quote(
            currency_code="EUR",
            export_country_code="DE",
            import_country_code="US",
            commodities=[
                {"hs_code": "6109.10", "price": 25, "quantity": 10},
                {"hs_code": "6205.30", "price": 50, "quantity": 5, "weight": 2.5, "weight_unit": "KGS"},
            ],
        )
        items = self.fake.calls[0]["kwargs"]["json_body"]["LandedCostRequest"]["shipment"]["shipmentItems"]
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["commodityId"], "1")
        self.assertEqual(items[1]["commodityId"], "2")
        self.assertEqual(items[1]["grossWeight"], "2.5")
        self.assertEqual(items[1]["grossWeightUnit"], "KGS")
        self.assertNotIn("grossWeight", items[0])

    def test_missing_price_raises_tool_error(self) -> None:
        with self.assertRaises(ToolError) as ctx:
            self.manager.get_landed_cost_quote(
                currency_code="USD", export_country_code="US", import_country_code="GB",
                commodities=[{"quantity": 5}],
            )
        self.assertIn("price", str(ctx.exception))

    def test_missing_quantity_raises_tool_error(self) -> None:
        with self.assertRaises(ToolError) as ctx:
            self.manager.get_landed_cost_quote(
                currency_code="USD", export_country_code="US", import_country_code="GB",
                commodities=[{"price": 10}],
            )
        self.assertIn("quantity", str(ctx.exception))

    def test_default_and_custom_shipment_type(self) -> None:
        self.manager.get_landed_cost_quote(
            currency_code="USD", export_country_code="US", import_country_code="GB",
            commodities=[{"price": 10, "quantity": 1}],
        )
        body1 = self.fake.calls[0]["kwargs"]["json_body"]
        self.assertEqual(body1["LandedCostRequest"]["shipment"]["shipmentType"], "Sale")

        self.manager.get_landed_cost_quote(
            currency_code="USD", export_country_code="US", import_country_code="GB",
            commodities=[{"price": 10, "quantity": 1}], shipment_type="Gift",
        )
        body2 = self.fake.calls[1]["kwargs"]["json_body"]
        self.assertEqual(body2["LandedCostRequest"]["shipment"]["shipmentType"], "Gift")

    def test_trans_id_is_auto_generated_in_payload(self) -> None:
        """transID is required by spec and auto-generated as a UUID."""
        self.manager.get_landed_cost_quote(
            currency_code="USD", export_country_code="US", import_country_code="GB",
            commodities=[{"price": 10, "quantity": 1}],
        )
        req = self.fake.calls[0]["kwargs"]["json_body"]["LandedCostRequest"]
        self.assertIn("transID", req)
        self.assertTrue(len(req["transID"]) > 0)

    def test_shipment_id_is_auto_generated(self) -> None:
        """shipment.id is required by spec and auto-generated."""
        self.manager.get_landed_cost_quote(
            currency_code="USD", export_country_code="US", import_country_code="GB",
            commodities=[{"price": 10, "quantity": 1}],
        )
        shipment = self.fake.calls[0]["kwargs"]["json_body"]["LandedCostRequest"]["shipment"]
        self.assertIn("id", shipment)
        self.assertTrue(len(shipment["id"]) > 0)

    # --- Contract test: validates payload satisfies OpenAPI required fields ---

    def test_contract_payload_has_all_required_fields(self) -> None:
        """Verify generated payload includes all fields the LandedCost spec marks as required."""
        self.manager.get_landed_cost_quote(
            currency_code="USD",
            export_country_code="US",
            import_country_code="GB",
            commodities=[{"hs_code": "6109.10", "price": 25, "quantity": 10, "description": "T-shirts"}],
        )
        body = self.fake.calls[0]["kwargs"]["json_body"]

        # Top-level wrapper
        self.assertIn("LandedCostRequest", body)
        req = body["LandedCostRequest"]

        # Required top-level fields (spec: currencyCode, transID, alversion, shipment)
        self.assertIn("currencyCode", req)
        self.assertIn("transID", req)
        self.assertIn("alversion", req)
        self.assertIn("shipment", req)

        # Required shipment fields (spec: id, importCountryCode, exportCountryCode, shipmentItems)
        shipment = req["shipment"]
        self.assertIn("id", shipment)
        self.assertIn("importCountryCode", shipment)
        self.assertIn("exportCountryCode", shipment)
        self.assertIn("shipmentItems", shipment)
        self.assertIsInstance(shipment["shipmentItems"], list)
        self.assertGreater(len(shipment["shipmentItems"]), 0)

        # Required per-item fields
        item = shipment["shipmentItems"][0]
        for key in ("commodityId", "priceEach", "quantity", "commodityCurrencyCode", "originCountryCode"):
            self.assertIn(key, item, f"Missing required commodity field: {key}")


if __name__ == "__main__":
    unittest.main()
