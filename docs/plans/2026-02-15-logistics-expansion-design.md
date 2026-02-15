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
    "Locater.yaml",
    "Pickup.yaml",
)
```

**2. `http_client.py` — Add `additional_headers` parameter**

Add `additional_headers: dict[str, str] | None = None` to `call_operation()`. Merge into request headers after standard Auth/transId/transactionSrc headers. Filter out `None` values.

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
        headers.update({k: v for k, v in additional_headers.items() if v is not None})
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
- **Parameters:** `pickup_type: Literal["oncall","smart","both"]`, address fields, `pickup_date`, `service_code`, `container_code`, `quantity`, `destination_country_code`

#### `schedule_pickup`
- **Operation ID:** `Pickup Creation` (POST `/pickupcreation/{version}/pickup`)
- **Parameters:** `pickup_date`, `ready_time`, `close_time`, address fields, `contact_name`, `phone_number`, service/container/quantity/weight fields, `payment_method`, `account_number`
- **Pre-flight validation:** Validate `ready_time < close_time` before sending to UPS

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
- FakeHTTPClient capturing pattern (same as test_legacy_tools.py)
- Verify correct operation_id, path_params, additional_headers
- Validate ToolError for invalid inputs
- No live API calls

### Existing Test Updates
- `test_openapi_registry.py`: Expect 7 spec files (currently 3)
- `test_package_data.py`: Verify new specs accessible as package resources
- `test_http_client.py`: Test additional_headers merge behavior

### E2E Updates
- `superpowers_debug.py`: Add sections for each new tool against CIE

## Implementation Order

1. **Infrastructure** (registry, http_client, tools init, server init, constants)
2. **Landed Cost** (1 tool + tests)
3. **Paperless Documents** (3 tools + tests)
4. **Locator** (1 tool + tests)
5. **Pickup** (6 tools + tests)
6. **Server endpoints** (all 11 @mcp.tool definitions)
7. **Existing test updates** (registry, package data, http_client)
8. **E2E diagnostic** (superpowers_debug.py)
