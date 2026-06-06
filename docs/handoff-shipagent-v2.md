# UPS MCP v2 Handoff — ShipAgent Integration Update

**Date:** 2026-02-15
**Scope:** UPS MCP server expanded from 7 tools to 18 tools across 4 new API domains.
**Audience:** ShipAgent development team

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [What Changed in UPS MCP](#2-what-changed-in-ups-mcp)
3. [Breaking Changes](#3-breaking-changes)
4. [Updated Tool Inventory](#4-updated-tool-inventory)
5. [New Environment Variables and Spec Files](#5-new-environment-variables-and-spec-files)
6. [Per-Tool Integration Guide](#6-per-tool-integration-guide)
7. [New Response Normalization Targets](#7-new-response-normalization-targets)
8. [New Error Codes to Map](#8-new-error-codes-to-map)
9. [Payload Construction Updates](#9-payload-construction-updates)
10. [Updated Hard-Won UPS API Lessons](#10-updated-hard-won-ups-api-lessons)
11. [Recommended Integration Priorities](#11-recommended-integration-priorities)
12. [File Change Matrix](#12-file-change-matrix)
13. [Testing Checklist Additions](#13-testing-checklist-additions)
14. [Updated Potential Expansions](#14-updated-potential-expansions)

---

## 1. Executive Summary

The UPS MCP server has expanded from **7 tools to 18 tools**, adding coverage for:

| Domain | New Tools | Count |
|--------|-----------|:-----:|
| **Landed Cost** | `get_landed_cost_quote` | 1 |
| **Paperless Documents** | `upload_paperless_document`, `push_document_to_shipment`, `delete_paperless_document` | 3 |
| **Locator** | `find_locations` | 1 |
| **Pickup** | `rate_pickup`, `schedule_pickup`, `cancel_pickup`, `get_pickup_status`, `get_political_divisions`, `get_service_center_facilities` | 6 |

**Impact on ShipAgent:**

- **One behavioral change:** `rate_shipment` now validates required fields pre-flight and supports MCP form-mode elicitation (same as `create_shipment`). Batch callers sending incomplete rate bodies will now receive `ELICITATION_UNSUPPORTED` instead of UPS API errors. See [Section 3](#3-breaking-changes).
- **Interactive path (Path A):** All 11 new tools are auto-discovered by the SDK. No code changes required for basic agent access. System prompt updates recommended. `rate_shipment` now prompts for missing fields via form elicitation.
- **Batch path (Path B):** New tools require explicit `UPSMCPClient` wrapping only if ShipAgent needs programmatic/batch access to them. Ensure `build_ups_rate_payload()` produces complete bodies (see [Section 9.3](#93-existing-payload-builder--rate-validation-awareness)).
- **One critical new discovery:** The Shipping API uses `Packaging` (not `PackagingType`) as the key name inside `Package`. Rating API uses `PackagingType`. See [Section 10](#10-updated-hard-won-ups-api-lessons).

---

## 2. What Changed in UPS MCP

### 2.1 Architecture Changes

The MCP server's layered architecture now includes two new modules for preflight validation and elicitation:

```
server.py (FastMCP, 18 async @mcp.tool endpoints)
    ↓
elicitation.py (shared elicitation infrastructure — schema, normalize, validate, rehydrate)
shipment_validator.py (shipment-specific rules, defaults, canonicalization)
rating_validator.py (rating-specific rules, defaults, canonicalization)     ← NEW
    ↓
tools.py (ToolManager — orchestration, parameter validation, operation routing)
    ↓
http_client.py (UPSHTTPClient — path rendering, HTTP execution, error parsing)
    ↓
authorization.py (OAuthManager — thread-safe OAuth2 client_credentials)
```

New tools follow the same pattern as existing spec-backed tools: operations are looked up from the `OpenAPIRegistry` by `operation_id`, path params resolved from spec defaults + caller overrides.

### 2.2 Spec File Changes

The OpenAPI spec loading now distinguishes **required** and **optional** spec files:

| File | Status | Tools Powered |
|------|--------|---------------|
| `Rating.yaml` | Required | `rate_shipment` |
| `Shipping.yaml` | Required | `create_shipment`, `void_shipment`, `recover_label` |
| `TimeInTransit.yaml` | Required | `get_time_in_transit` |
| `LandedCost.yaml` | **Optional (new)** | `get_landed_cost_quote` |
| `Paperless.yaml` | **Optional (new)** | `upload_paperless_document`, `push_document_to_shipment`, `delete_paperless_document` |
| `Locator.yaml` | **Optional (new)** | `find_locations` |
| `Pickup.yaml` | **Optional (new)** | `rate_pickup`, `schedule_pickup`, `cancel_pickup`, `get_pickup_status`, `get_political_divisions`, `get_service_center_facilities` |

If an optional spec file is absent, the corresponding tools are **unavailable** (the MCP server starts without them; calling one raises `ToolError`). Required spec files must all be present or the server fails to start.

### 2.3 Tool Design Philosophy

New tools fall into two categories:

**Structured-parameter tools** (Landed Cost, Paperless, Locator, Pickup) — The MCP tool accepts simple, flat parameters and constructs the UPS API payload internally. Callers never build raw UPS request bodies.

```
# Example: get_landed_cost_quote
# Caller passes flat args; tool constructs the full UPS payload internally
get_landed_cost_quote(
    currency_code="USD",
    export_country_code="US",
    import_country_code="GB",
    commodities=[{"price": 25.00, "quantity": 2, "hs_code": "6109.10"}],
)
```

**Raw-body tools with validation & elicitation** (`create_shipment`, `rate_shipment`) — The caller provides the full UPS API request body. The tool validates required fields, applies 3-tier defaults, and prompts for missing data via MCP form elicitation if supported. See [Section 2.4](#24-elicitation-expansion).

**Raw-body pass-through tools** (`recover_label`, `get_time_in_transit`) — The caller provides the full UPS API request body. No preflight validation; body is forwarded to UPS as-is.

This distinction matters for ShipAgent: **structured tools need no payload builder** on the ShipAgent side. The tool handles payload construction.

### 2.4 Elicitation Expansion

`create_shipment` and `rate_shipment` now share a centralized elicitation infrastructure extracted into `ups_mcp/elicitation.py`. This is a significant architectural change:

**What is MCP form-mode elicitation?**

When a caller sends an incomplete request body (e.g. missing shipper address), the MCP tool can prompt the connected client to fill in the missing fields via a dynamically generated form (Pydantic model → JSON Schema). This only works when the MCP client advertises `capabilities.elicitation.form` support.

**How it works (both `create_shipment` and `rate_shipment`):**

```
1. Canonicalize body (Package/ShipmentCharge dict → list)
2. Apply 3-tier defaults (built-in → env → caller body)
3. Preflight: find missing required fields
4. If none missing → send to UPS
5. If missing + client supports form elicitation:
   a. Build Pydantic schema from missing fields (with enums, defaults, constraints)
   b. Call ctx.elicit() → client shows form → user fills in values
   c. Normalize elicited values (trim, uppercase country/state codes)
   d. Validate elicited values (weight > 0, country = 2-alpha, postal format)
   e. Rehydrate flat values back into nested UPS structure
   f. Re-check for still-missing fields → error if any remain
   g. Send to UPS
6. If missing + NO elicitation support → raise ELICITATION_UNSUPPORTED ToolError
   with structured payload listing all missing fields (dot_paths, flat_keys, prompts)
```

**Shared infrastructure in `elicitation.py`:**

| Component | Purpose |
|-----------|---------|
| `FieldRule` | Declares a required field with dot-path, flat_key, prompt, type metadata |
| `MissingField` | A specific missing field instance (from checking a body against rules) |
| `build_elicitation_schema()` | Generates dynamic Pydantic model from missing fields |
| `normalize_elicited_values()` | Trims, uppercases country/state/weight-unit codes |
| `validate_elicited_values()` | Semantic validation (weight, country, postal format, enums) |
| `rehydrate()` | Merges flat form data back into nested UPS dict structure |
| `check_form_elicitation()` | Checks if connected MCP client supports form elicitation |
| `elicit_and_rehydrate()` | Full orchestration flow (steps 5a–5g above) |

**Tool-specific validators:**

| Module | Tool | Root Path | Unique Rules |
|--------|------|-----------|-------------|
| `shipment_validator.py` | `create_shipment` | `ShipmentRequest.*` | International description, invoice line total, shipper contact |
| `rating_validator.py` | `rate_shipment` | `RateRequest.*` | Service.Code conditional (skipped in Shop mode) |

Both validators reuse shared sub-path rules for packages (`PACKAGE_RULES`), payment (`PAYMENT_*`), and country-conditional fields (`COUNTRY_CONDITIONAL_RULES`) from `shipment_validator.py`, prefixing with the appropriate root path at check-time.

**Impact on ShipAgent:**

- **Interactive path:** If the MCP client supports form elicitation, users see a form for missing fields instead of a raw error. No ShipAgent code changes needed.
- **Batch path:** `UPSMCPClient.get_rate()` now receives `ELICITATION_UNSUPPORTED` errors (with structured `missing` array) instead of UPS API errors when required fields are absent. See [Section 3](#3-breaking-changes) for migration details.
- **Error handling:** Six new error codes from both tools. See [Section 8](#8-new-error-codes-to-map).

---

## 3. Breaking Changes

### To Existing Tools

**`rate_shipment` — Behavioral Change (Preflight Validation + Elicitation)**

`rate_shipment` now validates required fields **before** sending to UPS, matching the `create_shipment` pattern. Previously, an incomplete body was forwarded to UPS and the UPS API returned its own error. Now:

| Scenario | Before | After |
|----------|--------|-------|
| Missing required fields, no `ctx` | UPS API error (various codes) | `ELICITATION_UNSUPPORTED` ToolError with structured `missing` array |
| Missing required fields, `ctx` with form support | UPS API error | Form prompt → user fills in → UPS call |
| Ambiguous payer (multiple billing objects) | UPS API error | `MALFORMED_REQUEST` ToolError with `reason: "ambiguous_payer"` |
| Malformed body structure | UPS API error | `MALFORMED_REQUEST` ToolError with `reason: "malformed_structure"` |
| Complete body | UPS call (unchanged) | UPS call (unchanged) |

**ShipAgent action required for `UPSMCPClient.get_rate()`:**

The batch path doesn't have MCP `ctx`, so any incomplete rate body now raises `ELICITATION_UNSUPPORTED` instead of a UPS API error. Two options:

1. **Preferred:** Ensure `build_ups_rate_payload()` always produces a complete body with all required fields. The 3-tier defaults in `rating_validator.py` fill in `ShipperNumber` (from `UPS_ACCOUNT_NUMBER`), `PaymentInformation.ShipmentCharge[0].Type` (default `"01"`), and `BillShipper.AccountNumber` (from `UPS_ACCOUNT_NUMBER`). As long as the caller provides Shipper name/address, ShipTo name/address, Package info, and Service.Code (for Rate mode), the body will pass validation.

2. **Alternative:** Handle `ELICITATION_UNSUPPORTED` in the error mapper. The `missing` array in the error payload provides exactly which fields are absent, so ShipAgent could surface these as user-facing validation errors.

**New `rate_shipment` signature:**

```python
rate_shipment(
    requestoption: str,
    request_body: dict,
    version: str = "v2409",
    additionalinfo: str = "",
    trans_id: str = "",
    transaction_src: str = "ups-mcp",
    ctx: Context | None = None,        # NEW — injected by FastMCP, not by callers
)
```

The `ctx` parameter is injected by FastMCP — callers do not provide it. Programmatic/batch callers see `ctx=None`, which means elicitation is unavailable and missing fields raise `ELICITATION_UNSUPPORTED`.

**All other existing tools are unchanged.** `track_package`, `validate_address`, `void_shipment`, `recover_label`, and `get_time_in_transit` retain their exact same signatures and response formats.

### To Environment Variables

| Variable | Before | After | Action Required |
|----------|--------|-------|-----------------|
| `UPS_ACCOUNT_NUMBER` | Used only for `create_shipment` billing | Now also used by `rate_shipment` (ShipperNumber + BillShipper defaults), Landed Cost, Paperless, Pickup, and Cancel tools as fallback account | **None** — behavior is additive. If already set, new tools use it automatically. |
| `UPS_MCP_SPECS_DIR` | All spec files required | Required files (3) + optional files (4). Missing optional specs disable corresponding tools, no error. | **Action needed** — see [Section 5](#5-new-environment-variables-and-spec-files). |

---

## 4. Updated Tool Inventory

### Full 18-Tool Inventory

| # | Tool | Domain | Interactive | Batch | UPSMCPClient Method | Account Required | Elicitation |
|---|------|--------|:-----------:|:-----:|---------------------|:----------------:|:-----------:|
| 1 | `track_package` | Tracking | Yes | No | — | No | — |
| 2 | `validate_address` | Address | Yes | Yes | `validate_address()` | No | — |
| 3 | `rate_shipment` | Rating | Yes | Yes | `get_rate()` | No | **Yes** |
| 4 | `create_shipment` | Shipping | Yes | Yes | `create_shipment()` | Yes | **Yes** |
| 5 | `void_shipment` | Shipping | Yes | Yes | `void_shipment()` | No | — |
| 6 | `recover_label` | Shipping | Yes | No | — | No | — |
| 7 | `get_time_in_transit` | Transit | Yes | No | — | No | — |
| 8 | `get_landed_cost_quote` | **Landed Cost** | Yes | — | — | Optional | — |
| 9 | `upload_paperless_document` | **Paperless** | Yes | — | — | Yes | — |
| 10 | `push_document_to_shipment` | **Paperless** | Yes | — | — | Yes | — |
| 11 | `delete_paperless_document` | **Paperless** | Yes | — | — | Yes | — |
| 12 | `find_locations` | **Locator** | Yes | — | — | No | — |
| 13 | `rate_pickup` | **Pickup** | Yes | — | — | No | — |
| 14 | `schedule_pickup` | **Pickup** | Yes | — | — | Yes* | — |
| 15 | `cancel_pickup` | **Pickup** | Yes | — | — | Conditional | — |
| 16 | `get_pickup_status` | **Pickup** | Yes | — | — | Yes | — |
| 17 | `get_political_divisions` | **Pickup** | Yes | — | — | No | — |
| 18 | `get_service_center_facilities` | **Pickup** | Yes | — | — | No | — |

\* `schedule_pickup` requires account when `payment_method="01"` (shipper account billing).

"Account Required" means the tool calls `_require_account()` which uses the `UPS_ACCOUNT_NUMBER` env var as fallback if no explicit value is provided.

"Elicitation" means the tool validates required fields pre-flight and prompts for missing data via MCP form-mode elicitation (if the client supports it). Without elicitation support, missing fields raise `ELICITATION_UNSUPPORTED` with a structured `missing` array. See [Section 2.4](#24-elicitation-expansion) for architecture details.

### New Tool MCP Names

When the agent calls these via the interactive path, they appear as:

```
mcp__ups__get_landed_cost_quote
mcp__ups__upload_paperless_document
mcp__ups__push_document_to_shipment
mcp__ups__delete_paperless_document
mcp__ups__find_locations
mcp__ups__rate_pickup
mcp__ups__schedule_pickup
mcp__ups__cancel_pickup
mcp__ups__get_pickup_status
mcp__ups__get_political_divisions
mcp__ups__get_service_center_facilities
```

---

## 5. New Environment Variables and Spec Files

### 5.1 UPS_ACCOUNT_NUMBER (Elevated Importance)

Previously only needed for `create_shipment` billing. Now serves as the default account for:

| Tool | Header/Field Used |
|------|-------------------|
| `get_landed_cost_quote` | `AccountNumber` HTTP header |
| `upload_paperless_document` | `ShipperNumber` HTTP header + request body |
| `push_document_to_shipment` | `ShipperNumber` HTTP header + request body |
| `delete_paperless_document` | `ShipperNumber` HTTP header |
| `schedule_pickup` | `Shipper.Account.AccountNumber` in request body |
| `cancel_pickup` (by account) | `AccountNumber` HTTP header |
| `get_pickup_status` | `AccountNumber` HTTP header |

**ShipAgent action:** Ensure `UPS_ACCOUNT_NUMBER` is always passed in the MCP subprocess environment. It was previously optional.

### 5.2 Spec Files for UPS_MCP_SPECS_DIR

If ShipAgent uses `UPS_MCP_SPECS_DIR` to provide spec overrides, the directory must now include the new optional spec files for the new tools to be available:

```
specs/
  Rating.yaml          # Required (existing)
  Shipping.yaml        # Required (existing)
  TimeInTransit.yaml   # Required (existing)
  LandedCost.yaml      # Optional (new) — enables get_landed_cost_quote
  Paperless.yaml       # Optional (new) — enables upload/push/delete paperless
  Locator.yaml         # Optional (new) — enables find_locations
  Pickup.yaml          # Optional (new) — enables all 6 pickup tools
```

**ShipAgent action in `src/services/ups_specs.py`:**

```python
# Add new spec files to ensure_ups_specs_dir()
SPEC_FILES = {
    "Rating.yaml": ...,
    "Shipping.yaml": ...,
    "TimeInTransit.yaml": ...,
    # New — add these:
    "LandedCost.yaml": ...,
    "Paperless.yaml": ...,
    "Locator.yaml": ...,
    "Pickup.yaml": ...,
}
```

If ShipAgent doesn't use `UPS_MCP_SPECS_DIR` (i.e., lets the MCP server use bundled specs), no spec changes are needed — the MCP server ships with all 7 files included.

### 5.3 Config Update

**File:** `src/orchestrator/agent/config.py`

Ensure `UPS_ACCOUNT_NUMBER` is passed to the MCP subprocess:

```python
def get_ups_mcp_config() -> MCPServerConfig:
    return MCPServerConfig(
        command=python_path,
        args=["-m", "ups_mcp"],
        env={
            "CLIENT_ID": os.environ.get("UPS_CLIENT_ID", ""),
            "CLIENT_SECRET": os.environ.get("UPS_CLIENT_SECRET", ""),
            "ENVIRONMENT": _environment,
            "UPS_ACCOUNT_NUMBER": os.environ.get("UPS_ACCOUNT_NUMBER", ""),  # ← Ensure present
            "UPS_MCP_SPECS_DIR": str(specs_dir),
            "PATH": os.environ.get("PATH", ""),
        },
    )
```

---

## 6. Per-Tool Integration Guide

### 6.1 get_landed_cost_quote

**Purpose:** Calculate duties, taxes, and fees for international shipments.

**Integration classification:** Interactive-only. Useful for agent conversations about international shipping costs.

**Signature:**
```
get_landed_cost_quote(
    currency_code: str,           # ISO currency (USD, EUR, GBP)
    export_country_code: str,     # Origin country (US)
    import_country_code: str,     # Destination country (GB)
    commodities: list[dict],      # [{price, quantity, hs_code?, description?, weight?, weight_unit?}]
    shipment_type: str = "Sale",  # Sale, Gift, etc.
    account_number: str = "",     # Falls back to UPS_ACCOUNT_NUMBER
)
```

**Notes:**
- Payload construction is handled entirely inside the MCP tool. ShipAgent does NOT need a payload builder for this.
- The tool auto-generates `transID` (UUID) and `shipment.id` (UUID) per request.
- `alversion` is fixed to `1`.
- Each commodity gets a sequential `commodityId` ("1", "2", ...).
- Requires `AccountNumber` HTTP header — falls back to `UPS_ACCOUNT_NUMBER`.

**ShipAgent changes:**

| File | Change | Required? |
|------|--------|:---------:|
| `src/orchestrator/agent/system_prompt.py` | Add guidance for international cost estimation | Recommended |
| `src/services/ups_mcp_client.py` | Add `get_landed_cost()` method | Only if batch use needed |

**Batch integration candidate?** Yes, if ShipAgent adds international shipping. Pre-flight landed cost for each row before execute.

---

### 6.2 upload_paperless_document

**Purpose:** Upload customs/trade documents to UPS Forms History for paperless customs clearance.

**Signature:**
```
upload_paperless_document(
    file_content_base64: str,     # Base64-encoded file content
    file_name: str,               # "invoice.pdf"
    file_format: str,             # pdf, doc, docx, xls, xlsx, txt, rtf, tif, jpg
    document_type: str,           # UPS code: "002" (invoice), "003" (CO), etc.
    shipper_number: str = "",     # Falls back to UPS_ACCOUNT_NUMBER
)
```

**Response structure:**
```
UploadResponse
  └─ FormsHistoryDocumentID
      └─ DocumentID: "2013-12-04-00.15.33.207814"  (use this in push/delete)
```

**Important:** The returned `DocumentID` is required for `push_document_to_shipment` and `delete_paperless_document`. It must be captured and passed to subsequent calls.

**ShipAgent changes:**

| File | Change | Required? |
|------|--------|:---------:|
| `src/orchestrator/agent/system_prompt.py` | Add paperless document workflow guidance | Recommended |

**Batch integration candidate?** Yes, if ShipAgent adds international shipment support with customs documents. The workflow is: upload documents → create shipment → push documents to shipment.

---

### 6.3 push_document_to_shipment

**Purpose:** Attach a previously uploaded document to an existing shipment.

**Signature:**
```
push_document_to_shipment(
    document_id: str,             # From upload_paperless_document response
    shipment_identifier: str,     # 1Z tracking number
    shipment_type: str = "1",     # "1" = forward, "2" = return
    shipper_number: str = "",     # Falls back to UPS_ACCOUNT_NUMBER
)
```

**Notes:**
- Requires a real `document_id` from a prior `upload_paperless_document` call.
- Requires a real `shipment_identifier` (tracking number) from `create_shipment`.
- This is a chained operation: upload → create shipment → push document.

**ShipAgent changes:** Same as `upload_paperless_document` — if paperless docs are supported, this tool must be part of the post-shipment-creation workflow.

---

### 6.4 delete_paperless_document

**Purpose:** Remove a previously uploaded document from Forms History.

**Signature:**
```
delete_paperless_document(
    document_id: str,             # From upload_paperless_document response
    shipper_number: str = "",     # Falls back to UPS_ACCOUNT_NUMBER
)
```

**Notes:**
- Uses HTTP DELETE with `DocumentId` and `ShipperNumber` as custom headers (not path params).
- Useful for cleanup after shipment cancellation/voiding.

---

### 6.5 find_locations

**Purpose:** Find UPS Access Points, retail stores, and service locations near an address.

**Signature:**
```
find_locations(
    location_type: "access_point" | "retail" | "general" | "services",
    address_line: str,
    city: str,
    state: str,
    postal_code: str,
    country_code: str,
    radius: float = 15.0,
    unit_of_measure: "MI" | "KM" = "MI",
)
```

**Notes:**
- `location_type` maps to UPS `reqOption` codes internally: `access_point→64`, `retail→32`, `general→1`, `services→8`.
- For `access_point`, the tool automatically adds `AccessPointSearch.AccessPointStatus: "01"` (active only).
- Payload construction is handled entirely inside the MCP tool.

**ShipAgent changes:**

| File | Change | Required? |
|------|--------|:---------:|
| `src/orchestrator/agent/system_prompt.py` | Add location search guidance | Recommended |

**Batch integration candidate?** Low priority. Primarily an interactive/conversational tool.

---

### 6.6 rate_pickup

**Purpose:** Get a cost estimate for a scheduled pickup before committing.

**Signature:**
```
rate_pickup(
    pickup_type: "oncall" | "smart" | "both",
    address_line: str, city: str, state: str, postal_code: str, country_code: str,
    pickup_date: str,              # YYYYMMDD
    ready_time: str,               # HHMM (24hr)
    close_time: str,               # HHMM (24hr)
    service_date_option: "01"|"02"|"03" = "02",
    residential_indicator: "Y"|"N" = "Y",
    service_code: str = "001",
    container_code: str = "01",
    quantity: int = 1,
    destination_country_code: str = "US",
)
```

**Notes:**
- Rate-only, no side effects. Safe to retry.
- Payload construction handled internally.

---

### 6.7 schedule_pickup

**Purpose:** Schedule a carrier pickup at a specified address and time.

**Signature:**
```
schedule_pickup(
    pickup_date: str,              # YYYYMMDD
    ready_time: str,               # HHMM (must be < close_time)
    close_time: str,               # HHMM
    address_line: str, city: str, state: str, postal_code: str, country_code: str,
    contact_name: str,
    phone_number: str,
    residential_indicator: "Y"|"N" = "N",
    service_code: str = "001",
    container_code: str = "01",
    quantity: int = 1,
    weight: float = 5.0,
    weight_unit: "LBS"|"KGS" = "LBS",
    payment_method: str = "01",    # "01"=shipper account, "00"=no payment
    rate_pickup_indicator: "Y"|"N" = "N",
    account_number: str = "",      # Falls back to UPS_ACCOUNT_NUMBER
)
```

**Response structure:**
```
PickupCreationResponse
  └─ PRN: "2929602E9CP"   (Pickup Request Number — use for cancel_pickup)
```

**Validation rules:**
- `ready_time` must be before `close_time` (tool raises `ToolError` if not).
- `payment_method="01"` requires `account_number` or `UPS_ACCOUNT_NUMBER` (tool raises `ToolError` if missing).
- `payment_method="00"` does NOT require account and omits `Shipper` block entirely.

**This is a mutating operation.** Do NOT retry.

**ShipAgent changes:**

| File | Change | Required? |
|------|--------|:---------:|
| `src/orchestrator/agent/system_prompt.py` | Add pickup scheduling workflow | Recommended |
| `src/orchestrator/agent/hooks.py` | Add safety gate (pickup = financial commitment) | Recommended |

**Batch integration candidate?** Yes, for post-batch-execute pickup scheduling. After all shipments are created, schedule a pickup for the batch.

---

### 6.8 cancel_pickup

**Purpose:** Cancel a previously scheduled pickup.

**Signature:**
```
cancel_pickup(
    cancel_by: "account" | "prn",
    prn: str = "",                 # Required when cancel_by="prn"
)
```

**Notes:**
- `cancel_by="account"` cancels the most recent pickup for the account. Requires `UPS_ACCOUNT_NUMBER`. Sends `AccountNumber` header.
- `cancel_by="prn"` cancels a specific pickup by PRN. Sends `Prn` header.
- This is a DELETE operation (mutating). Do NOT retry.

---

### 6.9 get_pickup_status

**Purpose:** Get pending pickup status for the account.

**Signature:**
```
get_pickup_status(
    pickup_type: "oncall" | "smart" | "both",
    account_number: str = "",      # Falls back to UPS_ACCOUNT_NUMBER
)
```

**Notes:**
- Read-only, safe to retry.
- Requires `AccountNumber` header — raises `ToolError` if no account available.

---

### 6.10 get_political_divisions

**Purpose:** Get list of states/provinces for a country (useful for pickup address validation).

**Signature:**
```
get_political_divisions(
    country_code: str,             # ISO country code (US, CA, GB, etc.)
)
```

**Notes:**
- Read-only, no account required.
- GET request with no request body.
- Useful as a reference lookup for valid state/province codes.

---

### 6.11 get_service_center_facilities

**Purpose:** Find UPS service center drop-off locations.

**Signature:**
```
get_service_center_facilities(
    city: str,
    state: str,
    postal_code: str,
    country_code: str,
    pickup_pieces: int = 1,
    container_code: str = "03",    # Default: package
)
```

**Notes:**
- Read-only, no account required.
- Internal defaults: `ServiceCode: "096"`, `ContainerCode: "03"`.

---

## 7. New Response Normalization Targets

If any of these tools are wrapped in `UPSMCPClient` for batch use, here are the response structures to normalize.

### Landed Cost Response

```
Input (raw):
  LandedCostResponse
    └─ shipment
        ├─ totalLandedCost: "45.23"
        ├─ currencyCode: "USD"
        └─ shipmentItems[]
            ├─ commodityId: "1"
            ├─ duties: "12.50"
            ├─ taxes: "7.73"
            └─ fees: "0.00"

Suggested normalized output:
  {
    "success": True,
    "totalLandedCost": "45.23",
    "currencyCode": "USD",
    "items": [
      {"commodityId": "1", "duties": "12.50", "taxes": "7.73", "fees": "0.00"}
    ]
  }
```

### Paperless Upload Response

```
Input (raw):
  UploadResponse
    └─ FormsHistoryDocumentID
        └─ DocumentID: "2013-12-04-00.15.33.207814"

Suggested normalized output:
  {
    "success": True,
    "documentId": "2013-12-04-00.15.33.207814"
  }
```

### Schedule Pickup Response

```
Input (raw):
  PickupCreationResponse
    └─ PRN: "2929602E9CP"

Suggested normalized output:
  {
    "success": True,
    "prn": "2929602E9CP"
  }
```

### Find Locations Response

```
Input (raw):
  LocatorResponse
    └─ SearchResults
        └─ DropLocation[]
            ├─ LocationID: "..."
            ├─ AddressKeyFormat: {...}
            ├─ PhoneNumber: "..."
            └─ OperatingHours: {...}

Suggested normalized output:
  {
    "success": True,
    "locations": [
      {"id": "...", "address": {...}, "phone": "...", "hours": {...}}
    ]
  }
```

---

## 8. New Error Codes to Map

New tools may return these error codes not currently in ShipAgent's `UPS_ERROR_MAP`.

### Elicitation Errors (create_shipment + rate_shipment)

Both `create_shipment` and `rate_shipment` now perform preflight validation and may raise these structured `ToolError` codes **before** hitting the UPS API:

| MCP Error Code | Reason | When | Suggested E-Code | Action |
|----------------|--------|------|:-----------------:|--------|
| `ELICITATION_UNSUPPORTED` | `unsupported` | Missing fields + no elicitation support | E-2020 (new) | Surface `missing` array as validation errors |
| `MALFORMED_REQUEST` | `malformed_structure` | Body has wrong types (e.g. string where dict expected) | E-2021 (new) | Surface as payload construction error |
| `MALFORMED_REQUEST` | `ambiguous_payer` | Multiple billing objects in same ShipmentCharge | E-2022 (new) | Surface as payload construction error |
| `ELICITATION_DECLINED` | `declined` | User declined the elicitation form | E-4001 (new) | User chose not to proceed |
| `ELICITATION_CANCELLED` | `cancelled` | User cancelled the elicitation form | E-4002 (new) | User cancelled operation |
| `ELICITATION_INVALID_RESPONSE` | `validation_errors` | Elicited values fail semantic validation | E-2023 (new) | Should not occur in batch path |
| `ELICITATION_INVALID_RESPONSE` | `rehydration_error` | Elicited values conflict with body structure | E-2024 (new) | Should not occur in batch path |
| `ELICITATION_FAILED` | `transport_error` | ctx.elicit() raised unexpected exception | E-5002 (new) | Should not occur in batch path |
| `INCOMPLETE_SHIPMENT` | `still_missing` | Fields still missing after elicitation | E-2025 (new) | Should not occur in batch path |

**Error payload structure** (all elicitation errors):

```json
{
  "code": "ELICITATION_UNSUPPORTED",
  "message": "Missing 3 required field(s) and client does not support form elicitation",
  "reason": "unsupported",
  "missing": [
    {
      "dot_path": "RateRequest.Shipment.Shipper.Name",
      "flat_key": "shipper_name",
      "prompt": "Shipper name"
    },
    ...
  ]
}
```

**For the batch path**, only `ELICITATION_UNSUPPORTED`, `MALFORMED_REQUEST` (both reasons) are relevant. The other codes only occur during interactive elicitation sessions.

**rate_shipment-specific behavior:** When `requestoption` is `"Shop"` or `"Shoptimeintransit"`, `Service.Code` is NOT required (UPS returns all service rates). The `missing` array will not include `service_code` in Shop mode.

### Landed Cost

| UPS Code | Message Pattern | Suggested E-Code | Notes |
|----------|----------------|:-----------------:|-------|
| `500` | Internal server error | E-3001 | CIE-specific; may not occur in production |
| — | "Missing transID" | E-2010 | Shouldn't occur (tool auto-generates), but guard |

### Paperless

| UPS Code | Message Pattern | Suggested E-Code | Notes |
|----------|----------------|:-----------------:|-------|
| `9590009` | "Valid Tracking Number is Required" | E-2001 | Invalid tracking number in push |
| `9590022` | "No PDF found for given documentId" | E-3006 (new) | Document not found or expired |

### Pickup

| UPS Code | Message Pattern | Suggested E-Code | Notes |
|----------|----------------|:-----------------:|-------|
| `190102` | "No shipment found within the allowed void period" | E-3007 (new) | Pickup/void timing issue |
| — | "Missing or invalid AccountNumber" | E-5001 | Account not provided for account-required operation |
| — | "Missing or invalid ContainerCode" | E-2010 | Missing required field |

### Locator

| UPS Code | Message Pattern | Suggested E-Code | Notes |
|----------|----------------|:-----------------:|-------|
| — | "No locations found" | E-3008 (new) | No results for search criteria |

### Retry Policy for New Tools

| Tool | Classification | Max Retries | Rationale |
|------|---------------|:-----------:|-----------|
| `get_landed_cost_quote` | Read-only | 2 | No side effects |
| `upload_paperless_document` | Mutating | 0 | Creates a resource |
| `push_document_to_shipment` | Mutating | 0 | Links document to shipment |
| `delete_paperless_document` | Mutating | 0 | Deletes a resource |
| `find_locations` | Read-only | 2 | No side effects |
| `rate_pickup` | Read-only | 2 | No side effects |
| `schedule_pickup` | Mutating | 0 | Creates a pickup (financial) |
| `cancel_pickup` | Mutating | 0 | Cancels a pickup |
| `get_pickup_status` | Read-only | 2 | No side effects |
| `get_political_divisions` | Read-only | 2 | No side effects |
| `get_service_center_facilities` | Read-only | 2 | No side effects |

---

## 9. Payload Construction Updates

### 9.1 Structured Tools — No Payload Builder Needed

The following new tools construct UPS payloads internally. ShipAgent callers pass **flat parameters**, not raw UPS bodies:

- `get_landed_cost_quote` — pass commodities list, country codes, currency
- `find_locations` — pass address, location type, radius
- `rate_pickup` — pass address, date/time, pickup type
- `schedule_pickup` — pass address, date/time, contact info
- `cancel_pickup` — pass cancel method + optional PRN
- `get_pickup_status` — pass pickup type
- `get_political_divisions` — pass country code
- `get_service_center_facilities` — pass address

**No `ups_payload_builder.py` changes are needed for these tools** unless ShipAgent wants to pre-validate or transform inputs before calling them.

### 9.2 Paperless Tools — Minimal Payload

Paperless tools also construct payloads internally, but callers must provide:
- Base64-encoded file content (upload)
- Document IDs from prior operations (push/delete)

If ShipAgent adds batch international shipping, the workflow is:

```
1. Read customs document from disk → base64 encode
2. upload_paperless_document(base64_content, "invoice.pdf", "pdf", "002")
3. Extract document_id from response
4. create_shipment(...)  → extract tracking_number
5. push_document_to_shipment(document_id, tracking_number)
```

### 9.3 Existing Payload Builder — Rate Validation Awareness

`build_ups_rate_payload()` and `build_ups_api_payload()` remain correct for field naming. The critical `Packaging` vs `PackagingType` distinction is already handled correctly by ShipAgent:
- Rating uses `PackagingType` (correct)
- Shipping uses `Packaging` (correct)

**New: `rate_shipment` now validates required fields.** The MCP tool applies 3-tier defaults before validation, so some fields are auto-filled:

| Field | Default Source | Value |
|-------|---------------|-------|
| `RateRequest.Shipment.Shipper.ShipperNumber` | `UPS_ACCOUNT_NUMBER` env var | Account number |
| `RateRequest.Shipment.PaymentInformation.ShipmentCharge[0].Type` | Built-in | `"01"` (Transportation) |
| `RateRequest.Shipment.PaymentInformation.ShipmentCharge[0].BillShipper.AccountNumber` | `UPS_ACCOUNT_NUMBER` env var | Account number (only if no billing object exists) |

**Fields the payload builder MUST provide** (not auto-defaulted):

| Field | Path |
|-------|------|
| Shipper name | `RateRequest.Shipment.Shipper.Name` |
| Shipper address | `RateRequest.Shipment.Shipper.Address.AddressLine[0]`, `.City`, `.CountryCode` |
| ShipTo name | `RateRequest.Shipment.ShipTo.Name` |
| ShipTo address | `RateRequest.Shipment.ShipTo.Address.AddressLine[0]`, `.City`, `.CountryCode` |
| Service code | `RateRequest.Shipment.Service.Code` (not required for Shop mode) |
| Package info | Per-package: `PackagingType.Code`, `PackageWeight.UnitOfMeasurement.Code`, `PackageWeight.Weight` |
| State/postal (US/CA/PR) | Conditional: `.StateProvinceCode` and `.PostalCode` for US, CA, or PR addresses |

**Body canonicalization:** The MCP tool normalizes `Package` and `ShipmentCharge` from dict to list form before validation. ShipAgent can pass either format.

If `build_ups_rate_payload()` already includes all of the above fields, **no changes are needed**. The MCP tool's validation will pass and the request proceeds to UPS.

---

## 10. Updated Hard-Won UPS API Lessons

Add these to the existing lessons table:

| Lesson | Detail | Discovery Context |
|--------|--------|-------------------|
| **Packaging vs PackagingType** | Shipping API `create_shipment` uses `Packaging` as the key inside Package. Rating API uses `PackagingType`. They are NOT interchangeable. Sending `PackagingType` to the Shipping API returns "Missing or invalid Package PackagingType Code". | Live E2E testing — `create_shipment` failed with Code `120600` |
| **Landed Cost: flat body** | Unlike all other UPS APIs, Landed Cost does NOT use a wrapper key. The body is flat: `{currencyCode, transID, shipment, ...}` — NOT `{LandedCostRequest: {...}}`. | Live E2E testing — "Missing transID" error because transID was nested under wrapper |
| **cancel_pickup: AccountNumber header** | `cancel_by="account"` (code `01`) requires `AccountNumber` as a custom HTTP header, even though the OpenAPI spec doesn't list it as a parameter. Without it: "Missing or invalid AccountNumber". | Live E2E testing |
| **Service center defaults** | The `get_service_center_facilities` tool uses `ServiceCode: "096"` and `ContainerCode: "03"` as defaults. Using other codes (e.g., `"001"`, `"01"`) returns "Missing or invalid ContainerCode". | Spec example analysis + live testing |
| **Paperless: ShipperNumber dual injection** | Paperless upload and push require `ShipperNumber` in BOTH the request body AND as a custom HTTP header. Missing either causes silent failures. | Spec analysis |
| **Pickup: ready_time < close_time** | `schedule_pickup` validates that `ready_time` is before `close_time` client-side and raises `ToolError` before hitting the API. | Unit test coverage |
| **Pickup: payment_method + account coupling** | `payment_method="01"` (shipper account billing) requires a valid account number. `payment_method="00"` (no payment needed) does NOT require account and the tool omits the `Shipper` block entirely. | Unit test coverage |
| **CIE dummy tracking numbers** | CIE `create_shipment` returns `1ZXXXXXXXXXXXXXXXX` — a dummy tracking number that cannot be used for subsequent operations (void, recover label, push document). Production returns real tracking numbers. | Live E2E testing |
| **CIE Landed Cost unavailable** | CIE environment returns HTTP 500 for Landed Cost (Apache Camel internal error). This is a CIE infrastructure limitation, not a code bug. Production may work. | Live E2E testing |
| **Rating + Shipping share field rules** | Package rules (PackagingType.Code, PackageWeight), payment rules (BillShipper/BillReceiver/BillThirdParty), and country-conditional rules (StateProvinceCode/PostalCode for US/CA/PR) are shared between `create_shipment` and `rate_shipment`. The only differences: root path prefix (`ShipmentRequest.*` vs `RateRequest.*`) and Service.Code is conditional in rating (not required for Shop mode). | Elicitation expansion refactoring |
| **rate_shipment Shop mode skips Service.Code** | When `requestoption` is `"Shop"` or `"Shoptimeintransit"`, `Service.Code` is NOT required — UPS returns rates for all available services. The preflight validator respects this. | Rating validator implementation |

---

## 11. Recommended Integration Priorities

### Immediate (No Code, High Value)

| Priority | Action | Effort |
|----------|--------|:------:|
| 1 | **Update system prompt** to document all 11 new tools for agent discovery | Low |
| 2 | **Pass `UPS_ACCOUNT_NUMBER`** in MCP subprocess env (if not already) | Minimal |
| 3 | **Add optional spec files** to `ups_specs.py` (if using `UPS_MCP_SPECS_DIR`) | Low |

These three changes enable all 11 new tools in the interactive path with zero additional code.

### Short-Term (Batch Integration Candidates)

| Priority | Tool | Use Case | Effort |
|----------|------|----------|:------:|
| 4 | `schedule_pickup` | Post-batch-execute: schedule pickup for all shipped orders | Medium |
| 5 | `cancel_pickup` | Cancel pickup if batch is voided | Low |
| 6 | `find_locations` | Suggest nearest drop-off when pickup isn't available | Low |

### Medium-Term (International Shipping)

| Priority | Tool | Use Case | Effort |
|----------|------|----------|:------:|
| 7 | `get_landed_cost_quote` | Pre-flight landed cost in batch preview for international rows | Medium |
| 8 | `upload_paperless_document` | Upload customs docs during batch execute | Medium |
| 9 | `push_document_to_shipment` | Attach docs post-shipment-creation in batch execute | Medium |

### Low Priority (Reference/Utility)

| Priority | Tool | Use Case | Effort |
|----------|------|----------|:------:|
| 10 | `rate_pickup` | Show pickup cost estimate before scheduling | Low |
| 11 | `get_pickup_status` | Check pickup status in agent conversation | Minimal |
| 12 | `get_political_divisions` | Reference data for address validation UI | Minimal |
| 13 | `get_service_center_facilities` | Find drop-off locations | Minimal |
| 14 | `delete_paperless_document` | Cleanup on shipment void | Low |

---

## 12. File Change Matrix

### UPS MCP Internal File Changes (Reference)

New and modified files within the UPS MCP package:

| # | File | Status | Purpose |
|---|------|:------:|---------|
| 1 | `ups_mcp/elicitation.py` | **NEW** | Shared elicitation infrastructure (schema, normalize, validate, rehydrate, orchestrate) |
| 2 | `ups_mcp/rating_validator.py` | **NEW** | Rating-specific field rules, defaults, canonicalization, and `find_missing_rate_fields()` |
| 3 | `ups_mcp/shipment_validator.py` | Modified | Moved generic code to `elicitation.py`; kept shipment-specific rules |
| 4 | `ups_mcp/server.py` | Modified | `rate_shipment` now has preflight validation + elicitation; `create_shipment` refactored to use centralized flow |
| 5 | `tests/test_elicitation.py` | **NEW** | Tests for shared elicitation infrastructure (22 tests) |
| 6 | `tests/test_rating_validator.py` | **NEW** | Tests for rating validation rules and defaults (30 tests) |
| 7 | `tests/test_server_rate_elicitation.py` | **NEW** | Integration tests for `rate_shipment` elicitation flow (14 tests) |
| 8 | `tests/rating_fixtures.py` | **NEW** | Test fixture: `make_complete_rate_body()` for generating valid RateRequest bodies |

### Minimum Viable Integration (All New Tools Interactive)

| # | File | Change | Effort |
|---|------|--------|:------:|
| 1 | `src/orchestrator/agent/system_prompt.py` | Add 11 new tool descriptions and workflow guidance | Low |
| 2 | `src/orchestrator/agent/config.py` | Ensure `UPS_ACCOUNT_NUMBER` in env dict | Minimal |
| 3 | `src/services/ups_specs.py` | Add 4 optional spec files | Low |
| 4 | `.env.example` | Document `UPS_ACCOUNT_NUMBER` as recommended | Minimal |
| 5 | `src/errors/ups_translation.py` | Map new elicitation error codes from `rate_shipment` | Low |

**That's it for basic interactive access.** The SDK auto-discovers all tools. Item 5 is only needed if ShipAgent's batch path calls `rate_shipment` with potentially incomplete bodies.

### Full Pickup Batch Integration

| # | File | Change |
|---|------|--------|
| 1 | `src/services/ups_mcp_client.py` | Add `schedule_pickup()`, `cancel_pickup()`, `get_pickup_status()`, `rate_pickup()` methods + normalizers |
| 2 | `src/services/ups_mcp_client.py` | Add retry policies (mutating for schedule/cancel, read-only for rate/status) |
| 3 | `src/services/batch_engine.py` | Add post-execute pickup scheduling step |
| 4 | `src/orchestrator/agent/tools/pipeline.py` | Add `schedule_pickup_tool`, `cancel_pickup_tool` handlers |
| 5 | `src/orchestrator/agent/tools/__init__.py` | Register new tool definitions |
| 6 | `src/orchestrator/agent/hooks.py` | Add safety gate for `schedule_pickup` (financial commitment) |
| 7 | `src/errors/ups_translation.py` | Map pickup error codes |
| 8 | `src/errors/registry.py` | Register E-3007 (pickup timing error) |
| 9 | `tests/services/test_ups_mcp_client.py` | Test pickup response normalization |
| 10 | `tests/services/test_batch_engine.py` | Test post-execute pickup integration |

### Full International Shipping Batch Integration

| # | File | Change |
|---|------|--------|
| 1 | `src/services/ups_mcp_client.py` | Add `get_landed_cost()`, `upload_document()`, `push_document()`, `delete_document()` methods + normalizers |
| 2 | `src/services/ups_mcp_client.py` | Add retry policies |
| 3 | `src/services/batch_engine.py` | Add pre-flight landed cost + post-create document push steps |
| 4 | `src/services/column_mapping.py` | Add customs-related field mappings (`hsCode`, `customsValue`, `countryOfOrigin`, etc.) |
| 5 | `src/orchestrator/agent/tools/pipeline.py` | Add international shipping tool handlers |
| 6 | `src/orchestrator/agent/tools/__init__.py` | Register new tool definitions |
| 7 | `src/orchestrator/agent/system_prompt.py` | Add international shipping workflow |
| 8 | `src/orchestrator/agent/hooks.py` | Add safety gates for international shipments |
| 9 | `src/errors/ups_translation.py` | Map paperless + landed cost error codes |
| 10 | `src/errors/registry.py` | Register E-3006 (document not found), etc. |
| 11 | `tests/` | Test all new normalizers, batch integration, column mappings |

---

## 13. Testing Checklist Additions

Add these to the existing testing checklist for each new tool:

### Structured-Parameter Tools (No Payload Builder)

- [ ] MCP tool name is correct in `call_tool(name, args)`
- [ ] All required parameters are passed (no silent omission)
- [ ] Optional parameters with empty string defaults are converted to `None` or omitted
- [ ] Response normalizer handles the tool's specific response structure
- [ ] Response normalizer handles empty/malformed response gracefully

### Chained Operations (Paperless + Shipment)

- [ ] Document upload → extract `documentId` → pass to push/delete
- [ ] Create shipment → extract `trackingNumber` → pass to push
- [ ] Error in chain step produces clear, non-cascading error message
- [ ] Cleanup (delete document, void shipment) runs on chain failure

### Pickup Operations

- [ ] `ready_time` < `close_time` validation (tool-side, but worth testing client-side too)
- [ ] `payment_method="01"` + no account raises clear error
- [ ] `cancel_by="prn"` + no PRN raises clear error
- [ ] Schedule → extract PRN → cancel by PRN works end-to-end

### Account-Dependent Tools

- [ ] Tool works when `UPS_ACCOUNT_NUMBER` is set
- [ ] Tool raises clear error when account is required but missing
- [ ] Explicit `account_number` param overrides env var fallback

### CIE vs Production Awareness

- [ ] Tests mock UPS responses (don't rely on CIE)
- [ ] CIE dummy tracking numbers (`1ZXXXXXXXXXXXXXXXX`) are handled gracefully
- [ ] CIE limitations are documented in test comments (not treated as bugs)

---

## 14. Updated Potential Expansions

The following items from the original integration guide have been **implemented** and can be removed from the "potential" list:

| Previously Planned | Status | Tool Name |
|-------------------|:------:|-----------|
| `create_pickup` | **Done** | `schedule_pickup` |
| `estimate_duties_taxes` | **Done** | `get_landed_cost_quote` |
| `get_shipping_documents` | **Partially done** | `upload_paperless_document` + `push_document_to_shipment` + `delete_paperless_document` |

### Remaining Potential Expansions

| Tool | Description | UPS API Available? |
|------|-------------|:------------------:|
| `create_return_shipment` | Generate return labels | Yes (same Shipping API with ReturnService block) |
| `rate_shipment_multi` | Rate multiple services at once | Yes (Shop/Shoptimeintransit requestoption — already supported) |
| `create_international_shipment` | Ship with customs forms | Yes (same Shipping API with InternationalForms) |
| `validate_address_international` | Non-US address validation | Uncertain (UPS XAV is US/PR only) |
| `create_freight_shipment` | LTL/freight shipping | Yes (separate Freight API) |
| `manage_subscription` | Tracking notifications | Yes (separate Tracking Subscription API) |
| `get_proof_of_delivery` | Retrieve POD documents | Yes (Track API with `returnPOD=True` — already exposed) |

---

## Appendix A: Complete New Tool Signatures (Quick Reference)

```python
# Landed Cost
get_landed_cost_quote(currency_code, export_country_code, import_country_code,
                      commodities, shipment_type="Sale", account_number="")

# Paperless
upload_paperless_document(file_content_base64, file_name, file_format,
                          document_type, shipper_number="")
push_document_to_shipment(document_id, shipment_identifier,
                          shipment_type="1", shipper_number="")
delete_paperless_document(document_id, shipper_number="")

# Locator
find_locations(location_type, address_line, city, state, postal_code,
               country_code, radius=15.0, unit_of_measure="MI")

# Pickup
rate_pickup(pickup_type, address_line, city, state, postal_code, country_code,
            pickup_date, ready_time, close_time, service_date_option="02",
            residential_indicator="Y", service_code="001", container_code="01",
            quantity=1, destination_country_code="US")
schedule_pickup(pickup_date, ready_time, close_time, address_line, city, state,
                postal_code, country_code, contact_name, phone_number,
                residential_indicator="N", service_code="001", container_code="01",
                quantity=1, weight=5.0, weight_unit="LBS", payment_method="01",
                rate_pickup_indicator="N", account_number="")
cancel_pickup(cancel_by, prn="")
get_pickup_status(pickup_type, account_number="")
get_political_divisions(country_code)
get_service_center_facilities(city, state, postal_code, country_code,
                              pickup_pieces=1, container_code="03")
```

All tools also accept optional `trans_id` and `transaction_src` parameters (omitted above for brevity).

---

## Appendix B: Live Test Results (CIE)

As of 2026-02-15, all 18 tools verified against UPS CIE test environment:

```
Results: 14 PASS, 0 FAIL, 4 CIE-LIMIT out of 18 tools

PASS: track_package, validate_address, rate_shipment, get_time_in_transit,
      find_locations, rate_pickup, get_pickup_status, get_political_divisions,
      get_service_center_facilities, upload_paperless_document, create_shipment,
      void_shipment, schedule_pickup, cancel_pickup

CIE-LIMIT (not code bugs):
  get_landed_cost_quote    — CIE returns HTTP 500 (infrastructure)
  push_document_to_shipment — CIE returns dummy tracking numbers
  recover_label            — CIE returns dummy tracking numbers
  delete_paperless_document — CIE returns canned document IDs
```

365 unit tests pass (up from 288 — added elicitation infrastructure, rating validator, and rate_shipment elicitation integration tests). All CIE limitations are test-environment restrictions that do not affect production.
