# ShipAgent Hosted-v1 UPS MCP Contract Design

Date: 2026-06-05
Status: Superseded by implementation plan and README

> Superseded design note: this document captured an earlier design direction and
> is retained only as historical context. Do not use the response shapes,
> capability list, label-format examples, elicitation flow, or error taxonomy in
> this file as the hosted-v1 contract. The current contract is defined by
> the implementation, tests, and the "ShipAgent Hosted-v1 Boundary" section in
> `README.md`. In particular, the final contract omits
> `international_charges`, does not use hosted MCP elicitation, supports create
> label formats `GIF`, `ZPL`, `EPL`, and `SPL`, and excludes domain-specific
> public error categories such as `address` and `customs`.

## Context

ShipAgent hosted marketplace clients connect to ShipAgent's public hosted MCP app. The `ups-mcp` repository remains a private carrier integration boundary that ShipAgent calls through an internal adapter. This phase updates `ups-mcp` so ShipAgent can verify and consume the hosted-v1 UPS boundary contract without changing existing raw UPS MCP behavior.

The current `ups-mcp` codebase exposes FastMCP tools in `ups_mcp/server.py`, routes UPS operations through `ups_mcp/tools.py`, and performs HTTP/OAuth behavior in `ups_mcp/http_client.py`. Existing clients expect raw UPS response dictionaries on success and raised `ToolError` failures. That compatibility contract must remain the default.

Remote private MCP transport, service-to-service authentication, and per-tenant UPS credential handoff are intentionally out of scope for this phase. ShipAgent hosted infrastructure phases own those concerns.

## Goals

- Add a read-only `shipagent_capabilities` MCP tool for hosted-v1 readiness inspection.
- Add opt-in `response_format="shipagent_v1"` support to `rate_shipment`, `validate_address`, and `create_shipment`.
- Preserve `response_format="raw"` as the default for existing clients.
- Return normalized hosted-v1 success mappings for supported operations.
- Return hosted-safe error envelopes as normal tool results in hosted mode.
- Require and echo a non-empty `idempotency_key` for hosted-mode `create_shipment`.
- Keep hosted normalization isolated from UPS execution and elicitation logic.
- Add focused tests and documentation for the hosted-v1 contract.

## Non-goals

- Do not make `ups-mcp` the public ShipAgent marketplace MCP surface.
- Do not add ShipAgent widgets, public workflow tools, provider-runtime behavior, or tenant storage logic.
- Do not implement remote transport, service auth, or per-tenant credential handoff.
- Do not claim true carrier-level idempotent shipment creation unless UPS semantics are later proven.
- Do not decode, inspect, persist, or publish label artifacts in `ups-mcp`.
- Do not change raw-mode response or error behavior.

## Architecture

Add a focused pure-helper module:

`ups_mcp/shipagent_normalization.py`

This module owns ShipAgent hosted-v1 contract shaping and has no MCP runtime dependency. It should provide helpers equivalent to:

- `build_shipagent_capabilities(server_version: str) -> dict[str, Any]`
- `normalize_rate_result(raw: Mapping[str, Any], requestoption: str) -> dict[str, Any]`
- `normalize_address_result(raw: Mapping[str, Any]) -> dict[str, Any]`
- `normalize_create_shipment_result(raw: Mapping[str, Any], idempotency_key: str) -> dict[str, Any]`
- `to_safe_error(exc: BaseException, correlation_id: str) -> dict[str, Any]`

`ups_mcp/server.py` remains the MCP boundary. It adds:

- `shipagent_capabilities`
- `response_format: Literal["raw", "shipagent_v1"] = "raw"` on `rate_shipment`
- `response_format: Literal["raw", "shipagent_v1"] = "raw"` on `validate_address`
- `response_format: Literal["raw", "shipagent_v1"] = "raw"` and `idempotency_key: str = ""` on `create_shipment`

Raw mode returns exactly what the existing execution path returns today and allows existing `ToolError` exceptions to propagate.

Hosted mode catches operation failures and returns a hosted-safe error envelope as the tool result. Hosted mode passes successful raw UPS responses to `shipagent_normalization.py` before returning them.

`ups_mcp/tools.py` continues to own UPS operation routing. The only hosted-related behavior that may belong there is safe metadata pass-through for `create_shipment`, such as placing the hosted `idempotency_key` into `ShipmentRequest.Request.TransactionReference.CustomerContext` when the field is absent or safely mergeable. This is metadata pass-through only.

