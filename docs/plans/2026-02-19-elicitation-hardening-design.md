# Elicitation Hardening Design

**Date:** 2026-02-19
**Scope:** Bug fixes, retry loop, general-purpose array flattening for elicitation.py

## Context

The elicitation system is the MCP server's core differentiator: tools detect missing required fields at runtime and interactively prompt users via MCP form-mode elicitation. Currently 2 of 18 tools have elicitation (`create_shipment`, `rate_shipment`).

An audit identified several bugs, a missing retry loop, and the inability to elicit complex array structures (InternationalForms.Product). This design addresses all three via a layered approach.

### Ground Truth: MCP SDK 1.26.0 API

The project uses `mcp.server.fastmcp.Context` (from the MCP SDK), NOT the standalone `fastmcp` package.

- `ctx.elicit(message=..., schema=...)` — `schema` is a Pydantic BaseModel type. No `response_type` parameter exists.
- Returns `ElicitationResult[T]` which is `AcceptedElicitation[T] | DeclinedElicitation | CancelledElicitation`
- `AcceptedElicitation` has `.data: T` (validated Pydantic instance)
- `ctx.report_progress()` and `ctx.info()` exist but are out of scope for this iteration
- MCP SDK enforces primitive-only schemas: `str | int | float | bool | list[str]`

## Layer 1: Bug Fixes

### 1a. Remove `"strict"` from `_PYDANTIC_NATIVE_CONSTRAINTS`

**File:** `elicitation.py:193-196`

Remove `"strict"` from the frozenset. In Pydantic V2, `strict` controls type coercion and passing it dynamically from constraint tuples causes schema generation crashes when elicitation forms send strings that need coercion to numbers.

### 1b. NaN/Infinity validation in weight fields

**File:** `elicitation.py:330-336`

Add `import math` and check `math.isfinite(w)`:
```python
w = float(value)
if not math.isfinite(w) or w <= 0:
    errors.append(f"{label}: must be a positive, finite number")
```

### 1c. Typed `isinstance` pattern matching for elicitation results

**File:** `elicitation.py` — `elicit_and_rehydrate()`

Import typed classes from `mcp.server.elicitation`:
```python
from mcp.server.elicitation import AcceptedElicitation, DeclinedElicitation, CancelledElicitation
```

Replace string matching (`result.action == "accept"`) with isinstance checks:
```python
if isinstance(result, AcceptedElicitation):
    normalized = normalize_elicited_values(result.data.model_dump())
    ...
elif isinstance(result, DeclinedElicitation):
    raise ToolError(...)
else:  # CancelledElicitation
    raise ToolError(...)
```

### 1d. Defensive schema build — pass only elicitable fields

**File:** `elicitation.py:495`

Change `build_elicitation_schema(missing)` to `build_elicitation_schema(elicitable)` to use the already-filtered list at line 474.

### 1e. Tighten ReturnService check

**Files:** `shipment_validator.py:605`, `rating_validator.py:450`

Replace:
```python
is_return = shipment.get("ReturnService") is not None
```
With:
```python
rs = shipment.get("ReturnService")
is_return = isinstance(rs, dict) and bool(rs.get("Code"))
```

Prevents LLM-hallucinated empty structures from being treated as valid return shipments.

## Layer 2: Retry Loop

### Core Change in `elicit_and_rehydrate()`

**File:** `elicitation.py`

Add `max_retries: int = 3` parameter to `elicit_and_rehydrate()`.

Wrap the elicit → validate → rehydrate sequence in a `for attempt in range(max_retries)` loop:

1. Build schema from elicitable fields
2. Call `ctx.elicit(message=current_message, schema=schema)`
3. On `AcceptedElicitation`:
   - Normalize → validate
   - If validation errors: prepend bullet-list errors to message, `continue` to retry
   - If validation passes: rehydrate → `find_missing_fn(updated)`
   - If still_missing with structural fields: raise immediately (can't retry)
   - If still_missing with only elicitable fields: update loop state (new elicitable list, new schema, carry forward body), `continue`
   - If complete: return updated body
4. On `DeclinedElicitation` or `CancelledElicitation`: raise ToolError immediately
5. After loop exhaustion: raise `ELICITATION_MAX_RETRIES` ToolError

### Error message format for retries

```
Please correct the following:
- Shipper postal code: must be a valid US postal code (e.g. 10001 or 10001-1234)
- Package weight: must be a positive, finite number

Missing 8 required field(s) for shipment creation.
```

### Backward compatibility

- `max_retries=3` default means no changes in server.py callers
- Existing tests (mock returns AcceptedElicitation on first try) still pass
- New error code `ELICITATION_MAX_RETRIES` follows existing JSON format

## Layer 3: General-Purpose Array Flattening

### New data structure: `ArrayFieldRule`

**File:** `elicitation.py`

```python
@dataclass(frozen=True)
class ArrayFieldRule:
    """Declares an array of structured items elicitable via flat forms.

    The system flattens each item's sub-fields into indexed scalar keys
    (e.g. product_1_description, product_1_value) and reconstructs the
    nested array during rehydration.
    """
    array_dot_path: str            # e.g. "...InternationalForms.Product"
    item_prefix: str               # e.g. "product" -> product_1_*, product_2_*
    item_rules: tuple[FieldRule, ...]  # Sub-path rules per item
    max_items: int = 10            # Safety cap
    default_count: int = 1         # If no existing items
```

### New functions in `elicitation.py`

**`expand_array_fields(rule, data, start_count=None) -> list[MissingField]`**

Inspects existing data at `array_dot_path` to determine item count. For each item, checks which sub-fields are missing and generates indexed MissingFields with flat keys like `product_1_description`.

**`reconstruct_array(flat_data, rule, count) -> list[dict]`**

Inverse of expansion. Matches flat keys `product_1_*` and builds nested dicts using `_set_field()` on each item.

**`_get_existing_array(data, dot_path) -> list[dict]`**

Navigates to `dot_path` and returns the existing array items (or `[]` if missing/empty).

### Changes to `shipment_validator.py`

Define InternationalForms.Product as an expandable array:

```python
PRODUCT_ITEM_RULES: tuple[FieldRule, ...] = (
    FieldRule("Description", "description", "Product description",
              constraints=(("maxLength", 35),)),
    FieldRule("Unit.Number", "quantity", "Quantity",
              type_hint=int, constraints=(("gt", 0),)),
    FieldRule("Unit.Value", "value", "Unit value ($)",
              type_hint=float, constraints=(("gt", 0),)),
    FieldRule("Unit.UnitOfMeasurement.Code", "unit_code", "Unit of measure",
              enum_values=("PCS", "BOX", "DZ", "EA", "KG", "LB", "PR"),
              enum_titles=("Pieces", "Box", "Dozen", "Each", "Kilogram", "Pound", "Pair"),
              default="PCS"),
    FieldRule("OriginCountryCode", "origin_country", "Country of origin",
              constraints=(("maxLength", 2), ("pattern", "^[A-Z]{2}$"))),
)

PRODUCT_ARRAY_RULE = ArrayFieldRule(
    array_dot_path="ShipmentRequest.Shipment.ShipmentServiceOptions.InternationalForms.Product",
    item_prefix="product",
    item_rules=PRODUCT_ITEM_RULES,
)
```

In `find_missing_fields()`, replace the `elicitable=False` Product MissingField with:
```python
missing.extend(expand_array_fields(PRODUCT_ARRAY_RULE, body))
```

### Integration with `elicit_and_rehydrate()`

Add `array_rules: list[ArrayFieldRule] | None = None` parameter.

After standard `rehydrate()`, call `reconstruct_array()` for each array rule and inject the results at their `array_dot_path`.

Server.py callers pass their array rules:
```python
merged_body = await elicit_and_rehydrate(
    ctx, merged_body, missing,
    find_missing_fn=find_missing_fields,
    tool_label="shipment creation",
    canonicalize_fn=canonicalize_body,
    array_rules=[PRODUCT_ARRAY_RULE],  # NEW
)
```

### What this unlocks

InternationalForms.Product goes from STRUCTURAL_FIELDS_REQUIRED error to a flat form:
- "Item 1: Product description"
- "Item 1: Quantity"
- "Item 1: Unit value ($)"
- "Item 1: Unit of measure" (dropdown: Pieces, Box, Dozen, etc.)
- "Item 1: Country of origin"

Reusable for `get_landed_cost_quote` commodity arrays.

## Layer 4: SoldTo + EEI Filing Rules

### SoldTo Address Rules

**File:** `shipment_validator.py`

SoldTo (the party who receives the invoice) is required for Invoice (01) and USMCA (04) forms. Its structure mirrors ShipTo — flat scalar fields, fully elicitable:

```python
SOLD_TO_RULES: list[FieldRule] = [
    FieldRule(
        "ShipmentRequest.Shipment.ShipmentServiceOptions.InternationalForms.Contacts.SoldTo.Name",
        "sold_to_name", "Sold-to party name",
        constraints=(("maxLength", 35),),
    ),
    FieldRule(
        "ShipmentRequest.Shipment.ShipmentServiceOptions.InternationalForms.Contacts.SoldTo.AttentionName",
        "sold_to_attention_name", "Sold-to attention name",
        constraints=(("maxLength", 35),),
    ),
    FieldRule(
        "ShipmentRequest.Shipment.ShipmentServiceOptions.InternationalForms.Contacts.SoldTo.Phone.Number",
        "sold_to_phone", "Sold-to phone number",
        constraints=(("maxLength", 15),),
    ),
    FieldRule(
        "ShipmentRequest.Shipment.ShipmentServiceOptions.InternationalForms.Contacts.SoldTo.Address.AddressLine",
        "sold_to_address_line", "Sold-to street address",
    ),
    FieldRule(
        "ShipmentRequest.Shipment.ShipmentServiceOptions.InternationalForms.Contacts.SoldTo.Address.City",
        "sold_to_city", "Sold-to city",
    ),
    FieldRule(
        "ShipmentRequest.Shipment.ShipmentServiceOptions.InternationalForms.Contacts.SoldTo.Address.CountryCode",
        "sold_to_country_code", "Sold-to country code",
        constraints=(("maxLength", 2), ("pattern", "^[A-Z]{2}$")),
    ),
]
```

In `find_missing_fields()`, check SoldTo when FormType includes "01" or "04":
```python
if form_types and any(ft in ("01", "04") for ft in form_types):
    sold_to = intl_forms.get("Contacts", {}).get("SoldTo", {})
    if not isinstance(sold_to, dict):
        sold_to = {}
    for rule in SOLD_TO_RULES:
        if not _field_exists(body, rule.dot_path):
            missing.append(_missing_from_rule(rule))
```

### EEI Filing Option Rules

**File:** `shipment_validator.py`

EEI (Electronic Export Information) is required when FormType includes "11". The top-level Code is a scalar enum (fully elicitable). The sub-objects (ShipperFiled, UPSFiled) are conditional on Code value and contain their own scalars:

```python
EEI_FILING_OPTION_CODE_RULE: FieldRule = FieldRule(
    "ShipmentRequest.Shipment.ShipmentServiceOptions.InternationalForms.EEIFilingOption.Code",
    "eei_filing_code", "EEI filing option",
    enum_values=("1", "2", "3"),
    enum_titles=("Shipper Filed", "AES Direct", "UPS Filed"),
)
```

In `find_missing_fields()`, check EEI when FormType includes "11":
```python
if "11" in form_types:
    eei = intl_forms.get("EEIFilingOption")
    if not isinstance(eei, dict) or not eei.get("Code"):
        missing.append(_missing_from_rule(EEI_FILING_OPTION_CODE_RULE))
```

## Test Plan

### Layer 1 tests
- Verify `"strict"` removal doesn't break existing schema generation
- Verify `float("inf")` and `float("nan")` are rejected by weight validation
- Verify isinstance pattern matching produces identical behavior to string matching
- Verify `build_elicitation_schema(elicitable)` only receives scalar fields
- Verify tightened ReturnService check: `{"ReturnService": ""}`, `{"ReturnService": {}}`, `{"ReturnService": {"Code": ""}}` all treated as non-return

### Layer 2 tests
- Successful first attempt (existing behavior unchanged)
- Validation error -> retry -> success on attempt 2
- Three validation errors -> ELICITATION_MAX_RETRIES error
- Still-missing after rehydration -> retry with remaining fields
- Decline/cancel on any attempt -> immediate ToolError

### Layer 3 tests
- `expand_array_fields`: generates correct indexed MissingFields for 1, 2, N items
- `expand_array_fields`: respects existing data (skips populated sub-fields)
- `expand_array_fields`: caps at max_items
- `reconstruct_array`: builds correct nested structure from flat keys
- `reconstruct_array`: handles partial data (missing optional sub-fields)
- Integration: international shipment with Product array flows through full elicitation pipeline
- Integration: Product with pre-populated items only elicits missing sub-fields

### Layer 4 tests
- SoldTo: Invoice form (01) with no SoldTo generates all sold_to_* missing fields
- SoldTo: USMCA form (04) with no SoldTo generates sold_to_* missing fields
- SoldTo: Non-invoice form (e.g. 06) does NOT require SoldTo
- SoldTo: Partially populated SoldTo only elicits missing sub-fields
- EEI: Form type 11 with no EEIFilingOption generates eei_filing_code missing field
- EEI: Form type 11 with EEIFilingOption.Code present does NOT generate missing field
- EEI: Non-EEI form (e.g. 01) does NOT require EEIFilingOption

## Files Changed

| File | Changes |
|------|---------|
| `elicitation.py` | Remove strict, add math.isfinite, isinstance matching, retry loop, ArrayFieldRule, expand/reconstruct functions, array_rules param |
| `shipment_validator.py` | Tighten ReturnService, add PRODUCT_ITEM_RULES + PRODUCT_ARRAY_RULE, replace elicitable=False Product with expand_array_fields, add SOLD_TO_RULES + EEI_FILING_OPTION_CODE_RULE |
| `rating_validator.py` | Tighten ReturnService |
| `server.py` | Pass array_rules to elicit_and_rehydrate for create_shipment |
| `tests/test_elicitation.py` | Layer 1 + 2 + 3 unit tests |
| `tests/test_shipment_validator.py` | ReturnService + array rule + SoldTo + EEI tests |
| `tests/test_rating_validator.py` | ReturnService tests |
| `tests/test_server_elicitation.py` | Retry integration + array integration tests |
