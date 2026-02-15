# UPS MCP Logistics Expansion — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add 11 new MCP tools (Landed Cost, Paperless Documents, Locator, Pickup) to the UPS MCP server, expanding it from 7 to 18 tools.

**Architecture:** Each new tool follows the structured flat parameter pattern — `server.py` exposes typed parameters, `tools.py` ToolManager constructs UPS payloads internally, `http_client.py` handles transport. Infrastructure changes add `additional_headers` support to the HTTP client and `account_number` to the ToolManager.

**Tech Stack:** Python 3.11+, FastMCP, requests, PyYAML, unittest

**Design doc:** `docs/plans/2026-02-15-logistics-expansion-design.md`

---

## Task 1: Infrastructure — additional_headers in http_client.py

**Files:**
- Modify: `ups_mcp/http_client.py:22-32` (call_operation signature) and `:50-54` (headers dict)
- Test: `tests/test_http_client.py`

**Step 1: Write the failing test**

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
Expected: 3 new tests FAIL — `call_operation()` does not accept `additional_headers`

**Step 3: Implement additional_headers in http_client.py**

In `ups_mcp/http_client.py`, modify `call_operation`:

1. Add `additional_headers: dict[str, str] | None = None,` parameter after `transaction_src` (line 31).
2. After building the `headers` dict (after line 54), add:

```python
if additional_headers:
    headers.update({k: v for k, v in additional_headers.items() if v is not None})
```

**Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_http_client.py -v`
Expected: All tests PASS (existing + 3 new)

**Step 5: Commit**

```bash
git add ups_mcp/http_client.py tests/test_http_client.py
git commit -m "feat: add additional_headers support to UPSHTTPClient.call_operation"
```

---

## Task 2: Infrastructure — account_number and additional_headers in tools.py

**Files:**
- Modify: `ups_mcp/tools.py:51-66` (ToolManager.__init__) and `:250-282` (_execute_operation)
- Test: `tests/test_tool_mapping.py`

**Step 1: Write the failing test**

Add to `tests/test_tool_mapping.py`, inside `ToolMappingTests`:

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

**Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_tool_mapping.py -v`
Expected: FAIL — `ToolManager.__init__()` got unexpected keyword argument `account_number`

**Step 3: Implement changes in tools.py**

1. In `ToolManager.__init__` (line 52-66), add `account_number: str | None = None` parameter before `registry`, and store it as `self.account_number = account_number` before the existing `self.base_url = base_url` line.

2. In `_execute_operation` (line 250-282):
   - Add `additional_headers: dict[str, str] | None = None,` parameter after `transaction_src`.
   - Pass it through to `self.http_client.call_operation(...)` as `additional_headers=additional_headers`.

The full updated `_execute_operation` signature:

```python
def _execute_operation(
    self,
    *,
    operation_id: str,
    operation_name: str,
    path_params: dict[str, Any],
    query_params: dict[str, Any] | None,
    request_body: dict[str, Any] | None,
    trans_id: str | None,
    transaction_src: str,
    additional_headers: dict[str, str] | None = None,
) -> dict[str, Any]:
```

And the call at the bottom:

```python
return self.http_client.call_operation(
    operation,
    operation_name=operation_name,
    path_params=resolved_path_params,
    query_params=query_params,
    json_body=request_body,
    trans_id=trans_id,
    transaction_src=transaction_src,
    additional_headers=additional_headers,
)
```

**Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_tool_mapping.py tests/test_legacy_tools.py -v`
Expected: All PASS (existing behavior unchanged + new tests pass)

**Step 5: Commit**

```bash
git add ups_mcp/tools.py tests/test_tool_mapping.py
git commit -m "feat: add account_number to ToolManager and additional_headers to _execute_operation"
```

---

## Task 3: Infrastructure — constants and registry expansion

**Files:**
- Modify: `ups_mcp/constants.py`
- Modify: `ups_mcp/openapi_registry.py:13` (DEFAULT_SPEC_FILES)
- Modify: `ups_mcp/server.py:32-38` (_initialize_tool_manager)
- Test: `tests/test_openapi_registry.py`
- Test: `tests/test_package_data.py`

**Step 1: Update constants.py**

Add to the end of `ups_mcp/constants.py`:

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
    "Locater.yaml",
    "Pickup.yaml",
)
```

**Step 3: Update server.py _initialize_tool_manager**

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

**Step 4: Update test_openapi_registry.py**

In `tests/test_openapi_registry.py`:

Update `test_registry_exposes_expected_non_deprecated_operations_from_bundled_specs` (line 22-33):

```python
def test_registry_exposes_expected_non_deprecated_operations_from_bundled_specs(self) -> None:
    os.environ.pop("UPS_MCP_SPECS_DIR", None)
    registry = load_default_registry()
    operations = registry.list_operations(include_deprecated=False)
    operation_ids = {operation.operation_id for operation in operations}

    expected_ids = {
        # Existing
        "Rate", "Shipment", "VoidShipment", "LabelRecovery", "TimeInTransit",
        # LandedCost
        "LandedCost",
        # Paperless
        "Upload", "PushToImageRepository", "Delete",
        # Locator
        "Locator",
        # Pickup
        "Pickup Rate", "Pickup Pending Status", "Pickup Cancel",
        "Pickup Creation", "Pickup Get Political Division1 List",
        "Pickup Get Service Center Facilities",
    }
    self.assertEqual(operation_ids, expected_ids)
    self.assertTrue(all(not operation.deprecated for operation in operations))
```

Update the override-specs test `test_registry_uses_override_specs_dir_when_configured` (line 44-56) and `_write_override_specs` (line 71-177) to include stub specs for the 4 new files. Add these writes inside `_write_override_specs`:

```python
(output_dir / "LandedCost.yaml").write_text(
    textwrap.dedent("""
        openapi: 3.0.1
        info:
          title: LandedCost
          version: 1.0.0
        paths:
          /landedcost/{version}/quotes:
            post:
              operationId: LandedCost
              summary: Landed cost quote
              parameters:
                - in: path
                  name: version
                  required: true
                  schema:
                    type: string
    """).strip() + "\n",
    encoding="utf-8",
)
(output_dir / "Paperless.yaml").write_text(
    textwrap.dedent("""
        openapi: 3.0.1
        info:
          title: Paperless
          version: 1.0.0
        paths:
          /paperlessdocuments/{version}/upload:
            post:
              operationId: Upload
              summary: Upload document
              parameters:
                - in: path
                  name: version
                  required: true
                  schema:
                    type: string
          /paperlessdocuments/{version}/image:
            post:
              operationId: PushToImageRepository
              summary: Push to image repo
              parameters:
                - in: path
                  name: version
                  required: true
                  schema:
                    type: string
          /paperlessdocuments/{version}/DocumentId/ShipperNumber:
            delete:
              operationId: Delete
              summary: Delete document
              parameters:
                - in: path
                  name: version
                  required: true
                  schema:
                    type: string
    """).strip() + "\n",
    encoding="utf-8",
)
(output_dir / "Locater.yaml").write_text(
    textwrap.dedent("""
        openapi: 3.0.1
        info:
          title: Locater
          version: 1.0.0
        paths:
          /locations/{version}/search/availabilities/{reqOption}:
            post:
              operationId: Locator
              summary: Find locations
              parameters:
                - in: path
                  name: version
                  required: true
                  schema:
                    type: string
                - in: path
                  name: reqOption
                  required: true
                  schema:
                    type: string
    """).strip() + "\n",
    encoding="utf-8",
)
(output_dir / "Pickup.yaml").write_text(
    textwrap.dedent("""
        openapi: 3.0.1
        info:
          title: Pickup
          version: 1.0.0
        paths:
          /shipments/{version}/pickup/{pickuptype}:
            post:
              operationId: Pickup Rate
              summary: Rate pickup
              parameters:
                - in: path
                  name: version
                  required: true
                  schema:
                    type: string
                - in: path
                  name: pickuptype
                  required: true
                  schema:
                    type: string
            get:
              operationId: Pickup Pending Status
              summary: Pickup pending status
              parameters:
                - in: path
                  name: version
                  required: true
                  schema:
                    type: string
                - in: path
                  name: pickuptype
                  required: true
                  schema:
                    type: string
          /shipments/{version}/pickup/{CancelBy}:
            delete:
              operationId: Pickup Cancel
              summary: Cancel pickup
              parameters:
                - in: path
                  name: version
                  required: true
                  schema:
                    type: string
                - in: path
                  name: CancelBy
                  required: true
                  schema:
                    type: string
          /pickupcreation/{version}/pickup:
            post:
              operationId: Pickup Creation
              summary: Create pickup
              parameters:
                - in: path
                  name: version
                  required: true
                  schema:
                    type: string
          /pickup/{version}/countries/{countrycode}:
            get:
              operationId: Pickup Get Political Division1 List
              summary: Get political divisions
              parameters:
                - in: path
                  name: version
                  required: true
                  schema:
                    type: string
                - in: path
                  name: countrycode
                  required: true
                  schema:
                    type: string
          /pickup/{version}/servicecenterlocations:
            post:
              operationId: Pickup Get Service Center Facilities
              summary: Get service centers
              parameters:
                - in: path
                  name: version
                  required: true
                  schema:
                    type: string
    """).strip() + "\n",
    encoding="utf-8",
)
```

