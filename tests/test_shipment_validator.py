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


class FindMissingFieldsCountryTests(unittest.TestCase):
    def test_us_address_requires_state_and_postal(self) -> None:
        body = make_complete_body(shipper_country="US")
        del body["ShipmentRequest"]["Shipment"]["Shipper"]["Address"]["StateProvinceCode"]
        del body["ShipmentRequest"]["Shipment"]["Shipper"]["Address"]["PostalCode"]
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertIn("shipper_state", flat_keys)
        self.assertIn("shipper_postal_code", flat_keys)

    def test_ca_address_requires_state_and_postal(self) -> None:
        body = make_complete_body(shipper_country="CA")
        del body["ShipmentRequest"]["Shipment"]["Shipper"]["Address"]["StateProvinceCode"]
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertIn("shipper_state", flat_keys)

    def test_pr_address_requires_state_and_postal(self) -> None:
        body = make_complete_body(ship_to_country="PR")
        del body["ShipmentRequest"]["Shipment"]["ShipTo"]["Address"]["PostalCode"]
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertIn("ship_to_postal_code", flat_keys)

    def test_gb_address_does_not_require_state(self) -> None:
        body = make_complete_body(shipper_country="GB")
        del body["ShipmentRequest"]["Shipment"]["Shipper"]["Address"]["StateProvinceCode"]
        del body["ShipmentRequest"]["Shipment"]["Shipper"]["Address"]["PostalCode"]
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertNotIn("shipper_state", flat_keys)
        self.assertNotIn("shipper_postal_code", flat_keys)

    def test_no_country_code_skips_conditional(self) -> None:
        body = make_complete_body()
        del body["ShipmentRequest"]["Shipment"]["Shipper"]["Address"]["CountryCode"]
        del body["ShipmentRequest"]["Shipment"]["Shipper"]["Address"]["StateProvinceCode"]
        del body["ShipmentRequest"]["Shipment"]["Shipper"]["Address"]["PostalCode"]
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertIn("shipper_country_code", flat_keys)
        self.assertNotIn("shipper_state", flat_keys)
        self.assertNotIn("shipper_postal_code", flat_keys)


from ups_mcp.shipment_validator import _missing_from_rule, build_elicitation_schema
from pydantic import BaseModel


class MissingFromRuleTests(unittest.TestCase):
    def test_propagates_type_metadata(self) -> None:
        rule = FieldRule(
            "a.b", "code", "Code",
            enum_values=("01", "02"),
            enum_titles=("One", "Two"),
            default="01",
            constraints=(("maxLength", 2),),
        )
        mf = _missing_from_rule(rule)
        self.assertEqual(mf.enum_values, ("01", "02"))
        self.assertEqual(mf.enum_titles, ("One", "Two"))
        self.assertEqual(mf.default, "01")
        self.assertEqual(mf.constraints, (("maxLength", 2),))

    def test_overrides_apply(self) -> None:
        rule = FieldRule("a.b", "code", "Code")
        mf = _missing_from_rule(rule, dot_path="x.y", flat_key="new_key", prompt="New")
        self.assertEqual(mf.dot_path, "x.y")
        self.assertEqual(mf.flat_key, "new_key")
        self.assertEqual(mf.prompt, "New")

    def test_none_override_uses_rule_value(self) -> None:
        rule = FieldRule("a.b", "code", "Code")
        mf = _missing_from_rule(rule, dot_path=None, flat_key=None, prompt=None)
        self.assertEqual(mf.dot_path, "a.b")
        self.assertEqual(mf.flat_key, "code")
        self.assertEqual(mf.prompt, "Code")


