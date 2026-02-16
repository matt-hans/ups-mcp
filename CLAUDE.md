# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

UPS MCP Server — a Model Context Protocol server exposing 18 tools for UPS shipping/logistics APIs (tracking, address validation, rating, shipping, voiding, label recovery, time-in-transit, landed cost, paperless documents, locator, pickup).

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

# End-to-end diagnostic against live CIE environment
python3 superpowers_debug.py
```

No linter or formatter is configured.

## Architecture

```
server.py (FastMCP, 18 async @mcp.tool endpoints)
    ↓
tools.py (ToolManager — orchestration, parameter validation, operation routing)
    ↓
shipment_validator.py (preflight validation + elicitation schema generation for create_shipment)
constants.py (CIE/production URLs, locator/pickup/paperless constants)
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
- CIE quirks: address validation only works for certain states (NY works, GA doesn't); test tracking number: `1Z12345E0205271688`
