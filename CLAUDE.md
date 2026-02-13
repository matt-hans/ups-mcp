# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

UPS MCP Server — a Model Context Protocol server exposing 7 tools for UPS shipping/logistics APIs (tracking, address validation, rating, shipping, voiding, label recovery, time-in-transit).

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
server.py (FastMCP, 7 async @mcp.tool endpoints)
    ↓
tools.py (ToolManager — orchestration, parameter validation, operation routing)
    ↓
http_client.py (UPSHTTPClient — path rendering, HTTP execution, error parsing)
    ↓
authorization.py (OAuthManager — thread-safe OAuth2 client_credentials with token caching)
    ↓
openapi_registry.py (OpenAPIRegistry — loads specs, extracts OperationSpec metadata)
```

**Two tool categories:**
- **Legacy tools** (`track_package`, `validate_address`): hardcoded `OperationSpec` constants in `tools.py`, custom parameter assembly
- **Spec-backed tools** (`rate_shipment`, `create_shipment`, `void_shipment`, `recover_label`, `get_time_in_transit`): operation looked up from `OpenAPIRegistry` by `operation_id`, path params resolved from spec defaults + caller overrides

**OpenAPI specs** (`ups_mcp/specs/*.yaml`) are used only for operation discovery and path routing — not for request/response schema validation. Schema validation was intentionally removed because UPS API schemas are stricter than what UPS actually accepts.

**Spec loading priority:** `UPS_MCP_SPECS_DIR` env var → bundled package resources (`ups_mcp/specs/`)

**Error handling:** All failures raise `ToolError` (from `mcp.server.fastmcp.exceptions`) with a JSON-serialized payload containing `status_code`, `code`, `message`, `details`. Success returns raw UPS API response dicts.

## Environment

- `.env`: `CLIENT_ID`, `CLIENT_SECRET`, `ENVIRONMENT` (test|production), optional `UPS_MCP_SPECS_DIR`
- `ENVIRONMENT=test` (default) → CIE base URL `https://wwwcie.ups.com`
- `ENVIRONMENT=production` → `https://onlinetools.ups.com`
- All API calls go through `/api` prefix: `{base_url}/api{rendered_path}`
- OAuth token endpoint: `{base_url}/security/v1/oauth/token`

## Testing Patterns

- Tests use `unittest.TestCase` and `unittest.IsolatedAsyncioTestCase`
- Heavy mocking — no live API calls in tests
- Server tool tests inject a `FakeToolManager` into `server.tool_manager` (see `test_server_tools.py`)
- CIE quirks: address validation only works for certain states (NY works, GA doesn't); test tracking number: `1Z12345E0205271688`
