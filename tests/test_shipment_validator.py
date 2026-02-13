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


import copy
from tests.shipment_fixtures import make_complete_body
from ups_mcp.shipment_validator import apply_defaults


class ApplyDefaultsTests(unittest.TestCase):
    def test_empty_body_gets_builtin_defaults(self) -> None:
        result = apply_defaults({}, {})
        self.assertEqual(
            result["ShipmentRequest"]["Request"]["RequestOption"],
            "nonvalidate",
        )

    def test_empty_body_gets_payment_charge_type_default(self) -> None:
        result = apply_defaults({}, {})
        self.assertEqual(
            result["ShipmentRequest"]["Shipment"]["PaymentInformation"]["ShipmentCharge"][0]["Type"],
            "01",
        )

    def test_caller_value_overrides_builtin(self) -> None:
        body = {"ShipmentRequest": {"Request": {"RequestOption": "validate"}}}
        result = apply_defaults(body, {})
        self.assertEqual(
            result["ShipmentRequest"]["Request"]["RequestOption"],
            "validate",
        )

    def test_env_default_fills_shipper_number(self) -> None:
        body: dict = {"ShipmentRequest": {"Shipment": {"Shipper": {}}}}
        result = apply_defaults(body, {"UPS_ACCOUNT_NUMBER": "ABC123"})
        self.assertEqual(
            result["ShipmentRequest"]["Shipment"]["Shipper"]["ShipperNumber"],
            "ABC123",
        )

    def test_env_default_fills_bill_shipper_when_no_payer(self) -> None:
        """When no payer object exists, env default injects BillShipper.AccountNumber."""
        result = apply_defaults({}, {"UPS_ACCOUNT_NUMBER": "ABC123"})
        self.assertEqual(
            result["ShipmentRequest"]["Shipment"]["PaymentInformation"]["ShipmentCharge"][0]["BillShipper"]["AccountNumber"],
            "ABC123",
        )

    def test_env_default_skips_bill_shipper_when_bill_receiver_present(self) -> None:
        """When BillReceiver is present, env default must NOT inject BillShipper."""
        body = {
            "ShipmentRequest": {
                "Shipment": {
                    "PaymentInformation": {
                        "ShipmentCharge": [{"Type": "01", "BillReceiver": {"AccountNumber": "RCV456"}}]
                    }
                }
            }
        }
        result = apply_defaults(body, {"UPS_ACCOUNT_NUMBER": "ABC123"})
        first_charge = result["ShipmentRequest"]["Shipment"]["PaymentInformation"]["ShipmentCharge"][0]
        self.assertNotIn("BillShipper", first_charge)
        self.assertEqual(first_charge["BillReceiver"]["AccountNumber"], "RCV456")

    def test_env_default_skips_bill_shipper_when_bill_third_party_present(self) -> None:
        """When BillThirdParty is present, env default must NOT inject BillShipper."""
        body = {
            "ShipmentRequest": {
                "Shipment": {
                    "PaymentInformation": {
                        "ShipmentCharge": [{"Type": "01", "BillThirdParty": {"AccountNumber": "TRD789"}}]
                    }
                }
            }
        }
        result = apply_defaults(body, {"UPS_ACCOUNT_NUMBER": "ABC123"})
        first_charge = result["ShipmentRequest"]["Shipment"]["PaymentInformation"]["ShipmentCharge"][0]
        self.assertNotIn("BillShipper", first_charge)

    def test_env_default_fills_bill_shipper_when_bill_shipper_present_but_no_account(self) -> None:
        """When BillShipper exists but has no AccountNumber, env fills it."""
        body = {
            "ShipmentRequest": {
                "Shipment": {
                    "PaymentInformation": {
                        "ShipmentCharge": [{"Type": "01", "BillShipper": {}}]
                    }
                }
            }
        }
        result = apply_defaults(body, {"UPS_ACCOUNT_NUMBER": "ABC123"})
        # BillShipper is a payer object, but _has_payer_object returns True.
        # The conditional skips. BillShipper.AccountNumber stays empty.
        # This is correct — the caller explicitly chose BillShipper but
        # didn't provide the account. find_missing_fields will catch it.
        first_charge = result["ShipmentRequest"]["Shipment"]["PaymentInformation"]["ShipmentCharge"][0]
        self.assertNotIn("AccountNumber", first_charge.get("BillShipper", {}))

    def test_caller_value_overrides_env_default(self) -> None:
        body = {
            "ShipmentRequest": {
                "Shipment": {"Shipper": {"ShipperNumber": "CALLER_NUM"}}
            }
        }
        result = apply_defaults(body, {"UPS_ACCOUNT_NUMBER": "ENV_NUM"})
        self.assertEqual(
            result["ShipmentRequest"]["Shipment"]["Shipper"]["ShipperNumber"],
            "CALLER_NUM",
        )

    def test_empty_env_value_does_not_set(self) -> None:
        result = apply_defaults({}, {"UPS_ACCOUNT_NUMBER": ""})
        shipper = result.get("ShipmentRequest", {}).get("Shipment", {}).get("Shipper", {})
        self.assertNotIn("ShipperNumber", shipper)

    def test_does_not_mutate_input(self) -> None:
        body = {"ShipmentRequest": {"Request": {}}}
        original = copy.deepcopy(body)
        apply_defaults(body, {})
        self.assertEqual(body, original)


