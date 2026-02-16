"""Tests for the rating validator module."""

import copy
import unittest

from ups_mcp.rating_validator import (
    RATE_UNCONDITIONAL_RULES,
    RATE_SERVICE_CODE_RULE,
    RATE_PAYMENT_CHARGE_TYPE_RULE,
    RATE_PAYMENT_PAYER_RULES,
    RATE_BUILT_IN_DEFAULTS,
    RATE_ENV_DEFAULTS,
    find_missing_rate_fields,
    apply_rate_defaults,
    canonicalize_rate_body,
)
from ups_mcp.shipment_validator import AmbiguousPayerError
from ups_mcp.elicitation import FieldRule, MissingField

from tests.rating_fixtures import make_complete_rate_body


# ---------------------------------------------------------------------------
# Data structure tests
# ---------------------------------------------------------------------------

class RateDataStructureTests(unittest.TestCase):
    def test_unconditional_rules_is_nonempty_list(self) -> None:
        self.assertIsInstance(RATE_UNCONDITIONAL_RULES, list)
        self.assertGreater(len(RATE_UNCONDITIONAL_RULES), 0)

    def test_all_rules_use_rate_request_prefix(self) -> None:
        for rule in RATE_UNCONDITIONAL_RULES:
            self.assertTrue(rule.dot_path.startswith("RateRequest."), rule.dot_path)

    def test_service_code_rule_uses_rate_prefix(self) -> None:
        self.assertTrue(RATE_SERVICE_CODE_RULE.dot_path.startswith("RateRequest."))

    def test_payment_rules_use_rate_prefix(self) -> None:
        self.assertTrue(RATE_PAYMENT_CHARGE_TYPE_RULE.dot_path.startswith("RateRequest."))
        for rule in RATE_PAYMENT_PAYER_RULES.values():
            self.assertTrue(rule.dot_path.startswith("RateRequest."), rule.dot_path)

    def test_service_code_has_enum_values(self) -> None:
        self.assertIsNotNone(RATE_SERVICE_CODE_RULE.enum_values)
        self.assertIn("03", RATE_SERVICE_CODE_RULE.enum_values)

    def test_service_code_enum_titles_paired(self) -> None:
        self.assertEqual(
            len(RATE_SERVICE_CODE_RULE.enum_values),
            len(RATE_SERVICE_CODE_RULE.enum_titles),
        )


# ---------------------------------------------------------------------------
# find_missing_rate_fields tests
# ---------------------------------------------------------------------------

class FindMissingRateFieldsTests(unittest.TestCase):
    def test_complete_body_returns_empty(self) -> None:
        body = make_complete_rate_body()
        missing = find_missing_rate_fields(body)
        self.assertEqual(missing, [])

    def test_empty_body_returns_many_fields(self) -> None:
        missing = find_missing_rate_fields({})
        flat_keys = {mf.flat_key for mf in missing}
        self.assertIn("shipper_name", flat_keys)
        self.assertIn("shipper_number", flat_keys)
        self.assertIn("shipper_address_line_1", flat_keys)
        self.assertIn("shipper_city", flat_keys)
        self.assertIn("shipper_country_code", flat_keys)
        self.assertIn("ship_to_name", flat_keys)
        self.assertIn("ship_to_address_line_1", flat_keys)
        self.assertIn("ship_to_city", flat_keys)
        self.assertIn("ship_to_country_code", flat_keys)
        self.assertIn("service_code", flat_keys)
        self.assertIn("payment_charge_type", flat_keys)
        self.assertIn("payment_account_number", flat_keys)
        self.assertIn("package_1_packaging_code", flat_keys)
        self.assertIn("package_1_weight_unit", flat_keys)
        self.assertIn("package_1_weight", flat_keys)

    def test_missing_shipper_name_detected(self) -> None:
        body = make_complete_rate_body()
        del body["RateRequest"]["Shipment"]["Shipper"]["Name"]
        missing = find_missing_rate_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertIn("shipper_name", flat_keys)

    def test_missing_ship_to_address_detected(self) -> None:
        body = make_complete_rate_body()
        del body["RateRequest"]["Shipment"]["ShipTo"]["Address"]["AddressLine"]
        missing = find_missing_rate_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertIn("ship_to_address_line_1", flat_keys)

    def test_dot_paths_use_rate_request_prefix(self) -> None:
        body = make_complete_rate_body()
        del body["RateRequest"]["Shipment"]["Shipper"]["Name"]
        missing = find_missing_rate_fields(body)
        shipper_name = [mf for mf in missing if mf.flat_key == "shipper_name"]
        self.assertEqual(len(shipper_name), 1)
        self.assertTrue(shipper_name[0].dot_path.startswith("RateRequest."))


