# AGENTS.md

This file is the primary operating guide for AI coding agents working in this repository. It mirrors and extends `CLAUDE.md`; keep both files in sync whenever repository architecture, workflows, tests, or hosted ShipAgent contract behavior changes.

## Mission

Build and maintain the most robust UPS Model Context Protocol server possible.

The server exposes 18 UPS shipping/logistics operation tools plus one read-only hosted contract inspection tool, `shipagent_capabilities`. UPS operation coverage includes tracking, address validation, rating, shipment creation, voiding, label recovery, time-in-transit, landed cost, paperless documents, locator, and pickup APIs.

The defining product goal is progressive, additive elicitation: callers should be able to provide partial UPS request bodies, and the MCP server should collect missing scalar fields through form-mode elicitation instead of forcing callers to memorize complex UPS schemas. This must be implemented without breaking existing raw UPS behavior.

## Source Of Truth

- `CLAUDE.md` is the companion agent reference and currently the best historical summary of how this codebase is intended to work.
- `README.md` is the user-facing contract, especially for the ShipAgent hosted-v1 boundary.
- `ups_mcp/server.py`, `ups_mcp/tools.py`, `ups_mcp/elicitation.py`, `ups_mcp/shipment_validator.py`, `ups_mcp/rating_validator.py`, and `ups_mcp/shipagent_normalization.py` are the core implementation references.
- `tests/` is the executable specification. When documentation and tests disagree, inspect the code and tests before changing behavior.
- `docs/superpowers/specs/2026-06-05-shipagent-hosted-v1-ups-mcp-design.md` is explicitly superseded historical context. Do not use it as the hosted-v1 contract authority.

## Development Commands

```bash
# Full test suite
python3 -m pytest -q
python3 -m pytest tests/
python3 -m pytest tests/ -v

# Focused tests
python3 -m pytest tests/test_http_client.py
python3 -m pytest tests/test_http_client.py::HTTPClientTests::test_success_response
python3 -m pytest tests/test_shipagent_normalization.py tests/test_shipagent_server_hosted.py -q

# Syntax and whitespace verification
python3 -m compileall -q ups_mcp tests
git diff --check

# Run locally. Requires .env with CLIENT_ID and CLIENT_SECRET.
python3 -m ups_mcp

# Development install
pip install -e .

# Live CIE integration. Uses real UPS CIE credentials and chains IDs across tools.
python3 live_test.py
```

No linter or formatter is configured. Keep edits consistent with the surrounding Python style.

## Repository Architecture

```text
ups_mcp/server.py
  FastMCP boundary with 19 async @mcp.tool endpoints.
  Owns MCP signatures, elicitation wiring, raw-vs-hosted branching, hosted response_format validation,
  hosted correlation IDs, hosted transaction_src validation, and hosted create_shipment preflights.

ups_mcp/tools.py
  ToolManager orchestration layer.
  Owns UPS operation routing, request assembly, path/query parameter mapping, defaults that belong below MCP,
  and create_shipment idempotency metadata passthrough to TransactionReference.CustomerContext.

ups_mcp/elicitation.py
  Shared MCP form-mode elicitation foundation.
  Defines FieldRule, MissingField, schema generation, answer normalization, validation,
  rehydration, retry behavior, and elicit_and_rehydrate().

ups_mcp/shipment_validator.py
  Pure validator/default/canonicalization module for create_shipment.

ups_mcp/rating_validator.py
  Pure validator/default/canonicalization module for rate_shipment.

ups_mcp/shipagent_normalization.py
  Pure hosted-v1 contract module.
  Builds ShipAgent capabilities, normalizes hosted rate/address/create successes,
  raises ShipAgentNormalizationError for unusable 2xx UPS payloads, and maps failures to safe envelopes.

ups_mcp/http_client.py
  UPSHTTPClient path rendering, HTTP execution, and UPS error parsing.

ups_mcp/authorization.py
  OAuth2 client_credentials manager with token caching.

ups_mcp/openapi_registry.py
  Loads bundled or override OpenAPI specs and extracts OperationSpec metadata.

ups_mcp/constants.py
  CIE/production URLs and locator/pickup/paperless/international constants.
```