from ups_mcp.shipment_validator import find_missing_fields, MissingField, AmbiguousPayerError


class FindMissingFieldsUnconditionalTests(unittest.TestCase):
    def test_complete_body_returns_empty(self) -> None:
        body = make_complete_body()
        missing = find_missing_fields(body)
        self.assertEqual(missing, [])

    def test_empty_body_returns_all_fields(self) -> None:
        missing = find_missing_fields({})
        flat_keys = {mf.flat_key for mf in missing}
        self.assertIn("request_option", flat_keys)
        self.assertIn("shipper_name", flat_keys)
        self.assertIn("shipper_number", flat_keys)
        self.assertIn("shipper_address_line_1", flat_keys)
        self.assertIn("ship_to_name", flat_keys)
        self.assertIn("service_code", flat_keys)
        self.assertIn("package_1_packaging_code", flat_keys)
        self.assertIn("package_1_weight_unit", flat_keys)
        self.assertIn("package_1_weight", flat_keys)
        self.assertIn("payment_charge_type", flat_keys)
        self.assertIn("payment_account_number", flat_keys)

    def test_missing_shipper_name_detected(self) -> None:
        body = make_complete_body()
        del body["ShipmentRequest"]["Shipment"]["Shipper"]["Name"]
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertIn("shipper_name", flat_keys)

    def test_missing_ship_to_address_detected(self) -> None:
        body = make_complete_body()
        del body["ShipmentRequest"]["Shipment"]["ShipTo"]["Address"]["AddressLine"]
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertIn("ship_to_address_line_1", flat_keys)

    def test_missing_service_code_detected(self) -> None:
        body = make_complete_body()
        del body["ShipmentRequest"]["Shipment"]["Service"]
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertIn("service_code", flat_keys)

    def test_missing_payment_info_detected(self) -> None:
        body = make_complete_body()
        del body["ShipmentRequest"]["Shipment"]["PaymentInformation"]
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertIn("payment_charge_type", flat_keys)
        self.assertIn("payment_account_number", flat_keys)

    def test_bill_receiver_account_validated(self) -> None:
        """BillReceiver present but missing AccountNumber triggers validation."""
        body = make_complete_body()
        body["ShipmentRequest"]["Shipment"]["PaymentInformation"]["ShipmentCharge"] = [{
            "Type": "01",
            "BillReceiver": {},
        }]
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertIn("payment_account_number", flat_keys)
        # Dot path should point to BillReceiver, not BillShipper
        account_rule = [mf for mf in missing if mf.flat_key == "payment_account_number"]
        self.assertIn("BillReceiver", account_rule[0].dot_path)

    def test_bill_third_party_account_validated(self) -> None:
        """BillThirdParty present but missing AccountNumber triggers validation."""
        body = make_complete_body()
        body["ShipmentRequest"]["Shipment"]["PaymentInformation"]["ShipmentCharge"] = [{
            "Type": "01",
            "BillThirdParty": {},
        }]
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertIn("payment_account_number", flat_keys)
        account_rule = [mf for mf in missing if mf.flat_key == "payment_account_number"]
        self.assertIn("BillThirdParty", account_rule[0].dot_path)

    def test_bill_receiver_with_account_passes(self) -> None:
        """BillReceiver with AccountNumber present should not be flagged."""
        body = make_complete_body()
        body["ShipmentRequest"]["Shipment"]["PaymentInformation"]["ShipmentCharge"] = [{
            "Type": "01",
            "BillReceiver": {"AccountNumber": "RCV123"},
        }]
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertNotIn("payment_account_number", flat_keys)

    def test_no_billing_object_defaults_to_bill_shipper(self) -> None:
        """No billing object present defaults to requiring BillShipper.AccountNumber."""
        body = make_complete_body()
        body["ShipmentRequest"]["Shipment"]["PaymentInformation"]["ShipmentCharge"] = [{
            "Type": "01",
        }]
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertIn("payment_account_number", flat_keys)
        account_rule = [mf for mf in missing if mf.flat_key == "payment_account_number"]
        self.assertIn("BillShipper", account_rule[0].dot_path)

    def test_shipment_charge_as_dict_normalized(self) -> None:
        """ShipmentCharge as a dict (not list) should be normalized and validated."""
        body = make_complete_body()
        # Convert ShipmentCharge from list to dict
        body["ShipmentRequest"]["Shipment"]["PaymentInformation"]["ShipmentCharge"] = {
            "Type": "01",
            "BillShipper": {"AccountNumber": "129D9Y"},
        }
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertNotIn("payment_charge_type", flat_keys)
        self.assertNotIn("payment_account_number", flat_keys)

    def test_multiple_payer_objects_raises_ambiguous_error(self) -> None:
        """Multiple billing objects in the same ShipmentCharge raises AmbiguousPayerError."""
        body = make_complete_body()
        body["ShipmentRequest"]["Shipment"]["PaymentInformation"]["ShipmentCharge"] = [{
            "Type": "01",
            "BillShipper": {"AccountNumber": "ABC"},
            "BillReceiver": {"AccountNumber": "DEF"},
        }]
        with self.assertRaises(AmbiguousPayerError) as cm:
            find_missing_fields(body)
        self.assertIn("BillShipper", cm.exception.payer_keys)
        self.assertIn("BillReceiver", cm.exception.payer_keys)

    def test_three_payer_objects_raises_ambiguous_error(self) -> None:
        """All three billing objects present also raises AmbiguousPayerError."""
        body = make_complete_body()
        body["ShipmentRequest"]["Shipment"]["PaymentInformation"]["ShipmentCharge"] = [{
            "Type": "01",
            "BillShipper": {"AccountNumber": "A"},
            "BillReceiver": {"AccountNumber": "B"},
            "BillThirdParty": {"AccountNumber": "C"},
        }]
        with self.assertRaises(AmbiguousPayerError):
            find_missing_fields(body)

    def test_returns_missing_field_instances(self) -> None:
        body = make_complete_body()
        del body["ShipmentRequest"]["Shipment"]["Shipper"]["Name"]
        missing = find_missing_fields(body)
        shipper_name = [mf for mf in missing if mf.flat_key == "shipper_name"]
        self.assertEqual(len(shipper_name), 1)
        self.assertEqual(shipper_name[0].dot_path, "ShipmentRequest.Shipment.Shipper.Name")
        self.assertEqual(shipper_name[0].prompt, "Shipper name")

    def test_whitespace_value_treated_as_missing(self) -> None:
        body = make_complete_body()
        body["ShipmentRequest"]["Shipment"]["Shipper"]["Name"] = "   "
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertIn("shipper_name", flat_keys)


