# UPS MCP Logistics Expansion — Implementation Plan (v2)

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add 11 new MCP tools (Landed Cost, Paperless Documents, Locator, Pickup) to the UPS MCP server, expanding it from 7 to 18 tools.

**Architecture:** New tools are organized in per-suite modules under `ups_mcp/tools/`. Shared builders eliminate repeated address/transaction scaffolding. `server.py` exposes `Literal`-typed parameters. `http_client.py` supports `additional_headers` with reserved-header protection. Contract tests validate payloads against OpenAPI-required fields.

**Tech Stack:** Python 3.11+, FastMCP, requests, PyYAML, unittest

**Design doc:** `docs/plans/2026-02-15-logistics-expansion-design.md`

---

## Task 1: Infrastructure — additional_headers with reserved-header protection

**Files:**
- Modify: `ups_mcp/http_client.py:22-32` (call_operation signature) and `:50-54` (headers dict)
- Test: `tests/test_http_client.py`

**Step 1: Write the failing tests**

Add to `tests/test_http_client.py`, inside `UPSHTTPClientTests`:

```python
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
```

**Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_http_client.py -v`
Expected: 4 new tests FAIL — `call_operation()` does not accept `additional_headers`

**Step 3: Implement additional_headers in http_client.py**

In `ups_mcp/http_client.py`, modify `call_operation`:

1. Add `additional_headers: dict[str, str] | None = None,` parameter after `transaction_src` (line 31).
2. After building the `headers` dict (after line 54), add:

```python
if additional_headers:
    for k, v in additional_headers.items():
        if v is not None and k not in headers:
            headers[k] = v
```

The `k not in headers` check prevents overwriting `Authorization`, `transId`, and `transactionSrc`.

**Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_http_client.py -v`
Expected: All tests PASS (existing + 4 new)

**Step 5: Commit**

```bash
git add ups_mcp/http_client.py tests/test_http_client.py
git commit -m "feat: add additional_headers support to UPSHTTPClient with reserved-header protection"
```

---

## Task 2: Infrastructure — constants, registry, account_number, shared builders

**Files:**
- Modify: `ups_mcp/constants.py`
- Modify: `ups_mcp/openapi_registry.py:13` (DEFAULT_SPEC_FILES)
- Modify: `ups_mcp/server.py:32-38` (_initialize_tool_manager)
- Modify: `ups_mcp/tools.py:51-66` (ToolManager.__init__) and `:250-282` (_execute_operation)
- Test: `tests/test_tool_mapping.py`
- Test: `tests/test_openapi_registry.py`
- Test: `tests/test_package_data.py`

**Step 1: Update constants.py**

Add to end of `ups_mcp/constants.py`:

```python
LOCATOR_OPTIONS = {
    "access_point": "64",
    "retail": "32",
    "general": "1",
    "services": "8",
}

PICKUP_CANCEL_OPTIONS = {
    "account": "01",
    "prn": "02",
}

PAPERLESS_VALID_FORMATS = frozenset({
    "pdf", "doc", "docx", "xls", "xlsx", "txt", "rtf", "tif", "jpg",
})
```

**Step 2: Expand DEFAULT_SPEC_FILES**

In `ups_mcp/openapi_registry.py`, line 13, change:

```python
DEFAULT_SPEC_FILES = ("Rating.yaml", "Shipping.yaml", "TimeInTransit.yaml")
```

to:

```python
DEFAULT_SPEC_FILES = (
    "Rating.yaml",
    "Shipping.yaml",
    "TimeInTransit.yaml",
    "LandedCost.yaml",
    "Paperless.yaml",
    "Locator.yaml",
    "Pickup.yaml",
)
```

**Step 3: Add account_number + additional_headers to tools.py**

In `ups_mcp/tools.py`:

1. Add `from . import constants` to imports.

2. In `ToolManager.__init__` (line 52-66), add `account_number: str | None = None` parameter before `registry`, store as `self.account_number = account_number`.

3. Add shared helper methods to `ToolManager` (DRY builders for repeated patterns):

```python
def _resolve_account(self, explicit: str | None = None) -> str | None:
    """Resolve account number: explicit arg > self.account_number > None."""
    return explicit or self.account_number

def _require_account(self, explicit: str | None = None, header_name: str = "AccountNumber") -> str:
    """Resolve account number or raise ToolError if unavailable."""
    resolved = self._resolve_account(explicit)
    if not resolved:
        raise ToolError(f"{header_name} is required via argument or UPS_ACCOUNT_NUMBER env var")
    return resolved

@staticmethod
def _build_transaction_ref(context: str = "ups-mcp") -> dict[str, Any]:
    """Build the standard TransactionReference object."""
    return {"TransactionReference": {"CustomerContext": context}}
```

4. In `_execute_operation` (line 250-282):
   - Add `additional_headers: dict[str, str] | None = None,` parameter after `transaction_src`.
   - Pass it through to `self.http_client.call_operation(...)` as `additional_headers=additional_headers`.

**Step 4: Update server.py _initialize_tool_manager**

In `ups_mcp/server.py`, modify `_initialize_tool_manager` (line 32-38) to pass `account_number`:

```python
def _initialize_tool_manager() -> None:
    global tool_manager
    tool_manager = tools.ToolManager(
        base_url=base_url,
        client_id=client_id,
        client_secret=client_secret,
        account_number=os.getenv("UPS_ACCOUNT_NUMBER"),
    )
```

**Step 5: Write tests**

Add to `tests/test_tool_mapping.py`:

```python
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
```

Update `tests/test_openapi_registry.py`:

- `test_registry_exposes_expected_non_deprecated_operations_from_bundled_specs`: Update expected IDs to include all new operation IDs from the 4 new specs.
- `_write_override_specs`: Add stub YAML for `LandedCost.yaml`, `Paperless.yaml`, `Locator.yaml`, `Pickup.yaml` matching the non-deprecated operation IDs.
- `test_incomplete_override_specs_dir_raises_actionable_error`: Still valid (missing TimeInTransit).

The expected non-deprecated operation IDs become:

```python
expected_ids = {
    "Rate", "Shipment", "VoidShipment", "LabelRecovery", "TimeInTransit",
    "LandedCost",
    "Upload", "PushToImageRepository", "Delete",
    "Locator",
    "Pickup Rate", "Pickup Pending Status", "Pickup Cancel",
    "Pickup Creation", "Pickup Get Political Division1 List",
    "Pickup Get Service Center Facilities",
}
```

`tests/test_package_data.py` needs no changes — it already iterates `DEFAULT_SPEC_FILES` dynamically.

**Step 6: Run tests**

Run: `python3 -m pytest tests/test_tool_mapping.py tests/test_openapi_registry.py tests/test_package_data.py -v`
Expected: All PASS

**Step 7: Commit**

```bash
git add ups_mcp/constants.py ups_mcp/openapi_registry.py ups_mcp/server.py ups_mcp/tools.py tests/test_tool_mapping.py tests/test_openapi_registry.py
git commit -m "feat: expand registry to 7 specs, add constants, account_number, shared builders"
```

---

## Task 3: Landed Cost — ToolManager method + unit tests + contract tests

**Files:**
- Modify: `ups_mcp/tools.py` (add operation ID constant + `get_landed_cost_quote` method)
- Create: `tests/test_landed_cost_tools.py`

**Step 1: Write the failing tests (unit + contract)**

Create `tests/test_landed_cost_tools.py`:

```python
import unittest

from mcp.server.fastmcp.exceptions import ToolError

from ups_mcp.tools import ToolManager


class FakeHTTPClient:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def call_operation(self, operation, **kwargs):  # noqa: ANN001
        self.calls.append({"operation": operation, "kwargs": kwargs})
        return {"LandedCostResponse": {"shipment": {}}}


class LandedCostToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = ToolManager(
            base_url="https://example.test",
            client_id="cid",
            client_secret="csec",
            account_number="ACCT123",
        )
        self.fake = FakeHTTPClient()
        self.manager.http_client = self.fake

    # --- Unit tests ---

    def test_routes_to_landed_cost_operation(self) -> None:
        self.manager.get_landed_cost_quote(
            currency_code="USD",
            export_country_code="US",
            import_country_code="GB",
            commodities=[{"hs_code": "6109.10", "price": 25.00, "quantity": 10}],
        )
        call = self.fake.calls[0]
        self.assertEqual(call["operation"].operation_id, "LandedCost")
        self.assertEqual(call["kwargs"]["path_params"]["version"], "v1")

    def test_injects_account_number_header(self) -> None:
        self.manager.get_landed_cost_quote(
            currency_code="USD",
            export_country_code="US",
            import_country_code="GB",
            commodities=[{"price": 10, "quantity": 1}],
        )
        headers = self.fake.calls[0]["kwargs"]["additional_headers"]
        self.assertEqual(headers["AccountNumber"], "ACCT123")

    def test_explicit_account_overrides_default(self) -> None:
        self.manager.get_landed_cost_quote(
            currency_code="USD",
            export_country_code="US",
            import_country_code="CA",
            commodities=[{"price": 10, "quantity": 1}],
            account_number="OVERRIDE999",
        )
        self.assertEqual(self.fake.calls[0]["kwargs"]["additional_headers"]["AccountNumber"], "OVERRIDE999")

    def test_no_account_omits_header(self) -> None:
        self.manager.account_number = None
        self.manager.get_landed_cost_quote(
            currency_code="USD",
            export_country_code="US",
            import_country_code="GB",
            commodities=[{"price": 10, "quantity": 1}],
        )
        self.assertIsNone(self.fake.calls[0]["kwargs"].get("additional_headers"))

    def test_multiple_commodities_with_weight(self) -> None:
        self.manager.get_landed_cost_quote(
            currency_code="EUR",
            export_country_code="DE",
            import_country_code="US",
            commodities=[
                {"hs_code": "6109.10", "price": 25, "quantity": 10},
                {"hs_code": "6205.30", "price": 50, "quantity": 5, "weight": 2.5, "weight_unit": "KGS"},
            ],
        )
        items = self.fake.calls[0]["kwargs"]["json_body"]["LandedCostRequest"]["shipment"]["shipmentItems"]
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["commodityId"], "1")
        self.assertEqual(items[1]["commodityId"], "2")
        self.assertEqual(items[1]["grossWeight"], "2.5")
        self.assertEqual(items[1]["grossWeightUnit"], "KGS")
        self.assertNotIn("grossWeight", items[0])

    def test_missing_price_raises_tool_error(self) -> None:
        with self.assertRaises(ToolError) as ctx:
            self.manager.get_landed_cost_quote(
                currency_code="USD", export_country_code="US", import_country_code="GB",
                commodities=[{"quantity": 5}],
            )
        self.assertIn("price", str(ctx.exception))

    def test_missing_quantity_raises_tool_error(self) -> None:
        with self.assertRaises(ToolError) as ctx:
            self.manager.get_landed_cost_quote(
                currency_code="USD", export_country_code="US", import_country_code="GB",
                commodities=[{"price": 10}],
            )
        self.assertIn("quantity", str(ctx.exception))

    def test_default_and_custom_shipment_type(self) -> None:
        self.manager.get_landed_cost_quote(
            currency_code="USD", export_country_code="US", import_country_code="GB",
            commodities=[{"price": 10, "quantity": 1}],
        )
        body1 = self.fake.calls[0]["kwargs"]["json_body"]
        self.assertEqual(body1["LandedCostRequest"]["shipment"]["shipmentType"], "Sale")

        self.manager.get_landed_cost_quote(
            currency_code="USD", export_country_code="US", import_country_code="GB",
            commodities=[{"price": 10, "quantity": 1}], shipment_type="Gift",
        )
        body2 = self.fake.calls[1]["kwargs"]["json_body"]
        self.assertEqual(body2["LandedCostRequest"]["shipment"]["shipmentType"], "Gift")

    # --- Contract test: validates payload satisfies OpenAPI required fields ---

    def test_contract_payload_has_all_required_fields(self) -> None:
        """Verify generated payload includes all fields the LandedCost spec marks as required."""
        self.manager.get_landed_cost_quote(
            currency_code="USD",
            export_country_code="US",
            import_country_code="GB",
            commodities=[{"hs_code": "6109.10", "price": 25, "quantity": 10, "description": "T-shirts"}],
        )
        body = self.fake.calls[0]["kwargs"]["json_body"]

        # Top-level wrapper
        self.assertIn("LandedCostRequest", body)
        req = body["LandedCostRequest"]

        # Required top-level fields
        self.assertIn("currencyCode", req)
        self.assertIn("shipment", req)

        # Required shipment fields
        shipment = req["shipment"]
        self.assertIn("importCountryCode", shipment)
        self.assertIn("exportCountryCode", shipment)
        self.assertIn("shipmentItems", shipment)
        self.assertIsInstance(shipment["shipmentItems"], list)
        self.assertGreater(len(shipment["shipmentItems"]), 0)

        # Required per-item fields
        item = shipment["shipmentItems"][0]
        for key in ("commodityId", "priceEach", "quantity", "commodityCurrencyCode", "originCountryCode"):
            self.assertIn(key, item, f"Missing required commodity field: {key}")


if __name__ == "__main__":
    unittest.main()
```

**Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_landed_cost_tools.py -v`
Expected: FAIL — `ToolManager` has no attribute `get_landed_cost_quote`

**Step 3: Implement get_landed_cost_quote in tools.py**

Add constant after existing operation IDs:

```python
LANDED_COST_OPERATION_ID = "LandedCost"
```

Add method to `ToolManager` (after `get_time_in_transit`, before `_execute_operation`):

```python
def get_landed_cost_quote(
    self,
    currency_code: str,
    export_country_code: str,
    import_country_code: str,
    commodities: list[dict[str, Any]],
    shipment_type: str = "Sale",
    account_number: str | None = None,
    trans_id: str | None = None,
    transaction_src: str = "ups-mcp",
) -> dict[str, Any]:
    effective_account = self._resolve_account(account_number)

    shipment_items = []
    for idx, item in enumerate(commodities):
        if "price" not in item:
            raise ToolError(f"Commodity at index {idx} missing required key 'price'")
        if "quantity" not in item:
            raise ToolError(f"Commodity at index {idx} missing required key 'quantity'")

        ups_item: dict[str, Any] = {
            "commodityId": str(idx + 1),
            "priceEach": str(item["price"]),
            "quantity": int(item["quantity"]),
            "commodityCurrencyCode": currency_code,
            "originCountryCode": export_country_code,
            "UOM": item.get("uom", "EA"),
            "hsCode": item.get("hs_code", ""),
            "description": item.get("description", ""),
        }
        if "weight" in item and "weight_unit" in item:
            ups_item["grossWeight"] = str(item["weight"])
            ups_item["grossWeightUnit"] = item["weight_unit"]
        shipment_items.append(ups_item)

    request_body = {
        "LandedCostRequest": {
            "currencyCode": currency_code,
            "allowPartialLandedCostResult": True,
            "alversion": 1,
            "shipment": {
                "importCountryCode": import_country_code,
                "exportCountryCode": export_country_code,
                "shipmentItems": shipment_items,
                "shipmentType": shipment_type,
            },
        }
    }

    return self._execute_operation(
        operation_id=LANDED_COST_OPERATION_ID,
        operation_name="get_landed_cost_quote",
        path_params={"version": "v1"},
        query_params=None,
        request_body=request_body,
        trans_id=trans_id,
        transaction_src=transaction_src,
        additional_headers={"AccountNumber": effective_account} if effective_account else None,
    )
```

**Step 4: Run tests**

Run: `python3 -m pytest tests/test_landed_cost_tools.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add ups_mcp/tools.py tests/test_landed_cost_tools.py
git commit -m "feat: add get_landed_cost_quote to ToolManager with contract tests"
```

---

## Task 4: Paperless Documents — 3 ToolManager methods + tests

**Files:**
- Modify: `ups_mcp/tools.py` (add 3 operation ID constants + 3 methods)
- Create: `tests/test_paperless_tools.py`

**Step 1: Write the failing tests**

Create `tests/test_paperless_tools.py`:

```python
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
```

**Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_paperless_tools.py -v`
Expected: FAIL — missing methods

**Step 3: Implement 3 Paperless methods in tools.py**

Add operation ID constants:

```python
PAPERLESS_UPLOAD_OPERATION_ID = "Upload"
PAPERLESS_PUSH_OPERATION_ID = "PushToImageRepository"
PAPERLESS_DELETE_OPERATION_ID = "Delete"
```

Add 3 methods to `ToolManager`. Each uses `self._require_account(shipper_number, "ShipperNumber")` and `self._build_transaction_ref(transaction_src)` (DRY builders from Task 2):

```python
def upload_paperless_document(
    self,
    file_content_base64: str,
    file_name: str,
    file_format: str,
    document_type: str,
    shipper_number: str | None = None,
    trans_id: str | None = None,
    transaction_src: str = "ups-mcp",
) -> dict[str, Any]:
    effective_shipper = self._require_account(shipper_number, "ShipperNumber")
    normalized_format = file_format.lower()
    if normalized_format not in constants.PAPERLESS_VALID_FORMATS:
        raise ToolError(
            f"Invalid file_format '{file_format}'. "
            f"Supported: {', '.join(sorted(constants.PAPERLESS_VALID_FORMATS))}"
        )

    request_body = {
        "UploadRequest": {
            "Request": self._build_transaction_ref(transaction_src),
            "ShipperNumber": effective_shipper,
            "UserCreatedForm": [{
                "UserCreatedFormFileName": file_name,
                "UserCreatedFormFileFormat": normalized_format,
                "UserCreatedFormDocumentType": document_type,
                "UserCreatedFormFile": file_content_base64,
            }],
        }
    }
    return self._execute_operation(
        operation_id=PAPERLESS_UPLOAD_OPERATION_ID,
        operation_name="upload_paperless_document",
        path_params={"version": "v2"},
        query_params=None, request_body=request_body,
        trans_id=trans_id, transaction_src=transaction_src,
        additional_headers={"ShipperNumber": effective_shipper},
    )

def push_document_to_shipment(
    self,
    document_id: str,
    shipment_identifier: str,
    shipment_type: str = "1",
    shipper_number: str | None = None,
    trans_id: str | None = None,
    transaction_src: str = "ups-mcp",
) -> dict[str, Any]:
    effective_shipper = self._require_account(shipper_number, "ShipperNumber")
    request_body = {
        "PushToImageRepositoryRequest": {
            "Request": self._build_transaction_ref(transaction_src),
            "ShipperNumber": effective_shipper,
            "FormsHistoryDocumentID": {"DocumentID": [document_id]},
            "ShipmentIdentifier": shipment_identifier,
            "ShipmentType": shipment_type,
        }
    }
    return self._execute_operation(
        operation_id=PAPERLESS_PUSH_OPERATION_ID,
        operation_name="push_document_to_shipment",
        path_params={"version": "v2"},
        query_params=None, request_body=request_body,
        trans_id=trans_id, transaction_src=transaction_src,
        additional_headers={"ShipperNumber": effective_shipper},
    )

def delete_paperless_document(
    self,
    document_id: str,
    shipper_number: str | None = None,
    trans_id: str | None = None,
    transaction_src: str = "ups-mcp",
) -> dict[str, Any]:
    effective_shipper = self._require_account(shipper_number, "ShipperNumber")
    return self._execute_operation(
        operation_id=PAPERLESS_DELETE_OPERATION_ID,
        operation_name="delete_paperless_document",
        path_params={"version": "v2"},
        query_params=None, request_body=None,
        trans_id=trans_id, transaction_src=transaction_src,
        additional_headers={"ShipperNumber": effective_shipper, "DocumentId": document_id},
    )
```