OpenAPI specs live in `ups_mcp/specs/*.yaml`. They are used for operation discovery and path routing only, not request/response schema validation. UPS schemas are often stricter than what UPS actually accepts, so do not reintroduce broad OpenAPI schema validation without a careful compatibility plan and tests.

Spec loading priority is:

1. `UPS_MCP_SPECS_DIR`
2. Bundled package resources under `ups_mcp/specs/`

## Tool Categories

- Hosted contract inspection: `shipagent_capabilities`. Read-only metadata. Must not require UPS credentials, initialize `ToolManager`, or call UPS.
- Legacy tools: `track_package`, `validate_address`. These use hardcoded `OperationSpec` constants in `tools.py` and custom parameter assembly.
- Original spec-backed tools: `rate_shipment`, `create_shipment`, `void_shipment`, `recover_label`, `get_time_in_transit`. These are looked up from `OpenAPIRegistry` by `operation_id`.
- New spec-backed tools: `get_landed_cost_quote`, `upload_paperless_document`, `push_document_to_shipment`, `delete_paperless_document`, `find_locations`, `rate_pickup`, `schedule_pickup`, `cancel_pickup`, `get_pickup_status`, `get_political_divisions`, `get_service_center_facilities`.

## Raw Error Contract

Raw mode is the compatibility default.

- Success returns raw UPS API response dictionaries.
- Failures raise `ToolError` from `mcp.server.fastmcp.exceptions`.
- `ToolError` payloads are JSON-serialized mappings containing fields such as `status_code`, `code`, `message`, and `details`.
- Do not turn raw-mode failures into hosted safe envelopes.
- Do not alter raw UPS response shape for existing clients.

## ShipAgent Hosted-v1 Boundary

`ups-mcp` can act as ShipAgent's private UPS carrier integration boundary. It is not the public ShipAgent marketplace MCP app. Hosted marketplace transport, service-to-service authentication, tenant storage, artifact publication, and per-tenant UPS credential handoff belong to ShipAgent hosted infrastructure, not this package.

Hosted mode is opt-in on exactly these UPS tools:

- `rate_shipment`
- `validate_address`
- `create_shipment`

These tools accept `response_format="raw"` or `response_format="shipagent_v1"`. Raw remains the default. The `response_format` parameter is deliberately typed as `str` with JSON schema enum metadata so FastMCP exposes the valid choices while custom `INVALID_RESPONSE_FORMAT` validation still runs. Invalid values raise direct MCP `ToolError` before UPS is called and must not return a hosted safe envelope.

Hosted mode is deterministic and never prompts through MCP elicitation. For hosted rate and create requests, if required fields are still missing after defaults are applied, return hosted `UPS_VALIDATION_ERROR` before UPS is called.

### Hosted Capabilities

`shipagent_capabilities` returns metadata like:

```json
{
  "contract_version": "hosted-v1",
  "server_version": "1.1.0",
  "capabilities": [
    "rate_quote",
    "rate_shop",
    "address_validation",
    "create_shipment",
    "idempotency_metadata_passthrough",
    "shipment_response_normalization",
    "safe_error_mapping",
    "mutating_retry_policy"
  ],
  "response_formats": ["raw", "shipagent_v1"]
}
```

`contract_version` is the compatibility signal for this release. The capabilities response intentionally does not include a schema hash, separate schema version, or structured `retry_policy` field. `mutating_retry_policy` signals that this package does not retry mutating create-shipment calls after an ambiguous UPS boundary crossing.

### Hosted Correlation IDs

Hosted success responses include top-level `correlationId`. Hosted error envelopes include `error.correlation_id`. These are intentionally different public shapes.

- If callers omit `trans_id`, hosted mode generates `corr_<32 lowercase hex characters>`.
- If callers provide `trans_id`, hosted mode strips and preserves it when it contains no ASCII control characters.
- Hosted-v1 does not impose a `trans_id` length limit.
- Caller-supplied `trans_id` containing ASCII control characters returns hosted `UPS_VALIDATION_ERROR` before UPS is called, using a generated safe `corr_...` id instead of echoing the invalid value.

### Hosted transaction_src

Hosted mode does not override `transaction_src`.

