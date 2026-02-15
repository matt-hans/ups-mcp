import unittest

from mcp.server.fastmcp.exceptions import ToolError

from ups_mcp.tools import ToolManager


class FakeHTTPClient:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def call_operation(self, operation, **kwargs):  # noqa: ANN001
        self.calls.append({"operation": operation, "kwargs": kwargs})
        return {"mock": True}


class RatePickupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = ToolManager(
            base_url="https://example.test", client_id="cid", client_secret="csec",
            account_number="ACCT123",
        )
        self.fake = FakeHTTPClient()
        self.manager.http_client = self.fake

    def test_routes_to_pickup_rate_operation(self) -> None:
        self.manager.rate_pickup(
            pickup_type="oncall", address_line="123 Main St", city="Atlanta",
            state="GA", postal_code="30301", country_code="US",
            pickup_date="20260301", ready_time="0900", close_time="1700",
        )
        call = self.fake.calls[0]
        self.assertEqual(call["operation"].operation_id, "Pickup Rate")
        self.assertEqual(call["kwargs"]["path_params"]["pickuptype"], "oncall")
        self.assertEqual(call["kwargs"]["path_params"]["version"], "v2409")

    def test_contract_rate_payload_has_all_required_fields(self) -> None:
        """Spec requires: ServiceDateOption, PickupAddress (with ResidentialIndicator,
        PostalCode, City, CountryCode), Request, AlternateAddressIndicator."""
        self.manager.rate_pickup(
            pickup_type="oncall", address_line="123 Main", city="Atlanta",
            state="GA", postal_code="30301", country_code="US",
            pickup_date="20260301", ready_time="0900", close_time="1700",
        )
        body = self.fake.calls[0]["kwargs"]["json_body"]
        req = body["PickupRateRequest"]

        # Top-level required fields
        self.assertIn("Request", req)
        self.assertIn("ServiceDateOption", req)
        self.assertIn("AlternateAddressIndicator", req)
        self.assertIn("PickupAddress", req)

        # PickupAddress required fields
        addr = req["PickupAddress"]
        self.assertIn("ResidentialIndicator", addr)
        self.assertIn("PostalCode", addr)
        self.assertIn("City", addr)
        self.assertIn("CountryCode", addr)

        # PickupDateInfo (always included)
        self.assertIn("PickupDateInfo", req)
        date_info = req["PickupDateInfo"]
        self.assertIn("ReadyTime", date_info)
        self.assertIn("CloseTime", date_info)
        self.assertIn("PickupDate", date_info)


class SchedulePickupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = ToolManager(
            base_url="https://example.test", client_id="cid", client_secret="csec",
            account_number="ACCT123",
        )
        self.fake = FakeHTTPClient()
        self.manager.http_client = self.fake

    def _call_default(self, **overrides):
        defaults = dict(
            pickup_date="20260301", ready_time="0900", close_time="1700",
            address_line="123 Main St", city="Atlanta", state="GA",
            postal_code="30301", country_code="US",
            contact_name="John Doe", phone_number="5551234567",
        )
        defaults.update(overrides)
        return self.manager.schedule_pickup(**defaults)

    def test_routes_to_pickup_creation(self) -> None:
        self._call_default()
        call = self.fake.calls[0]
        self.assertEqual(call["operation"].operation_id, "Pickup Creation")
        self.assertEqual(call["kwargs"]["path_params"]["version"], "v2409")

    def test_contract_schedule_payload_has_all_required_fields(self) -> None:
        """Spec requires: PickupDateInfo, PickupAddress (CompanyName, ContactName,
        AddressLine, City, CountryCode, ResidentialIndicator, Phone.Number),
        Request, PaymentMethod, PickupPiece, RatePickupIndicator,
        AlternateAddressIndicator. Account goes in Shipper.Account.AccountNumber."""
        self._call_default()
        body = self.fake.calls[0]["kwargs"]["json_body"]
        req = body["PickupCreationRequest"]

        # Top-level required
        for key in ("Request", "RatePickupIndicator", "AlternateAddressIndicator",
                     "PaymentMethod", "PickupDateInfo", "PickupAddress", "PickupPiece"):
            self.assertIn(key, req, f"Missing required top-level field: {key}")

        # Shipper nesting: Shipper.Account.AccountNumber
        self.assertIn("Shipper", req)
        self.assertIn("Account", req["Shipper"])
        self.assertIn("AccountNumber", req["Shipper"]["Account"])
        self.assertIn("AccountCountryCode", req["Shipper"]["Account"])

        # PickupAddress required
        addr = req["PickupAddress"]
        for key in ("CompanyName", "ContactName", "AddressLine", "City",
                     "CountryCode", "ResidentialIndicator", "Phone"):
            self.assertIn(key, addr, f"Missing PickupAddress field: {key}")
        self.assertIn("Number", addr["Phone"])

        # PickupDateInfo required
        for key in ("ReadyTime", "CloseTime", "PickupDate"):
            self.assertIn(key, req["PickupDateInfo"])

        # PickupPiece required per-item
        self.assertIsInstance(req["PickupPiece"], list)
        piece = req["PickupPiece"][0]
        for key in ("ServiceCode", "Quantity", "DestinationCountryCode", "ContainerCode"):
            self.assertIn(key, piece)

    def test_ready_time_after_close_time_raises(self) -> None:
        with self.assertRaises(ToolError) as ctx:
            self._call_default(ready_time="1800", close_time="0900")
        self.assertIn("ready_time", str(ctx.exception).lower())

    def test_uses_account_in_shipper_nesting(self) -> None:
        self._call_default()
        body = self.fake.calls[0]["kwargs"]["json_body"]
        acct = body["PickupCreationRequest"]["Shipper"]["Account"]["AccountNumber"]
        self.assertEqual(acct, "ACCT123")

    def test_payment_method_01_without_account_raises(self) -> None:
        """Spec: if payment_method=01, ShipperAccountNumber must be provided."""
        self.manager.account_number = None
        with self.assertRaises(ToolError) as ctx:
            self._call_default(payment_method="01")
        self.assertIn("account", str(ctx.exception).lower())

    def test_payment_method_00_without_account_succeeds(self) -> None:
        """payment_method=00 (no payment needed) does not require account."""
        self.manager.account_number = None
        self._call_default(payment_method="00")
        body = self.fake.calls[0]["kwargs"]["json_body"]
        self.assertEqual(body["PickupCreationRequest"]["PaymentMethod"], "00")


class CancelPickupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = ToolManager(
            base_url="https://example.test", client_id="cid", client_secret="csec",
            account_number="ACCT123",
        )
        self.fake = FakeHTTPClient()
        self.manager.http_client = self.fake

    def test_cancel_by_account_maps_to_01(self) -> None:
        self.manager.cancel_pickup(cancel_by="account")
        self.assertEqual(self.fake.calls[0]["kwargs"]["path_params"]["CancelBy"], "01")

    def test_cancel_by_prn_maps_to_02_and_injects_header(self) -> None:
        self.manager.cancel_pickup(cancel_by="prn", prn="PRN123456789")
        call = self.fake.calls[0]
        self.assertEqual(call["kwargs"]["path_params"]["CancelBy"], "02")
        self.assertEqual(call["kwargs"]["additional_headers"]["Prn"], "PRN123456789")

    def test_cancel_by_prn_without_prn_raises(self) -> None:
        with self.assertRaises(ToolError):
            self.manager.cancel_pickup(cancel_by="prn")

    def test_invalid_cancel_by_raises(self) -> None:
        with self.assertRaises(ToolError):
            self.manager.cancel_pickup(cancel_by="invalid")


class GetPickupStatusTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = ToolManager(
            base_url="https://example.test", client_id="cid", client_secret="csec",
            account_number="ACCT123",
        )
        self.fake = FakeHTTPClient()
        self.manager.http_client = self.fake

    def test_routes_and_injects_header(self) -> None:
        self.manager.get_pickup_status(pickup_type="oncall")
        call = self.fake.calls[0]
        self.assertEqual(call["operation"].operation_id, "Pickup Pending Status")
        self.assertEqual(call["kwargs"]["additional_headers"]["AccountNumber"], "ACCT123")

    def test_no_account_raises(self) -> None:
        self.manager.account_number = None
        with self.assertRaises(ToolError):
            self.manager.get_pickup_status(pickup_type="oncall")


class GetPoliticalDivisionsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = ToolManager(
            base_url="https://example.test", client_id="cid", client_secret="csec",
        )
        self.fake = FakeHTTPClient()
        self.manager.http_client = self.fake

    def test_routes_correctly(self) -> None:
        self.manager.get_political_divisions(country_code="US")
        call = self.fake.calls[0]
        self.assertEqual(call["operation"].operation_id, "Pickup Get Political Division1 List")
        self.assertEqual(call["kwargs"]["path_params"]["countrycode"], "US")
        self.assertIsNone(call["kwargs"]["json_body"])


class GetServiceCenterFacilitiesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = ToolManager(
            base_url="https://example.test", client_id="cid", client_secret="csec",
        )
        self.fake = FakeHTTPClient()
        self.manager.http_client = self.fake

    def test_routes_and_constructs_payload(self) -> None:
        self.manager.get_service_center_facilities(
            city="Atlanta", state="GA", postal_code="30301", country_code="US",
        )
        call = self.fake.calls[0]
        self.assertEqual(call["operation"].operation_id, "Pickup Get Service Center Facilities")
        self.assertIn("PickupGetServiceCenterFacilitiesRequest", call["kwargs"]["json_body"])


if __name__ == "__main__":
    unittest.main()