**Step 4: Run tests**

Run: `python3 -m pytest tests/test_paperless_tools.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add ups_mcp/tools.py tests/test_paperless_tools.py
git commit -m "feat: add paperless document tools (upload, push, delete) to ToolManager"
```

---

## Task 5: Locator — ToolManager method + tests (version v3)

**Files:**
- Modify: `ups_mcp/tools.py` (add `find_locations` method)
- Create: `tests/test_locator_tools.py`

**Step 1: Write the failing tests**

Create `tests/test_locator_tools.py`:

```python
import unittest

from mcp.server.fastmcp.exceptions import ToolError

from ups_mcp.tools import ToolManager


class FakeHTTPClient:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def call_operation(self, operation, **kwargs):  # noqa: ANN001
        self.calls.append({"operation": operation, "kwargs": kwargs})
        return {"LocatorResponse": {"SearchResults": {}}}


class FindLocationsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = ToolManager(
            base_url="https://example.test", client_id="cid", client_secret="csec",
        )
        self.fake = FakeHTTPClient()
        self.manager.http_client = self.fake

    def _call_default(self, **overrides):
        defaults = dict(
            location_type="general", address_line="123 Main St", city="Atlanta",
            state="GA", postal_code="30301", country_code="US",
        )
        defaults.update(overrides)
        return self.manager.find_locations(**defaults)

    def test_maps_access_point_to_64(self) -> None:
        self._call_default(location_type="access_point")
        self.assertEqual(self.fake.calls[0]["kwargs"]["path_params"]["reqOption"], "64")

    def test_maps_retail_to_32(self) -> None:
        self._call_default(location_type="retail")
        self.assertEqual(self.fake.calls[0]["kwargs"]["path_params"]["reqOption"], "32")

    def test_maps_general_to_1(self) -> None:
        self._call_default(location_type="general")
        self.assertEqual(self.fake.calls[0]["kwargs"]["path_params"]["reqOption"], "1")

    def test_invalid_location_type_raises(self) -> None:
        with self.assertRaises(ToolError) as ctx:
            self._call_default(location_type="warehouse")
        self.assertIn("location_type", str(ctx.exception))

    def test_uses_version_v3(self) -> None:
        self._call_default()
        self.assertEqual(self.fake.calls[0]["kwargs"]["path_params"]["version"], "v3")

    def test_constructs_origin_address(self) -> None:
        self._call_default()
        body = self.fake.calls[0]["kwargs"]["json_body"]
        addr = body["LocatorRequest"]["OriginAddress"]["AddressKeyFormat"]
        self.assertEqual(addr["AddressLine"], "123 Main St")
        self.assertEqual(addr["PoliticalDivision2"], "Atlanta")
        self.assertEqual(addr["CountryCode"], "US")

    def test_default_radius_and_unit(self) -> None:
        self._call_default()
        body = self.fake.calls[0]["kwargs"]["json_body"]
        self.assertEqual(body["LocatorRequest"]["LocationSearchCriteria"]["SearchRadius"], "15.0")
        self.assertEqual(body["LocatorRequest"]["UnitOfMeasurement"]["Code"], "MI")

    def test_access_point_includes_access_point_search(self) -> None:
        self._call_default(location_type="access_point")
        criteria = self.fake.calls[0]["kwargs"]["json_body"]["LocatorRequest"]["LocationSearchCriteria"]
        self.assertEqual(criteria["AccessPointSearch"]["AccessPointStatus"], "01")

    def test_non_access_point_omits_access_point_search(self) -> None:
        self._call_default(location_type="retail")
        criteria = self.fake.calls[0]["kwargs"]["json_body"]["LocatorRequest"]["LocationSearchCriteria"]
        self.assertNotIn("AccessPointSearch", criteria)

    def test_contract_payload_has_required_fields(self) -> None:
        """LocatorRequest spec requires: Request, OriginAddress, Translate."""
        self._call_default()
        req = self.fake.calls[0]["kwargs"]["json_body"]["LocatorRequest"]
        self.assertIn("Request", req)
        self.assertIn("OriginAddress", req)
        self.assertIn("Translate", req)


if __name__ == "__main__":
    unittest.main()
```

**Step 2: Run tests, verify they fail**

Run: `python3 -m pytest tests/test_locator_tools.py -v`

**Step 3: Implement find_locations**

Add constant:

```python
LOCATOR_OPERATION_ID = "Locator"
```

Add method to ToolManager:

```python
def find_locations(
    self,
    location_type: str,
    address_line: str,
    city: str,
    state: str,
    postal_code: str,
    country_code: str,
    radius: float = 15.0,
    unit_of_measure: str = "MI",
    trans_id: str | None = None,
    transaction_src: str = "ups-mcp",
) -> dict[str, Any]:
    req_option = constants.LOCATOR_OPTIONS.get(location_type)
    if not req_option:
        allowed = ", ".join(sorted(constants.LOCATOR_OPTIONS.keys()))
        raise ToolError(f"Invalid location_type '{location_type}'. Must be one of: {allowed}")

    search_criteria: dict[str, Any] = {"SearchRadius": str(radius)}
    if req_option == "64":
        search_criteria["AccessPointSearch"] = {"AccessPointStatus": "01"}

    request_body = {
        "LocatorRequest": {
            "Request": {"RequestAction": "Locator"},
            "OriginAddress": {
                "AddressKeyFormat": {
                    "AddressLine": address_line,
                    "PoliticalDivision2": city,
                    "PoliticalDivision1": state,
                    "PostcodePrimaryLow": postal_code,
                    "CountryCode": country_code,
                }
            },
            "Translate": {"Locale": "en_US"},
            "UnitOfMeasurement": {"Code": unit_of_measure},
            "LocationSearchCriteria": search_criteria,
        }
    }

    return self._execute_operation(
        operation_id=LOCATOR_OPERATION_ID,
        operation_name="find_locations",
        path_params={"version": "v3", "reqOption": req_option},
        query_params=None, request_body=request_body,
        trans_id=trans_id, transaction_src=transaction_src,
    )
```

Note: version is `v3` per the Locator.yaml spec default.

**Step 4: Run tests**

Run: `python3 -m pytest tests/test_locator_tools.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add ups_mcp/tools.py tests/test_locator_tools.py
git commit -m "feat: add find_locations to ToolManager with v3 version and contract tests"
```

---

## Task 6: Pickup Suite — 6 ToolManager methods + tests (spec-compliant payloads)

**Files:**
- Modify: `ups_mcp/tools.py` (add 6 operation ID constants + 6 methods)
- Create: `tests/test_pickup_tools.py`

**Step 1: Write the failing tests**

Create `tests/test_pickup_tools.py`:

```python
import unittest

from mcp.server.fastmcp.exceptions import ToolError

from ups_mcp.tools import ToolManager


class FakeHTTPClient:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def call_operation(self, operation, **kwargs):  # noqa: ANN001
        self.calls.append({"operation": operation, "kwargs": kwargs})
        return {"mock": True}


class RatePickupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = ToolManager(
            base_url="https://example.test", client_id="cid", client_secret="csec",
            account_number="ACCT123",
        )
        self.fake = FakeHTTPClient()
        self.manager.http_client = self.fake

    def test_routes_to_pickup_rate_operation(self) -> None:
        self.manager.rate_pickup(
            pickup_type="oncall", address_line="123 Main St", city="Atlanta",
            state="GA", postal_code="30301", country_code="US",
            pickup_date="20260301", ready_time="0900", close_time="1700",
        )
        call = self.fake.calls[0]
        self.assertEqual(call["operation"].operation_id, "Pickup Rate")
        self.assertEqual(call["kwargs"]["path_params"]["pickuptype"], "oncall")
        self.assertEqual(call["kwargs"]["path_params"]["version"], "v2409")

    def test_contract_rate_payload_has_all_required_fields(self) -> None:
        """Spec requires: ServiceDateOption, PickupAddress (with ResidentialIndicator,
        PostalCode, City, CountryCode), Request, AlternateAddressIndicator."""
        self.manager.rate_pickup(
            pickup_type="oncall", address_line="123 Main", city="Atlanta",
            state="GA", postal_code="30301", country_code="US",
            pickup_date="20260301", ready_time="0900", close_time="1700",
        )
        body = self.fake.calls[0]["kwargs"]["json_body"]
        req = body["PickupRateRequest"]

        # Top-level required fields
        self.assertIn("Request", req)
        self.assertIn("ServiceDateOption", req)
        self.assertIn("AlternateAddressIndicator", req)
        self.assertIn("PickupAddress", req)

        # PickupAddress required fields
        addr = req["PickupAddress"]
        self.assertIn("ResidentialIndicator", addr)
        self.assertIn("PostalCode", addr)
        self.assertIn("City", addr)
        self.assertIn("CountryCode", addr)

        # PickupDateInfo (always included)
        self.assertIn("PickupDateInfo", req)
        date_info = req["PickupDateInfo"]
        self.assertIn("ReadyTime", date_info)
        self.assertIn("CloseTime", date_info)
        self.assertIn("PickupDate", date_info)


class SchedulePickupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = ToolManager(
            base_url="https://example.test", client_id="cid", client_secret="csec",
            account_number="ACCT123",
        )
        self.fake = FakeHTTPClient()
        self.manager.http_client = self.fake

    def _call_default(self, **overrides):
        defaults = dict(
            pickup_date="20260301", ready_time="0900", close_time="1700",
            address_line="123 Main St", city="Atlanta", state="GA",
            postal_code="30301", country_code="US",
            contact_name="John Doe", phone_number="5551234567",
        )
        defaults.update(overrides)
        return self.manager.schedule_pickup(**defaults)

    def test_routes_to_pickup_creation(self) -> None:
        self._call_default()
        call = self.fake.calls[0]
        self.assertEqual(call["operation"].operation_id, "Pickup Creation")
        self.assertEqual(call["kwargs"]["path_params"]["version"], "v2409")

    def test_contract_schedule_payload_has_all_required_fields(self) -> None:
        """Spec requires: PickupDateInfo, PickupAddress (CompanyName, ContactName,
        AddressLine, City, CountryCode, ResidentialIndicator, Phone.Number),
        Request, PaymentMethod, PickupPiece, RatePickupIndicator,
        AlternateAddressIndicator. Account goes in Shipper.Account.AccountNumber."""
        self._call_default()
        body = self.fake.calls[0]["kwargs"]["json_body"]
        req = body["PickupCreationRequest"]

        # Top-level required
        for key in ("Request", "RatePickupIndicator", "AlternateAddressIndicator",
                     "PaymentMethod", "PickupDateInfo", "PickupAddress", "PickupPiece"):
            self.assertIn(key, req, f"Missing required top-level field: {key}")

        # Shipper nesting: Shipper.Account.AccountNumber
        self.assertIn("Shipper", req)
        self.assertIn("Account", req["Shipper"])
        self.assertIn("AccountNumber", req["Shipper"]["Account"])
        self.assertIn("AccountCountryCode", req["Shipper"]["Account"])

        # PickupAddress required
        addr = req["PickupAddress"]
        for key in ("CompanyName", "ContactName", "AddressLine", "City",
                     "CountryCode", "ResidentialIndicator", "Phone"):
            self.assertIn(key, addr, f"Missing PickupAddress field: {key}")
        self.assertIn("Number", addr["Phone"])

        # PickupDateInfo required
        for key in ("ReadyTime", "CloseTime", "PickupDate"):
            self.assertIn(key, req["PickupDateInfo"])

        # PickupPiece required per-item
        self.assertIsInstance(req["PickupPiece"], list)
        piece = req["PickupPiece"][0]
        for key in ("ServiceCode", "Quantity", "DestinationCountryCode", "ContainerCode"):
            self.assertIn(key, piece)

    def test_ready_time_after_close_time_raises(self) -> None:
        with self.assertRaises(ToolError) as ctx:
            self._call_default(ready_time="1800", close_time="0900")
        self.assertIn("ready_time", str(ctx.exception).lower())

    def test_uses_account_in_shipper_nesting(self) -> None:
        self._call_default()
        body = self.fake.calls[0]["kwargs"]["json_body"]
        acct = body["PickupCreationRequest"]["Shipper"]["Account"]["AccountNumber"]
        self.assertEqual(acct, "ACCT123")


class CancelPickupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = ToolManager(
            base_url="https://example.test", client_id="cid", client_secret="csec",
            account_number="ACCT123",
        )
        self.fake = FakeHTTPClient()
        self.manager.http_client = self.fake

    def test_cancel_by_account_maps_to_01(self) -> None:
        self.manager.cancel_pickup(cancel_by="account")
        self.assertEqual(self.fake.calls[0]["kwargs"]["path_params"]["CancelBy"], "01")

    def test_cancel_by_prn_maps_to_02_and_injects_header(self) -> None:
        self.manager.cancel_pickup(cancel_by="prn", prn="PRN123456789")
        call = self.fake.calls[0]
        self.assertEqual(call["kwargs"]["path_params"]["CancelBy"], "02")
        self.assertEqual(call["kwargs"]["additional_headers"]["Prn"], "PRN123456789")

    def test_cancel_by_prn_without_prn_raises(self) -> None:
        with self.assertRaises(ToolError):
            self.manager.cancel_pickup(cancel_by="prn")

    def test_invalid_cancel_by_raises(self) -> None:
        with self.assertRaises(ToolError):
            self.manager.cancel_pickup(cancel_by="invalid")


class GetPickupStatusTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = ToolManager(
            base_url="https://example.test", client_id="cid", client_secret="csec",
            account_number="ACCT123",
        )
        self.fake = FakeHTTPClient()
        self.manager.http_client = self.fake

    def test_routes_and_injects_header(self) -> None:
        self.manager.get_pickup_status(pickup_type="oncall")
        call = self.fake.calls[0]
        self.assertEqual(call["operation"].operation_id, "Pickup Pending Status")
        self.assertEqual(call["kwargs"]["additional_headers"]["AccountNumber"], "ACCT123")

    def test_no_account_raises(self) -> None:
        self.manager.account_number = None
        with self.assertRaises(ToolError):
            self.manager.get_pickup_status(pickup_type="oncall")


class GetPoliticalDivisionsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = ToolManager(
            base_url="https://example.test", client_id="cid", client_secret="csec",
        )
        self.fake = FakeHTTPClient()
        self.manager.http_client = self.fake

    def test_routes_correctly(self) -> None:
        self.manager.get_political_divisions(country_code="US")
        call = self.fake.calls[0]
        self.assertEqual(call["operation"].operation_id, "Pickup Get Political Division1 List")
        self.assertEqual(call["kwargs"]["path_params"]["countrycode"], "US")
        self.assertIsNone(call["kwargs"]["json_body"])


class GetServiceCenterFacilitiesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = ToolManager(
            base_url="https://example.test", client_id="cid", client_secret="csec",
        )
        self.fake = FakeHTTPClient()
        self.manager.http_client = self.fake

    def test_routes_and_constructs_payload(self) -> None:
        self.manager.get_service_center_facilities(
            city="Atlanta", state="GA", postal_code="30301", country_code="US",
        )
        call = self.fake.calls[0]
        self.assertEqual(call["operation"].operation_id, "Pickup Get Service Center Facilities")
        self.assertIn("PickupGetServiceCenterFacilitiesRequest", call["kwargs"]["json_body"])


if __name__ == "__main__":
    unittest.main()
```

**Step 2: Run tests, verify fail**

Run: `python3 -m pytest tests/test_pickup_tools.py -v`

**Step 3: Implement 6 Pickup methods**

Add operation ID constants:

```python
PICKUP_RATE_OPERATION_ID = "Pickup Rate"
PICKUP_PENDING_STATUS_OPERATION_ID = "Pickup Pending Status"
PICKUP_CANCEL_OPERATION_ID = "Pickup Cancel"
PICKUP_CREATION_OPERATION_ID = "Pickup Creation"
PICKUP_POLITICAL_DIVISIONS_OPERATION_ID = "Pickup Get Political Division1 List"
PICKUP_SERVICE_CENTER_OPERATION_ID = "Pickup Get Service Center Facilities"
```

Add 6 methods. **Critical: Pickup payloads match the Pickup.yaml spec exactly.**

