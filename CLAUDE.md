# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

UPS MCP Server — a Model Context Protocol server exposing 18 tools for UPS shipping/logistics APIs (tracking, address validation, rating, shipping, voiding, label recovery, time-in-transit, landed cost, paperless documents, locator, pickup). The server uses **additive elicitation** as a core MCP technique: tools detect missing required fields at runtime and interactively prompt the user to supply them via MCP form-mode elicitation, progressively building complete API requests without requiring callers to know every field upfront.

## Development Objective

Build the most robust MCP server for full UPS API integration by progressively adding **additive elicitation** to every tool that accepts complex input. The goal: any MCP client can call any UPS tool with partial information and the server conversationally collects the rest — making the entire UPS API suite accessible without requiring callers to memorize payload schemas. Each enhancement should follow the established validator pattern, reuse shared rules, and maintain complementary tool workflows where output from one tool pre-fills input for the next.

**Current state:** 2 of 18 tools have elicitation (`create_shipment`, `rate_shipment`). Next targets: `recover_label`, `get_time_in_transit`.

## Commands

```bash
# Run tests
python3 -m pytest tests/
python3 -m pytest tests/ -v                    # verbose
python3 -m pytest tests/test_http_client.py    # single file
python3 -m pytest tests/test_http_client.py::HTTPClientTests::test_success_response  # single test

# Run the server locally (requires .env with CLIENT_ID, CLIENT_SECRET)
python3 -m ups_mcp

# Install in development mode
pip install -e .

# Full end-to-end test of all 18 tools against live CIE (chains real IDs across tools)
python3 live_test.py

# Legacy diagnostic (7 tools) against live CIE environment
python3 superpowers_debug.py
```

No linter or formatter is configured.

## Architecture

```
server.py (FastMCP, 18 async @mcp.tool endpoints — elicitation wiring lives here)
    ↓
tools.py (ToolManager — orchestration, parameter validation, operation routing)
    ↓
elicitation.py       (shared form-mode elicitation foundation — FieldRule, MissingField,
                      schema generation, normalization, validation, rehydration, elicit_and_rehydrate())
shipment_validator.py (FieldRules + find_missing_fields() for create_shipment)
rating_validator.py   (FieldRules + find_missing_rate_fields() for rate_shipment)
constants.py          (CIE/production URLs, locator/pickup/paperless/intl constants)
    ↓
http_client.py (UPSHTTPClient — path rendering, HTTP execution, error parsing)
    ↓
authorization.py (OAuthManager — thread-safe OAuth2 client_credentials with token caching)
    ↓
openapi_registry.py (OpenAPIRegistry — loads specs, extracts OperationSpec metadata)
```

**Three tool categories:**
- **Legacy tools** (`track_package`, `validate_address`): hardcoded `OperationSpec` constants in `tools.py`, custom parameter assembly
- **Original spec-backed tools** (`rate_shipment`, `create_shipment`, `void_shipment`, `recover_label`, `get_time_in_transit`): looked up from `OpenAPIRegistry` by `operation_id`
- **New spec-backed tools** (`get_landed_cost_quote`, `upload_paperless_document`, `push_document_to_shipment`, `delete_paperless_document`, `find_locations`, `rate_pickup`, `schedule_pickup`, `cancel_pickup`, `get_pickup_status`, `get_political_divisions`, `get_service_center_facilities`): same pattern, specs in LandedCost.yaml, Paperless.yaml, Locator.yaml, Pickup.yaml

**OpenAPI specs** (`ups_mcp/specs/*.yaml` — 7 files: Rating, Shipping, TimeInTransit, LandedCost, Locator, Paperless, Pickup) are used only for operation discovery and path routing — not for request/response schema validation. Schema validation was intentionally removed because UPS API schemas are stricter than what UPS actually accepts.

**Spec loading priority:** `UPS_MCP_SPECS_DIR` env var → bundled package resources (`ups_mcp/specs/`)

**Error handling:** All failures raise `ToolError` (from `mcp.server.fastmcp.exceptions`) with a JSON-serialized payload containing `status_code`, `code`, `message`, `details`. Success returns raw UPS API response dicts.

## Elicitation System — Core MCP Technique

The elicitation system is the server's primary differentiator. It turns complex UPS API calls into conversational interactions — callers provide what they know, and the server asks for the rest.

### How It Works