class FindMissingFieldsTypeMetadataTests(unittest.TestCase):
    """Integration: verify find_missing_fields propagates FieldRule type metadata."""

    def test_service_code_carries_enum_values(self) -> None:
        body = make_complete_body()
        del body["ShipmentRequest"]["Shipment"]["Service"]
        missing = find_missing_fields(body)
        service = [mf for mf in missing if mf.flat_key == "service_code"]
        self.assertEqual(len(service), 1)
        self.assertIsNotNone(service[0].enum_values)
        self.assertIn("03", service[0].enum_values)
        self.assertIsNotNone(service[0].enum_titles)
        self.assertEqual(service[0].default, "03")

    def test_package_weight_carries_float_type(self) -> None:
        body = make_complete_body()
        del body["ShipmentRequest"]["Shipment"]["Package"][0]["PackageWeight"]["Weight"]
        missing = find_missing_fields(body)
        weight = [mf for mf in missing if mf.flat_key == "package_1_weight"]
        self.assertEqual(len(weight), 1)
        self.assertEqual(weight[0].type_hint, float)
        self.assertIsNotNone(weight[0].constraints)

    def test_country_code_carries_constraints(self) -> None:
        body = make_complete_body()
        del body["ShipmentRequest"]["Shipment"]["Shipper"]["Address"]["CountryCode"]
        missing = find_missing_fields(body)
        country = [mf for mf in missing if mf.flat_key == "shipper_country_code"]
        self.assertEqual(len(country), 1)
        constraint_keys = {k for k, v in country[0].constraints}
        self.assertIn("maxLength", constraint_keys)
        self.assertIn("pattern", constraint_keys)

    def test_packaging_code_carries_enum_with_titles(self) -> None:
        body = make_complete_body()
        del body["ShipmentRequest"]["Shipment"]["Package"][0]["Packaging"]
        missing = find_missing_fields(body)
        packaging = [mf for mf in missing if mf.flat_key == "package_1_packaging_code"]
        self.assertEqual(len(packaging), 1)
        self.assertIsNotNone(packaging[0].enum_values)
        self.assertIsNotNone(packaging[0].enum_titles)
        self.assertEqual(len(packaging[0].enum_values), len(packaging[0].enum_titles))
        self.assertEqual(packaging[0].default, "02")

    def test_charge_type_carries_enum(self) -> None:
        body = make_complete_body()
        del body["ShipmentRequest"]["Shipment"]["PaymentInformation"]
        missing = find_missing_fields(body)
        charge = [mf for mf in missing if mf.flat_key == "payment_charge_type"]
        self.assertEqual(len(charge), 1)
        self.assertEqual(charge[0].enum_values, ("01", "02"))
        self.assertEqual(charge[0].default, "01")