```python
def rate_pickup(
    self,
    pickup_type: str,
    address_line: str,
    city: str,
    state: str,
    postal_code: str,
    country_code: str,
    pickup_date: str,
    ready_time: str,
    close_time: str,
    service_date_option: str = "02",
    residential_indicator: str = "Y",
    service_code: str = "001",
    container_code: str = "01",
    quantity: int = 1,
    destination_country_code: str = "US",
    trans_id: str | None = None,
    transaction_src: str = "ups-mcp",
) -> dict[str, Any]:
    request_body = {
        "PickupRateRequest": {
            "Request": self._build_transaction_ref(transaction_src),
            "ServiceDateOption": service_date_option,
            "AlternateAddressIndicator": "N",
            "PickupAddress": {
                "AddressLine": address_line,
                "City": city,
                "StateProvince": state,
                "PostalCode": postal_code,
                "CountryCode": country_code,
                "ResidentialIndicator": residential_indicator,
            },
            "PickupDateInfo": {
                "PickupDate": pickup_date,
                "ReadyTime": ready_time,
                "CloseTime": close_time,
            },
            "PickupPiece": [{
                "ServiceCode": service_code,
                "Quantity": str(quantity),
                "DestinationCountryCode": destination_country_code,
                "ContainerCode": container_code,
            }],
        }
    }
    return self._execute_operation(
        operation_id=PICKUP_RATE_OPERATION_ID,
        operation_name="rate_pickup",
        path_params={"version": "v2409", "pickuptype": pickup_type},
        query_params=None, request_body=request_body,
        trans_id=trans_id, transaction_src=transaction_src,
    )

def schedule_pickup(
    self,
    pickup_date: str,
    ready_time: str,
    close_time: str,
    address_line: str,
    city: str,
    state: str,
    postal_code: str,
    country_code: str,
    contact_name: str,
    phone_number: str,
    residential_indicator: str = "N",
    service_code: str = "001",
    container_code: str = "01",
    quantity: int = 1,
    weight: float = 5.0,
    weight_unit: str = "LBS",
    payment_method: str = "01",
    rate_pickup_indicator: str = "N",
    account_number: str | None = None,
    trans_id: str | None = None,
    transaction_src: str = "ups-mcp",
) -> dict[str, Any]:
    if ready_time >= close_time:
        raise ToolError(f"ready_time ({ready_time}) must be before close_time ({close_time})")

    effective_account = self._resolve_account(account_number) or ""

    request_body = {
        "PickupCreationRequest": {
            "Request": self._build_transaction_ref(transaction_src),
            "RatePickupIndicator": rate_pickup_indicator,
            "AlternateAddressIndicator": "N",
            "PaymentMethod": payment_method,
            "Shipper": {
                "Account": {
                    "AccountNumber": effective_account,
                    "AccountCountryCode": country_code,
                },
            },
            "PickupDateInfo": {
                "CloseTime": close_time,
                "ReadyTime": ready_time,
                "PickupDate": pickup_date,
            },
            "PickupAddress": {
                "CompanyName": contact_name,
                "ContactName": contact_name,
                "AddressLine": address_line,
                "City": city,
                "StateProvince": state,
                "PostalCode": postal_code,
                "CountryCode": country_code,
                "ResidentialIndicator": residential_indicator,
                "Phone": {"Number": phone_number},
            },
            "PickupPiece": [{
                "ServiceCode": service_code,
                "Quantity": str(quantity),
                "DestinationCountryCode": country_code,
                "ContainerCode": container_code,
            }],
            "TotalWeight": {
                "Weight": str(weight),
                "UnitOfMeasurement": weight_unit,
            },
        }
    }
    return self._execute_operation(
        operation_id=PICKUP_CREATION_OPERATION_ID,
        operation_name="schedule_pickup",
        path_params={"version": "v2409"},
        query_params=None, request_body=request_body,
        trans_id=trans_id, transaction_src=transaction_src,
    )

def cancel_pickup(
    self,
    cancel_by: str,
    prn: str | None = None,
    trans_id: str | None = None,
    transaction_src: str = "ups-mcp",
) -> dict[str, Any]:
    cancel_code = constants.PICKUP_CANCEL_OPTIONS.get(cancel_by)
    if not cancel_code:
        allowed = ", ".join(sorted(constants.PICKUP_CANCEL_OPTIONS.keys()))
        raise ToolError(f"Invalid cancel_by '{cancel_by}'. Must be one of: {allowed}")

    additional_headers: dict[str, str] | None = None
    if cancel_by == "prn":
        if not prn:
            raise ToolError("prn is required when cancel_by='prn'")
        additional_headers = {"Prn": prn}

    return self._execute_operation(
        operation_id=PICKUP_CANCEL_OPERATION_ID,
        operation_name="cancel_pickup",
        path_params={"version": "v2409", "CancelBy": cancel_code},
        query_params=None, request_body=None,
        trans_id=trans_id, transaction_src=transaction_src,
        additional_headers=additional_headers,
    )

def get_pickup_status(
    self,
    pickup_type: str,
    account_number: str | None = None,
    trans_id: str | None = None,
    transaction_src: str = "ups-mcp",
) -> dict[str, Any]:
    effective_account = self._require_account(account_number, "AccountNumber")
    return self._execute_operation(
        operation_id=PICKUP_PENDING_STATUS_OPERATION_ID,
        operation_name="get_pickup_status",
        path_params={"version": "v2409", "pickuptype": pickup_type},
        query_params=None, request_body=None,
        trans_id=trans_id, transaction_src=transaction_src,
        additional_headers={"AccountNumber": effective_account},
    )

def get_political_divisions(
    self,
    country_code: str,
    trans_id: str | None = None,
    transaction_src: str = "ups-mcp",
) -> dict[str, Any]:
    return self._execute_operation(
        operation_id=PICKUP_POLITICAL_DIVISIONS_OPERATION_ID,
        operation_name="get_political_divisions",
        path_params={"version": "v2409", "countrycode": country_code},
        query_params=None, request_body=None,
        trans_id=trans_id, transaction_src=transaction_src,
    )

def get_service_center_facilities(
    self,
    city: str,
    state: str,
    postal_code: str,
    country_code: str,
    pickup_pieces: int = 1,
    container_code: str = "01",
    trans_id: str | None = None,
    transaction_src: str = "ups-mcp",
) -> dict[str, Any]:
    request_body = {
        "PickupGetServiceCenterFacilitiesRequest": {
            "Request": self._build_transaction_ref(transaction_src),
            "PickupPiece": {
                "ServiceCode": "001",
                "Quantity": str(pickup_pieces),
                "ContainerCode": container_code,
            },
            "DestinationAddress": {
                "City": city,
                "StateProvince": state,
                "PostalCode": postal_code,
                "CountryCode": country_code,
            },
        }
    }
    return self._execute_operation(
        operation_id=PICKUP_SERVICE_CENTER_OPERATION_ID,
        operation_name="get_service_center_facilities",
        path_params={"version": "v2409"},
        query_params=None, request_body=request_body,
        trans_id=trans_id, transaction_src=transaction_src,
    )
```