```
Caller provides partial request_body
    ↓
server.py: canonicalize → apply 3-tier defaults → find_missing_*_fields()
    ↓ (if fields missing)
elicitation.py: elicit_and_rehydrate()
    → separate structural vs scalar missing fields
    → structural fields (elicitable=False) → immediate STRUCTURAL_FIELDS_REQUIRED error with guidance
    → scalar fields → build_elicitation_schema() → ctx.elicit() → normalize → validate → rehydrate
    → re-run find_missing to verify completeness
    ↓
send completed request to UPS API
```

### Key Data Structures (all in `elicitation.py`)

- **`FieldRule`**: frozen dataclass declaring a required field — `dot_path` (nested location), `flat_key` (form field name), `prompt`, plus optional `enum_values`/`enum_titles`, `default`, `type_hint`, `constraints`
- **`MissingField`**: a FieldRule instantiated for an actually-missing field. `elicitable=False` → structural fields that need guidance prompts instead of form collection
- **`elicit_and_rehydrate()`**: centralized flow all elicitation-enabled tools call. Full cycle: capability check → schema build → `ctx.elicit()` → normalize → validate → rehydrate → re-check completeness

### 3-Tier Defaults

Before elicitation, tools apply defaults in priority order:
1. **Built-in** (lowest): e.g. `RequestOption=nonvalidate`, `ShipmentCharge.Type=01`
2. **Environment**: e.g. `UPS_ACCOUNT_NUMBER` → `Shipper.ShipperNumber`
3. **Caller-supplied** (highest): values already in `request_body` are never overwritten

Conditional defaults: `BillShipper.AccountNumber` from env is only injected when no payer object (BillShipper/BillReceiver/BillThirdParty) exists, preserving caller billing intent.

### Elicitation Status by Tool

| Tool | Status | Validator | Notes |
|------|--------|-----------|-------|
| `create_shipment` | **Enabled** | `shipment_validator.py` | Full domestic + international + InternationalForms + Duties&Taxes |
| `rate_shipment` | **Enabled** | `rating_validator.py` | Mirrors shipment pattern; Service.Code conditional on Shop mode |
| `recover_label` | Candidate | — | Raw `request_body` — validate TrackingNumber, LabelSpecification |
| `get_time_in_transit` | Candidate | — | Raw `request_body` — validate origin/destination/weight/date |
| `get_landed_cost_quote` | Candidate | — | Structured params, but commodity validation could be richer |
| All others (13 tools) | N/A | — | Use explicit params; MCP clients already see typed schemas |

### Adding Elicitation to a New Tool — Step by Step

1. **Create `{tool}_validator.py`** (pure functions, no MCP deps):
   - Define `FieldRule` lists for unconditional, conditional, and per-item rules
   - Reuse shared rules from `shipment_validator.py` where applicable (e.g. `PACKAGE_RULES`, `COUNTRY_CONDITIONAL_RULES`)
   - Implement `find_missing_{tool}_fields(request_body) → list[MissingField]`
   - Implement `canonicalize_{tool}_body()` for list normalization (Package/ShipmentCharge as arrays)
   - Implement `apply_{tool}_defaults()` with 3-tier pattern (BUILT_IN → ENV → caller)
   - Mark structural fields (nested dicts/arrays) as `elicitable=False` with guidance in their prompt

2. **Wire into `server.py`** tool endpoint:
   ```python
   # In the @mcp.tool() function:
   from .{tool}_validator import apply_defaults, find_missing_fields, canonicalize_body
   from .elicitation import elicit_and_rehydrate

   env_config = {"UPS_ACCOUNT_NUMBER": os.getenv("UPS_ACCOUNT_NUMBER", "")}
   canonical = canonicalize_body(request_body)
   merged = apply_defaults(canonical, env_config)
   missing = find_missing_fields(merged)
   if not missing:
       return _send_to_ups(merged)
   merged = await elicit_and_rehydrate(ctx, merged, missing, find_missing_fn=find_missing_fields, tool_label="...", canonicalize_fn=canonicalize_body)
   return _send_to_ups(merged)
   ```

3. **Add `ctx: Context | None = None`** to the tool function signature (FastMCP injects it)

4. **Write tests** following existing patterns:
   - `test_{tool}_validator.py`: unit tests for rules, find_missing, canonicalize, defaults
   - `test_server_{tool}_elicitation.py`: integration tests with mocked `ctx.elicit()`
   - Add to `live_test.py` for CIE end-to-end coverage

### Elicitation Design Principles