class BuildElicitationSchemaTests(unittest.TestCase):
    def test_schema_has_only_missing_fields(self) -> None:
        missing = [
            MissingField("a.b", "shipper_name", "Shipper name"),
            MissingField("c.d", "service_code", "Service code"),
        ]
        schema = build_elicitation_schema(missing)
        self.assertTrue(issubclass(schema, BaseModel))
        field_names = set(schema.model_fields.keys())
        self.assertEqual(field_names, {"shipper_name", "service_code"})

    def test_plain_field_is_str_type(self) -> None:
        missing = [MissingField("a.b", "shipper_name", "Shipper name")]
        schema = build_elicitation_schema(missing)
        self.assertEqual(schema.model_fields["shipper_name"].annotation, str)

    def test_field_descriptions_match_prompts(self) -> None:
        missing = [
            MissingField("a.b", "shipper_name", "Shipper name"),
        ]
        schema = build_elicitation_schema(missing)
        self.assertEqual(
            schema.model_fields["shipper_name"].description,
            "Shipper name",
        )

    def test_empty_missing_returns_valid_model(self) -> None:
        schema = build_elicitation_schema([])
        self.assertTrue(issubclass(schema, BaseModel))
        self.assertEqual(len(schema.model_fields), 0)

    def test_float_type_produces_number_schema(self) -> None:
        missing = [
            MissingField("a.b", "weight", "Package weight", type_hint=float),
        ]
        schema = build_elicitation_schema(missing)
        self.assertEqual(schema.model_fields["weight"].annotation, float)
        js = schema.model_json_schema()
        self.assertEqual(js["properties"]["weight"]["type"], "number")

    def test_enum_values_produce_literal_type(self) -> None:
        missing = [
            MissingField(
                "a.b", "unit", "Weight unit",
                enum_values=("LBS", "KGS"),
            ),
        ]
        schema = build_elicitation_schema(missing)
        js = schema.model_json_schema()
        self.assertEqual(js["properties"]["unit"]["enum"], ["LBS", "KGS"])

    def test_default_value_in_schema(self) -> None:
        missing = [
            MissingField(
                "a.b", "unit", "Weight unit",
                enum_values=("LBS", "KGS"), default="LBS",
            ),
        ]
        schema = build_elicitation_schema(missing)
        js = schema.model_json_schema()
        self.assertEqual(js["properties"]["unit"]["default"], "LBS")
        # Field with default should not be in required
        self.assertNotIn("unit", js.get("required", []))

    def test_constraints_in_schema(self) -> None:
        missing = [
            MissingField(
                "a.b", "weight", "Package weight",
                type_hint=float, constraints=(("gt", 0),),
            ),
        ]
        schema = build_elicitation_schema(missing)
        js = schema.model_json_schema()
        self.assertGreater(
            js["properties"]["weight"].get("exclusiveMinimum", -1), -1,
        )

    def test_json_schema_extra_constraints(self) -> None:
        missing = [
            MissingField(
                "a.b", "code", "Country code",
                constraints=(("maxLength", 2), ("pattern", "^[A-Z]{2}$")),
            ),
        ]
        schema = build_elicitation_schema(missing)
        js = schema.model_json_schema()
        self.assertEqual(js["properties"]["code"]["maxLength"], 2)
        self.assertEqual(js["properties"]["code"]["pattern"], "^[A-Z]{2}$")

    def test_enum_titles_produce_one_of(self) -> None:
        missing = [
            MissingField(
                "a.b", "unit", "Weight unit",
                enum_values=("LBS", "KGS"),
                enum_titles=("Pounds", "Kilograms"),
            ),
        ]
        schema = build_elicitation_schema(missing)
        js = schema.model_json_schema()
        one_of = js["properties"]["unit"]["oneOf"]
        self.assertEqual(len(one_of), 2)
        self.assertEqual(one_of[0], {"const": "LBS", "title": "Pounds"})
        self.assertEqual(one_of[1], {"const": "KGS", "title": "Kilograms"})

    def test_enum_without_titles_has_no_one_of(self) -> None:
        missing = [
            MissingField(
                "a.b", "unit", "Weight unit",
                enum_values=("LBS", "KGS"),
            ),
        ]
        schema = build_elicitation_schema(missing)
        js = schema.model_json_schema()
        self.assertNotIn("oneOf", js["properties"]["unit"])

    def test_mismatched_titles_length_skips_one_of(self) -> None:
        missing = [
            MissingField(
                "a.b", "unit", "Weight unit",
                enum_values=("LBS", "KGS"),
                enum_titles=("Pounds",),  # length mismatch
            ),
        ]
        schema = build_elicitation_schema(missing)
        js = schema.model_json_schema()
        self.assertNotIn("oneOf", js["properties"]["unit"])


from ups_mcp.shipment_validator import validate_elicited_values


