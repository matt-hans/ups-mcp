import unittest

from mcp.server.fastmcp.exceptions import ToolError

from ups_mcp.tools import ToolManager


class FakeHTTPClient:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def call_operation(self, operation, **kwargs):  # noqa: ANN001
        self.calls.append({"operation": operation, "kwargs": kwargs})
        return {"mock": True}


class UploadPaperlessDocumentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = ToolManager(
            base_url="https://example.test", client_id="cid", client_secret="csec",
            account_number="SHIP123",
        )
        self.fake = FakeHTTPClient()
        self.manager.http_client = self.fake

    def test_upload_routes_and_constructs_payload(self) -> None:
        self.manager.upload_paperless_document(
            file_content_base64="dGVzdA==", file_name="invoice.pdf",
            file_format="pdf", document_type="002",
        )
        call = self.fake.calls[0]
        self.assertEqual(call["operation"].operation_id, "Upload")
        self.assertEqual(call["kwargs"]["path_params"]["version"], "v2")
        form = call["kwargs"]["json_body"]["UploadRequest"]["UserCreatedForm"][0]
        self.assertEqual(form["UserCreatedFormFile"], "dGVzdA==")
        self.assertEqual(form["UserCreatedFormFileFormat"], "pdf")

    def test_upload_injects_shipper_number_header(self) -> None:
        self.manager.upload_paperless_document(
            file_content_base64="dGVzdA==", file_name="inv.pdf",
            file_format="pdf", document_type="002",
        )
        self.assertEqual(self.fake.calls[0]["kwargs"]["additional_headers"]["ShipperNumber"], "SHIP123")

    def test_upload_explicit_shipper_overrides(self) -> None:
        self.manager.upload_paperless_document(
            file_content_base64="dGVzdA==", file_name="inv.pdf",
            file_format="pdf", document_type="002", shipper_number="OVERRIDE",
        )
        self.assertEqual(self.fake.calls[0]["kwargs"]["additional_headers"]["ShipperNumber"], "OVERRIDE")

    def test_upload_no_shipper_raises(self) -> None:
        self.manager.account_number = None
        with self.assertRaises(ToolError) as ctx:
            self.manager.upload_paperless_document(
                file_content_base64="dGVzdA==", file_name="inv.pdf",
                file_format="pdf", document_type="002",
            )
        self.assertIn("ShipperNumber", str(ctx.exception))

    def test_upload_invalid_format_raises(self) -> None:
        with self.assertRaises(ToolError) as ctx:
            self.manager.upload_paperless_document(
                file_content_base64="dGVzdA==", file_name="inv.exe",
                file_format="exe", document_type="002",
            )
        self.assertIn("file_format", str(ctx.exception))

    def test_upload_normalizes_format_to_lowercase(self) -> None:
        self.manager.upload_paperless_document(
            file_content_base64="dGVzdA==", file_name="inv.PDF",
            file_format="PDF", document_type="002",
        )
        form = self.fake.calls[0]["kwargs"]["json_body"]["UploadRequest"]["UserCreatedForm"][0]
        self.assertEqual(form["UserCreatedFormFileFormat"], "pdf")

    def test_contract_upload_payload_has_required_fields(self) -> None:
        self.manager.upload_paperless_document(
            file_content_base64="dGVzdA==", file_name="invoice.pdf",
            file_format="pdf", document_type="002",
        )
        body = self.fake.calls[0]["kwargs"]["json_body"]
        req = body["UploadRequest"]
        self.assertIn("ShipperNumber", req)
        self.assertIn("UserCreatedForm", req)
        form = req["UserCreatedForm"][0]
        for key in ("UserCreatedFormFileName", "UserCreatedFormFileFormat",
                     "UserCreatedFormDocumentType", "UserCreatedFormFile"):
            self.assertIn(key, form, f"Missing required field: {key}")


class PushDocumentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = ToolManager(
            base_url="https://example.test", client_id="cid", client_secret="csec",
            account_number="SHIP123",
        )
        self.fake = FakeHTTPClient()
        self.manager.http_client = self.fake

    def test_push_routes_and_constructs_payload(self) -> None:
        self.manager.push_document_to_shipment(
            document_id="DOC123", shipment_identifier="1Z999AA10123456784",
        )
        call = self.fake.calls[0]
        self.assertEqual(call["operation"].operation_id, "PushToImageRepository")
        body = call["kwargs"]["json_body"]["PushToImageRepositoryRequest"]
        self.assertEqual(body["FormsHistoryDocumentID"]["DocumentID"], ["DOC123"])
        self.assertEqual(body["ShipmentIdentifier"], "1Z999AA10123456784")

    def test_push_injects_shipper_header(self) -> None:
        self.manager.push_document_to_shipment(document_id="D", shipment_identifier="1Z")
        self.assertEqual(self.fake.calls[0]["kwargs"]["additional_headers"]["ShipperNumber"], "SHIP123")

    def test_push_no_shipper_raises(self) -> None:
        self.manager.account_number = None
        with self.assertRaises(ToolError):
            self.manager.push_document_to_shipment(document_id="D", shipment_identifier="1Z")


class DeletePaperlessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = ToolManager(
            base_url="https://example.test", client_id="cid", client_secret="csec",
            account_number="SHIP123",
        )
        self.fake = FakeHTTPClient()
        self.manager.http_client = self.fake

    def test_delete_routes_and_injects_headers(self) -> None:
        self.manager.delete_paperless_document(document_id="DOC456")
        call = self.fake.calls[0]
        self.assertEqual(call["operation"].operation_id, "Delete")
        headers = call["kwargs"]["additional_headers"]
        self.assertEqual(headers["ShipperNumber"], "SHIP123")
        self.assertEqual(headers["DocumentId"], "DOC456")

    def test_delete_no_shipper_raises(self) -> None:
        self.manager.account_number = None
        with self.assertRaises(ToolError):
            self.manager.delete_paperless_document(document_id="DOC456")


if __name__ == "__main__":
    unittest.main()
