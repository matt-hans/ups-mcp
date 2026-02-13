import unittest

from ups_mcp.shipment_validator import (
    MissingField,
    FieldRule,
    UNCONDITIONAL_RULES,
    PACKAGE_RULES,
    PAYMENT_CHARGE_TYPE_RULE,
    PAYMENT_PAYER_RULES,
    COUNTRY_CONDITIONAL_RULES,
    BUILT_IN_DEFAULTS,
    ENV_DEFAULTS,
)


class DataStructureTests(unittest.TestCase):
    def test_missing_field_has_required_attrs(self) -> None:
        mf = MissingField(
            dot_path="ShipmentRequest.Shipment.Shipper.Name",
            flat_key="shipper_name",
            prompt="Shipper name",
        )
        self.assertEqual(mf.dot_path, "ShipmentRequest.Shipment.Shipper.Name")
        self.assertEqual(mf.flat_key, "shipper_name")
        self.assertEqual(mf.prompt, "Shipper name")

    def test_unconditional_rules_is_nonempty_list(self) -> None:
        self.assertIsInstance(UNCONDITIONAL_RULES, list)
        self.assertGreater(len(UNCONDITIONAL_RULES), 0)

    def test_package_rules_is_nonempty_list(self) -> None:
        self.assertIsInstance(PACKAGE_RULES, list)
        self.assertEqual(len(PACKAGE_RULES), 3)  # packaging code, weight unit, weight

    def test_payment_charge_type_rule_exists(self) -> None:
        self.assertIsInstance(PAYMENT_CHARGE_TYPE_RULE, FieldRule)
        self.assertEqual(PAYMENT_CHARGE_TYPE_RULE.flat_key, "payment_charge_type")

    def test_payment_payer_rules_has_bill_shipper(self) -> None:
        self.assertIn("BillShipper", PAYMENT_PAYER_RULES)
        rule = PAYMENT_PAYER_RULES["BillShipper"]
        self.assertEqual(rule.flat_key, "payment_account_number")

    def test_payment_payer_rules_has_bill_receiver(self) -> None:
        self.assertIn("BillReceiver", PAYMENT_PAYER_RULES)

    def test_payment_payer_rules_has_bill_third_party(self) -> None:
        self.assertIn("BillThirdParty", PAYMENT_PAYER_RULES)

    def test_country_conditional_rules_has_us_ca_pr(self) -> None:
        self.assertIn(("US", "CA", "PR"), COUNTRY_CONDITIONAL_RULES)

    def test_built_in_defaults_has_request_option(self) -> None:
        self.assertIn("ShipmentRequest.Request.RequestOption", BUILT_IN_DEFAULTS)
        self.assertEqual(
            BUILT_IN_DEFAULTS["ShipmentRequest.Request.RequestOption"],
            "nonvalidate",
        )

    def test_built_in_defaults_has_payment_charge_type(self) -> None:
        self.assertIn(
            "ShipmentRequest.Shipment.PaymentInformation.ShipmentCharge[0].Type",
            BUILT_IN_DEFAULTS,
        )

    def test_env_defaults_has_shipper_number(self) -> None:
        self.assertIn(
            "ShipmentRequest.Shipment.Shipper.ShipperNumber",
            ENV_DEFAULTS,
        )
        self.assertEqual(
            ENV_DEFAULTS["ShipmentRequest.Shipment.Shipper.ShipperNumber"],
            "UPS_ACCOUNT_NUMBER",
        )

    def test_env_defaults_does_not_have_bill_shipper_account(self) -> None:
        """BillShipper.AccountNumber is conditionally applied, not in ENV_DEFAULTS."""
        self.assertNotIn(
            "ShipmentRequest.Shipment.PaymentInformation.ShipmentCharge[0].BillShipper.AccountNumber",
            ENV_DEFAULTS,
        )


from ups_mcp.shipment_validator import _field_exists, _set_field


class FieldExistsTests(unittest.TestCase):
    def test_simple_path(self) -> None:
        data = {"a": {"b": {"c": "value"}}}
        self.assertTrue(_field_exists(data, "a.b.c"))

    def test_missing_intermediate(self) -> None:
        data = {"a": {}}
        self.assertFalse(_field_exists(data, "a.b.c"))

    def test_missing_leaf(self) -> None:
        data = {"a": {"b": {}}}
        self.assertFalse(_field_exists(data, "a.b.c"))

    def test_empty_string_is_missing(self) -> None:
        data = {"a": {"b": ""}}
        self.assertFalse(_field_exists(data, "a.b"))

    def test_whitespace_only_is_missing(self) -> None:
        data = {"a": {"b": "   "}}
        self.assertFalse(_field_exists(data, "a.b"))

    def test_whitespace_with_tabs_is_missing(self) -> None:
        data = {"a": " \t\n "}
        self.assertFalse(_field_exists(data, "a"))

    def test_none_is_missing(self) -> None:
        data = {"a": None}
        self.assertFalse(_field_exists(data, "a"))

    def test_array_index(self) -> None:
        data = {"a": {"b": ["first", "second"]}}
        self.assertTrue(_field_exists(data, "a.b[0]"))
        self.assertTrue(_field_exists(data, "a.b[1]"))

    def test_array_index_out_of_bounds(self) -> None:
        data = {"a": {"b": ["only"]}}
        self.assertFalse(_field_exists(data, "a.b[1]"))

    def test_array_index_empty_list(self) -> None:
        data = {"a": {"b": []}}
        self.assertFalse(_field_exists(data, "a.b[0]"))

    def test_zero_value_is_present(self) -> None:
        data = {"a": 0}
        self.assertTrue(_field_exists(data, "a"))

    def test_false_value_is_present(self) -> None:
        data = {"a": False}
        self.assertTrue(_field_exists(data, "a"))


class SetFieldTests(unittest.TestCase):
    def test_simple_set(self) -> None:
        data: dict = {}
        _set_field(data, "a.b.c", "value")
        self.assertEqual(data, {"a": {"b": {"c": "value"}}})

    def test_set_array_index(self) -> None:
        data: dict = {}
        _set_field(data, "a.b[0]", "first")
        self.assertEqual(data, {"a": {"b": ["first"]}})

    def test_overwrites_leaf_value(self) -> None:
        data = {"a": {"b": "existing"}}
        _set_field(data, "a.b", "new")
        self.assertEqual(data["a"]["b"], "new")

    def test_creates_intermediate_dicts(self) -> None:
        data: dict = {}
        _set_field(data, "ShipmentRequest.Shipment.Shipper.Name", "Test")
        self.assertEqual(
            data["ShipmentRequest"]["Shipment"]["Shipper"]["Name"],
            "Test",
        )

    def test_raises_on_existing_non_dict_intermediate(self) -> None:
        """When an existing intermediate node is a string but we need a dict, raise."""
        data: dict = {"a": {"b": "was_a_string"}}
        with self.assertRaises(TypeError):
            _set_field(data, "a.b.c", "value")

    def test_raises_on_existing_non_list_intermediate(self) -> None:
        """When an existing intermediate should be a list but isn't, raise."""
        data: dict = {"a": {"b": "was_a_string"}}
        with self.assertRaises(TypeError):
            _set_field(data, "a.b[0]", "value")

    def test_preserves_existing_list_elements(self) -> None:
        data: dict = {"a": {"b": ["existing"]}}
        _set_field(data, "a.b[1]", "new")
        self.assertEqual(data["a"]["b"], ["existing", "new"])


if __name__ == "__main__":
    unittest.main()