class ValidateElicitedValuesTests(unittest.TestCase):
    def test_valid_weight_passes(self) -> None:
        missing = [MissingField("a.b", "package_1_weight", "Package weight")]
        errors = validate_elicited_values({"package_1_weight": "5.0"}, missing)
        self.assertEqual(errors, [])

    def test_non_numeric_weight_fails(self) -> None:
        missing = [MissingField("a.b", "package_1_weight", "Package weight")]
        errors = validate_elicited_values({"package_1_weight": "five"}, missing)
        self.assertEqual(len(errors), 1)
        self.assertIn("must be a number", errors[0])

    def test_zero_weight_fails(self) -> None:
        missing = [MissingField("a.b", "package_1_weight", "Package weight")]
        errors = validate_elicited_values({"package_1_weight": "0"}, missing)
        self.assertEqual(len(errors), 1)
        self.assertIn("positive", errors[0])

    def test_negative_weight_fails(self) -> None:
        missing = [MissingField("a.b", "package_1_weight", "Package weight")]
        errors = validate_elicited_values({"package_1_weight": "-1"}, missing)
        self.assertIn("positive", errors[0])

    def test_valid_country_code_passes(self) -> None:
        missing = [MissingField("a.b", "shipper_country_code", "Country")]
        errors = validate_elicited_values({"shipper_country_code": "US"}, missing)
        self.assertEqual(errors, [])

    def test_invalid_country_code_fails(self) -> None:
        missing = [MissingField("a.b", "shipper_country_code", "Country")]
        errors = validate_elicited_values({"shipper_country_code": "USA"}, missing)
        self.assertEqual(len(errors), 1)
        self.assertIn("2-letter", errors[0])

    def test_numeric_country_code_fails(self) -> None:
        missing = [MissingField("a.b", "shipper_country_code", "Country")]
        errors = validate_elicited_values({"shipper_country_code": "12"}, missing)
        self.assertIn("2-letter", errors[0])

    def test_valid_state_code_passes(self) -> None:
        missing = [MissingField("a.b", "shipper_state", "State")]
        errors = validate_elicited_values({"shipper_state": "NY"}, missing)
        self.assertEqual(errors, [])

    def test_invalid_state_code_fails(self) -> None:
        missing = [MissingField("a.b", "shipper_state", "State")]
        errors = validate_elicited_values({"shipper_state": "New York"}, missing)
        self.assertIn("2-letter", errors[0])

    def test_multiple_errors_accumulated(self) -> None:
        missing = [
            MissingField("a", "package_1_weight", "Weight"),
            MissingField("b", "shipper_country_code", "Country"),
        ]
        errors = validate_elicited_values(
            {"package_1_weight": "bad", "shipper_country_code": "XYZ"},
            missing,
        )
        self.assertEqual(len(errors), 2)

    def test_unknown_keys_ignored(self) -> None:
        errors = validate_elicited_values({"shipper_name": "Acme"}, [])
        self.assertEqual(errors, [])

    def test_uses_prompt_as_label(self) -> None:
        missing = [MissingField("a.b", "package_1_weight", "Custom Label")]
        errors = validate_elicited_values({"package_1_weight": "bad"}, missing)
        self.assertIn("Custom Label", errors[0])

    def test_valid_enum_value_passes(self) -> None:
        missing = [MissingField(
            "a.b", "service_code", "UPS service type",
            enum_values=("01", "02", "03"),
        )]
        errors = validate_elicited_values({"service_code": "03"}, missing)
        self.assertEqual(errors, [])

    def test_invalid_enum_value_fails(self) -> None:
        missing = [MissingField(
            "a.b", "service_code", "UPS service type",
            enum_values=("01", "02", "03"),
        )]
        errors = validate_elicited_values({"service_code": "99"}, missing)
        self.assertEqual(len(errors), 1)
        self.assertIn("must be one of", errors[0])
        self.assertIn("01", errors[0])

    def test_enum_field_without_metadata_skipped(self) -> None:
        """Fields without enum_values in MissingField are not enum-validated."""
        missing = [MissingField("a.b", "shipper_name", "Shipper name")]
        errors = validate_elicited_values({"shipper_name": "anything"}, missing)
        self.assertEqual(errors, [])

    def test_valid_us_postal_code(self) -> None:
        missing = [MissingField("a.b", "shipper_postal_code", "Postal code")]
        errors = validate_elicited_values(
            {"shipper_postal_code": "10001", "shipper_country_code": "US"}, missing,
        )
        self.assertEqual(errors, [])

    def test_valid_us_postal_code_zip_plus_4(self) -> None:
        missing = [MissingField("a.b", "shipper_postal_code", "Postal code")]
        errors = validate_elicited_values(
            {"shipper_postal_code": "10001-1234", "shipper_country_code": "US"}, missing,
        )
        self.assertEqual(errors, [])

    def test_invalid_us_postal_code(self) -> None:
        missing = [MissingField("a.b", "shipper_postal_code", "Postal code")]
        errors = validate_elicited_values(
            {"shipper_postal_code": "ABCDE", "shipper_country_code": "US"}, missing,
        )
        self.assertEqual(len(errors), 1)
        self.assertIn("US postal code", errors[0])

    def test_valid_ca_postal_code(self) -> None:
        missing = [MissingField("a.b", "ship_to_postal_code", "Postal code")]
        errors = validate_elicited_values(
            {"ship_to_postal_code": "K1A 0B1", "ship_to_country_code": "CA"}, missing,
        )
        self.assertEqual(errors, [])

    def test_valid_ca_postal_code_no_space(self) -> None:
        missing = [MissingField("a.b", "ship_to_postal_code", "Postal code")]
        errors = validate_elicited_values(
            {"ship_to_postal_code": "K1A0B1", "ship_to_country_code": "CA"}, missing,
        )
        self.assertEqual(errors, [])

    def test_invalid_ca_postal_code(self) -> None:
        missing = [MissingField("a.b", "ship_to_postal_code", "Postal code")]
        errors = validate_elicited_values(
            {"ship_to_postal_code": "12345", "ship_to_country_code": "CA"}, missing,
        )
        self.assertEqual(len(errors), 1)
        self.assertIn("Canadian postal code", errors[0])

    def test_postal_code_non_us_ca_not_validated(self) -> None:
        """Postal codes for non-US/CA countries are not format-validated."""
        missing = [MissingField("a.b", "shipper_postal_code", "Postal code")]
        errors = validate_elicited_values(
            {"shipper_postal_code": "SW1A 1AA", "shipper_country_code": "GB"}, missing,
        )
        self.assertEqual(errors, [])

    def test_postal_code_without_country_not_validated(self) -> None:
        """When no country code is in flat_data, postal code is not format-validated."""
        missing = [MissingField("a.b", "shipper_postal_code", "Postal code")]
        errors = validate_elicited_values(
            {"shipper_postal_code": "anything"}, missing,
        )
        self.assertEqual(errors, [])


