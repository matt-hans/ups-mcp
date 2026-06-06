import json
import unittest

from mcp.server.fastmcp.exceptions import ToolError

from ups_mcp.shipagent_normalization import (
    ShipAgentNormalizationError,
    build_shipagent_capabilities,
    normalize_address_result,
    normalize_rate_result,
    to_normalization_error,
    to_safe_error,
)


_MISSING = object()


class ShipAgentCapabilitiesAndErrorTests(unittest.TestCase):
    def test_build_shipagent_capabilities_returns_hosted_v1_contract(self) -> None:
        capabilities = build_shipagent_capabilities("1.1.0")

        self.assertEqual(
            set(capabilities),
            {
                "contract_version",
                "server_version",
                "capabilities",
                "response_formats",
            },
        )
        self.assertEqual(capabilities["contract_version"], "hosted-v1")
        self.assertEqual(capabilities["server_version"], "1.1.0")
        self.assertEqual(
            capabilities["capabilities"],
            [
                "rate_quote",
                "rate_shop",
                "address_validation",
                "create_shipment",
                "idempotency_metadata_passthrough",
                "shipment_response_normalization",
                "safe_error_mapping",
                "mutating_retry_policy",
            ],
        )
        self.assertEqual(capabilities["response_formats"], ["raw", "shipagent_v1"])
        self.assertNotIn("schema_hash", capabilities)
        self.assertNotIn("schema_version", capabilities)
        self.assertNotIn("retry_policy", capabilities)

    def test_to_normalization_error_returns_closed_safe_error(self) -> None:
        error = to_normalization_error("corr_123")

        self.assertEqual(
            error,
            {
                "success": False,
                "error": {
                    "category": "normalization",
                    "code": "UPS_NORMALIZATION_ERROR",
                    "message": "UPS response could not be normalized.",
                    "correlation_id": "corr_123",
                    "retryable": False,
                },
            },
        )
        self.assertTrue(issubclass(ShipAgentNormalizationError, ValueError))

    def test_to_safe_error_maps_public_categories(self) -> None:
        cases = [
            (
                ToolError(json.dumps({"status_code": 401, "code": "250003", "message": "invalid token"})),
                {
                    "category": "auth",
                    "code": "UPS_AUTH_ERROR",
                    "message": "UPS authentication failed.",
                    "retryable": False,
                },
            ),
            (
                ToolError(json.dumps({"code": "429", "message": "too many requests"})),
                {
                    "category": "rate_limit",
                    "code": "UPS_RATE_LIMIT_ERROR",
                    "message": "UPS rate limit exceeded.",
                    "retryable": True,
                },
            ),
            (
                ToolError(json.dumps({"status_code": 400, "code": "120100", "message": "bad address"})),
                {
                    "category": "validation",
                    "code": "UPS_VALIDATION_ERROR",
                    "message": "UPS request validation failed.",
                    "retryable": False,
                },
            ),
            (
                ToolError(json.dumps({"status_code": 503, "code": "503", "message": "maintenance"})),
                {
                    "category": "service_unavailable",
                    "code": "UPS_SERVICE_UNAVAILABLE",
                    "message": "UPS service is temporarily unavailable.",
                    "retryable": True,
                },
            ),
            (
                ToolError(json.dumps({"code": "REQUEST_ERROR", "message": "connection reset"})),
                {
                    "category": "transport",
                    "code": "UPS_TRANSPORT_ERROR",
                    "message": "UPS transport request failed.",
                    "retryable": True,
                },
            ),
            (
                RuntimeError("stack trace with local path /tmp/ups.py"),
                {
                    "category": "unknown",
                    "code": "UPS_UNKNOWN_ERROR",
                    "message": "UPS request failed unexpectedly.",
                    "retryable": False,
                },
            ),
        ]

        for exc, expected in cases:
            with self.subTest(expected["category"]):
                error = to_safe_error(exc, "corr_map")

                self.assertEqual(set(error), {"success", "error"})
                self.assertIs(error["success"], False)
                self.assertEqual(
                    error["error"],
                    {
                        **expected,
                        "correlation_id": "corr_map",
                    },
                )

    def test_to_safe_error_keeps_long_numeric_ups_codes_as_business_codes(self) -> None:
        for code in ("120100", "250003"):
            with self.subTest(code):
                error = to_safe_error(ToolError(json.dumps({"code": code})), "corr_business")

                self.assertEqual(
                    error,
                    {
                        "success": False,
                        "error": {
                            "category": "unknown",
                            "code": "UPS_UNKNOWN_ERROR",
                            "message": "UPS request failed unexpectedly.",
                            "correlation_id": "corr_business",
                            "retryable": False,
                        },
                    },
                )

    def test_to_safe_error_prioritizes_status_text_in_request_errors(self) -> None:
        cases = [
            (
                {"code": "REQUEST_ERROR", "message": "401 Unauthorized"},
                {
                    "category": "auth",
                    "code": "UPS_AUTH_ERROR",
                    "message": "UPS authentication failed.",
                    "retryable": False,
                },
            ),
            (
                {"code": "REQUEST_ERROR", "message": "403 Forbidden"},
                {
                    "category": "auth",
                    "code": "UPS_AUTH_ERROR",
                    "message": "UPS authentication failed.",
                    "retryable": False,
                },
            ),
            (
                {"code": "REQUEST_ERROR", "message": "429 Too Many Requests"},
                {
                    "category": "rate_limit",
                    "code": "UPS_RATE_LIMIT_ERROR",
                    "message": "UPS rate limit exceeded.",
                    "retryable": True,
                },
            ),
            (
                {"code": "REQUEST_ERROR", "message": "400 Bad Request"},
                {
                    "category": "validation",
                    "code": "UPS_VALIDATION_ERROR",
                    "message": "UPS request validation failed.",
                    "retryable": False,
                },
            ),
            (
                {"code": "REQUEST_ERROR", "message": "408 Request Timeout"},
                {
                    "category": "transport",
                    "code": "UPS_TRANSPORT_ERROR",
                    "message": "UPS transport request failed.",
                    "retryable": True,
                },
            ),
            (
                {"code": "REQUEST_ERROR", "message": "500 Internal Server Error"},
                {
                    "category": "service_unavailable",
                    "code": "UPS_SERVICE_UNAVAILABLE",
                    "message": "UPS service is temporarily unavailable.",
                    "retryable": True,
                },
            ),
            (
                {
                    "code": "REQUEST_ERROR",
                    "message": (
                        "401 Client Error: Unauthorized for url: "
                        "https://example.test/security/v1/oauth/token"
                    ),
                },
                {
                    "category": "auth",
                    "code": "UPS_AUTH_ERROR",
                    "message": "UPS authentication failed.",
                    "retryable": False,
                },
            ),
            (
                {
                    "code": "REQUEST_ERROR",
                    "message": (
                        "429 Client Error: Too Many Requests for url: "
                        "https://example.test/rating/v2409/Rate"
                    ),
                },
                {
                    "category": "rate_limit",
                    "code": "UPS_RATE_LIMIT_ERROR",
                    "message": "UPS rate limit exceeded.",
                    "retryable": True,
                },
            ),
            (
                {
                    "code": "REQUEST_ERROR",
                    "message": (
                        "500 Server Error: Internal Server Error for url: "
                        "https://example.test/rating/v2409/Rate"
                    ),
                },
                {
                    "category": "service_unavailable",
                    "code": "UPS_SERVICE_UNAVAILABLE",
                    "message": "UPS service is temporarily unavailable.",
                    "retryable": True,
                },
            ),
        ]

        for payload, expected in cases:
            with self.subTest(payload["message"]):
                error = to_safe_error(ToolError(json.dumps(payload)), "corr_request")

                self.assertEqual(set(error), {"success", "error"})
                self.assertIs(error["success"], False)
                self.assertEqual(
                    error["error"],
                    {
                        **expected,
                        "correlation_id": "corr_request",
                    },
                )

    def test_to_safe_error_does_not_treat_network_ports_as_status_codes(self) -> None:
        error = to_safe_error(
            ToolError(
                json.dumps(
                    {
                        "code": "REQUEST_ERROR",
                        "message": (
                            "HTTPSConnectionPool(host='example.test', port=443): "
                            "Max retries exceeded with url: /rating"
                        ),
                    },
                ),
            ),
            "corr_pool",
        )

        self.assertEqual(
            error,
            {
                "success": False,
                "error": {
                    "category": "transport",
                    "code": "UPS_TRANSPORT_ERROR",
                    "message": "UPS transport request failed.",
                    "correlation_id": "corr_pool",
                    "retryable": True,
                },
            },
        )

    def test_to_safe_error_prioritizes_status_text_with_ascii_controls(self) -> None:
        cases = [
            (
                {"code": "REQUEST_ERROR", "message": "HTTPError: 401 Unauthorized\nbody omitted"},
                {
                    "category": "auth",
                    "code": "UPS_AUTH_ERROR",
                    "message": "UPS authentication failed.",
                    "retryable": False,
                },
            ),
            (
                {"code": "REQUEST_ERROR", "message": "HTTPError:\t429 Too Many Requests"},
                {
                    "category": "rate_limit",
                    "code": "UPS_RATE_LIMIT_ERROR",
                    "message": "UPS rate limit exceeded.",
                    "retryable": True,
                },
            ),
        ]

        for payload, expected in cases:
            with self.subTest(payload["message"]):
                error = to_safe_error(ToolError(json.dumps(payload)), "corr_control")

                self.assertEqual(set(error), {"success", "error"})
                self.assertIs(error["success"], False)
                self.assertEqual(
                    error["error"],
                    {
                        **expected,
                        "correlation_id": "corr_control",
                    },
                )
                self.assertNotIn("HTTPError", json.dumps(error))

    def test_to_safe_error_maps_direct_request_timeout_as_transport(self) -> None:
        error = to_safe_error(
            ToolError(json.dumps({"status_code": 408, "code": "REQUEST_TIMEOUT"})),
            "corr_timeout",
        )

        self.assertEqual(
            error,
            {
                "success": False,
                "error": {
                    "category": "transport",
                    "code": "UPS_TRANSPORT_ERROR",
                    "message": "UPS transport request failed.",
                    "correlation_id": "corr_timeout",
                    "retryable": True,
                },
            },
        )

    def test_to_safe_error_maps_internal_validation_tool_errors(self) -> None:
        payloads = [
            {"code": "MALFORMED_REQUEST", "reason": "malformed_structure"},
            {"code": "STRUCTURAL_FIELDS_REQUIRED"},
            {"code": "ELICITATION_UNSUPPORTED"},
            {"code": "ELICITATION_INVALID_RESPONSE"},
            {"code": "ELICITATION_DECLINED"},
            {"code": "ELICITATION_CANCELLED"},
            {"code": "ELICITATION_FAILED"},
            {"code": "ELICITATION_MAX_RETRIES"},
        ]

        for payload in payloads:
            with self.subTest(payload["code"]):
                error = to_safe_error(ToolError(json.dumps(payload)), "corr_internal")

                self.assertEqual(
                    error,
                    {
                        "success": False,
                        "error": {
                            "category": "validation",
                            "code": "UPS_VALIDATION_ERROR",
                            "message": "UPS request validation failed.",
                            "correlation_id": "corr_internal",
                            "retryable": False,
                        },
                    },
                )

    def test_to_safe_error_maps_plain_validation_tool_errors(self) -> None:
        messages = [
            "request_body must be a JSON object",
            "Invalid requestoption 'bad'. Allowed values: Rate, Shop",
            "trackingnumber must be a string or a list of strings",
            "AccountNumber is required via argument or UPS_ACCOUNT_NUMBER env var",
            "missing required key ShipmentRequest",
            "pickup date must be before close time",
            "Invalid file_format 'TXT'. Must be one of: pdf, png, gif",
            "Invalid location_type 'bad'. Must be one of: retail, dropbox",
            (
                "PickupCreation requires a shipper account via "
                "Shipper.Account.AccountNumber or UPS_ACCOUNT_NUMBER"
            ),
            "Invalid cancel_by 'bad'. Must be one of: prn, transactionId",
            "prn is required when cancel_by='prn'",
            "request_body is required for operation Shipment",
        ]

        for message in messages:
            with self.subTest(message):
                error = to_safe_error(ToolError(message), "corr_plain")

                self.assertEqual(
                    error,
                    {
                        "success": False,
                        "error": {
                            "category": "validation",
                            "code": "UPS_VALIDATION_ERROR",
                            "message": "UPS request validation failed.",
                            "correlation_id": "corr_plain",
                            "retryable": False,
                        },
                    },
                )
                self.assertNotIn(message, json.dumps(error))

    def test_to_safe_error_does_not_leak_raw_ups_details(self) -> None:
        exc = ToolError(
            json.dumps(
                {
                    "status_code": 400,
                    "code": "250003",
                    "message": "Invalid account 1Z999AA10123456784 using secret-token",
                    "details": {
                        "request_body": {"shipper": {"account_number": "ABC123456"}},
                        "debug": "Traceback in /Users/matthewhans/Desktop/ups.py",
                    },
                },
            ),
        )

        error = to_safe_error(exc, "corr_safe")

        self.assertEqual(
            error,
            {
                "success": False,
                "error": {
                    "category": "validation",
                    "code": "UPS_VALIDATION_ERROR",
                    "message": "UPS request validation failed.",
                    "correlation_id": "corr_safe",
                    "retryable": False,
                },
            },
        )
        serialized = json.dumps(error)
        for leaked_fragment in (
            "250003",
            "1Z999AA10123456784",
            "secret-token",
            "ABC123456",
            "request_body",
            "/Users/matthewhans/Desktop/ups.py",
            "Traceback",
        ):
            self.assertNotIn(leaked_fragment, serialized)

    def test_to_safe_error_does_not_expose_domain_specific_categories_or_codes(self) -> None:
        cases = [
            {
                "status_code": 400,
                "code": "ADDRESS_VALIDATION_FAILED",
                "message": "address line is invalid",
            },
            {
                "status_code": 422,
                "code": "CUSTOMS_INVOICE_MISSING",
                "message": "customs form is missing",
            },
        ]

        for payload in cases:
            with self.subTest(payload["code"]):
                error = to_safe_error(ToolError(json.dumps(payload)), "corr_domain")

                self.assertEqual(set(error), {"success", "error"})
                self.assertIs(error["success"], False)
                self.assertEqual(error["error"]["category"], "validation")
                self.assertEqual(error["error"]["code"], "UPS_VALIDATION_ERROR")
                serialized = json.dumps(error).lower()
                self.assertNotIn("address", serialized)
                self.assertNotIn("customs", serialized)