- **Additive, not blocking**: callers provide what they have; the server fills gaps interactively
- **Pure validation modules**: no MCP/protocol dependencies in `*_validator.py` — testable in isolation
- **Structural vs scalar separation**: complex nested objects (InternationalForms, Product arrays) can't be flattened into forms — they get `elicitable=False` and rich guidance prompts
- **Canonicalize early**: normalize Package/ShipmentCharge to arrays before any validation
- **Type-rich schemas**: use `enum_values`+`enum_titles` for oneOf dropdowns, `type_hint` for numbers, `constraints` for patterns — MCP clients render better forms
- **Shared sub-path rules**: `PACKAGE_RULES`, `COUNTRY_CONDITIONAL_RULES`, payment rules are defined once in `shipment_validator.py` and reused by `rating_validator.py` with different root path prefixes

### UPS API Quirks Relevant to Elicitation

- **Packaging vs PackagingType**: Shipping API uses `Packaging`, Rating API uses `PackagingType` — `remap_packaging_for_rating()` handles this after validation
- **Package as dict vs list**: UPS accepts both — `_normalize_list_field()` canonicalizes to list
- **Service.Code conditional**: Rating API doesn't require it for Shop/Shoptimeintransit modes
- **InternationalForms exemptions**: UPS Letter packages and EU-to-EU Standard shipments are exempt
- **InvoiceLineTotal**: only required for forward US→CA/PR (not returns)
- **Duties payer**: second ShipmentCharge with Type "02" needs its own billing payer object

## Complementary Tool Workflows

The 18 tools form natural workflows where output from one feeds into another. When enhancing tools, consider these chains:

### Domestic Shipment Flow
`rate_shipment` (get rates) → `create_shipment` (book it) → `track_package` (monitor) → `void_shipment` (cancel if needed) → `recover_label` (reprint)

### International Shipment Flow
`rate_shipment` (get rates) → `get_landed_cost_quote` (duties/taxes estimate) → `upload_paperless_document` (customs docs) → `create_shipment` (book with InternationalForms) → `push_document_to_shipment` (attach docs) → `track_package` (monitor)

### Pickup Flow
`rate_pickup` (estimate cost) → `schedule_pickup` (book it) → `get_pickup_status` (check status) → `cancel_pickup` (cancel if needed)

### Location Discovery
`find_locations` (nearby access points/retail) → `get_service_center_facilities` (service centers) → `get_political_divisions` (valid states for a country)

### Cross-Tool Data Reuse

When enhancing elicitation, consider that data from prior tool calls can pre-fill fields:
- `rate_shipment` response contains service codes/costs → pre-populate `create_shipment` Service.Code
- `create_shipment` response contains tracking number → feed into `push_document_to_shipment`, `recover_label`, `track_package`
- `upload_paperless_document` response contains document_id → feed into `push_document_to_shipment`
- `schedule_pickup` response contains PRN → feed into `cancel_pickup`, `get_pickup_status`

## Environment

- `.env`: `CLIENT_ID`, `CLIENT_SECRET`, `UPS_ACCOUNT_NUMBER`, `ENVIRONMENT` (test|production), optional `UPS_MCP_SPECS_DIR`
- `ENVIRONMENT=test` (default) → CIE base URL `https://wwwcie.ups.com`
- `ENVIRONMENT=production` → `https://onlinetools.ups.com`
- All API calls go through `/api` prefix: `{base_url}/api{rendered_path}`
- OAuth token endpoint: `{base_url}/security/v1/oauth/token`

## Git & PRs

- **Fork:** `matt-hans/ups-mcp` (origin). **Upstream:** `UPS-API/ups-mcp`.
- **NEVER open pull requests on the upstream `UPS-API/ups-mcp` repository.** Always create PRs on the fork `matt-hans/ups-mcp`.
- Use `gh pr create --repo matt-hans/ups-mcp` when creating PRs.

## Testing Patterns

- Tests use `unittest.TestCase` and `unittest.IsolatedAsyncioTestCase`
- Heavy mocking — no live API calls in tests
- Server tool tests inject a `FakeToolManager` into `server.tool_manager` (see `test_server_tools.py`)
- Elicitation tests mock `ctx.elicit()` and verify schema generation, normalization, validation, and rehydration (see `test_elicitation.py`, `test_server_elicitation.py`, `test_server_rate_elicitation.py`)
- Validator tests verify FieldRules, find_missing, canonicalize, and defaults in isolation (see `test_shipment_validator.py`, `test_rating_validator.py`)
- CIE quirks: address validation only works for certain states (NY works, GA doesn't); test tracking number: `1Z12345E0205271688`
- `live_test.py` chains all 18 tools with real CIE IDs (document_id → tracking_number → PRN) for full integration coverage