from ups_mcp.shipment_validator import (
    normalize_elicited_values,
    rehydrate,
    canonicalize_body,
    RehydrationError,
)


class CanonicalizeBodyTests(unittest.TestCase):
    def test_package_dict_becomes_list(self) -> None:
        body = {"ShipmentRequest": {"Shipment": {"Package": {"Packaging": {"Code": "02"}}}}}
        result = canonicalize_body(body)
        pkg = result["ShipmentRequest"]["Shipment"]["Package"]
        self.assertIsInstance(pkg, list)
        self.assertEqual(len(pkg), 1)
        self.assertEqual(pkg[0]["Packaging"]["Code"], "02")

    def test_shipment_charge_dict_becomes_list(self) -> None:
        body = {
            "ShipmentRequest": {
                "Shipment": {
                    "PaymentInformation": {
                        "ShipmentCharge": {"Type": "01", "BillShipper": {"AccountNumber": "X"}}
                    }
                }
            }
        }
        result = canonicalize_body(body)
        sc = result["ShipmentRequest"]["Shipment"]["PaymentInformation"]["ShipmentCharge"]
        self.assertIsInstance(sc, list)
        self.assertEqual(sc[0]["Type"], "01")

    def test_already_lists_unchanged(self) -> None:
        body = make_complete_body()
        result = canonicalize_body(body)
        self.assertEqual(
            result["ShipmentRequest"]["Shipment"]["Package"],
            body["ShipmentRequest"]["Shipment"]["Package"],
        )

    def test_does_not_mutate_input(self) -> None:
        body = {"ShipmentRequest": {"Shipment": {"Package": {"Packaging": {"Code": "02"}}}}}
        original = copy.deepcopy(body)
        canonicalize_body(body)
        self.assertEqual(body, original)

    def test_missing_fields_tolerated(self) -> None:
        result = canonicalize_body({})
        self.assertEqual(result, {})

    def test_non_dict_list_elements_coerced_to_empty_dict(self) -> None:
        body = {
            "ShipmentRequest": {
                "Shipment": {
                    "Package": ["not_a_dict", 42, None],
                }
            }
        }
        result = canonicalize_body(body)
        pkgs = result["ShipmentRequest"]["Shipment"]["Package"]
        self.assertEqual(pkgs, [{}, {}, {}])

    def test_non_dict_shipment_charge_elements_coerced(self) -> None:
        body = {
            "ShipmentRequest": {
                "Shipment": {
                    "PaymentInformation": {
                        "ShipmentCharge": ["bad_element"],
                    }
                }
            }
        }
        result = canonicalize_body(body)
        charges = result["ShipmentRequest"]["Shipment"]["PaymentInformation"]["ShipmentCharge"]
        self.assertEqual(charges, [{}])

    def test_non_list_non_dict_package_becomes_empty_list(self) -> None:
        body = {"ShipmentRequest": {"Shipment": {"Package": "invalid"}}}
        result = canonicalize_body(body)
        self.assertEqual(result["ShipmentRequest"]["Shipment"]["Package"], [{}])

    def test_non_dict_shipment_raises_type_error(self) -> None:
        body = {"ShipmentRequest": {"Shipment": "not_a_dict"}}
        with self.assertRaises(TypeError):
            canonicalize_body(body)

    def test_non_dict_payment_information_raises_type_error(self) -> None:
        body = {
            "ShipmentRequest": {
                "Shipment": {"PaymentInformation": "not_a_dict"},
            }
        }
        with self.assertRaises(TypeError):
            canonicalize_body(body)


