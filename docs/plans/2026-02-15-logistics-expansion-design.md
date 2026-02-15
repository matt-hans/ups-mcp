# UPS MCP Logistics Expansion — Design Document

**Date:** 2026-02-15
**Status:** Approved

## Overview

Expand the UPS MCP server from 7 tools to 18 by integrating Landed Cost, Paperless Documents, Locator, and Pickup APIs. All new tools follow the **structured flat parameter** pattern — the ToolManager accepts semantic inputs and constructs UPS payloads internally.

## Architecture Decisions

### Approach: Consistent Structured Abstraction

Every new tool uses structured flat parameters. The LLM never sees raw UPS request structures. The ToolManager maps semantic inputs into the complex nested payloads required by UPS APIs. This provides:

- Best LLM experience — agents use simple, clear parameters
- Pre-flight validation before hitting UPS (time constraints, format checks)
- Consistent pattern across all 11 new tools

### Infrastructure Changes

**1. `openapi_registry.py` — Expand DEFAULT_SPEC_FILES**

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

**2. `http_client.py` — Add `additional_headers` parameter**

Add `additional_headers: dict[str, str] | None = None` to `call_operation()`. Merge into request headers after standard Auth/transId/transactionSrc headers. Filter out `None` values. **Reserved headers (`Authorization`, `transId`, `transactionSrc`) are protected and cannot be overwritten** — merge uses case-insensitive comparison to skip any key matching a reserved header.

```python
def call_operation(
    self,
    operation: OperationSpec,
    *,
    operation_name: str,
    path_params: dict[str, Any],
    query_params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
    trans_id: str | None = None,
    transaction_src: str | None = None,
    additional_headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    # ... existing logic ...
    headers = {
        "Authorization": f"Bearer {token}",
        "transId": request_trans_id,
        "transactionSrc": request_transaction_src,
    }
    if additional_headers:
        reserved = {k.lower() for k in headers}
        for k, v in additional_headers.items():
            if v is not None and k.lower() not in reserved:
                headers[k] = v
```

**3. `tools.py` — Add `account_number` to ToolManager**

```python
class ToolManager:
    def __init__(
        self,
        base_url: str,
        client_id: str | None,
        client_secret: str | None,
        account_number: str | None = None,
        registry: OpenAPIRegistry | None = None,
    ) -> None:
        self.account_number = account_number
        # ... existing init ...
```

**4. `tools.py` — Add `additional_headers` to `_execute_operation`**

Pass-through to `http_client.call_operation()`.

**5. `server.py` — Pass UPS_ACCOUNT_NUMBER**

```python
tool_manager = tools.ToolManager(
    base_url=base_url,
    client_id=client_id,
    client_secret=client_secret,
    account_number=os.getenv("UPS_ACCOUNT_NUMBER"),
)
```

**6. `constants.py` — Add mapping constants**

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

## Tool Inventory (11 New Tools)

### Landed Cost Suite (1 tool)

#### `get_landed_cost_quote`
- **Operation ID:** `LandedCost` (POST `/landedcost/{version}/quotes`)
- **Headers:** `AccountNumber` (optional, from env fallback)
- **Parameters:** `currency_code`, `export_country_code`, `import_country_code`, `commodities: list[dict]`, `shipment_type`
- **Payload construction:** ToolManager iterates commodity list, distributes top-level currency/country into each item, builds `LandedCostRequest` structure
- **Required by spec:** `transID` (auto-generated UUID), `alversion` (integer, default 1), `shipment.id` (auto-generated UUID). Both `transID` and `shipment.id` are generated internally — the caller does not need to provide them.
- **Commodity dict keys:** `hs_code`, `price` (required), `quantity` (required), `description`, `weight`, `weight_unit`, `uom`

### Paperless Document Suite (3 tools)

#### `upload_paperless_document`
- **Operation ID:** `Upload` (POST `/paperlessdocuments/{version}/upload`)
- **Headers:** `ShipperNumber` (required, from arg or env fallback)
- **Parameters:** `file_content_base64`, `file_name`, `file_format`, `document_type`, `shipper_number`
- **Validation:** File format checked against allowed set (pdf, doc, docx, xls, xlsx, txt, rtf, tif, jpg)
- **Input:** Base64 only — no file path support. Clients use a separate filesystem tool if needed.