class ShipAgentRateNormalizationTests(unittest.TestCase):
    def _raw_rate_response(self, rated_shipment: object) -> dict[str, object]:
        return {"RateResponse": {"RatedShipment": rated_shipment}}

    def _rated_shipment(
        self,
        *,
        service_code: object = "03",
        service_description: object = "UPS Ground",
        monetary_value: object = "12.34",
        currency_code: object = "USD",
        total_charges: object = _MISSING,
        negotiated_total: object = _MISSING,
    ) -> dict[str, object]:
        service: dict[str, object] = {}
        if service_code is not _MISSING:
            service["Code"] = service_code
        if service_description is not _MISSING:
            service["Description"] = service_description

        shipment: dict[str, object] = {"Service": service}
        if total_charges is _MISSING:
            shipment["TotalCharges"] = {
                "MonetaryValue": monetary_value,
                "CurrencyCode": currency_code,
            }
        elif total_charges is not None:
            shipment["TotalCharges"] = total_charges
        if negotiated_total is not _MISSING:
            shipment["NegotiatedRateCharges"] = {"TotalCharge": negotiated_total}
        return shipment

    def test_quote_requires_one_rated_shipment_and_prefers_complete_negotiated_total(self) -> None:
        raw = self._raw_rate_response(
            [
                self._rated_shipment(
                    service_code=" 03 ",
                    service_description=" UPS Ground ",
                    negotiated_total={"MonetaryValue": " 10.50 ", "CurrencyCode": " USD "},
                )
            ]
        )

        result = normalize_rate_result(raw, "Rate", "corr_rate_quote")

        self.assertEqual(
            result,
            {
                "success": True,
                "correlationId": "corr_rate_quote",
                "serviceCode": "03",
                "serviceDescription": "UPS Ground",
                "totalCharges": {"monetaryValue": "10.50", "currencyCode": "USD"},
            },
        )
        self.assertNotIn("contractVersion", result)
        self.assertNotIn("contract_version", result)

    def test_quote_rejects_multiple_rated_shipments(self) -> None:
        raw = self._raw_rate_response(
            [
                self._rated_shipment(service_code="03"),
                self._rated_shipment(service_code="02"),
            ]
        )

        with self.assertRaises(ShipAgentNormalizationError):
            normalize_rate_result(raw, "rate", "corr_rate_quote")

    def test_quote_omits_service_description_when_ups_omits_it(self) -> None:
        raw = self._raw_rate_response(
            [self._rated_shipment(service_description=_MISSING)]
        )

        result = normalize_rate_result(raw, "Ratetimeintransit", "corr_rate_quote")

        self.assertEqual(result["serviceCode"], "03")
        self.assertEqual(
            result["totalCharges"], {"monetaryValue": "12.34", "currencyCode": "USD"}
        )
        self.assertNotIn("serviceDescription", result)

    def test_monetary_value_remains_string(self) -> None:
        raw = self._raw_rate_response(
            [self._rated_shipment(monetary_value="0010.500")]
        )

        result = normalize_rate_result(raw, "Rate", "corr_rate_quote")

        self.assertEqual(result["totalCharges"]["monetaryValue"], "0010.500")
        self.assertIsInstance(result["totalCharges"]["monetaryValue"], str)

    def test_malformed_currency_codes_reject(self) -> None:
        for currency_code in ("usd", "US", "US1", "US$", "ØSD", "   "):
            with self.subTest(currency_code=currency_code):
                raw = self._raw_rate_response(
                    [self._rated_shipment(currency_code=currency_code)]
                )

                with self.assertRaises(ShipAgentNormalizationError):
                    normalize_rate_result(raw, "Rate", "corr_rate_quote")

    def test_ascii_control_characters_in_success_strings_reject(self) -> None:
        cases = [
            self._rated_shipment(service_code="03\n"),
            self._rated_shipment(service_description="UPS\tGround"),
            self._rated_shipment(monetary_value="12.34\x7f"),
            self._rated_shipment(currency_code="USD\r"),
        ]

        for rated_shipment in cases:
            with self.subTest(rated_shipment=rated_shipment):
                raw = self._raw_rate_response([rated_shipment])

                with self.assertRaises(ShipAgentNormalizationError):
                    normalize_rate_result(raw, "Rate", "corr_rate_quote")

    def test_non_string_success_fields_reject(self) -> None:
        cases = [
            self._rated_shipment(service_code=3),
            self._rated_shipment(service_description=True),
            self._rated_shipment(monetary_value=12.34),
            self._rated_shipment(currency_code=["USD"]),
        ]

        for rated_shipment in cases:
            with self.subTest(rated_shipment=rated_shipment):
                raw = self._raw_rate_response([rated_shipment])

                with self.assertRaises(ShipAgentNormalizationError):
                    normalize_rate_result(raw, "Rate", "corr_rate_quote")

    def test_incomplete_negotiated_rate_charge_rejects_without_standard_fallback(self) -> None:
        raw = self._raw_rate_response(
            [
                self._rated_shipment(
                    monetary_value="99.99",
                    negotiated_total={"MonetaryValue": "10.50"},
                )
            ]
        )

        with self.assertRaises(ShipAgentNormalizationError):
            normalize_rate_result(raw, "Rate", "corr_rate_quote")

    def test_present_null_or_missing_negotiated_rate_charge_rejects_without_standard_fallback(self) -> None:
        for negotiated_rate_charges in (None, {}, {"TotalCharge": None}):
            with self.subTest(negotiated_rate_charges=negotiated_rate_charges):
                rated_shipment = self._rated_shipment(monetary_value="99.99")
                rated_shipment["NegotiatedRateCharges"] = negotiated_rate_charges
                raw = self._raw_rate_response([rated_shipment])

                with self.assertRaises(ShipAgentNormalizationError):
                    normalize_rate_result(raw, "Rate", "corr_rate_quote")

    def test_quote_requires_service_code(self) -> None:
        raw = self._raw_rate_response(
            [self._rated_shipment(service_code=_MISSING)]
        )

        with self.assertRaises(ShipAgentNormalizationError):
            normalize_rate_result(raw, "Rate", "corr_rate_quote")

    def test_shop_returns_all_complete_options_and_uses_standard_total_when_negotiated_absent(self) -> None:
        raw = self._raw_rate_response(
            [
                self._rated_shipment(
                    service_code="03",
                    service_description="UPS Ground",
                    monetary_value="12.34",
                ),
                self._rated_shipment(
                    service_code="02",
                    service_description=_MISSING,
                    monetary_value="20.00",
                ),
            ]
        )

        result = normalize_rate_result(raw, "Shop", "corr_rate_shop")

        self.assertEqual(
            result,
            {
                "success": True,
                "correlationId": "corr_rate_shop",
                "ratedShipments": [
                    {
                        "serviceCode": "03",
                        "serviceDescription": "UPS Ground",
                        "totalCharges": {"monetaryValue": "12.34", "currencyCode": "USD"},
                    },
                    {
                        "serviceCode": "02",
                        "totalCharges": {"monetaryValue": "20.00", "currencyCode": "USD"},
                    },
                ],
            },
        )
        self.assertNotIn("contractVersion", result)
        self.assertNotIn("contract_version", result)

    def test_shop_rejects_any_incomplete_returned_option_including_non_mapping_shipment(self) -> None:
        cases = [
            [
                self._rated_shipment(service_code="03"),
                self._rated_shipment(service_code=_MISSING),
            ],
            [
                self._rated_shipment(service_code="03"),
                "not-a-rated-shipment",
            ],
        ]

        for rated_shipments in cases:
            with self.subTest(rated_shipments=rated_shipments):
                raw = self._raw_rate_response(rated_shipments)

                with self.assertRaises(ShipAgentNormalizationError):
                    normalize_rate_result(raw, "Shop", "corr_rate_shop")

    def test_shop_accepts_object_rated_shipment_shape(self) -> None:
        raw = self._raw_rate_response(
            self._rated_shipment(
                service_code="03",
                service_description=_MISSING,
                monetary_value="12.34",
            )
        )

        result = normalize_rate_result(raw, "Shoptimeintransit", "corr_rate_shop")

        self.assertEqual(
            result,
            {
                "success": True,
                "correlationId": "corr_rate_shop",
                "ratedShipments": [
                    {
                        "serviceCode": "03",
                        "totalCharges": {"monetaryValue": "12.34", "currencyCode": "USD"},
                    }
                ],
            },
        )

    def test_missing_required_hosted_fields_raise_normalization_error(self) -> None:
        cases = [
            ({}, "Rate", "corr_rate_quote"),
            ({"RateResponse": {}}, "Rate", "corr_rate_quote"),
            (
                self._raw_rate_response(
                    [self._rated_shipment(total_charges=None)]
                ),
                "Rate",
                "corr_rate_quote",
            ),
            (self._raw_rate_response([self._rated_shipment()]), "", "corr_rate_quote"),
            (self._raw_rate_response([self._rated_shipment()]), "Rate", ""),
        ]

        for raw, requestoption, correlation_id in cases:
            with self.subTest(raw=raw, requestoption=requestoption, correlation_id=correlation_id):
                with self.assertRaises(ShipAgentNormalizationError):
                    normalize_rate_result(raw, requestoption, correlation_id)


