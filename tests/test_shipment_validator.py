import unittest

from ups_mcp.elicitation import MissingField, FieldRule
from ups_mcp.shipment_validator import (
    UNCONDITIONAL_RULES,
    PACKAGE_RULES,
    PAYMENT_CHARGE_TYPE_RULE,
    PAYMENT_PAYER_RULES,
    COUNTRY_CONDITIONAL_RULES,
    BUILT_IN_DEFAULTS,
    ENV_DEFAULTS,
    INTERNATIONAL_DESCRIPTION_RULE,
    INTERNATIONAL_SHIPPER_CONTACT_RULES,
    SHIP_TO_CONTACT_RULES,
    INVOICE_LINE_TOTAL_RULES,
    EU_COUNTRIES,
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

    def test_service_code_enum_includes_international(self) -> None:
        service_rule = [r for r in UNCONDITIONAL_RULES if r.flat_key == "service_code"][0]
        for code in ("07", "08", "11", "17", "54", "72", "74"):
            self.assertIn(code, service_rule.enum_values)

    def test_service_code_enum_titles_paired(self) -> None:
        service_rule = [r for r in UNCONDITIONAL_RULES if r.flat_key == "service_code"][0]
        self.assertEqual(len(service_rule.enum_values), len(service_rule.enum_titles))

    def test_service_code_no_default(self) -> None:
        service_rule = [r for r in UNCONDITIONAL_RULES if r.flat_key == "service_code"][0]
        self.assertIsNone(service_rule.default)


from ups_mcp.elicitation import _field_exists, _set_field


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


from ups_mcp.shipment_validator import find_missing_fields, AmbiguousPayerError


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


class FindMissingFieldsInternationalTests(unittest.TestCase):
    """International baseline validation: contacts, description, InvoiceLineTotal."""

    # --- Effective origin ---

    def test_ship_from_precedence(self) -> None:
        """ShipFrom=CA, Shipper=US, ShipTo=CA → domestic (CA→CA), no intl fields."""
        body = make_complete_body(shipper_country="US", ship_to_country="CA")
        body["ShipmentRequest"]["Shipment"]["ShipFrom"] = {
            "Address": {"CountryCode": "CA"},
        }
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertNotIn("shipper_attention_name", flat_keys)
        self.assertNotIn("shipment_description", flat_keys)

    def test_shipper_fallback(self) -> None:
        """No ShipFrom, Shipper=US, ShipTo=GB → international fields flagged."""
        body = make_complete_body(shipper_country="US", ship_to_country="GB")
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertIn("shipper_attention_name", flat_keys)

    def test_missing_country_skips_intl(self) -> None:
        """No ShipTo country → ship_to_country_code flagged, no intl rules."""
        body = make_complete_body(shipper_country="US")
        del body["ShipmentRequest"]["Shipment"]["ShipTo"]["Address"]["CountryCode"]
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertIn("ship_to_country_code", flat_keys)
        self.assertNotIn("shipper_attention_name", flat_keys)

    # --- Shipper contact rules ---

    def test_intl_flags_shipper_contacts(self) -> None:
        body = make_complete_body(shipper_country="US", ship_to_country="GB")
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertIn("shipper_attention_name", flat_keys)
        self.assertIn("shipper_phone", flat_keys)

    def test_domestic_skips_shipper_contacts(self) -> None:
        body = make_complete_body(shipper_country="US", ship_to_country="US")
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertNotIn("shipper_attention_name", flat_keys)
        self.assertNotIn("shipper_phone", flat_keys)

    # --- ShipTo contact rules ---

    def test_intl_flags_ship_to_contacts(self) -> None:
        body = make_complete_body(shipper_country="US", ship_to_country="GB")
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertIn("ship_to_attention_name", flat_keys)
        self.assertIn("ship_to_phone", flat_keys)

    def test_domestic_service_14_flags_ship_to_contacts(self) -> None:
        body = make_complete_body(shipper_country="US", ship_to_country="US")
        body["ShipmentRequest"]["Shipment"]["Service"]["Code"] = "14"
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertIn("ship_to_attention_name", flat_keys)
        self.assertIn("ship_to_phone", flat_keys)

    def test_domestic_non_14_skips_ship_to_contacts(self) -> None:
        body = make_complete_body(shipper_country="US", ship_to_country="US")
        body["ShipmentRequest"]["Shipment"]["Service"]["Code"] = "03"
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertNotIn("ship_to_attention_name", flat_keys)
        self.assertNotIn("ship_to_phone", flat_keys)

    def test_contacts_present_not_flagged(self) -> None:
        body = make_complete_body(shipper_country="US", ship_to_country="GB")
        body["ShipmentRequest"]["Shipment"]["Shipper"]["AttentionName"] = "John"
        body["ShipmentRequest"]["Shipment"]["Shipper"]["Phone"] = {"Number": "5551234567"}
        body["ShipmentRequest"]["Shipment"]["ShipTo"]["AttentionName"] = "Jane"
        body["ShipmentRequest"]["Shipment"]["ShipTo"]["Phone"] = {"Number": "4401234567"}
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertNotIn("shipper_attention_name", flat_keys)
        self.assertNotIn("shipper_phone", flat_keys)
        self.assertNotIn("ship_to_attention_name", flat_keys)
        self.assertNotIn("ship_to_phone", flat_keys)

    # --- Description ---

    def test_intl_missing_description(self) -> None:
        body = make_complete_body(shipper_country="US", ship_to_country="GB")
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertIn("shipment_description", flat_keys)

    def test_intl_with_description_passes(self) -> None:
        body = make_complete_body(shipper_country="US", ship_to_country="GB")
        body["ShipmentRequest"]["Shipment"]["Description"] = "Electronics"
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertNotIn("shipment_description", flat_keys)

    def test_domestic_no_description(self) -> None:
        body = make_complete_body(shipper_country="US", ship_to_country="US")
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertNotIn("shipment_description", flat_keys)

    def test_ups_letter_all_packages_exempts(self) -> None:
        body = make_complete_body(shipper_country="US", ship_to_country="GB")
        body["ShipmentRequest"]["Shipment"]["Package"] = [
            {"Packaging": {"Code": "01"}, "PackageWeight": {"UnitOfMeasurement": {"Code": "LBS"}, "Weight": "1"}},
        ]
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertNotIn("shipment_description", flat_keys)

    def test_mixed_packages_requires_description(self) -> None:
        body = make_complete_body(shipper_country="US", ship_to_country="GB")
        body["ShipmentRequest"]["Shipment"]["Package"] = [
            {"Packaging": {"Code": "01"}, "PackageWeight": {"UnitOfMeasurement": {"Code": "LBS"}, "Weight": "1"}},
            {"Packaging": {"Code": "02"}, "PackageWeight": {"UnitOfMeasurement": {"Code": "LBS"}, "Weight": "5"}},
        ]
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertIn("shipment_description", flat_keys)

    def test_eu_to_eu_standard_exempts(self) -> None:
        body = make_complete_body(shipper_country="DE", ship_to_country="FR")
        body["ShipmentRequest"]["Shipment"]["Service"]["Code"] = "11"
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertNotIn("shipment_description", flat_keys)

    def test_eu_to_eu_non_standard_requires(self) -> None:
        body = make_complete_body(shipper_country="DE", ship_to_country="FR")
        body["ShipmentRequest"]["Shipment"]["Service"]["Code"] = "07"
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertIn("shipment_description", flat_keys)

    # --- InvoiceLineTotal ---

    def test_us_to_ca_requires_invoice(self) -> None:
        body = make_complete_body(shipper_country="US", ship_to_country="CA")
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertIn("invoice_currency_code", flat_keys)
        self.assertIn("invoice_monetary_value", flat_keys)

    def test_us_to_pr_requires_invoice(self) -> None:
        body = make_complete_body(shipper_country="US", ship_to_country="PR")
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertIn("invoice_currency_code", flat_keys)
        self.assertIn("invoice_monetary_value", flat_keys)

    def test_us_to_gb_no_invoice(self) -> None:
        body = make_complete_body(shipper_country="US", ship_to_country="GB")
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertNotIn("invoice_currency_code", flat_keys)
        self.assertNotIn("invoice_monetary_value", flat_keys)

    def test_return_us_to_ca_no_invoice(self) -> None:
        body = make_complete_body(shipper_country="US", ship_to_country="CA")
        body["ShipmentRequest"]["Shipment"]["ReturnService"] = {"Code": "8"}
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertNotIn("invoice_currency_code", flat_keys)
        self.assertNotIn("invoice_monetary_value", flat_keys)

    def test_malformed_return_service_treated_as_forward(self) -> None:
        """Non-dict ReturnService = forward shipment, invoice required."""
        body = make_complete_body(shipper_country="US", ship_to_country="CA")
        body["ShipmentRequest"]["Shipment"]["ReturnService"] = "malformed"
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertIn("invoice_currency_code", flat_keys)

    def test_empty_dict_return_service_treated_as_forward(self) -> None:
        """Empty dict ReturnService (no Code) = forward shipment, invoice required."""
        body = make_complete_body(shipper_country="US", ship_to_country="CA")
        body["ShipmentRequest"]["Shipment"]["ReturnService"] = {}
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertIn("invoice_currency_code", flat_keys)

    def test_return_service_none_treated_as_forward(self) -> None:
        """ReturnService: None = forward shipment, invoice required."""
        body = make_complete_body(shipper_country="US", ship_to_country="CA")
        body["ShipmentRequest"]["Shipment"]["ReturnService"] = None
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertIn("invoice_currency_code", flat_keys)
        self.assertIn("invoice_monetary_value", flat_keys)

    # --- Metadata ---

    def test_description_max_length(self) -> None:
        self.assertIn(("maxLength", 50), INTERNATIONAL_DESCRIPTION_RULE.constraints)

    def test_invoice_currency_pattern(self) -> None:
        rule = INVOICE_LINE_TOTAL_RULES[0]
        self.assertIn(("pattern", "^[A-Z]{3}$"), rule.constraints)

    def test_invoice_monetary_value_pattern(self) -> None:
        rule = INVOICE_LINE_TOTAL_RULES[1]
        self.assertIn(("pattern", r"^\d+(\.\d{1,2})?$"), rule.constraints)
        self.assertIn(("maxLength", 11), rule.constraints)

    def test_phone_max_length(self) -> None:
        for rules in (INTERNATIONAL_SHIPPER_CONTACT_RULES, SHIP_TO_CONTACT_RULES):
            phone_rule = [r for r in rules if "phone" in r.flat_key][0]
            self.assertIn(("maxLength", 15), phone_rule.constraints)


from ups_mcp.elicitation import _missing_from_rule, build_elicitation_schema
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
        self.assertIsNone(service[0].default)

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


from ups_mcp.elicitation import validate_elicited_values


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

    def test_international_service_code_validates(self) -> None:
        """International service code '07' passes enum validation."""
        service_rule = [r for r in UNCONDITIONAL_RULES if r.flat_key == "service_code"][0]
        missing = [MissingField(
            service_rule.dot_path, service_rule.flat_key, service_rule.prompt,
            enum_values=service_rule.enum_values,
        )]
        errors = validate_elicited_values({"service_code": "07"}, missing)
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


from ups_mcp.elicitation import normalize_elicited_values, rehydrate, RehydrationError
from ups_mcp.shipment_validator import canonicalize_body


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
        """If Package was a dict, callers should canonicalize before rehydrating.

        rehydrate() is generic and does not canonicalize internally.
        This test verifies the canonical-then-rehydrate workflow.
        """
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
        canonical = canonicalize_body(body)
        result = rehydrate(canonical, {"package_1_weight": "5"}, missing)
        pkg = result["ShipmentRequest"]["Shipment"]["Package"]
        self.assertIsInstance(pkg, list)
        self.assertEqual(pkg[0]["PackageWeight"]["Weight"], "5")
        # Original packaging preserved
        self.assertEqual(pkg[0]["Packaging"]["Code"], "02")


class FindMissingFieldsInternationalFormsTests(unittest.TestCase):
    """InternationalForms validation tests for international shipments."""

    # --- InternationalForms presence check ---

    def test_intl_no_forms_flagged(self) -> None:
        """International US→GB without InternationalForms → intl_forms_required flagged."""
        body = make_complete_body(shipper_country="US", ship_to_country="GB")
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertIn("intl_forms_required", flat_keys)

    def test_domestic_no_forms_not_flagged(self) -> None:
        """Domestic US→US → intl_forms_required NOT flagged."""
        body = make_complete_body(shipper_country="US", ship_to_country="US")
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertNotIn("intl_forms_required", flat_keys)

    def test_ups_letter_exempts_forms(self) -> None:
        """International US→GB with all UPS Letter packages → intl_forms_required NOT flagged."""
        body = make_complete_body(shipper_country="US", ship_to_country="GB")
        body["ShipmentRequest"]["Shipment"]["Package"] = [
            {"Packaging": {"Code": "01"}, "PackageWeight": {"UnitOfMeasurement": {"Code": "LBS"}, "Weight": "1"}},
        ]
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertNotIn("intl_forms_required", flat_keys)

    def test_eu_to_eu_standard_exempts_forms(self) -> None:
        """DE→FR with service '11' → intl_forms_required NOT flagged."""
        body = make_complete_body(shipper_country="DE", ship_to_country="FR")
        body["ShipmentRequest"]["Shipment"]["Service"]["Code"] = "11"
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertNotIn("intl_forms_required", flat_keys)

    def test_intl_complete_forms_not_flagged(self) -> None:
        """include_international=True with US→GB → no intl forms fields flagged."""
        body = make_complete_body(shipper_country="US", ship_to_country="GB", include_international=True)
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertNotIn("intl_forms_required", flat_keys)
        self.assertNotIn("intl_forms_form_type", flat_keys)
        self.assertNotIn("product_1_description", flat_keys)
        self.assertNotIn("intl_forms_currency_code", flat_keys)
        self.assertNotIn("intl_forms_reason_for_export", flat_keys)
        self.assertNotIn("intl_forms_invoice_number", flat_keys)
        self.assertNotIn("intl_forms_invoice_date", flat_keys)

    # --- FormType validation ---

    def test_form_type_missing_flagged(self) -> None:
        """InternationalForms present but no FormType → intl_forms_form_type flagged."""
        body = make_complete_body(shipper_country="US", ship_to_country="GB")
        body["ShipmentRequest"]["Shipment"]["ShipmentServiceOptions"] = {
            "InternationalForms": {}
        }
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertIn("intl_forms_form_type", flat_keys)

    def test_form_type_present_not_flagged(self) -> None:
        """InternationalForms with FormType '01' → intl_forms_form_type NOT flagged."""
        body = make_complete_body(shipper_country="US", ship_to_country="GB", include_international=True)
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertNotIn("intl_forms_form_type", flat_keys)

    # --- Product[] validation ---

    def test_product_missing_for_invoice_generates_indexed_fields(self) -> None:
        """FormType '01' without Product → product_1_* indexed fields generated."""
        body = make_complete_body(shipper_country="US", ship_to_country="GB", include_international=True)
        del body["ShipmentRequest"]["Shipment"]["ShipmentServiceOptions"]["InternationalForms"]["Product"]
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertIn("product_1_description", flat_keys)
        self.assertIn("product_1_value", flat_keys)

    def test_product_present_not_flagged(self) -> None:
        """FormType '01' with complete Product → no product_1_* fields generated."""
        body = make_complete_body(shipper_country="US", ship_to_country="GB", include_international=True)
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertNotIn("product_1_description", flat_keys)

    def test_product_not_required_for_cn22(self) -> None:
        """FormType '09' (CN22) without Product → no product_1_* fields generated."""
        body = make_complete_body(shipper_country="US", ship_to_country="GB")
        body["ShipmentRequest"]["Shipment"]["ShipmentServiceOptions"] = {
            "InternationalForms": {"FormType": "09"}
        }
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertNotIn("product_1_description", flat_keys)

    # --- CurrencyCode validation ---

    def test_currency_required_for_invoice(self) -> None:
        """FormType '01' without CurrencyCode → intl_forms_currency_code flagged."""
        body = make_complete_body(shipper_country="US", ship_to_country="GB", include_international=True)
        del body["ShipmentRequest"]["Shipment"]["ShipmentServiceOptions"]["InternationalForms"]["CurrencyCode"]
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertIn("intl_forms_currency_code", flat_keys)

    def test_currency_required_for_partial_invoice(self) -> None:
        """FormType '05' without CurrencyCode → intl_forms_currency_code flagged."""
        body = make_complete_body(shipper_country="US", ship_to_country="GB")
        body["ShipmentRequest"]["Shipment"]["ShipmentServiceOptions"] = {
            "InternationalForms": {
                "FormType": "05",
                "Product": [{"Description": "Test", "Unit": {"Number": "1", "Value": "10", "UnitOfMeasurement": {"Code": "PCS"}}, "OriginCountryCode": "US"}],
            }
        }
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertIn("intl_forms_currency_code", flat_keys)

    def test_currency_not_required_for_co(self) -> None:
        """FormType '03' without CurrencyCode → intl_forms_currency_code NOT flagged."""
        body = make_complete_body(shipper_country="US", ship_to_country="GB")
        body["ShipmentRequest"]["Shipment"]["ShipmentServiceOptions"] = {
            "InternationalForms": {"FormType": "03"}
        }
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertNotIn("intl_forms_currency_code", flat_keys)

    # --- ReasonForExport validation ---

    def test_reason_for_export_required_for_invoice(self) -> None:
        """FormType '01' without ReasonForExport → intl_forms_reason_for_export flagged."""
        body = make_complete_body(shipper_country="US", ship_to_country="GB", include_international=True)
        del body["ShipmentRequest"]["Shipment"]["ShipmentServiceOptions"]["InternationalForms"]["ReasonForExport"]
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertIn("intl_forms_reason_for_export", flat_keys)

    def test_reason_not_required_for_non_invoice(self) -> None:
        """FormType '03' without ReasonForExport → intl_forms_reason_for_export NOT flagged."""
        body = make_complete_body(shipper_country="US", ship_to_country="GB")
        body["ShipmentRequest"]["Shipment"]["ShipmentServiceOptions"] = {
            "InternationalForms": {"FormType": "03"}
        }
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertNotIn("intl_forms_reason_for_export", flat_keys)

    # --- InvoiceNumber / InvoiceDate validation ---

    def test_invoice_number_required_for_invoice(self) -> None:
        """FormType '01' without InvoiceNumber → intl_forms_invoice_number flagged."""
        body = make_complete_body(shipper_country="US", ship_to_country="GB", include_international=True)
        del body["ShipmentRequest"]["Shipment"]["ShipmentServiceOptions"]["InternationalForms"]["InvoiceNumber"]
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertIn("intl_forms_invoice_number", flat_keys)

    def test_invoice_date_required_for_invoice(self) -> None:
        """FormType '01' without InvoiceDate → intl_forms_invoice_date flagged."""
        body = make_complete_body(shipper_country="US", ship_to_country="GB", include_international=True)
        del body["ShipmentRequest"]["Shipment"]["ShipmentServiceOptions"]["InternationalForms"]["InvoiceDate"]
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertIn("intl_forms_invoice_date", flat_keys)

    def test_invoice_date_not_required_for_return(self) -> None:
        """FormType '01' + ReturnService present → intl_forms_invoice_date NOT flagged."""
        body = make_complete_body(shipper_country="US", ship_to_country="GB", include_international=True)
        body["ShipmentRequest"]["Shipment"]["ReturnService"] = {"Code": "8"}
        del body["ShipmentRequest"]["Shipment"]["ShipmentServiceOptions"]["InternationalForms"]["InvoiceDate"]
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertNotIn("intl_forms_invoice_date", flat_keys)

    # --- Duties payment validation ---

    def test_duties_charge_missing_payer_flagged(self) -> None:
        """Second ShipmentCharge Type '02' without payer → duties_payer_required flagged."""
        body = make_complete_body(shipper_country="US", ship_to_country="GB", include_international=True)
        body["ShipmentRequest"]["Shipment"]["PaymentInformation"]["ShipmentCharge"].append({
            "Type": "02",
        })
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertIn("duties_payer_required", flat_keys)

    def test_duties_charge_with_payer_not_flagged(self) -> None:
        """Second ShipmentCharge Type '02' with BillReceiver → duties_payer_required NOT flagged."""
        body = make_complete_body(shipper_country="US", ship_to_country="GB", include_international=True)
        body["ShipmentRequest"]["Shipment"]["PaymentInformation"]["ShipmentCharge"].append({
            "Type": "02",
            "BillReceiver": {"AccountNumber": "RCV456"},
        })
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertNotIn("duties_payer_required", flat_keys)

    def test_no_false_positives_domestic(self) -> None:
        """Complete domestic body returns zero missing fields (no intl fields leak)."""
        body = make_complete_body(shipper_country="US", ship_to_country="US")
        missing = find_missing_fields(body)
        self.assertEqual(missing, [])


class ReturnServiceCheckTests(unittest.TestCase):
    """ReturnService must be a dict with a non-empty Code to be treated as a return."""

    def _make_us_to_ca_body(self, return_service=None) -> dict:
        """Build a minimal US->CA body to trigger InvoiceLineTotal check."""
        body = {
            "ShipmentRequest": {
                "Request": {"RequestOption": "nonvalidate"},
                "Shipment": {
                    "Shipper": {
                        "Name": "Test",
                        "ShipperNumber": "129D9Y",
                        "Address": {"AddressLine": ["123 Main"], "City": "New York",
                                    "StateProvinceCode": "NY", "PostalCode": "10001",
                                    "CountryCode": "US"},
                        "AttentionName": "Attn", "Phone": {"Number": "1234567890"},
                    },
                    "ShipTo": {
                        "Name": "Recip",
                        "Address": {"AddressLine": ["456 Elm"], "City": "Toronto",
                                    "StateProvinceCode": "ON", "PostalCode": "M5V 2T6",
                                    "CountryCode": "CA"},
                        "AttentionName": "Recip Attn", "Phone": {"Number": "9876543210"},
                    },
                    "Service": {"Code": "07"},
                    "Description": "Test goods",
                    "Package": [{"Packaging": {"Code": "02"},
                                 "PackageWeight": {"UnitOfMeasurement": {"Code": "LBS"},
                                                   "Weight": "5"}}],
                    "PaymentInformation": {
                        "ShipmentCharge": [{"Type": "01",
                                            "BillShipper": {"AccountNumber": "129D9Y"}}],
                    },
                    "ShipmentServiceOptions": {
                        "InternationalForms": {
                            "FormType": "01", "CurrencyCode": "USD",
                            "ReasonForExport": "SALE", "InvoiceNumber": "INV-1",
                            "InvoiceDate": "20260219",
                            "Product": [{"Description": "Widget",
                                         "Unit": {"Number": "1", "Value": "100",
                                                  "UnitOfMeasurement": {"Code": "PCS"}},
                                         "OriginCountryCode": "US"}],
                        },
                    },
                },
            },
        }
        if return_service is not None:
            body["ShipmentRequest"]["Shipment"]["ReturnService"] = return_service
        return body

    def test_valid_return_service_suppresses_invoice_line_total(self) -> None:
        body = self._make_us_to_ca_body(return_service={"Code": "8"})
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertNotIn("invoice_currency_code", flat_keys)
        self.assertNotIn("invoice_monetary_value", flat_keys)

    def test_empty_string_return_service_requires_invoice(self) -> None:
        body = self._make_us_to_ca_body(return_service="")
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertIn("invoice_currency_code", flat_keys)

    def test_empty_dict_return_service_requires_invoice(self) -> None:
        body = self._make_us_to_ca_body(return_service={})
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertIn("invoice_currency_code", flat_keys)

    def test_dict_with_empty_code_requires_invoice(self) -> None:
        body = self._make_us_to_ca_body(return_service={"Code": ""})
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertIn("invoice_currency_code", flat_keys)

    def test_no_return_service_requires_invoice(self) -> None:
        body = self._make_us_to_ca_body(return_service=None)
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertIn("invoice_currency_code", flat_keys)


from ups_mcp.shipment_validator import PRODUCT_ITEM_RULES, PRODUCT_ARRAY_RULE
from ups_mcp.elicitation import ArrayFieldRule


class ProductArrayRuleTests(unittest.TestCase):
    """Product array should generate elicitable indexed fields instead of
    a structural STRUCTURAL_FIELDS_REQUIRED error."""

    def test_product_array_rule_exists(self) -> None:
        self.assertIsInstance(PRODUCT_ARRAY_RULE, ArrayFieldRule)
        self.assertEqual(PRODUCT_ARRAY_RULE.item_prefix, "product")

    def test_product_item_rules_has_required_fields(self) -> None:
        flat_keys = {r.flat_key for r in PRODUCT_ITEM_RULES}
        self.assertIn("description", flat_keys)
        self.assertIn("quantity", flat_keys)
        self.assertIn("value", flat_keys)
        self.assertIn("unit_code", flat_keys)
        self.assertIn("origin_country", flat_keys)

    def test_international_missing_product_generates_indexed_fields(self) -> None:
        """When InternationalForms has no Product, generate product_1_* fields."""
        body = {
            "ShipmentRequest": {
                "Request": {"RequestOption": "nonvalidate"},
                "Shipment": {
                    "Shipper": {
                        "Name": "Test", "ShipperNumber": "129D9Y",
                        "Address": {"AddressLine": ["123 Main"], "City": "NYC",
                                    "StateProvinceCode": "NY", "PostalCode": "10001",
                                    "CountryCode": "US"},
                        "AttentionName": "Attn", "Phone": {"Number": "1234567890"},
                    },
                    "ShipTo": {
                        "Name": "Recip",
                        "Address": {"AddressLine": ["456 Elm"], "City": "London",
                                    "CountryCode": "GB"},
                        "AttentionName": "Recip", "Phone": {"Number": "4412345678"},
                    },
                    "Service": {"Code": "07"},
                    "Description": "Test goods",
                    "Package": [{"Packaging": {"Code": "02"},
                                 "PackageWeight": {"UnitOfMeasurement": {"Code": "LBS"},
                                                   "Weight": "5"}}],
                    "PaymentInformation": {
                        "ShipmentCharge": [{"Type": "01",
                                            "BillShipper": {"AccountNumber": "129D9Y"}}],
                    },
                    "ShipmentServiceOptions": {
                        "InternationalForms": {
                            "FormType": "01", "CurrencyCode": "USD",
                            "ReasonForExport": "SALE", "InvoiceNumber": "INV-1",
                            "InvoiceDate": "20260219",
                            # Product is missing!
                        },
                    },
                },
            },
        }
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        # Should have product_1_* indexed fields, NOT intl_forms_product_required
        self.assertNotIn("intl_forms_product_required", flat_keys)
        self.assertIn("product_1_description", flat_keys)
        self.assertIn("product_1_value", flat_keys)
        self.assertIn("product_1_origin_country", flat_keys)
        # All should be elicitable
        product_fields = [mf for mf in missing if mf.flat_key.startswith("product_")]
        for mf in product_fields:
            self.assertTrue(mf.elicitable, f"{mf.flat_key} should be elicitable")

    def test_existing_product_only_elicits_missing_subfields(self) -> None:
        """When Product[0] has Description, only elicit the missing sub-fields."""
        body = {
            "ShipmentRequest": {
                "Request": {"RequestOption": "nonvalidate"},
                "Shipment": {
                    "Shipper": {
                        "Name": "Test", "ShipperNumber": "129D9Y",
                        "Address": {"AddressLine": ["123 Main"], "City": "NYC",
                                    "StateProvinceCode": "NY", "PostalCode": "10001",
                                    "CountryCode": "US"},
                        "AttentionName": "Attn", "Phone": {"Number": "1234567890"},
                    },
                    "ShipTo": {
                        "Name": "Recip",
                        "Address": {"AddressLine": ["456 Elm"], "City": "London",
                                    "CountryCode": "GB"},
                        "AttentionName": "Recip", "Phone": {"Number": "4412345678"},
                    },
                    "Service": {"Code": "07"},
                    "Description": "Test goods",
                    "Package": [{"Packaging": {"Code": "02"},
                                 "PackageWeight": {"UnitOfMeasurement": {"Code": "LBS"},
                                                   "Weight": "5"}}],
                    "PaymentInformation": {
                        "ShipmentCharge": [{"Type": "01",
                                            "BillShipper": {"AccountNumber": "129D9Y"}}],
                    },
                    "ShipmentServiceOptions": {
                        "InternationalForms": {
                            "FormType": "01", "CurrencyCode": "USD",
                            "ReasonForExport": "SALE", "InvoiceNumber": "INV-1",
                            "InvoiceDate": "20260219",
                            "Product": [{"Description": "Widget",
                                         "OriginCountryCode": "US"}],
                        },
                    },
                },
            },
        }
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        # Description and OriginCountryCode are present — should NOT be missing
        self.assertNotIn("product_1_description", flat_keys)
        self.assertNotIn("product_1_origin_country", flat_keys)
        # Unit.Number, Unit.Value, Unit.UnitOfMeasurement.Code ARE missing
        self.assertIn("product_1_quantity", flat_keys)
        self.assertIn("product_1_value", flat_keys)
        self.assertIn("product_1_unit_code", flat_keys)


class SoldToRuleTests(unittest.TestCase):
    """SoldTo (invoice recipient) should be required for Invoice/USMCA forms."""

    def _make_intl_body(self, form_type: str, sold_to: dict | None = None) -> dict:
        """Build US->GB body with InternationalForms and optional SoldTo."""
        body = {
            "ShipmentRequest": {
                "Request": {"RequestOption": "nonvalidate"},
                "Shipment": {
                    "Shipper": {
                        "Name": "Test", "ShipperNumber": "129D9Y",
                        "Address": {"AddressLine": ["123 Main"], "City": "NYC",
                                    "StateProvinceCode": "NY", "PostalCode": "10001",
                                    "CountryCode": "US"},
                        "AttentionName": "Attn", "Phone": {"Number": "1234567890"},
                    },
                    "ShipTo": {
                        "Name": "Recip",
                        "Address": {"AddressLine": ["456 Elm"], "City": "London",
                                    "CountryCode": "GB"},
                        "AttentionName": "Recip", "Phone": {"Number": "4412345678"},
                    },
                    "Service": {"Code": "07"}, "Description": "Test goods",
                    "Package": [{"Packaging": {"Code": "02"},
                                 "PackageWeight": {"UnitOfMeasurement": {"Code": "LBS"},
                                                   "Weight": "5"}}],
                    "PaymentInformation": {
                        "ShipmentCharge": [{"Type": "01",
                                            "BillShipper": {"AccountNumber": "129D9Y"}}],
                    },
                    "ShipmentServiceOptions": {
                        "InternationalForms": {
                            "FormType": form_type, "CurrencyCode": "USD",
                            "ReasonForExport": "SALE", "InvoiceNumber": "INV-1",
                            "InvoiceDate": "20260219",
                            "Product": [{"Description": "Widget",
                                         "Unit": {"Number": "1", "Value": "100",
                                                  "UnitOfMeasurement": {"Code": "PCS"}},
                                         "OriginCountryCode": "US"}],
                        },
                    },
                },
            },
        }
        if sold_to is not None:
            body["ShipmentRequest"]["Shipment"]["ShipmentServiceOptions"][
                "InternationalForms"].setdefault("Contacts", {})["SoldTo"] = sold_to
        return body

    def test_invoice_form_requires_sold_to(self) -> None:
        body = self._make_intl_body("01")
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertIn("sold_to_name", flat_keys)
        self.assertIn("sold_to_address_line", flat_keys)
        self.assertIn("sold_to_city", flat_keys)
        self.assertIn("sold_to_country_code", flat_keys)

    def test_usmca_form_requires_sold_to(self) -> None:
        body = self._make_intl_body("04")
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertIn("sold_to_name", flat_keys)

    def test_packing_list_does_not_require_sold_to(self) -> None:
        body = self._make_intl_body("06")
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertNotIn("sold_to_name", flat_keys)

    def test_populated_sold_to_not_missing(self) -> None:
        sold_to = {
            "Name": "Buyer Co", "AttentionName": "Jane",
            "Phone": {"Number": "5551234567"},
            "Address": {"AddressLine": "789 Oak", "City": "London",
                        "CountryCode": "GB"},
        }
        body = self._make_intl_body("01", sold_to=sold_to)
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertNotIn("sold_to_name", flat_keys)
        self.assertNotIn("sold_to_city", flat_keys)

    def test_partial_sold_to_elicits_missing_subfields(self) -> None:
        sold_to = {"Name": "Buyer Co"}  # Address fields missing
        body = self._make_intl_body("01", sold_to=sold_to)
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertNotIn("sold_to_name", flat_keys)
        self.assertIn("sold_to_address_line", flat_keys)
        self.assertIn("sold_to_city", flat_keys)

    def test_sold_to_fields_are_elicitable(self) -> None:
        body = self._make_intl_body("01")
        missing = find_missing_fields(body)
        sold_to_fields = [mf for mf in missing if mf.flat_key.startswith("sold_to_")]
        for mf in sold_to_fields:
            self.assertTrue(mf.elicitable, f"{mf.flat_key} should be elicitable")


class EEIFilingRuleTests(unittest.TestCase):
    """EEI filing option should be required for form type 11 (EEI)."""

    def _make_eei_body(self, eei_option: dict | None = None) -> dict:
        """Build US->GB body with FormType 11 and optional EEIFilingOption."""
        body = {
            "ShipmentRequest": {
                "Request": {"RequestOption": "nonvalidate"},
                "Shipment": {
                    "Shipper": {
                        "Name": "Test", "ShipperNumber": "129D9Y",
                        "Address": {"AddressLine": ["123 Main"], "City": "NYC",
                                    "StateProvinceCode": "NY", "PostalCode": "10001",
                                    "CountryCode": "US"},
                        "AttentionName": "Attn", "Phone": {"Number": "1234567890"},
                    },
                    "ShipTo": {
                        "Name": "Recip",
                        "Address": {"AddressLine": ["456 Elm"], "City": "London",
                                    "CountryCode": "GB"},
                        "AttentionName": "Recip", "Phone": {"Number": "4412345678"},
                    },
                    "Service": {"Code": "07"}, "Description": "Test goods",
                    "Package": [{"Packaging": {"Code": "02"},
                                 "PackageWeight": {"UnitOfMeasurement": {"Code": "LBS"},
                                                   "Weight": "5"}}],
                    "PaymentInformation": {
                        "ShipmentCharge": [{"Type": "01",
                                            "BillShipper": {"AccountNumber": "129D9Y"}}],
                    },
                    "ShipmentServiceOptions": {
                        "InternationalForms": {
                            "FormType": "11", "CurrencyCode": "USD",
                            "Product": [{"Description": "Widget",
                                         "Unit": {"Number": "1", "Value": "100",
                                                  "UnitOfMeasurement": {"Code": "PCS"}},
                                         "OriginCountryCode": "US"}],
                        },
                    },
                },
            },
        }
        if eei_option is not None:
            body["ShipmentRequest"]["Shipment"]["ShipmentServiceOptions"][
                "InternationalForms"]["EEIFilingOption"] = eei_option
        return body

    def test_eei_form_requires_filing_code(self) -> None:
        body = self._make_eei_body()
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertIn("eei_filing_code", flat_keys)

    def test_eei_form_with_code_not_missing(self) -> None:
        body = self._make_eei_body(eei_option={"Code": "3"})
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertNotIn("eei_filing_code", flat_keys)

    def test_eei_form_with_empty_code_missing(self) -> None:
        body = self._make_eei_body(eei_option={"Code": ""})
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertIn("eei_filing_code", flat_keys)

    def test_eei_form_with_empty_dict_missing(self) -> None:
        body = self._make_eei_body(eei_option={})
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertIn("eei_filing_code", flat_keys)

    def test_non_eei_form_does_not_require_filing(self) -> None:
        body = self._make_eei_body()
        body["ShipmentRequest"]["Shipment"]["ShipmentServiceOptions"][
            "InternationalForms"]["FormType"] = "01"
        body["ShipmentRequest"]["Shipment"]["ShipmentServiceOptions"][
            "InternationalForms"]["ReasonForExport"] = "SALE"
        body["ShipmentRequest"]["Shipment"]["ShipmentServiceOptions"][
            "InternationalForms"]["InvoiceNumber"] = "INV-1"
        body["ShipmentRequest"]["Shipment"]["ShipmentServiceOptions"][
            "InternationalForms"]["InvoiceDate"] = "20260219"
        missing = find_missing_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertNotIn("eei_filing_code", flat_keys)

    def test_eei_filing_code_is_elicitable(self) -> None:
        body = self._make_eei_body()
        missing = find_missing_fields(body)
        eei_fields = [mf for mf in missing if mf.flat_key == "eei_filing_code"]
        self.assertEqual(len(eei_fields), 1)
        self.assertTrue(eei_fields[0].elicitable)


if __name__ == "__main__":
    unittest.main()