# ---------------------------------------------------------------------------
# Service.Code conditional on requestoption
# ---------------------------------------------------------------------------

class ServiceCodeConditionalTests(unittest.TestCase):
    def test_rate_mode_requires_service_code(self) -> None:
        body = make_complete_rate_body()
        del body["RateRequest"]["Shipment"]["Service"]
        missing = find_missing_rate_fields(body, request_option="Rate")
        flat_keys = {mf.flat_key for mf in missing}
        self.assertIn("service_code", flat_keys)

    def test_ratetimeintransit_requires_service_code(self) -> None:
        body = make_complete_rate_body()
        del body["RateRequest"]["Shipment"]["Service"]
        missing = find_missing_rate_fields(body, request_option="Ratetimeintransit")
        flat_keys = {mf.flat_key for mf in missing}
        self.assertIn("service_code", flat_keys)

    def test_shop_mode_skips_service_code(self) -> None:
        body = make_complete_rate_body()
        del body["RateRequest"]["Shipment"]["Service"]
        missing = find_missing_rate_fields(body, request_option="Shop")
        flat_keys = {mf.flat_key for mf in missing}
        self.assertNotIn("service_code", flat_keys)

    def test_shoptimeintransit_skips_service_code(self) -> None:
        body = make_complete_rate_body()
        del body["RateRequest"]["Shipment"]["Service"]
        missing = find_missing_rate_fields(body, request_option="Shoptimeintransit")
        flat_keys = {mf.flat_key for mf in missing}
        self.assertNotIn("service_code", flat_keys)

    def test_shop_case_insensitive(self) -> None:
        body = make_complete_rate_body()
        del body["RateRequest"]["Shipment"]["Service"]
        missing = find_missing_rate_fields(body, request_option="shop")
        flat_keys = {mf.flat_key for mf in missing}
        self.assertNotIn("service_code", flat_keys)


# ---------------------------------------------------------------------------
# Per-package rules
# ---------------------------------------------------------------------------

class PackageRuleTests(unittest.TestCase):
    def test_missing_package_emits_package_1_fields(self) -> None:
        body = make_complete_rate_body()
        del body["RateRequest"]["Shipment"]["Package"]
        missing = find_missing_rate_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertIn("package_1_packaging_code", flat_keys)
        self.assertIn("package_1_weight_unit", flat_keys)
        self.assertIn("package_1_weight", flat_keys)

    def test_multi_package_validates_each(self) -> None:
        body = make_complete_rate_body(num_packages=2)
        body["RateRequest"]["Shipment"]["Package"][1].pop("PackageWeight")
        missing = find_missing_rate_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertNotIn("package_1_weight", flat_keys)
        self.assertIn("package_2_weight", flat_keys)
        self.assertIn("package_2_weight_unit", flat_keys)

    def test_multi_package_prompts_include_index(self) -> None:
        body = make_complete_rate_body(num_packages=2)
        body["RateRequest"]["Shipment"]["Package"][0].pop("PackageWeight")
        missing = find_missing_rate_fields(body)
        pkg1_weight = [mf for mf in missing if mf.flat_key == "package_1_weight"]
        self.assertEqual(len(pkg1_weight), 1)
        self.assertIn("Package 1", pkg1_weight[0].prompt)

    def test_package_dict_normalized_to_list(self) -> None:
        body = make_complete_rate_body()
        # Convert Package from list to dict
        body["RateRequest"]["Shipment"]["Package"] = (
            body["RateRequest"]["Shipment"]["Package"][0]
        )
        missing = find_missing_rate_fields(body)
        pkg_missing = [mf for mf in missing if "package_" in mf.flat_key]
        self.assertEqual(pkg_missing, [])


# ---------------------------------------------------------------------------
# Country-conditional rules
# ---------------------------------------------------------------------------