- Preserve printable caller-supplied values.
- Default remains `ups-mcp`.
- Values containing ASCII control characters such as newline, carriage return, tab, NUL, or DEL return hosted `UPS_VALIDATION_ERROR` before UPS is called.
- ShipAgent hosted infrastructure can pass `transaction_src="shipagent"` explicitly when it wants that UPS transaction source.

### Hosted Safe Errors

Hosted failures return normal result mappings instead of raising raw UPS details. Error envelopes are closed shape:

```json
{
  "success": false,
  "error": {
    "category": "validation",
    "code": "UPS_VALIDATION_ERROR",
    "message": "UPS request validation failed.",
    "correlation_id": "corr_123",
    "retryable": false
  }
}
```

Rules:

- Top-level keys are exactly `success` and `error`.
- Nested error keys are exactly `category`, `code`, `message`, `correlation_id`, and `retryable`.
- Do not add top-level `correlationId` or camelCase aliases to error envelopes.
- Do not expose raw UPS error codes, raw UPS messages, request bodies, credentials, stack traces, response details, arbitrary exception text, or create-shipment `idempotencyKey` on hosted errors.
- Public categories are `auth`, `rate_limit`, `validation`, `service_unavailable`, `transport`, `unknown`, and `normalization`.
- Unexpected hosted exceptions map to `UPS_UNKNOWN_ERROR`, category `unknown`, retryable `false`.
- Normalization failures map to `UPS_NORMALIZATION_ERROR`, category `normalization`, retryable `false`.
- For hosted `create_shipment`, ambiguous service-unavailable, transport, HTTP 408, or HTTP 503 failures are not retryable because the mutating UPS boundary may have been crossed.

### Hosted Rate Normalization

Hosted `rate_shipment` supports quote and shop modes:

- Quote options: `Rate`, `Ratetimeintransit`
- Shop options: `Shop`, `Shoptimeintransit`
- Option classification is case-insensitive after the existing execution path accepts the request option.

Hosted rate success uses camelCase and includes `correlationId`.

Quote mode requires exactly one UPS `RatedShipment`; use shop mode for multi-option responses. Quote success requires `serviceCode` and `totalCharges`. `serviceDescription` is included only when UPS provides it.

Shop success requires `ratedShipments`. Each returned UPS option must have required fields; hosted mode does not silently filter incomplete returned options. If any returned option is incomplete, return `UPS_NORMALIZATION_ERROR`.

`totalCharges.monetaryValue` preserves UPS string formatting. It is a string, not a JSON number. `totalCharges.currencyCode` must be exactly three uppercase ASCII letters.

If UPS includes `NegotiatedRateCharges`, hosted rate normalization requires a complete `NegotiatedRateCharges.TotalCharge`; do not fall back to standard `TotalCharges` when negotiated pricing is malformed.

### Hosted Address Normalization

Hosted `validate_address` returns successful domain statuses:

- `valid`
- `ambiguous`
- `invalid`
- `unknown`
- `unsupported`

Hosted mode strips and uppercases `countryCode` only for boundary decisions, while passing the caller's original `countryCode` through to UPS unchanged.

Preflight rules:

- Blank or malformed `countryCode` returns hosted `UPS_VALIDATION_ERROR` before UPS.
- A well-formed two-letter country code outside `US` or `PR` returns `unsupported` without UPS execution and before required address field validation.
- For supported `US` and `PR`, blank `addressLine1`, `politicalDivision1`, `politicalDivision2`, or `zipPrimary` returns hosted `UPS_VALIDATION_ERROR` before UPS.

Hosted candidates contain only safe address fields:

- `addressLines`
- `city`
- `stateProvince`
- `postalCode`
- `postalCodeExtended`
- `countryCode`

Do not expose `AddressClassification` or other UPS metadata in hosted candidates. Do not emit empty `{}` candidates. Return `UPS_NORMALIZATION_ERROR` rather than partial success when UPS address payloads cannot satisfy hosted-v1.

### Hosted Create Shipment Normalization

Hosted `create_shipment` success includes:

- `success: true`
- `correlationId`
- `idempotencyKey`
- `shipmentIdentificationNumber`
- `trackingNumbers`
- `totalCharges`
- `labelData`