Also update the override test's expected operation IDs to include the new ones:

```python
def test_registry_uses_override_specs_dir_when_configured(self) -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        self._write_override_specs(Path(tmp_dir), rate_summary="Override Rate")
        os.environ["UPS_MCP_SPECS_DIR"] = tmp_dir
        load_default_registry.cache_clear()

        registry = load_default_registry()

    self.assertEqual(registry.get_operation("Rate").summary, "Override Rate")
```

And update the incomplete-specs test to account for a missing new file:

```python
def test_incomplete_override_specs_dir_raises_actionable_error(self) -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        self._write_override_specs(Path(tmp_dir), include_time_in_transit=False)
        os.environ["UPS_MCP_SPECS_DIR"] = tmp_dir
        load_default_registry.cache_clear()

        with self.assertRaises(OpenAPISpecLoadError) as ctx:
            load_default_registry()

    message = str(ctx.exception)
    self.assertIn("UPS_MCP_SPECS_DIR=", message)
    self.assertIn("TimeInTransit.yaml", message)
```

**Step 5: Run tests**

Run: `python3 -m pytest tests/test_openapi_registry.py tests/test_package_data.py -v`
Expected: All PASS

**Step 6: Commit**

```bash
git add ups_mcp/constants.py ups_mcp/openapi_registry.py ups_mcp/server.py tests/test_openapi_registry.py tests/test_package_data.py
git commit -m "feat: expand registry to load 7 spec files, add mapping constants, pass account_number in server"
```

---

## Task 4: Landed Cost — ToolManager method + tests

**Files:**
- Modify: `ups_mcp/tools.py` (add operation ID constant + `get_landed_cost_quote` method)
- Create: `tests/test_landed_cost_tools.py`

**Step 1: Write the failing tests**

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

    def test_get_landed_cost_quote_constructs_correct_payload(self) -> None:
        self.manager.get_landed_cost_quote(
            currency_code="USD",
            export_country_code="US",
            import_country_code="GB",
            commodities=[
                {"hs_code": "6109.10", "price": 25.00, "quantity": 10, "description": "T-shirts"},
            ],
        )

        self.assertEqual(len(self.fake.calls), 1)
        call = self.fake.calls[0]
        self.assertEqual(call["operation"].operation_id, "LandedCost")
        self.assertEqual(call["kwargs"]["path_params"]["version"], "v1")
        body = call["kwargs"]["json_body"]
        self.assertEqual(body["LandedCostRequest"]["currencyCode"], "USD")
        shipment = body["LandedCostRequest"]["shipment"]
        self.assertEqual(shipment["importCountryCode"], "GB")
        self.assertEqual(shipment["exportCountryCode"], "US")
        self.assertEqual(len(shipment["shipmentItems"]), 1)
        item = shipment["shipmentItems"][0]
        self.assertEqual(item["hsCode"], "6109.10")
        self.assertEqual(item["priceEach"], "25.0")
        self.assertEqual(item["quantity"], 10)
        self.assertEqual(item["commodityCurrencyCode"], "USD")
        self.assertEqual(item["originCountryCode"], "US")

    def test_get_landed_cost_quote_injects_account_number_header(self) -> None:
        self.manager.get_landed_cost_quote(
            currency_code="USD",
            export_country_code="US",
            import_country_code="GB",
            commodities=[{"price": 10, "quantity": 1}],
        )

        call = self.fake.calls[0]
        headers = call["kwargs"]["additional_headers"]
        self.assertEqual(headers["AccountNumber"], "ACCT123")

    def test_get_landed_cost_quote_explicit_account_overrides_default(self) -> None:
        self.manager.get_landed_cost_quote(
            currency_code="USD",
            export_country_code="US",
            import_country_code="CA",
            commodities=[{"price": 10, "quantity": 1}],
            account_number="OVERRIDE999",
        )

        call = self.fake.calls[0]
        self.assertEqual(call["kwargs"]["additional_headers"]["AccountNumber"], "OVERRIDE999")

    def test_get_landed_cost_quote_no_account_sends_none_header(self) -> None:
        self.manager.account_number = None
        self.manager.get_landed_cost_quote(
            currency_code="USD",
            export_country_code="US",
            import_country_code="GB",
            commodities=[{"price": 10, "quantity": 1}],
        )

        call = self.fake.calls[0]
        # additional_headers should be None when no account available
        self.assertIsNone(call["kwargs"].get("additional_headers"))

    def test_get_landed_cost_quote_multiple_commodities(self) -> None:
        self.manager.get_landed_cost_quote(
            currency_code="EUR",
            export_country_code="DE",
            import_country_code="US",
            commodities=[
                {"hs_code": "6109.10", "price": 25, "quantity": 10},
                {"hs_code": "6205.30", "price": 50, "quantity": 5, "weight": 2.5, "weight_unit": "KGS"},
            ],
        )

        body = self.fake.calls[0]["kwargs"]["json_body"]
        items = body["LandedCostRequest"]["shipment"]["shipmentItems"]
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["commodityId"], "1")
        self.assertEqual(items[1]["commodityId"], "2")
        self.assertEqual(items[1]["grossWeight"], "2.5")
        self.assertEqual(items[1]["grossWeightUnit"], "KGS")
        self.assertNotIn("grossWeight", items[0])

    def test_get_landed_cost_quote_missing_price_raises_tool_error(self) -> None:
        with self.assertRaises(ToolError) as ctx:
            self.manager.get_landed_cost_quote(
                currency_code="USD",
                export_country_code="US",
                import_country_code="GB",
                commodities=[{"quantity": 5}],
            )
        self.assertIn("price", str(ctx.exception))

    def test_get_landed_cost_quote_missing_quantity_raises_tool_error(self) -> None:
        with self.assertRaises(ToolError) as ctx:
            self.manager.get_landed_cost_quote(
                currency_code="USD",
                export_country_code="US",
                import_country_code="GB",
                commodities=[{"price": 10}],
            )
        self.assertIn("quantity", str(ctx.exception))

    def test_get_landed_cost_quote_default_shipment_type(self) -> None:
        self.manager.get_landed_cost_quote(
            currency_code="USD",
            export_country_code="US",
            import_country_code="GB",
            commodities=[{"price": 10, "quantity": 1}],
        )

        body = self.fake.calls[0]["kwargs"]["json_body"]
        self.assertEqual(body["LandedCostRequest"]["shipment"]["shipmentType"], "Sale")

    def test_get_landed_cost_quote_custom_shipment_type(self) -> None:
        self.manager.get_landed_cost_quote(
            currency_code="USD",
            export_country_code="US",
            import_country_code="GB",
            commodities=[{"price": 10, "quantity": 1}],
            shipment_type="Gift",
        )

        body = self.fake.calls[0]["kwargs"]["json_body"]
        self.assertEqual(body["LandedCostRequest"]["shipment"]["shipmentType"], "Gift")