## Capability Tool

`shipagent_capabilities` is read-only and must not call UPS, require credentials, initialize `ToolManager`, or inspect tenant state.

It returns:

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
    "international_charges",
    "safe_error_mapping",
    "mutating_retry_policy"
  ],
  "response_formats": ["raw", "shipagent_v1"]
}
```

The implementation should read the installed package version where available and fall back to `"unknown"` if metadata cannot be resolved.

## Operation Flow

Each hosted-enabled operation follows this flow:

1. Validate that `response_format` is either `"raw"` or `"shipagent_v1"`.
2. Run the existing canonicalization, defaults, elicitation, validation, and UPS execution path.
3. In raw mode, return the raw UPS response or re-raise the current `ToolError`.
4. In hosted mode, normalize successful raw UPS responses into hosted-v1 mappings.
5. In hosted mode, catch `ToolError` and unexpected exceptions and return a safe error envelope.

`create_shipment` has one additional hosted-mode precondition: `idempotency_key.strip()` must be non-empty before crossing the UPS boundary. If it is missing, hosted mode returns a safe validation error and does not call UPS. Raw mode does not require or use this key.

## Response Normalization

### Rate

Rate normalization supports both a single UPS `RatedShipment` object and a list of rated shipments.

For `requestoption="Rate"` or `"Ratetimeintransit"`, hosted mode returns:

```json
{
  "success": true,
  "serviceCode": "03",
  "serviceDescription": "UPS Ground",
  "totalCharges": {
    "monetaryValue": "12.34",
    "currencyCode": "USD"
  }
}
```

Only `success` and `totalCharges` are required by the ShipAgent validator, but the implementation may include safe normalized fields such as service code, service description, negotiated-rate indicators, warnings, transit estimates, and charge breakdowns.

For `requestoption="Shop"` or `"Shoptimeintransit"`, hosted mode returns:

```json
{
  "success": true,
  "ratedShipments": [
    {
      "serviceCode": "03",
      "serviceDescription": "UPS Ground",
      "totalCharges": {
        "monetaryValue": "12.34",
        "currencyCode": "USD"
      }
    }
  ]
}
```

Each shop option must include a non-empty `serviceCode` and `totalCharges`.

### Address Validation

Address normalization maps UPS XAV response indicators into hosted statuses:

- `ValidAddressIndicator` becomes `valid`
- `AmbiguousAddressIndicator` becomes `ambiguous`
- `NoCandidatesIndicator` becomes `invalid`
- unsupported country or endpoint limitations become `unsupported`
- unrecognized but non-error response shapes become `unknown`

Optional `candidates` contain safe address fields only: address lines, city, state or province, postal code, and country code. They must not expose raw UPS payloads.

### Shipment Creation

Shipment normalization extracts safe fields from UPS `ShipmentResults`:

- `success: true`
- `idempotencyKey`, echoing the hosted request key
- `shipmentIdentificationNumber`
- `trackingNumbers`
- `totalCharges`
- `labelData`

Each label entry has:

```json
{
  "format": "PDF",
  "encoding": "base64",
  "contentBase64": "..."
}
```

`ups-mcp` does not decode labels, validate file bytes, scan content, persist artifacts, generate public URLs, or strip public output. ShipAgent hosted worker and artifact phases own those responsibilities.

### International Charges

International charge normalization is best-effort and safe-field only. Where UPS returns them, the normalizer may include structured transportation charges, service-option charges, duties, taxes, and totals with currency codes.

Hosted-normalized responses must not expose customs payloads, commodity descriptions, phone numbers, full addresses, raw commercial invoice details, request bodies, or raw UPS response bodies.

## Hosted-safe Errors

Raw mode remains unchanged: failures raise `ToolError`.

Hosted mode returns a normal result mapping:

```json
{
  "success": false,
  "error": {
    "code": "UPS_VALIDATION_ERROR",
    "category": "validation",
    "message": "The shipment request could not be validated.",
    "retryable": false,
    "correlation_id": "corr_123"
  }
}
```

Safe error envelopes are closed-shape:

- top-level keys are exactly `success` and `error`
- `success` is `false`
- nested error keys are exactly `code`, `category`, `message`, `retryable`, and `correlation_id`

Allowed categories are:

- `auth`
- `rate_limit`
- `validation`
- `service_unavailable`
- `address`
- `customs`
- `transport`
- `unknown`

Mapping rules:

- OAuth, 401, and 403 failures map to `auth`
- HTTP 429 maps to `rate_limit`
- malformed request, missing field, and validation failures map to `validation`
- address validation domain failures map to `address`
- customs and international-document failures map to `customs`
- network, timeout, and request exceptions map to `transport`
- HTTP 5xx maps to `service_unavailable`
- unclassified failures map to `unknown`

Hosted error messages should be generic but actionable. They must not include raw `details`, raw UPS XML or JSON, request payloads, OAuth tokens, client secrets, account numbers unless redacted, local paths, stack traces, arbitrary exception strings, labels, customs payloads, or full addresses.

## Idempotency And Retry Policy

In hosted mode, `create_shipment` requires a non-empty deterministic `idempotency_key` supplied by ShipAgent and returns it as `idempotencyKey`.

This phase declares `idempotency_metadata_passthrough`, not true carrier idempotency. The server may preserve the key in UPS transaction or correlation metadata where safely supported, but it must not declare `carrier_idempotent_create`.

`create_shipment` must not add a generic retry loop after the UPS boundary may have been crossed. The current code routes the mutating operation directly through `_execute_operation` and `UPSHTTPClient.call_operation`; tests should preserve that no-replay behavior.

## Tests

Add focused tests for:

- `shipagent_capabilities` returns hosted-v1 metadata with `shipagent_v1` in `response_formats`.
- `shipagent_capabilities` does not require credentials, UPS calls, or an initialized `tool_manager`.
- Raw mode remains the default for `rate_shipment`, `validate_address`, and `create_shipment`.
- Hosted rate quote responses include `success: true` and `totalCharges`.
- Hosted rate shop responses include `success: true` and non-empty `ratedShipments`.
- Hosted address validation returns one of the allowed statuses and safe candidates.
- Hosted create shipment requires a non-empty `idempotency_key` before UPS execution.
- Hosted create shipment returns `idempotencyKey`, shipment id, tracking numbers, total charges, and base64 labels.
- Hosted safe errors are closed-shape and omit unsafe keys such as `details`, `raw`, `request_body`, `stack_trace`, `client_secret`, and `access_token`.
- Hosted mode returns safe error mappings rather than raising `ToolError`.
- Raw mode still raises `ToolError`.
- `create_shipment` does not gain generic retry behavior.

The implementation should run the full existing test suite with:

```bash
python3 -m pytest -q
```

## Documentation

Update `README.md` to document:

- `shipagent_capabilities`
- raw default behavior
- opt-in `response_format="shipagent_v1"`
- hosted-mode safe error envelopes
- hosted-mode `create_shipment` `idempotency_key` requirement
- `ups-mcp` as a private ShipAgent carrier boundary, not the public marketplace MCP app
- remote transport, service auth, and per-tenant credential handoff as out of scope for this phase

A short repo-local contract note may also be added if it keeps `README.md` concise, but it should not duplicate the full ShipAgent contract document.

## Acceptance Criteria

- `shipagent_capabilities` appears in the MCP tool list.
- `shipagent_capabilities` returns `contract_version="hosted-v1"`.
- Required capabilities include `idempotency_metadata_passthrough`, `shipment_response_normalization`, `international_charges`, `safe_error_mapping`, and `mutating_retry_policy`.
- `response_formats` includes `shipagent_v1`.
- `rate_shipment`, `validate_address`, and `create_shipment` preserve raw behavior by default.
- `response_format="shipagent_v1"` returns normalized success mappings that satisfy ShipAgent's hosted boundary validators.
- Hosted-mode failures return closed safe error envelopes as normal tool results.
- Hosted safe errors do not leak raw details, request bodies, credentials, local paths, traces, label bytes beyond successful `labelData.contentBase64`, or customs internals.
- Hosted `create_shipment` requires and echoes a non-empty `idempotency_key`.
- No generic retry loop is added for mutating shipment creation.
- No ShipAgent marketplace UI, public workflow, provider-runtime, tenant storage, remote transport, service-auth, or per-tenant credential code is added to `ups-mcp`.
