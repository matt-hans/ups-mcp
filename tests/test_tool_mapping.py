import copy
import json
import unittest

from mcp.server.fastmcp.exceptions import ToolError

from ups_mcp.tools import ToolManager


class FakeHTTPClient:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def call_operation(self, operation, **kwargs):  # noqa: ANN001
        self.calls.append({"operation": operation, "kwargs": kwargs})
        return {"mock": True}


class FailingHTTPClient:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def call_operation(self, operation, **kwargs):  # noqa: ANN001
        self.calls.append({"operation": operation, "kwargs": kwargs})
        raise ToolError(json.dumps({"status_code": 503, "code": "503"}))


class ToolMappingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = ToolManager(
            base_url="https://example.test",
            client_id="client-id",
            client_secret="client-secret",
        )
        self.fake_http_client = FakeHTTPClient()
        self.manager.http_client = self.fake_http_client

    def test_rate_shipment_maps_inputs_to_rate_operation(self) -> None:
        response = self.manager.rate_shipment(
            requestoption="shop",
            request_body={"RateRequest": {}},
            additionalinfo="timeintransit",
            trans_id="trans-123",
        )

        self.assertEqual(response, {"mock": True})
        self.assertEqual(len(self.fake_http_client.calls), 1)
        call = self.fake_http_client.calls[0]
        self.assertEqual(call["operation"].operation_id, "Rate")
        self.assertEqual(call["kwargs"]["path_params"]["version"], "v2409")
        self.assertEqual(call["kwargs"]["path_params"]["requestoption"], "Shop")
        self.assertEqual(call["kwargs"]["query_params"]["additionalinfo"], "timeintransit")
        self.assertEqual(call["kwargs"]["json_body"], {"RateRequest": {}})

    def test_void_shipment_accepts_string_and_list_trackingnumber(self) -> None:
        self.manager.void_shipment(
            shipmentidentificationnumber="1Z999AA10123456784",
            trackingnumber="1Z999AA10123456784",
        )
        self.manager.void_shipment(
            shipmentidentificationnumber="1Z999AA10123456784",
            trackingnumber=["1Z999AA10123456784", "1Z999AA10123456785"],
        )

        first_query = self.fake_http_client.calls[0]["kwargs"]["query_params"]["trackingnumber"]
        second_query = self.fake_http_client.calls[1]["kwargs"]["query_params"]["trackingnumber"]
        self.assertEqual(first_query, "1Z999AA10123456784")
        self.assertEqual(second_query, ["1Z999AA10123456784", "1Z999AA10123456785"])

    def test_tool_manager_stores_account_number(self) -> None:
        manager = ToolManager(
            base_url="https://example.test",
            client_id="cid",
            client_secret="csec",
            account_number="ABC999",
        )
        self.assertEqual(manager.account_number, "ABC999")

    def test_tool_manager_account_number_defaults_to_none(self) -> None:
        manager = ToolManager(
            base_url="https://example.test",
            client_id="cid",
            client_secret="csec",
        )
        self.assertIsNone(manager.account_number)

    def test_invalid_rate_requestoption_raises_tool_error(self) -> None:
        with self.assertRaises(ToolError) as ctx:
            self.manager.rate_shipment(
                requestoption="invalid-option",
                request_body={"RateRequest": {}},
            )

        self.assertIn("Invalid requestoption", str(ctx.exception))
        self.assertEqual(len(self.fake_http_client.calls), 0)

    def test_create_shipment_sets_missing_customer_context_to_idempotency_key(self) -> None:
        body = {"ShipmentRequest": {"Request": {}, "Shipment": {}}}

        self.manager.create_shipment(
            request_body=body,
            idempotency_key=" idem-123 ",
        )

        sent_body = self.fake_http_client.calls[0]["kwargs"]["json_body"]
        context = sent_body["ShipmentRequest"]["Request"]["TransactionReference"]["CustomerContext"]
        self.assertEqual(context, "idem-123")
        self.assertNotIn("TransactionReference", body["ShipmentRequest"]["Request"])

    def test_create_shipment_sets_empty_customer_context_to_idempotency_key(self) -> None:
        body = {
            "ShipmentRequest": {
                "Request": {"TransactionReference": {"CustomerContext": "  "}},
                "Shipment": {},
            }
        }

        self.manager.create_shipment(request_body=body, idempotency_key="idem-empty")

        sent_body = self.fake_http_client.calls[0]["kwargs"]["json_body"]
        context = sent_body["ShipmentRequest"]["Request"]["TransactionReference"]["CustomerContext"]
        self.assertEqual(context, "idem-empty")

    def test_create_shipment_appends_idempotency_key_when_context_has_room(self) -> None:
        body = {
            "ShipmentRequest": {
                "Request": {
                    "TransactionReference": {"CustomerContext": "caller-context"}
                },
                "Shipment": {},
            }
        }

        self.manager.create_shipment(request_body=body, idempotency_key="idem-append")

        sent_body = self.fake_http_client.calls[0]["kwargs"]["json_body"]
        context = sent_body["ShipmentRequest"]["Request"]["TransactionReference"]["CustomerContext"]
        self.assertEqual(context, "caller-context; idempotency_key=idem-append")

    def test_create_shipment_preserves_existing_context_when_append_exceeds_512_chars(self) -> None:
        existing = "x" * 500
        body = {
            "ShipmentRequest": {
                "Request": {"TransactionReference": {"CustomerContext": existing}},
                "Shipment": {},
            }
        }

        self.manager.create_shipment(request_body=body, idempotency_key="idem-too-long")

        sent_body = self.fake_http_client.calls[0]["kwargs"]["json_body"]
        context = sent_body["ShipmentRequest"]["Request"]["TransactionReference"]["CustomerContext"]
        self.assertEqual(context, existing)
        self.assertEqual(len(context), 500)

    def test_create_shipment_without_idempotency_key_leaves_request_body_unchanged(self) -> None:
        body = {
            "ShipmentRequest": {
                "Request": {
                    "TransactionReference": {"CustomerContext": "caller-context"}
                },
                "Shipment": {},
            }
        }
        original = copy.deepcopy(body)

        self.manager.create_shipment(request_body=body)

        sent_body = self.fake_http_client.calls[0]["kwargs"]["json_body"]
        self.assertEqual(sent_body, original)
        self.assertEqual(body, original)

    def test_create_shipment_same_idempotency_key_is_not_deduped_locally(self) -> None:
        body = {"ShipmentRequest": {"Request": {}, "Shipment": {}}}

        first = self.manager.create_shipment(
            request_body=body,
            idempotency_key="idem-repeat",
        )
        second = self.manager.create_shipment(
            request_body=body,
            idempotency_key="idem-repeat",
        )

        self.assertEqual(first, {"mock": True})
        self.assertEqual(second, {"mock": True})
        self.assertEqual(len(self.fake_http_client.calls), 2)
        contexts = [
            call["kwargs"]["json_body"]["ShipmentRequest"]["Request"]["TransactionReference"]["CustomerContext"]
            for call in self.fake_http_client.calls
        ]
        self.assertEqual(contexts, ["idem-repeat", "idem-repeat"])

    def test_create_shipment_does_not_retry_after_http_error(self) -> None:
        failing_http_client = FailingHTTPClient()
        self.manager.http_client = failing_http_client

        with self.assertRaises(ToolError):
            self.manager.create_shipment(
                request_body={"ShipmentRequest": {"Request": {}, "Shipment": {}}},
                idempotency_key="idem-no-retry",
            )

        self.assertEqual(len(failing_http_client.calls), 1)
        self.assertEqual(
            failing_http_client.calls[0]["operation"].operation_id,
            "Shipment",
        )



if __name__ == "__main__":
    unittest.main()