#### `push_document_to_shipment`
- **Operation ID:** `PushToImageRepository` (POST `/paperlessdocuments/{version}/image`)
- **Headers:** `ShipperNumber` (required, from arg or env fallback)
- **Parameters:** `document_id`, `shipment_identifier`, `shipment_type` ('1'=Small Package, '2'=Freight)

#### `delete_paperless_document`
- **Operation ID:** `Delete` (DELETE `/paperlessdocuments/{version}/DocumentId/ShipperNumber`)
- **Headers:** `ShipperNumber` (required), `DocumentId` (required)
- **Parameters:** `document_id`, `shipper_number`
- **Note:** This endpoint uses header params for DocumentId/ShipperNumber, not path segments despite the URL pattern.

### Locator Suite (1 tool)

#### `find_locations`
- **Operation ID:** `Locator` (POST `/locations/{version}/search/availabilities/{reqOption}`)
- **Semantic mapping:** `location_type` string → `reqOption` integer via `LOCATOR_OPTIONS` constant
  - `access_point` → 64
  - `retail` → 32
  - `general` → 1
- **Parameters:** `address_line`, `city`, `state`, `postal_code`, `country_code`, `location_type: Literal[...]`, `radius`, `unit_of_measure: Literal["MI","KM"]`
- **Conditional body:** When `location_type == "access_point"`, includes `AccessPointSearch` container

### Pickup Suite (6 tools)

#### `rate_pickup`
- **Operation ID:** `Pickup Rate` (POST `/shipments/{version}/pickup/{pickuptype}`)
- **Parameters:** `pickup_type: Literal["oncall","smart","both"]`, address fields, `pickup_date`, `ready_time`, `close_time`, `service_date_option`, `residential_indicator`, `service_code`, `container_code`, `quantity`, `destination_country_code`
- **Required by spec:** `ServiceDateOption` ('01'=Same-Day, '02'=Future-Day, '03'=Specific-Day), `PickupAddress.ResidentialIndicator` ('Y'/'N'), `PickupDateInfo` with `ReadyTime`/`CloseTime`/`PickupDate` (required when `ServiceDateOption='03'`, always included for safety)

#### `schedule_pickup`
- **Operation ID:** `Pickup Creation` (POST `/pickupcreation/{version}/pickup`)
- **Parameters:** `pickup_date`, `ready_time`, `close_time`, address fields, `contact_name`, `phone_number`, `residential_indicator`, service/container/quantity/weight fields, `payment_method`, `rate_pickup_indicator`, `account_number`
- **Required by spec:** `RatePickupIndicator` ('Y'/'N'), `Shipper.Account.AccountNumber` (nested, not top-level), `PickupAddress.ResidentialIndicator`, `PickupAddress.CompanyName`, `PickupAddress.Phone.Number`
- **Pre-flight validation:**
  - Validate `ready_time < close_time` before sending to UPS
  - When `payment_method='01'` (pay by shipper account), account number must be available (via explicit arg or `UPS_ACCOUNT_NUMBER` env var). Raises `ToolError` if missing — prevents sending invalid requests to UPS.

#### `cancel_pickup`
- **Operation ID:** `Pickup Cancel` (DELETE `/shipments/{version}/pickup/{CancelBy}`)
- **Semantic mapping:** `cancel_by: Literal["account","prn"]` → `"01"/"02"` via `PICKUP_CANCEL_OPTIONS`
- **Parameters:** `cancel_by`, `prn` (required if cancel_by='prn')
- **Header:** `Prn` header injected when canceling by PRN

#### `get_pickup_status`
- **Operation ID:** `Pickup Pending Status` (GET `/shipments/{version}/pickup/{pickuptype}`)
- **Headers:** `AccountNumber` (required, from arg or env fallback)
- **Parameters:** `pickup_type: Literal["oncall","smart","both"]`, `account_number`

#### `get_political_divisions`
- **Operation ID:** `Pickup Get Political Division1 List` (GET `/pickup/{version}/countries/{countrycode}`)
- **Parameters:** `country_code`
- **Note:** Simple GET, no body. Returns list of states/provinces for a country.