class CountryConditionalTests(unittest.TestCase):
    def test_us_address_requires_state_and_postal(self) -> None:
        body = make_complete_rate_body(shipper_country="US")
        del body["RateRequest"]["Shipment"]["Shipper"]["Address"]["StateProvinceCode"]
        del body["RateRequest"]["Shipment"]["Shipper"]["Address"]["PostalCode"]
        missing = find_missing_rate_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertIn("shipper_state", flat_keys)
        self.assertIn("shipper_postal_code", flat_keys)

    def test_ca_address_requires_state(self) -> None:
        body = make_complete_rate_body(shipper_country="CA")
        del body["RateRequest"]["Shipment"]["Shipper"]["Address"]["StateProvinceCode"]
        missing = find_missing_rate_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertIn("shipper_state", flat_keys)

    def test_gb_address_does_not_require_state(self) -> None:
        body = make_complete_rate_body(shipper_country="GB")
        del body["RateRequest"]["Shipment"]["Shipper"]["Address"]["StateProvinceCode"]
        del body["RateRequest"]["Shipment"]["Shipper"]["Address"]["PostalCode"]
        missing = find_missing_rate_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertNotIn("shipper_state", flat_keys)
        self.assertNotIn("shipper_postal_code", flat_keys)

    def test_ship_to_country_conditional(self) -> None:
        body = make_complete_rate_body(ship_to_country="US")
        del body["RateRequest"]["Shipment"]["ShipTo"]["Address"]["PostalCode"]
        missing = find_missing_rate_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertIn("ship_to_postal_code", flat_keys)

    def test_country_conditional_dot_paths_use_rate_prefix(self) -> None:
        body = make_complete_rate_body(shipper_country="US")
        del body["RateRequest"]["Shipment"]["Shipper"]["Address"]["StateProvinceCode"]
        missing = find_missing_rate_fields(body)
        state = [mf for mf in missing if mf.flat_key == "shipper_state"]
        self.assertEqual(len(state), 1)
        self.assertTrue(state[0].dot_path.startswith("RateRequest."))


# ---------------------------------------------------------------------------
# Payment rules
# ---------------------------------------------------------------------------

class PaymentRuleTests(unittest.TestCase):
    def test_missing_payment_info_detected(self) -> None:
        body = make_complete_rate_body()
        del body["RateRequest"]["Shipment"]["PaymentInformation"]
        missing = find_missing_rate_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertIn("payment_charge_type", flat_keys)
        self.assertIn("payment_account_number", flat_keys)

    def test_bill_receiver_account_validated(self) -> None:
        body = make_complete_rate_body()
        body["RateRequest"]["Shipment"]["PaymentInformation"]["ShipmentCharge"] = [{
            "Type": "01",
            "BillReceiver": {},
        }]
        missing = find_missing_rate_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertIn("payment_account_number", flat_keys)
        account_rule = [mf for mf in missing if mf.flat_key == "payment_account_number"]
        self.assertIn("BillReceiver", account_rule[0].dot_path)

    def test_no_billing_object_defaults_to_bill_shipper(self) -> None:
        body = make_complete_rate_body()
        body["RateRequest"]["Shipment"]["PaymentInformation"]["ShipmentCharge"] = [{
            "Type": "01",
        }]
        missing = find_missing_rate_fields(body)
        flat_keys = {mf.flat_key for mf in missing}
        self.assertIn("payment_account_number", flat_keys)
        account_rule = [mf for mf in missing if mf.flat_key == "payment_account_number"]
        self.assertIn("BillShipper", account_rule[0].dot_path)

    def test_ambiguous_payer_raises_error(self) -> None:
        body = make_complete_rate_body()
        body["RateRequest"]["Shipment"]["PaymentInformation"]["ShipmentCharge"] = [{
            "Type": "01",
            "BillShipper": {"AccountNumber": "A"},
            "BillReceiver": {"AccountNumber": "B"},
        }]
        with self.assertRaises(AmbiguousPayerError):
            find_missing_rate_fields(body)


# ---------------------------------------------------------------------------
# apply_rate_defaults tests
# ---------------------------------------------------------------------------

class ApplyRateDefaultsTests(unittest.TestCase):
    def test_empty_body_gets_payment_charge_type(self) -> None:
        result = apply_rate_defaults({}, {})
        self.assertEqual(
            result["RateRequest"]["Shipment"]["PaymentInformation"]["ShipmentCharge"][0]["Type"],
            "01",
        )

    def test_env_fills_shipper_number(self) -> None:
        body: dict = {"RateRequest": {"Shipment": {"Shipper": {}}}}
        result = apply_rate_defaults(body, {"UPS_ACCOUNT_NUMBER": "ABC123"})
        self.assertEqual(
            result["RateRequest"]["Shipment"]["Shipper"]["ShipperNumber"],
            "ABC123",
        )

    def test_env_fills_bill_shipper_when_no_payer(self) -> None:
        result = apply_rate_defaults({}, {"UPS_ACCOUNT_NUMBER": "ABC123"})
        self.assertEqual(
            result["RateRequest"]["Shipment"]["PaymentInformation"]["ShipmentCharge"][0]["BillShipper"]["AccountNumber"],
            "ABC123",
        )

    def test_env_skips_bill_shipper_when_bill_receiver_present(self) -> None:
        body = {
            "RateRequest": {
                "Shipment": {
                    "PaymentInformation": {
                        "ShipmentCharge": [{"Type": "01", "BillReceiver": {"AccountNumber": "RCV456"}}]
                    }
                }
            }
        }
        result = apply_rate_defaults(body, {"UPS_ACCOUNT_NUMBER": "ABC123"})
        first_charge = result["RateRequest"]["Shipment"]["PaymentInformation"]["ShipmentCharge"][0]
        self.assertNotIn("BillShipper", first_charge)

    def test_caller_value_overrides_env(self) -> None:
        body = {
            "RateRequest": {"Shipment": {"Shipper": {"ShipperNumber": "CALLER_NUM"}}}
        }
        result = apply_rate_defaults(body, {"UPS_ACCOUNT_NUMBER": "ENV_NUM"})
        self.assertEqual(
            result["RateRequest"]["Shipment"]["Shipper"]["ShipperNumber"],
            "CALLER_NUM",
        )

    def test_does_not_mutate_input(self) -> None:
        body = {"RateRequest": {"Shipment": {}}}
        original = copy.deepcopy(body)
        apply_rate_defaults(body, {})
        self.assertEqual(body, original)