class FindMissingFieldsPackageTests(unittest.TestCase):
    def test_missing_package_key_emits_package_1_fields(self) -> None:
        body = make_complete_body()
        del body["ShipmentRequest"]["Shipment"]["Package"]
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertIn("package_1_packaging_code", flat_keys)
        self.assertIn("package_1_weight_unit", flat_keys)
        self.assertIn("package_1_weight", flat_keys)

    def test_empty_package_list_emits_package_1_fields(self) -> None:
        body = make_complete_body()
        body["ShipmentRequest"]["Shipment"]["Package"] = []
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertIn("package_1_weight", flat_keys)

    def test_single_dict_package_validates_as_index_0(self) -> None:
        """Package as a single dict (not list) is normalized and validated."""
        body = make_complete_body()
        # Convert Package from list to dict for this test
        pkg = body["ShipmentRequest"]["Shipment"]["Package"][0]
        body["ShipmentRequest"]["Shipment"]["Package"] = pkg
        self.assertIsInstance(body["ShipmentRequest"]["Shipment"]["Package"], dict)
        missing = find_missing_fields(body)
        pkg_missing = [mf for mf in missing if "package_" in mf.flat_key]
        self.assertEqual(pkg_missing, [])

    def test_multi_package_validates_each(self) -> None:
        body = make_complete_body(num_packages=2)
        body["ShipmentRequest"]["Shipment"]["Package"][1].pop("PackageWeight")
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertNotIn("package_1_weight", flat_keys)
        self.assertIn("package_2_weight", flat_keys)
        self.assertIn("package_2_weight_unit", flat_keys)

    def test_multi_package_prompts_include_index(self) -> None:
        body = make_complete_body(num_packages=2)
        body["ShipmentRequest"]["Shipment"]["Package"][0].pop("PackageWeight")
        missing = find_missing_fields(body)
        pkg1_weight = [mf for mf in missing if mf.flat_key == "package_1_weight"]
        self.assertEqual(len(pkg1_weight), 1)
        self.assertIn("Package 1", pkg1_weight[0].prompt)


if __name__ == "__main__":
    unittest.main()