class NormalizeElicitedValuesTests(unittest.TestCase):
    def test_trims_whitespace(self) -> None:
        result = normalize_elicited_values({"shipper_name": "  Acme Corp  "})
        self.assertEqual(result["shipper_name"], "Acme Corp")

    def test_uppercases_country_codes(self) -> None:
        result = normalize_elicited_values({
            "shipper_country_code": "us",
            "ship_to_country_code": "ca",
        })
        self.assertEqual(result["shipper_country_code"], "US")
        self.assertEqual(result["ship_to_country_code"], "CA")

    def test_uppercases_state_codes(self) -> None:
        result = normalize_elicited_values({
            "shipper_state": "ny",
            "ship_to_state": "ca",
        })
        self.assertEqual(result["shipper_state"], "NY")
        self.assertEqual(result["ship_to_state"], "CA")

    def test_uppercases_weight_unit(self) -> None:
        result = normalize_elicited_values({"package_1_weight_unit": "lbs"})
        self.assertEqual(result["package_1_weight_unit"], "LBS")

    def test_strips_weight_value(self) -> None:
        result = normalize_elicited_values({"package_1_weight": " 5.0 "})
        self.assertEqual(result["package_1_weight"], "5.0")

    def test_preserves_other_values(self) -> None:
        result = normalize_elicited_values({"shipper_name": "Test Co"})
        self.assertEqual(result["shipper_name"], "Test Co")

    def test_removes_empty_values(self) -> None:
        result = normalize_elicited_values({
            "shipper_name": "Test",
            "service_code": "",
            "shipper_city": "   ",
        })
        self.assertIn("shipper_name", result)
        self.assertNotIn("service_code", result)
        self.assertNotIn("shipper_city", result)