`labelData` entries include:

- `trackingNumber`
- `format`
- `encoding: "base64"`
- `contentBase64`

Every UPS `PackageResults` item returned for hosted create must include `TrackingNumber`, `ShippingLabel.ImageFormat.Code`, and strict unwrapped base64 `ShippingLabel.GraphicImage`.

Supported create-shipment label formats are `GIF`, `ZPL`, `EPL`, and `SPL` after uppercasing. Do not expose unsafe label fields such as HTML images, label URLs, receipts, forms, raw label containers, or recovered-label fields. `ups-mcp` does not decode labels, inspect file bytes, persist artifacts, or publish public URLs.

### Hosted Idempotency Policy

Hosted `create_shipment` requires an `idempotency_key`:

- Strip exactly once at the server boundary.
- Reject empty keys after stripping.
- Reject keys longer than 512 characters.
- Reject keys containing ASCII control characters.
- Echo the stripped key as `idempotencyKey` only on hosted create success.
- Never echo `idempotencyKey` on hosted create errors.

This key is metadata passthrough for ShipAgent retry coordination, not true carrier-level idempotency.

`tools.py` passes the stripped key into `ShipmentRequest.Request.TransactionReference.CustomerContext` when possible:

- Missing or blank `CustomerContext`: set it to the idempotency key.
- Existing non-empty `CustomerContext`: append `; idempotency_key=<key>` only when the combined string fits UPS's 512-character limit.
- If appending would exceed 512 characters, preserve the caller's existing context unchanged.
- Existing caller-supplied `CustomerContext` must be a string, at most 512 characters, and contain no ASCII control characters.
- Missing `CustomerContext` is allowed.

The package does not store idempotency keys, maintain a replay cache, dedupe repeat calls, suppress UPS requests when the same key appears again, or retry mutating creates after ambiguous UPS failures. ShipAgent hosted infrastructure owns tenant/request idempotency.

## Elicitation System

The elicitation system turns complex UPS calls into conversational interactions. Callers provide what they know; the server asks for the rest.

Flow:

```text
Caller provides partial request_body
  -> server.py canonicalizes and applies defaults
  -> validator finds missing fields
  -> elicitation.py splits structural vs scalar missing fields
  -> structural fields produce STRUCTURAL_FIELDS_REQUIRED guidance
  -> scalar fields become MCP form-mode schema
  -> ctx.elicit() collects values
  -> answers are normalized, validated, rehydrated
  -> missing-field check runs again
  -> completed request is sent to UPS
```

Key structures in `elicitation.py`:

- `FieldRule`: frozen dataclass declaring a required field with `dot_path`, `flat_key`, `prompt`, and optional enum/default/type/constraint metadata.
- `MissingField`: a `FieldRule` instantiated for an actually missing value. `elicitable=False` means the value is structural and should produce guidance instead of a form field.
- `elicit_and_rehydrate()`: centralized flow for capability check, schema build, `ctx.elicit()`, normalization, validation, rehydration, and final completeness verification.

Defaults apply before elicitation in this order:

1. Built-in defaults, such as `RequestOption=nonvalidate` or `ShipmentCharge.Type=01`.
2. Environment defaults, such as `UPS_ACCOUNT_NUMBER` to `Shipper.ShipperNumber`.
3. Caller-supplied values, which always win and must not be overwritten.

Conditional defaults matter. For example, `BillShipper.AccountNumber` from the environment is injected only when no payer object exists, preserving caller billing intent.

Current elicitation status:

| Tool | Status | Validator | Notes |
| --- | --- | --- | --- |
| `create_shipment` | Enabled | `shipment_validator.py` | Domestic, international, InternationalForms, Duties & Taxes |
| `rate_shipment` | Enabled | `rating_validator.py` | Mirrors shipment pattern; `Service.Code` conditional on shop mode |
| `recover_label` | Candidate | None | Raw `request_body`; likely needs TrackingNumber and LabelSpecification validation |
| `get_time_in_transit` | Candidate | None | Raw `request_body`; likely needs origin/destination/weight/date validation |
| `get_landed_cost_quote` | Candidate | None | Structured params; commodity validation could be richer |
| All others | N/A | None | Explicit params are already visible to MCP clients |

