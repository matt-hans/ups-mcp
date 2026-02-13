# Create Shipment Elicitation v1

## Scope

Add preflight validation and MCP form-mode elicitation to `create_shipment` only. When required fields are missing: attempt `ctx.elicit()` with a flat primitive schema if the client supports form-mode; otherwise raise a structured `ToolError` with missing-field metadata for agent-driven conversational fallback.

### Non-scope (v1)

- No URL-mode elicitation
- No cross-request state persistence
- No progressive/multi-step wizard
- No `rate_shipment` or other tools (planned v2)
- No ToolManager signature changes

## Architecture

```
server.py::create_shipment (orchestration: defaults -> preflight -> elicit/error -> ToolManager)
    |
    v
shipment_validator.py (NEW: pure functions for rules, defaults, flatten/unflatten)
    |
    v
tools.py::ToolManager.create_shipment (UNCHANGED: receives complete request_body)
```

## Public Interface Changes

1. Tool signature gains optional `ctx: Context | None = None` (injected by FastMCP, invisible to callers).
2. MCP tool input schema unchanged.
3. Successful output unchanged (raw UPS response dict).
4. New failure modes: structured `ToolError` with elicitation-specific codes.

## New Module: `ups_mcp/shipment_validator.py`

Pure functions, zero MCP/protocol dependencies.

### Required Fields — Unconditional

| Dot Path | Flat Key | Prompt |
|----------|----------|--------|
| `ShipmentRequest.Request.RequestOption` | `request_option` | Request option |
| `ShipmentRequest.Shipment.Shipper.Name` | `shipper_name` | Shipper name |
| `ShipmentRequest.Shipment.Shipper.ShipperNumber` | `shipper_number` | UPS account number |
| `ShipmentRequest.Shipment.Shipper.Address.AddressLine[0]` | `shipper_address_line_1` | Shipper street address |
| `ShipmentRequest.Shipment.Shipper.Address.City` | `shipper_city` | Shipper city |
| `ShipmentRequest.Shipment.Shipper.Address.CountryCode` | `shipper_country_code` | Shipper country code |
| `ShipmentRequest.Shipment.ShipTo.Name` | `ship_to_name` | Recipient name |
| `ShipmentRequest.Shipment.ShipTo.Address.AddressLine[0]` | `ship_to_address_line_1` | Recipient street address |
| `ShipmentRequest.Shipment.ShipTo.Address.City` | `ship_to_city` | Recipient city |
| `ShipmentRequest.Shipment.ShipTo.Address.CountryCode` | `ship_to_country_code` | Recipient country code |
| `ShipmentRequest.Shipment.Service.Code` | `service_code` | UPS service code (e.g. '03' for Ground) |
| `ShipmentRequest.Shipment.Package[{i}].Packaging.Code` | `package_{n}_packaging_code` | Packaging type code |
| `ShipmentRequest.Shipment.Package[{i}].PackageWeight.UnitOfMeasurement.Code` | `package_{n}_weight_unit` | Weight unit (LBS or KGS) |
| `ShipmentRequest.Shipment.Package[{i}].PackageWeight.Weight` | `package_{n}_weight` | Package weight |

`{i}` is 0-indexed (internal), `{n}` is 1-indexed (user-facing flat keys).

### Required Fields — Conditional by Country

| Countries | Additional Fields |
|-----------|-------------------|
| US, CA, PR | `StateProvinceCode`, `PostalCode` for both Shipper and ShipTo |

Applied per-address based on that address's `CountryCode` value. No other country-specific rules in v1.

### Deterministic Package Behavior

- If `Package` key missing or empty array: validate against package index 0 fields (`package_1_*`).
- If `Package` is a single dict (not array): treat as `[Package]`, validate index 0.
- If `Package` is an array: validate each element at its index.

### Default Values (3-tier merge)

Precedence: caller `request_body` (highest) > env config > built-in defaults (lowest).

**Built-in defaults:**
| Field | Value |
|-------|-------|
| `ShipmentRequest.Request.RequestOption` | `"nonvalidate"` |

**Env defaults:**
| Field | Env Var |
|-------|---------|
| `ShipmentRequest.Shipment.Shipper.ShipperNumber` | `UPS_ACCOUNT_NUMBER` |

No country code defaults. No packaging code defaults. No weight unit defaults.

### Functions

```python
def apply_defaults(request_body: dict, env_config: dict[str, str]) -> dict
```
Merge 3-tier defaults. Returns new dict (non-mutating).

```python
def find_missing_fields(request_body: dict) -> list[MissingField]
```
Check unconditional + country-conditional rules. Returns list of `MissingField(dot_path, flat_key, prompt)`.

```python
def build_elicitation_schema(missing: list[MissingField]) -> type[BaseModel]
```
Dynamically create flat Pydantic model. All fields `str`, all required. Field descriptions set from prompts.

```python
def rehydrate(request_body: dict, flat_data: dict[str, str]) -> dict
```
Map flat keys back to nested structure. `AddressLine` stored as array. Package index routing. Does not overwrite existing values.

### Flat Key Mapping

Deterministic, index-safe snake_case:

```
shipper_name                  <- Shipper.Name
shipper_address_line_1        <- Shipper.Address.AddressLine[0]
shipper_city                  <- Shipper.Address.City
shipper_state                 <- Shipper.Address.StateProvinceCode
shipper_postal_code           <- Shipper.Address.PostalCode
shipper_country_code          <- Shipper.Address.CountryCode
ship_to_name                  <- ShipTo.Name
ship_to_address_line_1        <- ShipTo.Address.AddressLine[0]
ship_to_city                  <- ShipTo.Address.City
ship_to_state                 <- ShipTo.Address.StateProvinceCode
ship_to_postal_code           <- ShipTo.Address.PostalCode
ship_to_country_code          <- ShipTo.Address.CountryCode
service_code                  <- Service.Code
package_1_packaging_code      <- Package[0].Packaging.Code
package_1_weight_unit         <- Package[0].PackageWeight.UnitOfMeasurement.Code
package_1_weight              <- Package[0].PackageWeight.Weight
```

Bidirectional mapping dict generated at module load from the rules table.

## Server Orchestration

### Sequence

```
create_shipment(request_body, ctx, ...)
  |
  +-- apply_defaults(request_body, env_config)
  |
  +-- find_missing_fields(merged_body)
  |
  +-- [none missing] --> ToolManager.create_shipment(merged_body)
  |
  +-- [missing] --> _check_form_elicitation(ctx)
       |
       +-- [supported] --> ctx.elicit(message, schema)
       |    |
       |    +-- action="accept" --> rehydrate + revalidate
       |    |    |
       |    |    +-- [complete] --> ToolManager.create_shipment
       |    |    +-- [still missing] --> ToolError(INCOMPLETE_SHIPMENT)
       |    |
       |    +-- action="decline" --> ToolError(ELICITATION_DECLINED)
       |    +-- action="cancel" --> ToolError(ELICITATION_CANCELLED)
       |
       +-- [unsupported] --> ToolError(ELICITATION_UNSUPPORTED)
```

### Form Elicitation Capability Check

`_check_form_elicitation(ctx: Context | None) -> bool`

- `ctx is None` -> `False`
- `capabilities.elicitation is None` -> `False`
- `capabilities.elicitation.form` present -> `True`
- Neither `.form` nor `.url` explicitly set (empty object) -> `True` (backward compat)
- Only `.url` set -> `False`

## ToolError Payload Contract

All elicitation-related errors return JSON string with:

```json
{
  "code": "<error_code>",
  "message": "<human_readable>",
  "reason": "<machine_readable_reason>",
  "missing_fields": ["<dot_path>", ...],
  "field_prompts": {"<flat_key>": "<prompt>", ...}
}
```

### Error Codes

| Code | Reason | When |
|------|--------|------|
| `ELICITATION_UNSUPPORTED` | `unsupported` | Client lacks form-mode elicitation |
| `ELICITATION_DECLINED` | `declined` | User declined the elicitation form |
| `ELICITATION_CANCELLED` | `cancelled` | User cancelled the elicitation form |
| `INCOMPLETE_SHIPMENT` | `still_missing` | Fields still missing after accepted elicitation |

## Tests

### `tests/test_shipment_validator.py`

Pure unit tests for the validator module.

**apply_defaults:**
- Caller values override env defaults
- Caller values override built-in defaults
- Env defaults override built-in defaults
- Empty body gets only built-in defaults
- Does not mutate input

**find_missing_fields:**
- Complete body returns empty list
- Empty body returns all unconditional fields
- Missing shipper name detected
- Missing ship-to address detected
- Missing package when no Package key
- Missing package when empty array
- Multi-package validates each package
- US address requires state and postal code
- Non-US/CA/PR address does not require state or postal
- Package as single dict treated as array

**build_elicitation_schema:**
- Schema has only missing fields
- All fields are str type
- Field descriptions match prompts

**rehydrate:**
- Flat data creates nested structure
- Address line becomes array element
- Package index routes correctly
- Does not overwrite existing values
- Multi-package rehydration

### `tests/test_server_elicitation.py`

Integration tests for server.py orchestration with mock Context.

**Happy path:**
- Complete request bypasses elicitation
- Defaults fill gaps preventing elicitation

**Elicitation flow (mock ctx with form support):**
- Missing fields triggers elicit call
- Accepted elicitation rehydrates and calls UPS
- Declined raises ToolError with ELICITATION_DECLINED
- Cancelled raises ToolError with ELICITATION_CANCELLED
- Still missing after accept raises INCOMPLETE_SHIPMENT

**Fallback (no elicitation support):**
- No ctx raises ELICITATION_UNSUPPORTED
- No elicitation capability raises ELICITATION_UNSUPPORTED
- ToolError payload contains missing_fields and field_prompts

## Assumptions

1. Form-mode elicitation fields are flat primitives only (MCP SDK constraint).
2. No sensitive credential collection in form mode.
3. No cross-request state in v1.
4. Only `create_shipment` in v1 scope.
5. `rate_shipment` reuse planned for v2 using same validator abstractions.
6. Single-round elicitation only (no retry loop).