if __name__ == "__main__":
    unittest.main()
```

**Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_landed_cost_tools.py -v`
Expected: FAIL — `ToolManager` has no attribute `get_landed_cost_quote`

**Step 3: Implement get_landed_cost_quote in tools.py**

Add after the existing operation ID constants (after line 15):

```python
LANDED_COST_OPERATION_ID = "LandedCost"
```

Add method to `ToolManager` class (after `get_time_in_transit`, before `_execute_operation`):

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
    effective_account = account_number or self.account_number

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

**Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_landed_cost_tools.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add ups_mcp/tools.py tests/test_landed_cost_tools.py
git commit -m "feat: add get_landed_cost_quote to ToolManager"
```

---

## Task 5: Paperless Documents — ToolManager methods + tests

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
            base_url="https://example.test",
            client_id="cid",
            client_secret="csec",
            account_number="SHIP123",
        )
        self.fake = FakeHTTPClient()
        self.manager.http_client = self.fake

    def test_upload_constructs_correct_payload(self) -> None:
        self.manager.upload_paperless_document(
            file_content_base64="dGVzdA==",
            file_name="invoice.pdf",
            file_format="pdf",
            document_type="002",
        )

        self.assertEqual(len(self.fake.calls), 1)
        call = self.fake.calls[0]
        self.assertEqual(call["operation"].operation_id, "Upload")
        self.assertEqual(call["kwargs"]["path_params"]["version"], "v2")
        body = call["kwargs"]["json_body"]
        form = body["UploadRequest"]["UserCreatedForm"][0]
        self.assertEqual(form["UserCreatedFormFile"], "dGVzdA==")
        self.assertEqual(form["UserCreatedFormFileName"], "invoice.pdf")
        self.assertEqual(form["UserCreatedFormFileFormat"], "pdf")
        self.assertEqual(form["UserCreatedFormDocumentType"], "002")

    def test_upload_injects_shipper_number_header(self) -> None:
        self.manager.upload_paperless_document(
            file_content_base64="dGVzdA==",
            file_name="inv.pdf",
            file_format="pdf",
            document_type="002",
        )

        headers = self.fake.calls[0]["kwargs"]["additional_headers"]
        self.assertEqual(headers["ShipperNumber"], "SHIP123")

    def test_upload_explicit_shipper_overrides_default(self) -> None:
        self.manager.upload_paperless_document(
            file_content_base64="dGVzdA==",
            file_name="inv.pdf",
            file_format="pdf",
            document_type="002",
            shipper_number="OVERRIDE",
        )

        headers = self.fake.calls[0]["kwargs"]["additional_headers"]
        self.assertEqual(headers["ShipperNumber"], "OVERRIDE")

    def test_upload_no_shipper_number_raises_tool_error(self) -> None:
        self.manager.account_number = None
        with self.assertRaises(ToolError) as ctx:
            self.manager.upload_paperless_document(
                file_content_base64="dGVzdA==",
                file_name="inv.pdf",
                file_format="pdf",
                document_type="002",
            )
        self.assertIn("ShipperNumber", str(ctx.exception))

    def test_upload_invalid_file_format_raises_tool_error(self) -> None:
        with self.assertRaises(ToolError) as ctx:
            self.manager.upload_paperless_document(
                file_content_base64="dGVzdA==",
                file_name="inv.exe",
                file_format="exe",
                document_type="002",
            )
        self.assertIn("file_format", str(ctx.exception))

    def test_upload_normalizes_file_format_to_lowercase(self) -> None:
        self.manager.upload_paperless_document(
            file_content_base64="dGVzdA==",
            file_name="inv.PDF",
            file_format="PDF",
            document_type="002",
        )

        body = self.fake.calls[0]["kwargs"]["json_body"]
        self.assertEqual(body["UploadRequest"]["UserCreatedForm"][0]["UserCreatedFormFileFormat"], "pdf")


class PushDocumentToShipmentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = ToolManager(
            base_url="https://example.test",
            client_id="cid",
            client_secret="csec",
            account_number="SHIP123",
        )
        self.fake = FakeHTTPClient()
        self.manager.http_client = self.fake

    def test_push_constructs_correct_payload(self) -> None:
        self.manager.push_document_to_shipment(
            document_id="DOC123",
            shipment_identifier="1Z999AA10123456784",
        )

        call = self.fake.calls[0]
        self.assertEqual(call["operation"].operation_id, "PushToImageRepository")
        body = call["kwargs"]["json_body"]
        self.assertEqual(body["PushToImageRepositoryRequest"]["FormsHistoryDocumentID"]["DocumentID"], ["DOC123"])
        self.assertEqual(body["PushToImageRepositoryRequest"]["ShipmentIdentifier"], "1Z999AA10123456784")
        self.assertEqual(body["PushToImageRepositoryRequest"]["ShipmentType"], "1")

    def test_push_injects_shipper_number_header(self) -> None:
        self.manager.push_document_to_shipment(
            document_id="DOC123",
            shipment_identifier="1Z999",
        )

        headers = self.fake.calls[0]["kwargs"]["additional_headers"]
        self.assertEqual(headers["ShipperNumber"], "SHIP123")

    def test_push_no_shipper_raises_tool_error(self) -> None:
        self.manager.account_number = None
        with self.assertRaises(ToolError):
            self.manager.push_document_to_shipment(
                document_id="DOC123",
                shipment_identifier="1Z999",
            )


class DeletePaperlessDocumentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = ToolManager(
            base_url="https://example.test",
            client_id="cid",
            client_secret="csec",
            account_number="SHIP123",
        )
        self.fake = FakeHTTPClient()
        self.manager.http_client = self.fake

    def test_delete_uses_correct_operation_and_headers(self) -> None:
        self.manager.delete_paperless_document(document_id="DOC456")

        call = self.fake.calls[0]
        self.assertEqual(call["operation"].operation_id, "Delete")
        headers = call["kwargs"]["additional_headers"]
        self.assertEqual(headers["ShipperNumber"], "SHIP123")
        self.assertEqual(headers["DocumentId"], "DOC456")

    def test_delete_no_shipper_raises_tool_error(self) -> None:
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

Add operation ID constants (after `LANDED_COST_OPERATION_ID`):

```python
PAPERLESS_UPLOAD_OPERATION_ID = "Upload"
PAPERLESS_PUSH_OPERATION_ID = "PushToImageRepository"
PAPERLESS_DELETE_OPERATION_ID = "Delete"
```

Add a module-level constant for valid file formats:

```python
PAPERLESS_VALID_FORMATS = frozenset({"pdf", "doc", "docx", "xls", "xlsx", "txt", "rtf", "tif", "jpg"})
```

Add 3 methods to `ToolManager` (after `get_landed_cost_quote`):

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
    effective_shipper = shipper_number or self.account_number
    if not effective_shipper:
        raise ToolError("ShipperNumber is required via argument or UPS_ACCOUNT_NUMBER env var")

    normalized_format = file_format.lower()
    if normalized_format not in PAPERLESS_VALID_FORMATS:
        raise ToolError(
            f"Invalid file_format '{file_format}'. "
            f"Supported: {', '.join(sorted(PAPERLESS_VALID_FORMATS))}"
        )

    request_body = {
        "UploadRequest": {
            "Request": {
                "TransactionReference": {"CustomerContext": transaction_src}
            },
            "ShipperNumber": effective_shipper,
            "UserCreatedForm": [
                {
                    "UserCreatedFormFileName": file_name,
                    "UserCreatedFormFileFormat": normalized_format,
                    "UserCreatedFormDocumentType": document_type,
                    "UserCreatedFormFile": file_content_base64,
                }
            ],
        }
    }

    return self._execute_operation(
        operation_id=PAPERLESS_UPLOAD_OPERATION_ID,
        operation_name="upload_paperless_document",
        path_params={"version": "v2"},
        query_params=None,
        request_body=request_body,
        trans_id=trans_id,
        transaction_src=transaction_src,
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
    effective_shipper = shipper_number or self.account_number
    if not effective_shipper:
        raise ToolError("ShipperNumber is required via argument or UPS_ACCOUNT_NUMBER env var")

    request_body = {
        "PushToImageRepositoryRequest": {
            "Request": {
                "TransactionReference": {"CustomerContext": transaction_src}
            },
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
        query_params=None,
        request_body=request_body,
        trans_id=trans_id,
        transaction_src=transaction_src,
        additional_headers={"ShipperNumber": effective_shipper},
    )

def delete_paperless_document(
    self,
    document_id: str,
    shipper_number: str | None = None,
    trans_id: str | None = None,
    transaction_src: str = "ups-mcp",
) -> dict[str, Any]:
    effective_shipper = shipper_number or self.account_number
    if not effective_shipper:
        raise ToolError("ShipperNumber is required via argument or UPS_ACCOUNT_NUMBER env var")

    return self._execute_operation(
        operation_id=PAPERLESS_DELETE_OPERATION_ID,
        operation_name="delete_paperless_document",
        path_params={"version": "v2"},
        query_params=None,
        request_body=None,
        trans_id=trans_id,
        transaction_src=transaction_src,
        additional_headers={"ShipperNumber": effective_shipper, "DocumentId": document_id},
    )
```

**Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_paperless_tools.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add ups_mcp/tools.py tests/test_paperless_tools.py
git commit -m "feat: add upload, push, delete paperless document tools to ToolManager"
```

---

## Task 6: Locator — ToolManager method + tests

**Files:**
- Modify: `ups_mcp/tools.py` (add operation ID constant + `find_locations` method)
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
            base_url="https://example.test",
            client_id="cid",
            client_secret="csec",
        )
        self.fake = FakeHTTPClient()
        self.manager.http_client = self.fake

    def test_find_locations_maps_access_point_to_req_option_64(self) -> None:
        self.manager.find_locations(
            location_type="access_point",
            address_line="123 Main St",
            city="Atlanta",
            state="GA",
            postal_code="30301",
            country_code="US",
        )

        call = self.fake.calls[0]
        self.assertEqual(call["operation"].operation_id, "Locator")
        self.assertEqual(call["kwargs"]["path_params"]["reqOption"], "64")

    def test_find_locations_maps_retail_to_req_option_32(self) -> None:
        self.manager.find_locations(
            location_type="retail",
            address_line="456 Oak Ave",
            city="New York",
            state="NY",
            postal_code="10001",
            country_code="US",
        )

        self.assertEqual(self.fake.calls[0]["kwargs"]["path_params"]["reqOption"], "32")

    def test_find_locations_maps_general_to_req_option_1(self) -> None:
        self.manager.find_locations(
            location_type="general",
            address_line="789 Elm St",
            city="Chicago",
            state="IL",
            postal_code="60601",
            country_code="US",
        )

        self.assertEqual(self.fake.calls[0]["kwargs"]["path_params"]["reqOption"], "1")

    def test_find_locations_invalid_location_type_raises_tool_error(self) -> None:
        with self.assertRaises(ToolError) as ctx:
            self.manager.find_locations(
                location_type="warehouse",
                address_line="123 Main St",
                city="Atlanta",
                state="GA",
                postal_code="30301",
                country_code="US",
            )
        self.assertIn("location_type", str(ctx.exception))

    def test_find_locations_constructs_origin_address(self) -> None:
        self.manager.find_locations(
            location_type="general",
            address_line="123 Main St",
            city="Atlanta",
            state="GA",
            postal_code="30301",
            country_code="US",
        )

        body = self.fake.calls[0]["kwargs"]["json_body"]
        addr = body["LocatorRequest"]["OriginAddress"]["AddressKeyFormat"]
        self.assertEqual(addr["AddressLine"], "123 Main St")
        self.assertEqual(addr["PoliticalDivision2"], "Atlanta")
        self.assertEqual(addr["PoliticalDivision1"], "GA")
        self.assertEqual(addr["PostcodePrimaryLow"], "30301")
        self.assertEqual(addr["CountryCode"], "US")

    def test_find_locations_uses_default_radius_and_unit(self) -> None:
        self.manager.find_locations(
            location_type="general",
            address_line="123 Main",
            city="A",
            state="GA",
            postal_code="30301",
            country_code="US",
        )

        body = self.fake.calls[0]["kwargs"]["json_body"]
        criteria = body["LocatorRequest"]["LocationSearchCriteria"]
        self.assertEqual(criteria["SearchRadius"], "15.0")
        self.assertEqual(body["LocatorRequest"]["UnitOfMeasurement"]["Code"], "MI")

    def test_find_locations_custom_radius_and_unit(self) -> None:
        self.manager.find_locations(
            location_type="general",
            address_line="123 Main",
            city="A",
            state="GA",
            postal_code="30301",
            country_code="US",
            radius=25.0,
            unit_of_measure="KM",
        )

        body = self.fake.calls[0]["kwargs"]["json_body"]
        self.assertEqual(body["LocatorRequest"]["LocationSearchCriteria"]["SearchRadius"], "25.0")
        self.assertEqual(body["LocatorRequest"]["UnitOfMeasurement"]["Code"], "KM")

    def test_find_locations_access_point_includes_access_point_search(self) -> None:
        self.manager.find_locations(
            location_type="access_point",
            address_line="123 Main",
            city="A",
            state="GA",
            postal_code="30301",
            country_code="US",
        )

        body = self.fake.calls[0]["kwargs"]["json_body"]
        criteria = body["LocatorRequest"]["LocationSearchCriteria"]
        self.assertIn("AccessPointSearch", criteria)
        self.assertEqual(criteria["AccessPointSearch"]["AccessPointStatus"], "01")

    def test_find_locations_non_access_point_omits_access_point_search(self) -> None:
        self.manager.find_locations(
            location_type="retail",
            address_line="123 Main",
            city="A",
            state="GA",
            postal_code="30301",
            country_code="US",
        )

        body = self.fake.calls[0]["kwargs"]["json_body"]
        criteria = body["LocatorRequest"]["LocationSearchCriteria"]
        self.assertNotIn("AccessPointSearch", criteria)

    def test_find_locations_uses_version_v2(self) -> None:
        self.manager.find_locations(
            location_type="general",
            address_line="123 Main",
            city="A",
            state="GA",
            postal_code="30301",
            country_code="US",
        )

        self.assertEqual(self.fake.calls[0]["kwargs"]["path_params"]["version"], "v2")


if __name__ == "__main__":
    unittest.main()
```

**Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_locator_tools.py -v`
Expected: FAIL — missing `find_locations` method

**Step 3: Implement find_locations in tools.py**

Add import at top of `ups_mcp/tools.py`:

```python
from . import constants
```

Add operation ID constant:

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

    search_criteria: dict[str, Any] = {
        "SearchRadius": str(radius),
    }
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
        path_params={"version": "v2", "reqOption": req_option},
        query_params=None,
        request_body=request_body,
        trans_id=trans_id,
        transaction_src=transaction_src,
    )
```

**Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_locator_tools.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add ups_mcp/tools.py tests/test_locator_tools.py
git commit -m "feat: add find_locations to ToolManager with semantic reqOption mapping"
```

---

## Task 7: Pickup Suite — ToolManager methods + tests

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
            base_url="https://example.test",
            client_id="cid",
            client_secret="csec",
            account_number="ACCT123",
        )
        self.fake = FakeHTTPClient()
        self.manager.http_client = self.fake

    def test_rate_pickup_routes_to_correct_operation(self) -> None:
        self.manager.rate_pickup(
            pickup_type="oncall",
            address_line="123 Main St",
            city="Atlanta",
            state="GA",
            postal_code="30301",
            country_code="US",
            pickup_date="20260301",
        )

        call = self.fake.calls[0]
        self.assertEqual(call["operation"].operation_id, "Pickup Rate")
        self.assertEqual(call["kwargs"]["path_params"]["pickuptype"], "oncall")
        self.assertEqual(call["kwargs"]["path_params"]["version"], "v2409")

    def test_rate_pickup_constructs_payload(self) -> None:
        self.manager.rate_pickup(
            pickup_type="smart",
            address_line="123 Main St",
            city="Atlanta",
            state="GA",
            postal_code="30301",
            country_code="US",
            pickup_date="20260301",
            service_code="002",
            quantity=3,
        )

        body = self.fake.calls[0]["kwargs"]["json_body"]
        self.assertIn("PickupRateRequest", body)
        self.assertEqual(body["PickupRateRequest"]["PickupAddress"]["PostalCode"], "30301")


class SchedulePickupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = ToolManager(
            base_url="https://example.test",
            client_id="cid",
            client_secret="csec",
            account_number="ACCT123",
        )
        self.fake = FakeHTTPClient()
        self.manager.http_client = self.fake

    def test_schedule_pickup_routes_to_pickup_creation(self) -> None:
        self.manager.schedule_pickup(
            pickup_date="20260301",
            ready_time="0900",
            close_time="1700",
            address_line="123 Main St",
            city="Atlanta",
            state="GA",
            postal_code="30301",
            country_code="US",
            contact_name="John Doe",
            phone_number="5551234567",
        )

        call = self.fake.calls[0]
        self.assertEqual(call["operation"].operation_id, "Pickup Creation")
        self.assertEqual(call["kwargs"]["path_params"]["version"], "v2409")

    def test_schedule_pickup_constructs_address_and_times(self) -> None:
        self.manager.schedule_pickup(
            pickup_date="20260301",
            ready_time="0900",
            close_time="1700",
            address_line="456 Oak Ave",
            city="New York",
            state="NY",
            postal_code="10001",
            country_code="US",
            contact_name="Jane Smith",
            phone_number="5559876543",
        )

        body = self.fake.calls[0]["kwargs"]["json_body"]
        req = body["PickupCreationRequest"]
        self.assertEqual(req["PickupDateInfo"]["ReadyTime"], "0900")
        self.assertEqual(req["PickupDateInfo"]["CloseTime"], "1700")
        self.assertEqual(req["PickupAddress"]["AddressLine"], "456 Oak Ave")
        self.assertEqual(req["PickupAddress"]["City"], "New York")

    def test_schedule_pickup_ready_time_after_close_time_raises_tool_error(self) -> None:
        with self.assertRaises(ToolError) as ctx:
            self.manager.schedule_pickup(
                pickup_date="20260301",
                ready_time="1800",
                close_time="0900",
                address_line="123 Main",
                city="A",
                state="GA",
                postal_code="30301",
                country_code="US",
                contact_name="Test",
                phone_number="5551234567",
            )
        self.assertIn("ready_time", str(ctx.exception).lower())

    def test_schedule_pickup_uses_account_number_in_body(self) -> None:
        self.manager.schedule_pickup(
            pickup_date="20260301",
            ready_time="0900",
            close_time="1700",
            address_line="123 Main",
            city="A",
            state="GA",
            postal_code="30301",
            country_code="US",
            contact_name="Test",
            phone_number="5551234567",
        )

        body = self.fake.calls[0]["kwargs"]["json_body"]
        self.assertEqual(body["PickupCreationRequest"]["ShipperAccountNumber"], "ACCT123")


class CancelPickupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = ToolManager(
            base_url="https://example.test",
            client_id="cid",
            client_secret="csec",
            account_number="ACCT123",
        )
        self.fake = FakeHTTPClient()
        self.manager.http_client = self.fake

    def test_cancel_by_account_maps_to_01(self) -> None:
        self.manager.cancel_pickup(cancel_by="account")

        call = self.fake.calls[0]
        self.assertEqual(call["operation"].operation_id, "Pickup Cancel")
        self.assertEqual(call["kwargs"]["path_params"]["CancelBy"], "01")

    def test_cancel_by_prn_maps_to_02_and_injects_header(self) -> None:
        self.manager.cancel_pickup(cancel_by="prn", prn="PRN123456789")

        call = self.fake.calls[0]
        self.assertEqual(call["kwargs"]["path_params"]["CancelBy"], "02")
        self.assertEqual(call["kwargs"]["additional_headers"]["Prn"], "PRN123456789")

    def test_cancel_by_prn_without_prn_raises_tool_error(self) -> None:
        with self.assertRaises(ToolError):
            self.manager.cancel_pickup(cancel_by="prn")

    def test_cancel_invalid_cancel_by_raises_tool_error(self) -> None:
        with self.assertRaises(ToolError) as ctx:
            self.manager.cancel_pickup(cancel_by="invalid")
        self.assertIn("cancel_by", str(ctx.exception))


class GetPickupStatusTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = ToolManager(
            base_url="https://example.test",
            client_id="cid",
            client_secret="csec",
            account_number="ACCT123",
        )
        self.fake = FakeHTTPClient()
        self.manager.http_client = self.fake

    def test_get_pickup_status_routes_correctly(self) -> None:
        self.manager.get_pickup_status(pickup_type="oncall")

        call = self.fake.calls[0]
        self.assertEqual(call["operation"].operation_id, "Pickup Pending Status")
        self.assertEqual(call["kwargs"]["path_params"]["pickuptype"], "oncall")

    def test_get_pickup_status_injects_account_number_header(self) -> None:
        self.manager.get_pickup_status(pickup_type="oncall")

        headers = self.fake.calls[0]["kwargs"]["additional_headers"]
        self.assertEqual(headers["AccountNumber"], "ACCT123")

    def test_get_pickup_status_no_account_raises_tool_error(self) -> None:
        self.manager.account_number = None
        with self.assertRaises(ToolError):
            self.manager.get_pickup_status(pickup_type="oncall")


class GetPoliticalDivisionsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = ToolManager(
            base_url="https://example.test",
            client_id="cid",
            client_secret="csec",
        )
        self.fake = FakeHTTPClient()
        self.manager.http_client = self.fake

    def test_get_political_divisions_routes_correctly(self) -> None:
        self.manager.get_political_divisions(country_code="US")

        call = self.fake.calls[0]
        self.assertEqual(call["operation"].operation_id, "Pickup Get Political Division1 List")
        self.assertEqual(call["kwargs"]["path_params"]["countrycode"], "US")
        self.assertIsNone(call["kwargs"]["json_body"])


class GetServiceCenterFacilitiesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = ToolManager(
            base_url="https://example.test",
            client_id="cid",
            client_secret="csec",
        )
        self.fake = FakeHTTPClient()
        self.manager.http_client = self.fake

    def test_get_service_center_facilities_routes_correctly(self) -> None:
        self.manager.get_service_center_facilities(
            city="Atlanta",
            state="GA",
            postal_code="30301",
            country_code="US",
        )

        call = self.fake.calls[0]
        self.assertEqual(call["operation"].operation_id, "Pickup Get Service Center Facilities")
        body = call["kwargs"]["json_body"]
        self.assertIn("PickupGetServiceCenterFacilitiesRequest", body)


if __name__ == "__main__":
    unittest.main()
```

**Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_pickup_tools.py -v`
Expected: FAIL — missing methods

**Step 3: Implement 6 Pickup methods in tools.py**

Add operation ID constants:

```python
PICKUP_RATE_OPERATION_ID = "Pickup Rate"
PICKUP_PENDING_STATUS_OPERATION_ID = "Pickup Pending Status"
PICKUP_CANCEL_OPERATION_ID = "Pickup Cancel"
PICKUP_CREATION_OPERATION_ID = "Pickup Creation"
PICKUP_POLITICAL_DIVISIONS_OPERATION_ID = "Pickup Get Political Division1 List"
PICKUP_SERVICE_CENTER_OPERATION_ID = "Pickup Get Service Center Facilities"
```

Add 6 methods to ToolManager:

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
    service_code: str = "001",
    container_code: str = "01",
    quantity: int = 1,
    destination_country_code: str = "US",
    trans_id: str | None = None,
    transaction_src: str = "ups-mcp",
) -> dict[str, Any]:
    request_body = {
        "PickupRateRequest": {
            "Request": {
                "TransactionReference": {"CustomerContext": transaction_src}
            },
            "ShipperAccount": {
                "AccountNumber": self.account_number or "",
                "AccountCountryCode": country_code,
            },
            "PickupAddress": {
                "AddressLine": address_line,
                "City": city,
                "StateProvince": state,
                "PostalCode": postal_code,
                "CountryCode": country_code,
            },
            "AlternateAddressIndicator": "N",
            "PickupDateInfo": {
                "PickupDate": pickup_date,
            },
            "PickupPiece": [
                {
                    "ServiceCode": service_code,
                    "Quantity": str(quantity),
                    "DestinationCountryCode": destination_country_code,
                    "ContainerCode": container_code,
                }
            ],
        }
    }

    return self._execute_operation(
        operation_id=PICKUP_RATE_OPERATION_ID,
        operation_name="rate_pickup",
        path_params={"version": "v2409", "pickuptype": pickup_type},
        query_params=None,
        request_body=request_body,
        trans_id=trans_id,
        transaction_src=transaction_src,
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
    service_code: str = "001",
    container_code: str = "01",
    quantity: int = 1,
    weight: float = 5.0,
    weight_unit: str = "LBS",
    payment_method: str = "01",
    account_number: str | None = None,
    trans_id: str | None = None,
    transaction_src: str = "ups-mcp",
) -> dict[str, Any]:
    if ready_time >= close_time:
        raise ToolError(
            f"ready_time ({ready_time}) must be before close_time ({close_time})"
        )

    effective_account = account_number or self.account_number or ""

    request_body = {
        "PickupCreationRequest": {
            "Request": {
                "TransactionReference": {"CustomerContext": transaction_src}
            },
            "ShipperAccountNumber": effective_account,
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
                "Phone": {"Number": phone_number},
            },
            "AlternateAddressIndicator": "N",
            "PickupPiece": [
                {
                    "ServiceCode": service_code,
                    "Quantity": str(quantity),
                    "DestinationCountryCode": country_code,
                    "ContainerCode": container_code,
                }
            ],
            "TotalWeight": {
                "Weight": str(weight),
                "UnitOfMeasurement": weight_unit,
            },
            "PaymentMethod": payment_method,
        }
    }

    return self._execute_operation(
        operation_id=PICKUP_CREATION_OPERATION_ID,
        operation_name="schedule_pickup",
        path_params={"version": "v2409"},
        query_params=None,
        request_body=request_body,
        trans_id=trans_id,
        transaction_src=transaction_src,
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
        query_params=None,
        request_body=None,
        trans_id=trans_id,
        transaction_src=transaction_src,
        additional_headers=additional_headers,
    )

def get_pickup_status(
    self,
    pickup_type: str,
    account_number: str | None = None,
    trans_id: str | None = None,
    transaction_src: str = "ups-mcp",
) -> dict[str, Any]:
    effective_account = account_number or self.account_number
    if not effective_account:
        raise ToolError("AccountNumber is required via argument or UPS_ACCOUNT_NUMBER env var")

    return self._execute_operation(
        operation_id=PICKUP_PENDING_STATUS_OPERATION_ID,
        operation_name="get_pickup_status",
        path_params={"version": "v2409", "pickuptype": pickup_type},
        query_params=None,
        request_body=None,
        trans_id=trans_id,
        transaction_src=transaction_src,
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
        query_params=None,
        request_body=None,
        trans_id=trans_id,
        transaction_src=transaction_src,
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
            "Request": {
                "TransactionReference": {"CustomerContext": transaction_src}
            },
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
        query_params=None,
        request_body=request_body,
        trans_id=trans_id,
        transaction_src=transaction_src,
    )
```

**Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_pickup_tools.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add ups_mcp/tools.py tests/test_pickup_tools.py
git commit -m "feat: add 6 pickup tools to ToolManager (rate, schedule, cancel, status, divisions, facilities)"
```

---

## Task 8: Server Endpoints — all 11 new @mcp.tool definitions + tests

**Files:**
- Modify: `ups_mcp/server.py` (add 11 new async tool functions + imports)
- Create: `tests/test_server_new_tools.py`

**Step 1: Write the failing tests**

Create `tests/test_server_new_tools.py`:

```python
import unittest

import ups_mcp.server as server