**Step 4: Run tests**

Run: `python3 -m pytest tests/test_pickup_tools.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add ups_mcp/tools.py tests/test_pickup_tools.py
git commit -m "feat: add 6 pickup tools with spec-compliant payloads and contract tests"
```

---

## Task 7: Server Endpoints — 11 new @mcp.tool definitions with Literal types

**Files:**
- Modify: `ups_mcp/server.py` (add imports + 11 async tool functions)
- Create: `tests/test_server_new_tools.py`

**Step 1: Write tests**

Create `tests/test_server_new_tools.py` with a `FakeToolManager` that has all 11 new methods returning stub dicts, and `NewServerToolsTests(IsolatedAsyncioTestCase)` with one test per tool verifying it returns the raw response dict.

(See test pattern from existing `tests/test_server_tools.py` — inject `FakeToolManager` into `server.tool_manager`, call the async tool, assert response key.)

**Step 2: Implement 11 endpoints in server.py**

Add `from typing import Literal` to imports.

All enum-like parameters use `Literal` types:
- `location_type: Literal["access_point", "retail", "general", "services"]`
- `unit_of_measure: Literal["MI", "KM"]`
- `pickup_type: Literal["oncall", "smart", "both"]`
- `cancel_by: Literal["account", "prn"]`
- `weight_unit: Literal["LBS", "KGS"]`
- `residential_indicator: Literal["Y", "N"]`
- `service_date_option: Literal["01", "02", "03"]`
- `rate_pickup_indicator: Literal["Y", "N"]`
- `shipment_type: Literal["1", "2"]` (for push_document_to_shipment)

Each endpoint is a thin wrapper that calls `_require_tool_manager().<method>()`, converting empty strings to None for optional params (same pattern as existing tools).

**Important:** `rate_pickup` now includes `ready_time` and `close_time` as required parameters. `schedule_pickup` includes `residential_indicator` and `rate_pickup_indicator`.

**Step 3: Run tests**

Run: `python3 -m pytest tests/test_server_new_tools.py tests/test_server_tools.py -v`
Expected: All PASS

**Step 4: Commit**

```bash
git add ups_mcp/server.py tests/test_server_new_tools.py
git commit -m "feat: expose 11 new MCP tool endpoints with Literal-typed parameters"
```

---

## Task 8: README and documentation updates

**Files:**
- Modify: `README.md`

**Step 1: Update environment variables section**

Add `UPS_ACCOUNT_NUMBER` to the env vars list. Update `UPS_MCP_SPECS_DIR` description to list all 7 spec files:

```
- `UPS_ACCOUNT_NUMBER` - UPS Account/Shipper Number (used for Paperless, Landed Cost, and Pickup tools)
- `UPS_MCP_SPECS_DIR` - Optional absolute path to a directory containing `Rating.yaml`, `Shipping.yaml`, `TimeInTransit.yaml`, `LandedCost.yaml`, `Paperless.yaml`, `Locator.yaml`, and `Pickup.yaml`.
```

**Step 2: Update Available Tools section**

Add documentation for all 11 new tools with their args.

**Step 3: Fix stale response envelope docs**

The README mentions a `{"ok": true, ...}` envelope and schema validation that no longer exist. Update to reflect current behavior: tools return raw UPS API response dicts, and errors raise `ToolError` with JSON payloads.

**Step 4: Commit**

```bash
git add README.md
git commit -m "docs: update README with 11 new tools, UPS_ACCOUNT_NUMBER env var, and 7 spec files"
```

---

## Task 9: Full regression

**Step 1: Run entire test suite**

Run: `python3 -m pytest tests/ -v`
Expected: All tests PASS

**Step 2: Spot-check tool count**

Verify 18 `@mcp.tool()` decorators exist in server.py.

**Step 3: Commit any remaining changes**

```bash
git status
# Stage and commit if needed
```

---

## Changes Summary (vs v1 plan)

| Finding | Severity | Fix Applied |
|---------|----------|-------------|
| #1 Registry filename `Locater.yaml` | P0 | Changed to `Locator.yaml` everywhere |
| #2 rate_pickup missing ServiceDateOption, ResidentialIndicator, ReadyTime/CloseTime | P0 | Reworked payload with all spec-required fields; added `service_date_option`, `residential_indicator`, `ready_time`, `close_time` params |
| #3 schedule_pickup wrong account nesting, missing RatePickupIndicator | P0 | Account now at `Shipper.Account.AccountNumber`; added `RatePickupIndicator`, `ResidentialIndicator`, `CompanyName`, `Phone.Number` |
| #4 Locator version v2 vs v3 | P1 | Changed to `v3` per spec default |
| #5 Tests only check call shape, not payload contract | P1 | Added contract tests per suite validating OpenAPI-required fields |
| #6 Reserved headers can be overwritten | P1 | `k not in headers` guard in merge; test for reserved-header protection |
| #7 SRP: monolithic tools.py/server.py | P2 | Added shared builders (`_resolve_account`, `_require_account`, `_build_transaction_ref`) to ToolManager; full module split deferred to post-MVP |
| #8 DRY: repeated scaffolding | P2 | Shared builders eliminate `TransactionReference` and account-resolution duplication |
| #9 Literal typing inconsistency | P2 | All enum-like server.py params use `Literal` types |
| #10 README not updated | P2 | Task 8 covers README (env vars, spec files, 18-tool inventory, stale envelope docs) |

**Note on P2 #7 (module split):** The full `tools.py → tools/` package split was considered but deferred. The shared builders address the immediate DRY concern. A module split can happen in a follow-up milestone after the 11 tools are working and tested, avoiding unnecessary churn during initial implementation. The ToolManager stays in one file for now but uses shared helpers to keep method bodies concise.