# ---------------------------------------------------------------------------
# canonicalize_rate_body tests
# ---------------------------------------------------------------------------

class CanonicalizeRateBodyTests(unittest.TestCase):
    def test_package_dict_becomes_list(self) -> None:
        body = {"RateRequest": {"Shipment": {"Package": {"Packaging": {"Code": "02"}}}}}
        result = canonicalize_rate_body(body)
        pkg = result["RateRequest"]["Shipment"]["Package"]
        self.assertIsInstance(pkg, list)
        self.assertEqual(len(pkg), 1)

    def test_shipment_charge_dict_becomes_list(self) -> None:
        body = {
            "RateRequest": {
                "Shipment": {
                    "PaymentInformation": {
                        "ShipmentCharge": {"Type": "01"}
                    }
                }
            }
        }
        result = canonicalize_rate_body(body)
        sc = result["RateRequest"]["Shipment"]["PaymentInformation"]["ShipmentCharge"]
        self.assertIsInstance(sc, list)

    def test_already_lists_unchanged(self) -> None:
        body = make_complete_rate_body()
        result = canonicalize_rate_body(body)
        self.assertEqual(
            result["RateRequest"]["Shipment"]["Package"],
            body["RateRequest"]["Shipment"]["Package"],
        )

    def test_does_not_mutate_input(self) -> None:
        body = {"RateRequest": {"Shipment": {"Package": {"Packaging": {"Code": "02"}}}}}
        original = copy.deepcopy(body)
        canonicalize_rate_body(body)
        self.assertEqual(body, original)

    def test_missing_fields_tolerated(self) -> None:
        result = canonicalize_rate_body({})
        self.assertEqual(result, {})

    def test_non_dict_shipment_raises_type_error(self) -> None:
        body = {"RateRequest": {"Shipment": "not_a_dict"}}
        with self.assertRaises(TypeError):
            canonicalize_rate_body(body)

    def test_non_dict_payment_raises_type_error(self) -> None:
        body = {"RateRequest": {"Shipment": {"PaymentInformation": "not_a_dict"}}}
        with self.assertRaises(TypeError):
            canonicalize_rate_body(body)


# ---------------------------------------------------------------------------
# Type metadata propagation
# ---------------------------------------------------------------------------

class TypeMetadataTests(unittest.TestCase):
    def test_service_code_carries_enum(self) -> None:
        body = make_complete_rate_body()
        del body["RateRequest"]["Shipment"]["Service"]
        missing = find_missing_rate_fields(body)
        service = [mf for mf in missing if mf.flat_key == "service_code"]
        self.assertEqual(len(service), 1)
        self.assertIsNotNone(service[0].enum_values)
        self.assertIn("03", service[0].enum_values)

    def test_package_weight_carries_float(self) -> None:
        body = make_complete_rate_body()
        del body["RateRequest"]["Shipment"]["Package"][0]["PackageWeight"]["Weight"]
        missing = find_missing_rate_fields(body)
        weight = [mf for mf in missing if mf.flat_key == "package_1_weight"]
        self.assertEqual(len(weight), 1)
        self.assertEqual(weight[0].type_hint, float)

    def test_country_code_carries_constraints(self) -> None:
        body = make_complete_rate_body()
        del body["RateRequest"]["Shipment"]["Shipper"]["Address"]["CountryCode"]
        missing = find_missing_rate_fields(body)
        country = [mf for mf in missing if mf.flat_key == "shipper_country_code"]
        self.assertEqual(len(country), 1)
        constraint_keys = {k for k, v in country[0].constraints}
        self.assertIn("maxLength", constraint_keys)
        self.assertIn("pattern", constraint_keys)


if __name__ == "__main__":
    unittest.main()