class FakeToolManager:
    """Extends the existing FakeToolManager pattern to cover all 11 new tools."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def get_landed_cost_quote(self, **kwargs):  # noqa: ANN003
        self.calls.append(("get_landed_cost_quote", kwargs))
        return {"LandedCostResponse": {"shipment": {}}}

    def upload_paperless_document(self, **kwargs):  # noqa: ANN003
        self.calls.append(("upload_paperless_document", kwargs))
        return {"UploadResponse": {"FormsHistoryDocumentID": {"DocumentID": ["DOC1"]}}}

    def push_document_to_shipment(self, **kwargs):  # noqa: ANN003
        self.calls.append(("push_document_to_shipment", kwargs))
        return {"PushToImageRepositoryResponse": {}}

    def delete_paperless_document(self, **kwargs):  # noqa: ANN003
        self.calls.append(("delete_paperless_document", kwargs))
        return {"DeleteResponse": {}}

    def find_locations(self, **kwargs):  # noqa: ANN003
        self.calls.append(("find_locations", kwargs))
        return {"LocatorResponse": {"SearchResults": {}}}

    def rate_pickup(self, **kwargs):  # noqa: ANN003
        self.calls.append(("rate_pickup", kwargs))
        return {"PickupRateResponse": {}}

    def schedule_pickup(self, **kwargs):  # noqa: ANN003
        self.calls.append(("schedule_pickup", kwargs))
        return {"PickupCreationResponse": {"PRN": "PRN123"}}

    def cancel_pickup(self, **kwargs):  # noqa: ANN003
        self.calls.append(("cancel_pickup", kwargs))
        return {"PickupCancelResponse": {}}

    def get_pickup_status(self, **kwargs):  # noqa: ANN003
        self.calls.append(("get_pickup_status", kwargs))
        return {"PickupPendingStatusResponse": {}}

    def get_political_divisions(self, **kwargs):  # noqa: ANN003
        self.calls.append(("get_political_divisions", kwargs))
        return {"PoliticalDivision1List": []}

    def get_service_center_facilities(self, **kwargs):  # noqa: ANN003
        self.calls.append(("get_service_center_facilities", kwargs))
        return {"ServiceCenterFacilitiesResponse": {}}


class NewServerToolsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.original_tool_manager = server.tool_manager
        self.fake = FakeToolManager()
        server.tool_manager = self.fake

    def tearDown(self) -> None:
        server.tool_manager = self.original_tool_manager

    async def test_get_landed_cost_quote_returns_raw_response(self) -> None:
        result = await server.get_landed_cost_quote(
            currency_code="USD",
            export_country_code="US",
            import_country_code="GB",
            commodities=[{"hs_code": "6109.10", "price": 25, "quantity": 10}],
        )
        self.assertIn("LandedCostResponse", result)
        self.assertEqual(self.fake.calls[0][0], "get_landed_cost_quote")

    async def test_upload_paperless_document_returns_raw_response(self) -> None:
        result = await server.upload_paperless_document(
            file_content_base64="dGVzdA==",
            file_name="invoice.pdf",
            file_format="pdf",
            document_type="002",
        )
        self.assertIn("UploadResponse", result)

    async def test_push_document_to_shipment_returns_raw_response(self) -> None:
        result = await server.push_document_to_shipment(
            document_id="DOC1",
            shipment_identifier="1Z999",
        )
        self.assertIn("PushToImageRepositoryResponse", result)

    async def test_delete_paperless_document_returns_raw_response(self) -> None:
        result = await server.delete_paperless_document(document_id="DOC1")
        self.assertIn("DeleteResponse", result)

    async def test_find_locations_returns_raw_response(self) -> None:
        result = await server.find_locations(
            address_line="123 Main St",
            city="Atlanta",
            state="GA",
            postal_code="30301",
            country_code="US",
        )
        self.assertIn("LocatorResponse", result)

    async def test_rate_pickup_returns_raw_response(self) -> None:
        result = await server.rate_pickup(
            pickup_type="oncall",
            address_line="123 Main St",
            city="Atlanta",
            state="GA",
            postal_code="30301",
            country_code="US",
            pickup_date="20260301",
        )
        self.assertIn("PickupRateResponse", result)

    async def test_schedule_pickup_returns_raw_response(self) -> None:
        result = await server.schedule_pickup(
            pickup_date="20260301",
            ready_time="0900",
            close_time="1700",
            address_line="123 Main",
            city="Atlanta",
            state="GA",
            postal_code="30301",
            country_code="US",
            contact_name="John",
            phone_number="5551234567",
        )
        self.assertIn("PickupCreationResponse", result)

    async def test_cancel_pickup_returns_raw_response(self) -> None:
        result = await server.cancel_pickup(cancel_by="account")
        self.assertIn("PickupCancelResponse", result)

    async def test_get_pickup_status_returns_raw_response(self) -> None:
        result = await server.get_pickup_status(pickup_type="oncall")
        self.assertIn("PickupPendingStatusResponse", result)

    async def test_get_political_divisions_returns_raw_response(self) -> None:
        result = await server.get_political_divisions(country_code="US")
        self.assertIn("PoliticalDivision1List", result)

    async def test_get_service_center_facilities_returns_raw_response(self) -> None:
        result = await server.get_service_center_facilities(
            city="Atlanta",
            state="GA",
            postal_code="30301",
            country_code="US",
        )
        self.assertIn("ServiceCenterFacilitiesResponse", result)


if __name__ == "__main__":
    unittest.main()
```

**Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_server_new_tools.py -v`
Expected: FAIL — server module has no `get_landed_cost_quote`, etc.

**Step 3: Add 11 tool endpoints to server.py**

Add `from typing import Literal` to imports (line 1 area). Then add all 11 tool functions after the existing `get_time_in_transit` function (after line 449, before `_validate_runtime_configuration`):

```python
@mcp.tool()
async def get_landed_cost_quote(
    currency_code: str,
    export_country_code: str,
    import_country_code: str,
    commodities: list[dict[str, Any]],
    shipment_type: str = "Sale",
    account_number: str = "",
    trans_id: str = "",
    transaction_src: str = "ups-mcp",
) -> dict[str, Any]:
    """
    Estimate duties, taxes, and brokerage fees for international shipments.

    Args:
        currency_code: 3-letter currency code (e.g., 'USD', 'EUR').
        export_country_code: Origin country ISO code (e.g., 'US').
        import_country_code: Destination country ISO code (e.g., 'GB', 'CA').
        shipment_type: Reason for export. Default 'Sale'. Options: 'Gift', 'Sample', 'Return'.
        commodities: List of items. Each dict must contain:
            - hs_code (str): Harmonized System code
            - price (float): Price per unit
            - quantity (int): Number of units
            Optional: description, weight, weight_unit ('KGS'/'LBS'), uom (default 'EA')
        account_number: Optional. Defaults to UPS_ACCOUNT_NUMBER env var.
        trans_id: Optional request id.
        transaction_src: Optional caller source name. Default 'ups-mcp'.
    """
    return _require_tool_manager().get_landed_cost_quote(
        currency_code=currency_code,
        export_country_code=export_country_code,
        import_country_code=import_country_code,
        commodities=commodities,
        shipment_type=shipment_type,
        account_number=account_number or None,
        trans_id=trans_id or None,
        transaction_src=transaction_src,
    )


@mcp.tool()
async def upload_paperless_document(
    file_content_base64: str,
    file_name: str,
    file_format: str,
    document_type: str,
    shipper_number: str = "",
    trans_id: str = "",
    transaction_src: str = "ups-mcp",
) -> dict[str, Any]:
    """
    Upload a trade document to UPS Paperless system.

    Args:
        file_content_base64: Raw file content as Base64 string.
        file_name: Filename (e.g., "invoice.pdf").
        file_format: Extension (pdf, doc, docx, xls, xlsx, txt, rtf, tif, jpg).
        document_type: 3-digit UPS code ('001'=Auth Form, '002'=Commercial Invoice,
                       '010'=Packing List, '013'=Declaration).
        shipper_number: Optional. Defaults to UPS_ACCOUNT_NUMBER env var.
        trans_id: Optional request id.
        transaction_src: Optional caller source name. Default 'ups-mcp'.
    """
    return _require_tool_manager().upload_paperless_document(
        file_content_base64=file_content_base64,
        file_name=file_name,
        file_format=file_format,
        document_type=document_type,
        shipper_number=shipper_number or None,
        trans_id=trans_id or None,
        transaction_src=transaction_src,
    )


@mcp.tool()
async def push_document_to_shipment(
    document_id: str,
    shipment_identifier: str,
    shipment_type: str = "1",
    shipper_number: str = "",
    trans_id: str = "",
    transaction_src: str = "ups-mcp",
) -> dict[str, Any]:
    """
    Link an uploaded paperless document to a specific shipment.

    Args:
        document_id: Document ID returned from upload_paperless_document.
        shipment_identifier: UPS Shipment ID or tracking number.
        shipment_type: '1' = Small Package (default), '2' = Freight.
        shipper_number: Optional. Defaults to UPS_ACCOUNT_NUMBER env var.
        trans_id: Optional request id.
        transaction_src: Optional caller source name. Default 'ups-mcp'.
    """
    return _require_tool_manager().push_document_to_shipment(
        document_id=document_id,
        shipment_identifier=shipment_identifier,
        shipment_type=shipment_type,
        shipper_number=shipper_number or None,
        trans_id=trans_id or None,
        transaction_src=transaction_src,
    )


@mcp.tool()
async def delete_paperless_document(
    document_id: str,
    shipper_number: str = "",
    trans_id: str = "",
    transaction_src: str = "ups-mcp",
) -> dict[str, Any]:
    """
    Delete a previously uploaded paperless document.

    Args:
        document_id: Document ID to delete.
        shipper_number: Optional. Defaults to UPS_ACCOUNT_NUMBER env var.
        trans_id: Optional request id.
        transaction_src: Optional caller source name. Default 'ups-mcp'.
    """
    return _require_tool_manager().delete_paperless_document(
        document_id=document_id,
        shipper_number=shipper_number or None,
        trans_id=trans_id or None,
        transaction_src=transaction_src,
    )


@mcp.tool()
async def find_locations(
    address_line: str,
    city: str,
    state: str,
    postal_code: str,
    country_code: str,
    location_type: str = "general",
    radius: float = 15.0,
    unit_of_measure: str = "MI",
    trans_id: str = "",
    transaction_src: str = "ups-mcp",
) -> dict[str, Any]:
    """
    Search for UPS locations near an address.

    Args:
        address_line: Street address (e.g., "123 Main St").
        city: City name.
        state: State/province code (e.g., "GA", "ON").
        postal_code: Zip/postal code.
        country_code: 2-letter ISO country code.
        location_type: 'access_point' (lockers/partners), 'retail' (UPS Stores),
                       'general' (drop boxes/centers). Default 'general'.
        radius: Search radius. Default 15.0.
        unit_of_measure: 'MI' or 'KM'. Default 'MI'.
        trans_id: Optional request id.
        transaction_src: Optional caller source name. Default 'ups-mcp'.
    """
    return _require_tool_manager().find_locations(
        location_type=location_type,
        address_line=address_line,
        city=city,
        state=state,
        postal_code=postal_code,
        country_code=country_code,
        radius=radius,
        unit_of_measure=unit_of_measure,
        trans_id=trans_id or None,
        transaction_src=transaction_src,
    )


@mcp.tool()
async def rate_pickup(
    pickup_type: str,
    address_line: str,
    city: str,
    state: str,
    postal_code: str,
    country_code: str,
    pickup_date: str,
    service_code: str = "001",
    container_code: str = "01",
    quantity: int = 1,
    destination_country_code: str = "US",
    trans_id: str = "",
    transaction_src: str = "ups-mcp",
) -> dict[str, Any]:
    """
    Get the cost of a pickup before scheduling.

    Args:
        pickup_type: 'oncall', 'smart', or 'both'.
        address_line, city, state, postal_code, country_code: Pickup address.
        pickup_date: Date in YYYYMMDD format.
        service_code: UPS service code (default '001' = Next Day Air).
        container_code: '01'=Package, '02'=UPS Letter.
        quantity: Number of pieces.
        destination_country_code: Destination country (default 'US').
        trans_id: Optional request id.
        transaction_src: Optional caller source name. Default 'ups-mcp'.
    """
    return _require_tool_manager().rate_pickup(
        pickup_type=pickup_type,
        address_line=address_line,
        city=city,
        state=state,
        postal_code=postal_code,
        country_code=country_code,
        pickup_date=pickup_date,
        service_code=service_code,
        container_code=container_code,
        quantity=quantity,
        destination_country_code=destination_country_code,
        trans_id=trans_id or None,
        transaction_src=transaction_src,
    )


@mcp.tool()
async def schedule_pickup(
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
    service_code: str = "001",
    container_code: str = "01",
    quantity: int = 1,
    weight: float = 5.0,
    weight_unit: str = "LBS",
    payment_method: str = "01",
    account_number: str = "",
    trans_id: str = "",
    transaction_src: str = "ups-mcp",
) -> dict[str, Any]:
    """
    Schedule a physical package pickup.

    Args:
        pickup_date: Date in YYYYMMDD format.
        ready_time: Earliest time packages ready, HHMM 24hr (e.g., '0900').
        close_time: Latest time driver can arrive, HHMM 24hr (e.g., '1700').
        address_line, city, state, postal_code, country_code: Pickup address.
        contact_name: Name of person at pickup location.
        phone_number: Contact phone number.
        service_code: UPS service code (default '001').
        container_code: '01'=Package, '02'=UPS Letter.
        quantity: Number of pieces.
        weight: Total weight (default 5.0).
        weight_unit: 'LBS' or 'KGS' (default 'LBS').
        payment_method: '01'=Account (default), '03'=Credit Card.
        account_number: Optional. Defaults to UPS_ACCOUNT_NUMBER env var.
        trans_id: Optional request id.
        transaction_src: Optional caller source name. Default 'ups-mcp'.
    """
    return _require_tool_manager().schedule_pickup(
        pickup_date=pickup_date,
        ready_time=ready_time,
        close_time=close_time,
        address_line=address_line,
        city=city,
        state=state,
        postal_code=postal_code,
        country_code=country_code,
        contact_name=contact_name,
        phone_number=phone_number,
        service_code=service_code,
        container_code=container_code,
        quantity=quantity,
        weight=weight,
        weight_unit=weight_unit,
        payment_method=payment_method,
        account_number=account_number or None,
        trans_id=trans_id or None,
        transaction_src=transaction_src,
    )


@mcp.tool()
async def cancel_pickup(
    cancel_by: str,
    prn: str = "",
    trans_id: str = "",
    transaction_src: str = "ups-mcp",
) -> dict[str, Any]:
    """
    Cancel a scheduled pickup.

    Args:
        cancel_by: 'account' = Cancel by Account Number, 'prn' = Cancel by PRN.
        prn: Pickup Request Number (required if cancel_by='prn').
        trans_id: Optional request id.
        transaction_src: Optional caller source name. Default 'ups-mcp'.
    """
    return _require_tool_manager().cancel_pickup(
        cancel_by=cancel_by,
        prn=prn or None,
        trans_id=trans_id or None,
        transaction_src=transaction_src,
    )


@mcp.tool()
async def get_pickup_status(
    pickup_type: str,
    account_number: str = "",
    trans_id: str = "",
    transaction_src: str = "ups-mcp",
) -> dict[str, Any]:
    """
    Check pending pickup status for an account.

    Args:
        pickup_type: 'oncall', 'smart', or 'both'.
        account_number: Optional. Defaults to UPS_ACCOUNT_NUMBER env var.
        trans_id: Optional request id.
        transaction_src: Optional caller source name. Default 'ups-mcp'.
    """
    return _require_tool_manager().get_pickup_status(
        pickup_type=pickup_type,
        account_number=account_number or None,
        trans_id=trans_id or None,
        transaction_src=transaction_src,
    )


@mcp.tool()
async def get_political_divisions(
    country_code: str,
    trans_id: str = "",
    transaction_src: str = "ups-mcp",
) -> dict[str, Any]:
    """
    Get list of states/provinces for a country.

    Args:
        country_code: 2-letter ISO country code.
        trans_id: Optional request id.
        transaction_src: Optional caller source name. Default 'ups-mcp'.
    """
    return _require_tool_manager().get_political_divisions(
        country_code=country_code,
        trans_id=trans_id or None,
        transaction_src=transaction_src,
    )


@mcp.tool()
async def get_service_center_facilities(
    city: str,
    state: str,
    postal_code: str,
    country_code: str,
    pickup_pieces: int = 1,
    container_code: str = "01",
    trans_id: str = "",
    transaction_src: str = "ups-mcp",
) -> dict[str, Any]:
    """
    Find UPS service center facilities for a destination.

    Args:
        city, state, postal_code, country_code: Destination address.
        pickup_pieces: Number of pieces.
        container_code: '01'=Package, '02'=UPS Letter.
        trans_id: Optional request id.
        transaction_src: Optional caller source name. Default 'ups-mcp'.
    """
    return _require_tool_manager().get_service_center_facilities(
        city=city,
        state=state,
        postal_code=postal_code,
        country_code=country_code,
        pickup_pieces=pickup_pieces,
        container_code=container_code,
        trans_id=trans_id or None,
        transaction_src=transaction_src,
    )
```

**Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_server_new_tools.py -v`
Expected: All PASS

**Step 5: Run full test suite**

Run: `python3 -m pytest tests/ -v`
Expected: All tests PASS (existing + all new)

**Step 6: Commit**

```bash
git add ups_mcp/server.py tests/test_server_new_tools.py
git commit -m "feat: expose 11 new MCP tool endpoints in server.py"
```

---

## Task 9: Full regression + cleanup commit

**Step 1: Run entire test suite**

Run: `python3 -m pytest tests/ -v`
Expected: All tests PASS

**Step 2: Verify all 18 tools are registered**

Run: `python3 -c "from ups_mcp.server import mcp; print([t.name for t in mcp._tool_manager.list_tools()])" 2>/dev/null || echo "manual verification needed"`

Or inspect the server module to count `@mcp.tool()` decorators.

**Step 3: Commit any remaining changes**

If there are any uncommitted files (e.g., constants.py if not committed in Task 3):

```bash
git status
# Stage and commit any remaining changes
```