class ShipAgentAddressNormalizationTests(unittest.TestCase):
    def _raw_xav_response(self, xav_response: object) -> dict[str, object]:
        return {"XAVResponse": xav_response}

    def _address_candidate(self, **fields: object) -> dict[str, object]:
        return {"AddressKeyFormat": fields}

    def test_valid_status_returns_object_candidate_safe_fields(self) -> None:
        raw = self._raw_xav_response(
            {
                "ValidAddressIndicator": "",
                "Candidate": {
                    "AddressKeyFormat": {
                        "AddressLine": [" 123 MAIN ST "],
                        "PoliticalDivision2": " ATLANTA ",
                        "PoliticalDivision1": " GA ",
                        "PostcodePrimaryLow": " 30301 ",
                        "PostcodeExtendedLow": " 1234 ",
                        "CountryCode": " US ",
                    },
                    "AddressClassification": {"Code": "1"},
                    "ConsigneeName": "Warehouse",
                    "Metadata": {"score": 1},
                },
            }
        )

        result = normalize_address_result(raw, "corr_address_valid")

        self.assertEqual(
            result,
            {
                "success": True,
                "correlationId": "corr_address_valid",
                "status": "valid",
                "candidates": [
                    {
                        "addressLines": ["123 MAIN ST"],
                        "city": "ATLANTA",
                        "stateProvince": "GA",
                        "postalCode": "30301",
                        "postalCodeExtended": "1234",
                        "countryCode": "US",
                    }
                ],
            },
        )
        serialized = json.dumps(result)
        self.assertNotIn("AddressClassification", serialized)
        self.assertNotIn("ConsigneeName", serialized)
        self.assertNotIn("contractVersion", result)
        self.assertNotIn("contract_version", result)
        self.assertNotIn("correlation_id", result)

    def test_ambiguous_status_returns_list_candidates_and_drops_non_substantive_candidates(self) -> None:
        raw = self._raw_xav_response(
            {
                "AmbiguousAddressIndicator": "",
                "Candidate": [
                    self._address_candidate(
                        AddressLine=" 456 OAK AVE ",
                        PoliticalDivision2=" SAVANNAH ",
                        PoliticalDivision1=" GA ",
                        PostcodePrimaryLow=" 31401 ",
                        CountryCode=" US ",
                    ),
                    {
                        "AddressLine": [" ", " APT 2 "],
                        "CountryCode": " US ",
                        "AddressClassification": {"Code": "2"},
                    },
                    {"AddressClassification": {"Code": "1"}, "ConsigneeName": "Only Metadata"},
                    self._address_candidate(CountryCode=" US "),
                ],
            }
        )

        result = normalize_address_result(raw, "corr_address_ambiguous")

        self.assertEqual(
            result,
            {
                "success": True,
                "correlationId": "corr_address_ambiguous",
                "status": "ambiguous",
                "candidates": [
                    {
                        "addressLines": ["456 OAK AVE"],
                        "city": "SAVANNAH",
                        "stateProvince": "GA",
                        "postalCode": "31401",
                        "countryCode": "US",
                    },
                    {
                        "addressLines": ["APT 2"],
                        "countryCode": "US",
                    },
                ],
            },
        )
        for candidate in result["candidates"]:
            self.assertNotEqual(candidate, {})

    def test_ascii_control_characters_in_candidate_fields_reject(self) -> None:
        cases = [
            self._address_candidate(AddressLine="123\nMAIN ST"),
            self._address_candidate(AddressLine=["123 MAIN ST", "APT\t2"]),
            self._address_candidate(PoliticalDivision2="ATLANTA\r"),
            self._address_candidate(PoliticalDivision1="G\x7fA"),
            self._address_candidate(PostcodePrimaryLow="30301\n"),
            self._address_candidate(PostcodeExtendedLow="12\t34"),
            self._address_candidate(CountryCode="U\rS"),
        ]

        for candidate in cases:
            with self.subTest(candidate=candidate):
                raw = self._raw_xav_response(
                    {"ValidAddressIndicator": "", "Candidate": candidate}
                )

                with self.assertRaises(ShipAgentNormalizationError):
                    normalize_address_result(raw, "corr_address_control")

    def test_non_string_candidate_fields_reject(self) -> None:
        cases = [
            self._address_candidate(AddressLine=123),
            self._address_candidate(AddressLine=["123 MAIN ST", 2]),
            self._address_candidate(PoliticalDivision2=True),
            self._address_candidate(PoliticalDivision1={"value": "GA"}),
            self._address_candidate(PostcodePrimaryLow=30301),
            self._address_candidate(PostcodeExtendedLow=["1234"]),
            self._address_candidate(CountryCode=False),
        ]

        for candidate in cases:
            with self.subTest(candidate=candidate):
                raw = self._raw_xav_response(
                    {"ValidAddressIndicator": "", "Candidate": candidate}
                )

                with self.assertRaises(ShipAgentNormalizationError):
                    normalize_address_result(raw, "corr_address_type")

    def test_invalid_and_unknown_statuses_return_empty_candidates(self) -> None:
        cases = [
            (
                self._raw_xav_response({"NoCandidatesIndicator": ""}),
                "corr_address_invalid",
                "invalid",
            ),
            (self._raw_xav_response({}), "corr_address_unknown", "unknown"),
        ]

        for raw, correlation_id, status in cases:
            with self.subTest(status=status):
                result = normalize_address_result(raw, correlation_id)

                self.assertEqual(
                    result,
                    {
                        "success": True,
                        "correlationId": correlation_id,
                        "status": status,
                        "candidates": [],
                    },
                )

    def test_valid_and_ambiguous_require_substantive_hosted_candidate(self) -> None:
        cases = [
            {"ValidAddressIndicator": ""},
            {"ValidAddressIndicator": "", "Candidate": {"AddressClassification": {"Code": "1"}}},
            {"ValidAddressIndicator": "", "Candidate": self._address_candidate(CountryCode="US")},
            {"AmbiguousAddressIndicator": "", "Candidate": []},
            {
                "AmbiguousAddressIndicator": "",
                "Candidate": [
                    {"AddressClassification": {"Code": "1"}},
                    self._address_candidate(CountryCode="US"),
                ],
            },
        ]

        for xav_response in cases:
            with self.subTest(xav_response=xav_response):
                raw = self._raw_xav_response(xav_response)

                with self.assertRaises(ShipAgentNormalizationError):
                    normalize_address_result(raw, "corr_address_empty")

    def test_invalid_and_unknown_reject_candidate_data_even_when_not_substantive(self) -> None:
        cases = [
            {"NoCandidatesIndicator": "", "Candidate": {"AddressClassification": {"Code": "1"}}},
            {"NoCandidatesIndicator": "", "Candidate": self._address_candidate(CountryCode="US")},
            {"Candidate": {"AddressClassification": {"Code": "1"}}},
            {"Candidate": self._address_candidate(CountryCode="US")},
        ]

        for xav_response in cases:
            with self.subTest(xav_response=xav_response):
                raw = self._raw_xav_response(xav_response)

                with self.assertRaises(ShipAgentNormalizationError):
                    normalize_address_result(raw, "corr_address_reject_candidate")

    def test_invalid_and_unknown_reject_candidate_key_even_when_empty(self) -> None:
        cases = [
            {"NoCandidatesIndicator": "", "Candidate": {}},
            {"NoCandidatesIndicator": "", "Candidate": []},
            {"NoCandidatesIndicator": "", "Candidate": None},
            {"Candidate": {}},
            {"Candidate": []},
            {"Candidate": None},
        ]

        for xav_response in cases:
            with self.subTest(xav_response=xav_response):
                raw = self._raw_xav_response(xav_response)

                with self.assertRaises(ShipAgentNormalizationError):
                    normalize_address_result(raw, "corr_address_reject_candidate_key")

    def test_conflicting_status_indicators_raise(self) -> None:
        raw = self._raw_xav_response(
            {
                "ValidAddressIndicator": "",
                "AmbiguousAddressIndicator": "",
                "Candidate": self._address_candidate(AddressLine="123 MAIN ST"),
            }
        )

        with self.assertRaises(ShipAgentNormalizationError):
            normalize_address_result(raw, "corr_address_conflict")

    def test_missing_or_non_object_xav_response_raises(self) -> None:
        cases = [
            {},
            self._raw_xav_response(None),
            self._raw_xav_response([]),
            self._raw_xav_response("not-an-object"),
        ]

        for raw in cases:
            with self.subTest(raw=raw):
                with self.assertRaises(ShipAgentNormalizationError):
                    normalize_address_result(raw, "corr_address_missing")


if __name__ == "__main__":
    unittest.main()
