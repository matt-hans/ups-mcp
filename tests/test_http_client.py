import json
import unittest
from unittest.mock import Mock, patch

import requests
from mcp.server.fastmcp.exceptions import ToolError

from ups_mcp.http_client import UPSHTTPClient
from ups_mcp.openapi_registry import OperationSpec


class DummyOAuthManager:
    def __init__(self, token: str = "token-123") -> None:
        self.token = token

    def get_access_token(self) -> str:
        return self.token


def build_operation_spec() -> OperationSpec:
    return OperationSpec(
        source_file="Shipping.yaml",
        operation_id="Shipment",
        method="POST",
        path="/shipments/{version}/ship",
        deprecated=False,
        summary="Shipment",
        request_body_required=True,
        path_params=(),
        query_params=(),
        header_params=(),
    )


def make_response(status_code: int, payload):  # noqa: ANN001
    response = Mock()
    response.status_code = status_code
    if payload is None:
        response.content = b""
        response.text = ""
        response.json.side_effect = ValueError("no json")
    elif isinstance(payload, (dict, list)):
        serialized = json.dumps(payload)
        response.content = serialized.encode()
        response.text = serialized
        response.json.return_value = payload
    else:
        response.content = str(payload).encode()
        response.text = str(payload)
        response.json.side_effect = ValueError("not json")
    return response


class UPSHTTPClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = UPSHTTPClient(
            base_url="https://wwwcie.ups.com",
            oauth_manager=DummyOAuthManager(),
        )
        self.operation = build_operation_spec()

    @patch("ups_mcp.http_client.requests.request")
    def test_success_response_returns_raw_payload(self, mock_request: Mock) -> None:
        mock_request.return_value = make_response(200, {"ShipmentResponse": {"status": "ok"}})

        result = self.client.call_operation(
            self.operation,
            operation_name="create_shipment",
            path_params={"version": "v2409"},
            query_params={"additionaladdressvalidation": "city"},
            json_body={"ShipmentRequest": {}},
            trans_id="trans-xyz",
            transaction_src="ups-mcp",
        )

        self.assertEqual(result, {"ShipmentResponse": {"status": "ok"}})
        called_kwargs = mock_request.call_args.kwargs
        self.assertEqual(called_kwargs["params"]["additionaladdressvalidation"], "city")

    @patch("ups_mcp.http_client.requests.request")
    def test_error_response_raises_tool_error(self, mock_request: Mock) -> None:
        mock_request.return_value = make_response(
            429,
            {"response": {"errors": [{"message": "Rate limit exceeded"}]}},
        )

        with self.assertRaises(ToolError) as ctx:
            self.client.call_operation(
                self.operation,
                operation_name="create_shipment",
                path_params={"version": "v2409"},
                json_body={"ShipmentRequest": {}},
            )

        error_data = json.loads(str(ctx.exception))
        self.assertEqual(error_data["status_code"], 429)
        self.assertEqual(error_data["code"], "429")
        self.assertEqual(error_data["message"], "Rate limit exceeded")

    @patch("ups_mcp.http_client.requests.request")
    def test_request_exception_raises_tool_error(self, mock_request: Mock) -> None:
        mock_request.side_effect = requests.RequestException("network down")

        with self.assertRaises(ToolError) as ctx:
            self.client.call_operation(
                self.operation,
                operation_name="create_shipment",
                path_params={"version": "v2409"},
                json_body={"ShipmentRequest": {}},
            )

        error_data = json.loads(str(ctx.exception))
        self.assertEqual(error_data["code"], "REQUEST_ERROR")
        self.assertIn("network down", error_data["message"])

    def test_missing_path_parameter_raises_tool_error(self) -> None:
        with self.assertRaises(ToolError) as ctx:
            self.client.call_operation(
                self.operation,
                operation_name="create_shipment",
                path_params={},
                json_body={"ShipmentRequest": {}},
            )

        error_data = json.loads(str(ctx.exception))
        self.assertEqual(error_data["code"], "VALIDATION_ERROR")

    @patch("ups_mcp.http_client.requests.request")
    def test_path_params_are_url_encoded(self, mock_request: Mock) -> None:
        mock_request.return_value = make_response(200, {"ok": True})
        operation = OperationSpec(
            source_file="legacy",
            operation_id="TrackPackage",
            method="GET",
            path="/track/v1/details/{inquiryNum}",
            deprecated=False,
            summary="Track",
            request_body_required=False,
            path_params=(),
            query_params=(),
            header_params=(),
        )
        self.client.call_operation(
            operation,
            operation_name="track_package",
            path_params={"inquiryNum": "1Z 99/ABC"},
            query_params={"trackingnumber": ["A", "B"]},
        )
        called_kwargs = mock_request.call_args.kwargs
        self.assertTrue(called_kwargs["url"].endswith("/track/v1/details/1Z%2099%2FABC"))
        self.assertEqual(called_kwargs["params"]["trackingnumber"], ["A", "B"])


    @patch("ups_mcp.http_client.requests.request")
    def test_additional_headers_are_merged_into_request(self, mock_request: Mock) -> None:
        mock_request.return_value = make_response(200, {"ok": True})

        self.client.call_operation(
            self.operation,
            operation_name="create_shipment",
            path_params={"version": "v2409"},
            json_body={"ShipmentRequest": {}},
            additional_headers={"ShipperNumber": "ABC123", "AccountNumber": "XYZ"},
        )

        called_kwargs = mock_request.call_args.kwargs
        self.assertEqual(called_kwargs["headers"]["ShipperNumber"], "ABC123")
        self.assertEqual(called_kwargs["headers"]["AccountNumber"], "XYZ")
        self.assertIn("Authorization", called_kwargs["headers"])
        self.assertIn("transId", called_kwargs["headers"])

    @patch("ups_mcp.http_client.requests.request")
    def test_additional_headers_none_values_are_filtered(self, mock_request: Mock) -> None:
        mock_request.return_value = make_response(200, {"ok": True})

        self.client.call_operation(
            self.operation,
            operation_name="create_shipment",
            path_params={"version": "v2409"},
            json_body={"ShipmentRequest": {}},
            additional_headers={"ShipperNumber": "ABC123", "AccountNumber": None},
        )

        called_kwargs = mock_request.call_args.kwargs
        self.assertEqual(called_kwargs["headers"]["ShipperNumber"], "ABC123")
        self.assertNotIn("AccountNumber", called_kwargs["headers"])

    @patch("ups_mcp.http_client.requests.request")
    def test_additional_headers_cannot_overwrite_reserved_headers(self, mock_request: Mock) -> None:
        mock_request.return_value = make_response(200, {"ok": True})

        self.client.call_operation(
            self.operation,
            operation_name="create_shipment",
            path_params={"version": "v2409"},
            json_body={"ShipmentRequest": {}},
            additional_headers={"Authorization": "EVIL", "transId": "EVIL", "ShipperNumber": "OK"},
        )

        called_kwargs = mock_request.call_args.kwargs
        self.assertTrue(called_kwargs["headers"]["Authorization"].startswith("Bearer "))
        self.assertNotEqual(called_kwargs["headers"]["transId"], "EVIL")
        self.assertEqual(called_kwargs["headers"]["ShipperNumber"], "OK")

    @patch("ups_mcp.http_client.requests.request")
    def test_additional_headers_case_insensitive_reserved_protection(self, mock_request: Mock) -> None:
        """Lowercase variants of reserved headers must also be blocked."""
        mock_request.return_value = make_response(200, {"ok": True})

        self.client.call_operation(
            self.operation,
            operation_name="create_shipment",
            path_params={"version": "v2409"},
            json_body={"ShipmentRequest": {}},
            additional_headers={"authorization": "EVIL", "transid": "EVIL", "transactionsrc": "EVIL"},
        )

        called_kwargs = mock_request.call_args.kwargs
        self.assertTrue(called_kwargs["headers"]["Authorization"].startswith("Bearer "))
        self.assertNotEqual(called_kwargs["headers"]["transId"], "EVIL")
        self.assertNotEqual(called_kwargs["headers"]["transactionSrc"], "EVIL")
        # Verify the lowercase variants were NOT added as separate keys
        self.assertNotIn("authorization", called_kwargs["headers"])
        self.assertNotIn("transid", called_kwargs["headers"])
        self.assertNotIn("transactionsrc", called_kwargs["headers"])

    @patch("ups_mcp.http_client.requests.request")
    def test_no_additional_headers_leaves_default_headers_unchanged(self, mock_request: Mock) -> None:
        mock_request.return_value = make_response(200, {"ok": True})

        self.client.call_operation(
            self.operation,
            operation_name="create_shipment",
            path_params={"version": "v2409"},
            json_body={"ShipmentRequest": {}},
        )

        called_kwargs = mock_request.call_args.kwargs
        self.assertEqual(set(called_kwargs["headers"].keys()), {"Authorization", "transId", "transactionSrc"})


if __name__ == "__main__":
    unittest.main()
