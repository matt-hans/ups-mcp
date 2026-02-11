import unittest

from mcp.server.fastmcp.exceptions import ToolError

from ups_mcp.tools import ToolManager


class FakeHTTPClient:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def call_operation(self, operation, **kwargs):  # noqa: ANN001
        self.calls.append({"operation": operation, "kwargs": kwargs})
        return {"mock": True}


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

    def test_invalid_rate_requestoption_raises_tool_error(self) -> None:
        with self.assertRaises(ToolError) as ctx:
            self.manager.rate_shipment(
                requestoption="invalid-option",
                request_body={"RateRequest": {}},
            )

        self.assertIn("Invalid requestoption", str(ctx.exception))
        self.assertEqual(len(self.fake_http_client.calls), 0)



if __name__ == "__main__":
    unittest.main()