## Adding Elicitation To A Tool

1. Create a pure `{tool}_validator.py` module with no MCP dependencies.
2. Define `FieldRule` lists for unconditional, conditional, and per-item requirements.
3. Reuse shared rules from `shipment_validator.py` where applicable.
4. Implement `canonicalize_{tool}_body()` for list normalization.
5. Implement `apply_{tool}_defaults()` using the built-in, environment, caller-supplied priority model.
6. Implement `find_missing_{tool}_fields(request_body) -> list[MissingField]`.
7. Mark complex nested dicts/lists as `elicitable=False` and provide actionable guidance prompts.
8. Add `ctx: Context | None = None` to the FastMCP tool signature.
9. Wire `canonicalize -> defaults -> find_missing -> elicit_and_rehydrate -> UPS execution` in `server.py`.
10. Add unit tests for the validator and integration tests with mocked `ctx.elicit()`.
11. Add or update live CIE coverage only when the flow can be safely exercised with real credentials.

Implementation sketch:

```python
env_config = {"UPS_ACCOUNT_NUMBER": os.getenv("UPS_ACCOUNT_NUMBER", "")}
canonical = canonicalize_tool_body(request_body)
merged = apply_tool_defaults(canonical, env_config)
missing = find_missing_tool_fields(merged)
if missing:
    merged = await elicit_and_rehydrate(
        ctx,
        merged,
        missing,
        find_missing_fn=find_missing_tool_fields,
        tool_label="Tool name",
        canonicalize_fn=canonicalize_tool_body,
    )
return _send_to_ups(merged)
```

## Elicitation Design Principles

- Additive, not blocking: accept partial caller input and collect only gaps.
- Pure validators: no MCP protocol objects in validator modules.
- Canonicalize early: normalize `Package`, `ShipmentCharge`, candidate/package result shapes, and similar dict-or-list UPS fields before validation.
- Separate structure from scalar collection: nested arrays and objects should not be flattened into brittle forms.
- Type-rich forms: use enum values/titles, numeric hints, patterns, and defaults so MCP clients render usable forms.
- Shared rules: keep package, country, payment, and billing rules reusable between shipment and rating validators.
- Preserve caller intent: never overwrite explicit request body values with defaults.
- Test the validator in isolation before testing server wiring.

## UPS API Quirks

- Shipping API uses `Packaging`; Rating API uses `PackagingType`. `remap_packaging_for_rating()` handles this after validation.
- UPS accepts some fields as either object or list. Canonicalize before validation.
- Rating `Service.Code` is not required for `Shop` or `Shoptimeintransit`.
- UPS Letter packages and EU-to-EU Standard shipments have international forms exemptions.
- `InvoiceLineTotal` is only required for forward US to CA/PR shipments, not returns.
- Duties payer uses a second `ShipmentCharge` with `Type="02"` and needs its own billing payer object.
- Address validation is limited to U.S. and Puerto Rico behavior in current hosted mode.
- CIE address validation has quirks; NY works more reliably than GA.

## Complementary UPS Workflows

When adding or changing a tool, consider whether its output should feed another tool.

Domestic shipment:

```text
rate_shipment -> create_shipment -> track_package -> void_shipment -> recover_label
```

International shipment:

```text
rate_shipment -> get_landed_cost_quote -> upload_paperless_document -> create_shipment -> push_document_to_shipment -> track_package
```

Pickup:

```text
rate_pickup -> schedule_pickup -> get_pickup_status -> cancel_pickup
```

Location discovery:

```text
find_locations -> get_service_center_facilities -> get_political_divisions
```

Cross-tool reuse examples:

- `rate_shipment` service codes/costs can pre-populate `create_shipment`.
- `create_shipment` tracking numbers can feed `track_package`, `recover_label`, and `push_document_to_shipment`.
- `upload_paperless_document` document IDs can feed `push_document_to_shipment`.
- `schedule_pickup` PRNs can feed `cancel_pickup` and `get_pickup_status`.

## Testing Expectations

Tests use `unittest.TestCase` and `unittest.IsolatedAsyncioTestCase` with heavy mocking. Unit tests must not call live UPS APIs.