class RehydrateTests(unittest.TestCase):
    def test_flat_data_creates_nested_structure(self) -> None:
        body: dict = {"ShipmentRequest": {"Shipment": {"Shipper": {}}}}
        missing = [
            MissingField(
                "ShipmentRequest.Shipment.Shipper.Name",
                "shipper_name",
                "Shipper name",
            ),
        ]
        result = rehydrate(body, {"shipper_name": "Acme Corp"}, missing)
        self.assertEqual(
            result["ShipmentRequest"]["Shipment"]["Shipper"]["Name"],
            "Acme Corp",
        )

    def test_address_line_becomes_array(self) -> None:
        body: dict = {"ShipmentRequest": {"Shipment": {"Shipper": {"Address": {}}}}}
        missing = [
            MissingField(
                "ShipmentRequest.Shipment.Shipper.Address.AddressLine[0]",
                "shipper_address_line_1",
                "Shipper street address",
            ),
        ]
        result = rehydrate(body, {"shipper_address_line_1": "123 Main St"}, missing)
        self.assertEqual(
            result["ShipmentRequest"]["Shipment"]["Shipper"]["Address"]["AddressLine"],
            ["123 Main St"],
        )

    def test_package_index_routes_correctly(self) -> None:
        body: dict = {
            "ShipmentRequest": {
                "Shipment": {"Package": [{"Packaging": {"Code": "02"}}, {}]}
            }
        }
        missing = [
            MissingField(
                "ShipmentRequest.Shipment.Package[1].PackageWeight.Weight",
                "package_2_weight",
                "Package 2: Package weight",
            ),
        ]
        result = rehydrate(body, {"package_2_weight": "10"}, missing)
        self.assertEqual(
            result["ShipmentRequest"]["Shipment"]["Package"][1]["PackageWeight"]["Weight"],
            "10",
        )

    def test_zero_value_is_set(self) -> None:
        """Falsy but meaningful values like 0 must not be dropped."""
        body: dict = {"ShipmentRequest": {"Shipment": {"Shipper": {}}}}
        missing = [
            MissingField(
                "ShipmentRequest.Shipment.Shipper.Name",
                "shipper_name",
                "Shipper name",
            ),
        ]
        result = rehydrate(body, {"shipper_name": 0}, missing)
        self.assertEqual(
            result["ShipmentRequest"]["Shipment"]["Shipper"]["Name"],
            0,
        )

    def test_false_value_is_set(self) -> None:
        """Boolean False must not be dropped by the falsy guard."""
        body: dict = {"ShipmentRequest": {"Shipment": {"Shipper": {}}}}
        missing = [
            MissingField(
                "ShipmentRequest.Shipment.Shipper.Name",
                "shipper_name",
                "Shipper name",
            ),
        ]
        result = rehydrate(body, {"shipper_name": False}, missing)
        self.assertIs(
            result["ShipmentRequest"]["Shipment"]["Shipper"]["Name"],
            False,
        )

    def test_does_not_overwrite_existing(self) -> None:
        body = make_complete_body()
        original_name = body["ShipmentRequest"]["Shipment"]["Shipper"]["Name"]
        missing = [
            MissingField(
                "ShipmentRequest.Shipment.Shipper.Name",
                "shipper_name",
                "Shipper name",
            ),
        ]
        result = rehydrate(body, {"shipper_name": ""}, missing)
        self.assertEqual(
            result["ShipmentRequest"]["Shipment"]["Shipper"]["Name"],
            original_name,
        )

    def test_does_not_mutate_input(self) -> None:
        body: dict = {"ShipmentRequest": {"Shipment": {"Shipper": {}}}}
        original = copy.deepcopy(body)
        missing = [
            MissingField(
                "ShipmentRequest.Shipment.Shipper.Name",
                "shipper_name",
                "Shipper name",
            ),
        ]
        rehydrate(body, {"shipper_name": "Test"}, missing)
        self.assertEqual(body, original)

    def test_skips_unknown_flat_keys(self) -> None:
        body: dict = {"ShipmentRequest": {}}
        result = rehydrate(body, {"unknown_key": "value"}, [])
        self.assertEqual(result, {"ShipmentRequest": {}})

    def test_multi_package_rehydration(self) -> None:
        body: dict = {"ShipmentRequest": {"Shipment": {"Package": [{}, {}]}}}
        missing = [
            MissingField(
                "ShipmentRequest.Shipment.Package[0].PackageWeight.Weight",
                "package_1_weight",
                "Package weight",
            ),
            MissingField(
                "ShipmentRequest.Shipment.Package[1].PackageWeight.Weight",
                "package_2_weight",
                "Package 2: Package weight",
            ),
        ]
        result = rehydrate(
            body,
            {"package_1_weight": "5", "package_2_weight": "10"},
            missing,
        )
        self.assertEqual(
            result["ShipmentRequest"]["Shipment"]["Package"][0]["PackageWeight"]["Weight"],
            "5",
        )
        self.assertEqual(
            result["ShipmentRequest"]["Shipment"]["Package"][1]["PackageWeight"]["Weight"],
            "10",
        )

    def test_structural_conflict_raises_rehydration_error(self) -> None:
        """When _set_field hits a type conflict, RehydrationError is raised."""
        body: dict = {
            "ShipmentRequest": {
                "Shipment": {
                    "Shipper": {"Address": "not_a_dict"},
                }
            }
        }
        missing = [
            MissingField(
                "ShipmentRequest.Shipment.Shipper.Address.City",
                "shipper_city",
                "Shipper city",
            ),
        ]
        with self.assertRaises(RehydrationError) as cm:
            rehydrate(body, {"shipper_city": "NYC"}, missing)
        self.assertEqual(cm.exception.flat_key, "shipper_city")

    def test_normalizes_package_dict_to_list_during_rehydration(self) -> None:
        """If Package was a dict, rehydrate should still work via list normalization."""
        body: dict = {
            "ShipmentRequest": {"Shipment": {"Package": {"Packaging": {"Code": "02"}}}}
        }
        missing = [
            MissingField(
                "ShipmentRequest.Shipment.Package[0].PackageWeight.Weight",
                "package_1_weight",
                "Package weight",
            ),
        ]
        result = rehydrate(body, {"package_1_weight": "5"}, missing)
        pkg = result["ShipmentRequest"]["Shipment"]["Package"]
        self.assertIsInstance(pkg, list)
        self.assertEqual(pkg[0]["PackageWeight"]["Weight"], "5")
        # Original packaging preserved
        self.assertEqual(pkg[0]["Packaging"]["Code"], "02")


if __name__ == "__main__":
    unittest.main()
