import unittest

from mcp.server.fastmcp.exceptions import ToolError

from ups_mcp.tools import ToolManager


class FakeHTTPClient:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def call_operation(self, operation, **kwargs):  # noqa: ANN001
        self.calls.append({"operation": operation, "kwargs": kwargs})
        return {"LocatorResponse": {"SearchResults": {}}}


class FindLocationsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = ToolManager(
            base_url="https://example.test", client_id="cid", client_secret="csec",
        )
        self.fake = FakeHTTPClient()
        self.manager.http_client = self.fake

    def _call_default(self, **overrides):
        defaults = dict(
            location_type="general", address_line="123 Main St", city="Atlanta",
            state="GA", postal_code="30301", country_code="US",
        )
        defaults.update(overrides)
        return self.manager.find_locations(**defaults)

    def test_maps_access_point_to_64(self) -> None:
        self._call_default(location_type="access_point")
        self.assertEqual(self.fake.calls[0]["kwargs"]["path_params"]["reqOption"], "64")

    def test_maps_retail_to_32(self) -> None:
        self._call_default(location_type="retail")
        self.assertEqual(self.fake.calls[0]["kwargs"]["path_params"]["reqOption"], "32")

    def test_maps_general_to_1(self) -> None:
        self._call_default(location_type="general")
        self.assertEqual(self.fake.calls[0]["kwargs"]["path_params"]["reqOption"], "1")

    def test_invalid_location_type_raises(self) -> None:
        with self.assertRaises(ToolError) as ctx:
            self._call_default(location_type="warehouse")
        self.assertIn("location_type", str(ctx.exception))

    def test_uses_version_v3(self) -> None:
        self._call_default()
        self.assertEqual(self.fake.calls[0]["kwargs"]["path_params"]["version"], "v3")

    def test_constructs_origin_address(self) -> None:
        self._call_default()
        body = self.fake.calls[0]["kwargs"]["json_body"]
        addr = body["LocatorRequest"]["OriginAddress"]["AddressKeyFormat"]
        self.assertEqual(addr["AddressLine"], "123 Main St")
        self.assertEqual(addr["PoliticalDivision2"], "Atlanta")
        self.assertEqual(addr["CountryCode"], "US")

    def test_default_radius_and_unit(self) -> None:
        self._call_default()
        body = self.fake.calls[0]["kwargs"]["json_body"]
        self.assertEqual(body["LocatorRequest"]["LocationSearchCriteria"]["SearchRadius"], "15.0")
        self.assertEqual(body["LocatorRequest"]["UnitOfMeasurement"]["Code"], "MI")

    def test_access_point_includes_access_point_search(self) -> None:
        self._call_default(location_type="access_point")
        criteria = self.fake.calls[0]["kwargs"]["json_body"]["LocatorRequest"]["LocationSearchCriteria"]
        self.assertEqual(criteria["AccessPointSearch"]["AccessPointStatus"], "01")

    def test_non_access_point_omits_access_point_search(self) -> None:
        self._call_default(location_type="retail")
        criteria = self.fake.calls[0]["kwargs"]["json_body"]["LocatorRequest"]["LocationSearchCriteria"]
        self.assertNotIn("AccessPointSearch", criteria)

    def test_contract_payload_has_required_fields(self) -> None:
        """LocatorRequest spec requires: Request, OriginAddress, Translate."""
        self._call_default()
        req = self.fake.calls[0]["kwargs"]["json_body"]["LocatorRequest"]
        self.assertIn("Request", req)
        self.assertIn("OriginAddress", req)
        self.assertIn("Translate", req)

    def test_default_max_results(self) -> None:
        """Default MaximumListSize should be '10'."""
        self._call_default()
        criteria = self.fake.calls[0]["kwargs"]["json_body"]["LocatorRequest"]["LocationSearchCriteria"]
        self.assertEqual(criteria["MaximumListSize"], "10")

    def test_custom_max_results(self) -> None:
        """Passing max_results=25 should set MaximumListSize to '25'."""
        self._call_default(max_results=25)
        criteria = self.fake.calls[0]["kwargs"]["json_body"]["LocatorRequest"]["LocationSearchCriteria"]
        self.assertEqual(criteria["MaximumListSize"], "25")

    def test_access_point_includes_exact_match_indicator(self) -> None:
        """Access point searches should include ExactMatchIndicator."""
        self._call_default(location_type="access_point")
        criteria = self.fake.calls[0]["kwargs"]["json_body"]["LocatorRequest"]["LocationSearchCriteria"]
        self.assertIn("ExactMatchIndicator", criteria["AccessPointSearch"])

    def test_non_access_point_omits_exact_match_indicator(self) -> None:
        """Non-access-point searches should not have AccessPointSearch at all."""
        self._call_default(location_type="retail")
        criteria = self.fake.calls[0]["kwargs"]["json_body"]["LocatorRequest"]["LocationSearchCriteria"]
        self.assertNotIn("AccessPointSearch", criteria)


if __name__ == "__main__":
    unittest.main()