Important test areas:

- `test_server_tools.py`: server tool tests with fake `ToolManager`.
- `test_elicitation.py`: schema generation, answer normalization, validation, rehydration.
- `test_server_elicitation.py`: create shipment elicitation integration.
- `test_server_rate_elicitation.py`: rating elicitation integration.
- `test_shipment_validator.py`: create shipment field rules, canonicalization, defaults.
- `test_rating_validator.py`: rating field rules, canonicalization, defaults.
- `test_shipagent_normalization.py`: pure hosted-v1 normalization and safe error behavior.
- `test_shipagent_server_hosted.py`: FastMCP hosted boundary behavior, response_format schema enum exposure, custom invalid response_format validation, safe error envelopes, unsupported address countries, idempotency metadata, and no retryable guidance for ambiguous mutating failures.
- `test_tool_mapping.py`: operation mapping and request passthrough details.
- `live_test.py`: optional real CIE end-to-end chain across all 18 UPS operation tools.

For hosted changes, run at least:

```bash
python3 -m pytest tests/test_shipagent_normalization.py tests/test_shipagent_server_hosted.py -q
python3 -m compileall -q ups_mcp tests
git diff --check
```

For shared behavior, run the full suite:

```bash
python3 -m pytest -q
```

Current expected full-suite baseline is `577 passed, 201 subtests passed`.

## Environment And Secrets

`.env` may contain:

- `CLIENT_ID`
- `CLIENT_SECRET`
- `UPS_ACCOUNT_NUMBER`
- `ENVIRONMENT` (`test` or `production`)
- `UPS_MCP_SPECS_DIR`

Defaults:

- `ENVIRONMENT=test` uses `https://wwwcie.ups.com`.
- `ENVIRONMENT=production` uses `https://onlinetools.ups.com`.
- UPS API calls go through `/api`: `{base_url}/api{rendered_path}`.
- OAuth endpoint is `{base_url}/security/v1/oauth/token`.

Never commit real UPS credentials, tokens, request bodies containing secrets, `.env`, or live UPS payloads that may contain customer data.

## Git And PR Rules

- Primary fork remote: `matt-hans/ups-mcp` (`origin`).
- Upstream source: `UPS-API/ups-mcp`.
- Never open PRs against `UPS-API/ups-mcp` unless the user explicitly changes that policy.
- Create PRs against the fork with `gh pr create --repo matt-hans/ups-mcp`.
- Branches created by agents should normally use the `codex/` prefix unless instructed otherwise.
- Before deleting branches or worktrees, verify they are clean and merged.
- Repository rules may prevent deleting remote branches even after merge; report that as a policy block rather than repeatedly retrying.

## Code Quality Rules

- Prefer existing local patterns over new abstractions.
- Keep MCP boundary logic in `server.py`, UPS orchestration in `tools.py`, pure validation in `*_validator.py`, and hosted normalization in `shipagent_normalization.py`.
- Keep pure modules free of MCP runtime dependencies.
- Preserve raw-mode backward compatibility unless the user explicitly asks for a breaking change.
- Avoid broad rewrites when a focused change will solve the problem.
- Add abstractions only when they remove real duplication or clarify a stable boundary.
- Do not leak UPS internals through hosted safe responses.
- Treat mutating shipment creation as a no-replay boundary after the UPS call may have happened.
- Prefer structured parsing over string scraping when handling JSON-like errors or payloads.
- Keep comments sparse and useful.

## Review Checklist

Before claiming work is complete:

- Does raw mode still behave exactly as before?
- Does hosted mode return safe envelopes instead of raw UPS details?
- Does hosted `create_shipment` avoid retryable guidance for ambiguous mutating failures?
- Does `response_format` still expose enum choices in FastMCP schema while custom validation catches invalid values?
- Are hosted normalization failures closed and non-leaky?
- Are caller-supplied request fields preserved unless the documented default/passthrough rule applies?
- Are tests focused on both pure helpers and server boundary behavior?
- Did you run the right tests for the blast radius?
- Is `CLAUDE.md` updated if this file changes repository guidance?
- Is `README.md` updated if user-facing behavior changes?