#### `get_service_center_facilities`
- **Operation ID:** `Pickup Get Service Center Facilities` (POST `/pickup/{version}/servicecenterlocations`)
- **Parameters:** `city`, `state`, `postal_code`, `country_code`, `pickup_pieces`, `container_code`

## Header Injection Summary

| Tool | Header | Source |
|------|--------|--------|
| `get_landed_cost_quote` | `AccountNumber` | Optional, env fallback |
| `upload_paperless_document` | `ShipperNumber` | Required, env fallback |
| `push_document_to_shipment` | `ShipperNumber` | Required, env fallback |
| `delete_paperless_document` | `ShipperNumber` + `DocumentId` | Required |
| `get_pickup_status` | `AccountNumber` | Required, env fallback |
| `cancel_pickup` | `Prn` | Conditional (cancel_by='prn') |

## Testing Strategy

### New Unit Test Files

| File | Coverage |
|------|----------|
| `test_landed_cost_tools.py` | Payload construction, commodity validation, header injection |
| `test_paperless_tools.py` | Upload/push/delete payloads, ShipperNumber header, format validation |
| `test_locator_tools.py` | reqOption mapping, body construction, invalid location_type |
| `test_pickup_tools.py` | All 6 pickup ops: payloads, time validation, cancel_by mapping |
| `test_server_new_tools.py` | FakeToolManager for all 11 new server endpoints |

### Test Patterns
- FakeHTTPClient capturing pattern (same as test_legacy_tools.py) for unit tests
- **Contract tests**: Validate generated payloads contain all OpenAPI-required fields per spec
- Verify correct operation_id, path_params, additional_headers
- Validate ToolError for invalid inputs
- No live API calls in unit/contract tests

### New Test Files

| File | Coverage |
|------|----------|
| `test_landed_cost_tools.py` | Payload construction, commodity validation, header injection, contract |
| `test_paperless_tools.py` | Upload/push/delete payloads, ShipperNumber header, format validation, contract |
| `test_locator_tools.py` | reqOption mapping, body construction, invalid location_type, contract |
| `test_pickup_tools.py` | All 6 pickup ops: payloads, time validation, cancel_by mapping, contract |
| `test_server_new_tools.py` | FakeToolManager for all 11 new server endpoints |

### Existing Test Updates
- `test_openapi_registry.py`: Expect 7 spec files (currently 3)
- `test_package_data.py`: Verify new specs accessible as package resources
- `test_http_client.py`: Test additional_headers merge behavior + reserved header protection

### E2E Updates
- `superpowers_debug.py`: Add sections for each new tool against CIE

### Documentation Updates
- `README.md`: Update env var docs (add `UPS_ACCOUNT_NUMBER`), spec file list, tool inventory (all 18 tools)

## Module Organization

All 11 new tools are added to `ups_mcp/tools.py` within the existing `ToolManager` class. Shared DRY builders (`_resolve_account`, `_require_account`, `_build_transaction_ref`) keep method bodies concise.

**Future consideration:** If the file exceeds ~600 lines after all tools are added, a follow-up milestone can split into `ups_mcp/tools/` package:
- `_base.py`: shared helpers + `_execute_operation`
- `core.py`, `landed_cost.py`, `paperless.py`, `locator.py`, `pickup.py`: per-suite methods
- `__init__.py`: re-exports composed `ToolManager`

This split is deferred to avoid unnecessary churn during initial implementation.

## Implementation Order

1. **Infrastructure** (registry, http_client with case-insensitive header guard, tools init, server init, constants, shared builders)
2. **Landed Cost** (1 tool + unit tests + contract tests — including `transID` and `shipment.id`)
3. **Paperless Documents** (3 tools + unit tests + contract tests)
4. **Locator** (1 tool + unit tests + contract tests — version v3)
5. **Pickup** (6 tools + unit tests + contract tests — including `payment_method='01'` account validation)
6. **Server endpoints** (all 11 @mcp.tool definitions with Literal types)
7. **README + docs** (env vars, spec files, tool inventory)
8. **Full regression**
