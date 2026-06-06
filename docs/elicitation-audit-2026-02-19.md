# Elicitation System Comprehensive Audit & Enhancement Plan

**Date:** 2026-02-19
**Scope:** Full audit of `elicitation.py`, `shipment_validator.py`, `rating_validator.py`, `server.py` wiring, test coverage, UPS Shipping.yaml spec alignment, and FastMCP best practices compliance.

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Architecture Assessment](#2-architecture-assessment)
3. [Spec-to-Validator Gap Analysis (International Focus)](#3-spec-to-validator-gap-analysis)
4. [Core Infrastructure Audit (elicitation.py)](#4-core-infrastructure-audit)
5. [Shipment Validator Audit](#5-shipment-validator-audit)
6. [Rating Validator Audit](#6-rating-validator-audit)
7. [Server Wiring Audit](#7-server-wiring-audit)
8. [FastMCP Best Practices Compliance](#8-fastmcp-best-practices-compliance)
9. [Test Coverage Analysis](#9-test-coverage-analysis)
10. [Enhancement & Optimization Plan](#10-enhancement--optimization-plan)

---

## 1. Executive Summary

### Overall Grade: B+

The elicitation system is well-architected with clean separation of concerns, pure validation modules, and a robust rehydration pipeline. The core pattern (FieldRules -> find_missing -> elicit_and_rehydrate) is sound and extensible.

**Key Strengths:**
- Clean additive elicitation model (caller provides what they know, server asks for the rest)
- Pure validators with no MCP dependencies (testable in isolation)
- Immutable data structures (frozen FieldRule/MissingField)
- Non-destructive rehydration (deep copy, never overwrites)
- Rich error payloads with structured JSON (code, reason, missing fields)
- Structural vs scalar separation (complex nested objects get guidance, not forms)
- 324 passing tests across 5 test files

**Critical Gaps:**
- **International coverage incomplete**: ~40% of Shipping.yaml's InternationalForms fields not validated
- **No retry on validation failure**: Single-shot elicitation; user must restart tool call on error
- **FastMCP modern patterns underutilized**: Not using Pydantic BaseModel, dataclass response_type, default values, or typed result matching
- **Spec fields missing**: SoldTo, Producer, EEI, CN22, USMCA, HazMat, and many optional but important fields have zero coverage

### Audit Methodology

Six parallel research agents audited:
1. `elicitation.py` — 35 gaps identified in core infrastructure
2. `shipment_validator.py` — 25 gaps, heavy international focus
3. `rating_validator.py` — Clean mirror of shipment; 7 divergences noted
4. `Shipping.yaml` — Full field extraction; cross-referenced against validators
5. `server.py` — Wiring consistency across all 18 tool endpoints
6. Test suite (5 files, 324 tests) — Gap analysis by category

FastMCP documentation (elicitation, context, tools, testing, client elicitation) fetched and compared against our implementation.

---

## 2. Architecture Assessment

### Current Architecture (Correct)

```
server.py (canonicalize → defaults → find_missing → elicit_and_rehydrate → send)
    ↓
{tool}_validator.py (FieldRules, find_missing, canonicalize, apply_defaults)
    ↓
elicitation.py (build_schema, normalize, validate, rehydrate, elicit_and_rehydrate)
```

### What Works Well

| Component | Assessment |
|-----------|------------|
| FieldRule/MissingField frozen dataclasses | Immutable, safe for module-level constants |
| _field_exists / _set_field navigation | Handles arrays, nested dicts, creates intermediates |
| build_elicitation_schema() | Dynamic Pydantic model with enum/constraint support |
| normalize/validate/rehydrate pipeline | Clean 3-stage post-elicitation processing |
| Structural vs scalar separation | Correct recognition that complex objects can't be form-flattened |
| 3-tier defaults (built-in → env → caller) | Never overwrites caller data; conditional BillShipper injection |
| Error code taxonomy | 8 distinct error codes with JSON payloads |
| Deep copy throughout | Input mutation protection at every layer |

### Architectural Concern: Manual Schema Generation

Our implementation builds Pydantic models manually via `create_model()` with extracted type metadata. FastMCP 2.14+ natively supports:

- **Pydantic BaseModel with `Field(default=...)`** for pre-populated forms
- **Dataclass response types** for structured elicitation
- **`AcceptedElicitation`/`DeclinedElicitation`/`CancelledElicitation`** typed results
- **Titled options** via dict format with SEP-1330 compliance
- **Multi-select** via `list[Enum]` or `[["option1", "option2"]]`

We use `ctx.elicit(message=..., schema=...)` with a raw schema dict. FastMCP's `ctx.elicit(message=..., response_type=Model)` is the preferred pattern.

---

## 3. Spec-to-Validator Gap Analysis

This is the critical section. Cross-references every international field in `Shipping.yaml` against `shipment_validator.py` coverage.

### 3.1 InternationalForms — Field Coverage Matrix

| Field Path | Shipping.yaml | Validator Coverage | Priority |
|------------|---------------|-------------------|----------|
| **FormType** | Required (array, 11 codes) | Validated (11 enum values) | Done |
| **Product[]** | Required for most form types | Structural (elicitable=False, guidance prompt) | Done |
| **Product[].Description** | Required (array max 3, 1-35 chars) | NOT validated (structural) | High |
| **Product[].Unit.Number** | Required for Invoice | NOT validated (structural) | High |
| **Product[].Unit.Value** | Required for Invoice | NOT validated (structural) | High |
| **Product[].Unit.UnitOfMeasurement.Code** | Required for Invoice | NOT validated (structural) | High |
| **Product[].CommodityCode** | Required for USMCA (6-15 chars) | NOT validated | High |
| **Product[].OriginCountryCode** | Optional (2 alpha) | NOT validated | Medium |
| **Product[].PartNumber** | Required for Invoice (max 35) | NOT validated | Medium |
| **CurrencyCode** | Required for Invoice/Partial (3 chars) | Validated (elicitable) | Done |
| **ReasonForExport** | Required for Invoice (6 enum values) | Validated (6 enum values) | Done |
| **InvoiceNumber** | Required for Invoice (max 35) | Validated (elicitable) | Done |
| **InvoiceDate** | Required for Invoice, not returns (YYYYMMDD) | Validated (pattern ^\d{8}$) | Done |
| **TermsOfShipment** | Optional (13 Incoterms codes) | NOT validated | Medium |
| **DeclarationStatement** | Optional (max 550) | NOT validated | Low |
| **Comments** | Optional (max 150) | NOT validated | Low |
| **PurchaseOrderNumber** | Optional (max 35) | NOT validated | Low |
| **Discount.MonetaryValue** | Optional | NOT validated | Low |
| **FreightCharges.MonetaryValue** | Optional | NOT validated | Low |
| **InsuranceCharges.MonetaryValue** | Optional | NOT validated | Low |
| **OtherCharges.MonetaryValue** | Optional | NOT validated | Low |
| **FormGroupIdName** | Optional (max 50) | NOT validated | Low |
| **AdditionalDocumentIndicator** | Optional (empty tag) | NOT validated | Low |

### 3.2 EEI (Export & Import) Fields — ZERO Coverage

| Field Path | Shipping.yaml | Status |
|------------|---------------|--------|
| EEIFilingOption.Code | Required (1/2/3) | NOT validated |
| EEIFilingOption.UPSFiled.POA.Code | Required if UPS Filed | NOT validated |
| EEIFilingOption.ShipperFiled.Code | Required if Shipper Filed (A/B/C) | NOT validated |
| EEIFilingOption.ShipperFiled.PreDepartureITNNumber | Required if Code=A (17 chars) | NOT validated |
| EEIFilingOption.ShipperFiled.ExemptionLegend | Required if Code=B (20 chars) | NOT validated |
| ExportDate | Required for EEI (YYYYMMDD) | NOT validated |
| ExportingCarrier | Required for CO/EEI (max 35) | NOT validated |
| CarrierID | EEI only (2-17 chars) | NOT validated |
| InBondCode | Required for EEI (70/67/68) | NOT validated |
| EntryNumber | Conditional if InBond != 70 | NOT validated |
| PointOfOrigin | Required for EEI (max 5) | NOT validated |
| PointOfOriginType | Required for EEI (S/F) | NOT validated |
| ModeOfTransport | Required for EEI (15 valid values) | NOT validated |
| PortOfExport | Optional | NOT validated |
| PartiesToTransaction | Conditional (R/N) | NOT validated |

### 3.3 CN22 Form Fields — ZERO Coverage

| Field Path | Shipping.yaml | Status |
|------------|---------------|--------|
| CN22Form.LabelSize | Required (6/1) | NOT validated |
| CN22Form.PrintsPerPage | Required (1) | NOT validated |
| CN22Form.LabelPrintType | Required (pdf/png/gif/zpl/star/epl2/spl) | NOT validated |
| CN22Form.CN22Type | Required (1-4: GIFT/DOCS/SAMPLE/OTHER) | NOT validated |
| CN22Form.CN22Content[].CN22ContentQuantity | Required | NOT validated |
| CN22Form.CN22Content[].CN22ContentDescription | Required (1-105 chars) | NOT validated |
| CN22Form.CN22Content[].CN22ContentWeight | Required (Code + Weight) | NOT validated |
| CN22Form.CN22Content[].CN22ContentTotalValue | Required (9 chars) | NOT validated |
| CN22Form.CN22Content[].CN22ContentCurrencyCode | Required (3 chars, USD only) | NOT validated |

### 3.4 USMCA (Formerly NAFTA) Fields — ZERO Coverage

| Field Path | Shipping.yaml | Status |
|------------|---------------|--------|
| Contacts.Producer (if no Option) | Required: CompanyName, TIN, Address | NOT validated |
| Contacts.Producer.Option | Optional (01-04) | NOT validated |
| Product[].NetCostCode | Required (NC/ND/NO) | NOT validated |
| Product[].PreferenceCriteria | Optional (A-F) | NOT validated |
| Product[].ProducerInfo | Required (Yes/No[1-3]) | NOT validated |
| BlanketPeriod.BeginDate | Required (YYYYMMDD) | NOT validated |
| BlanketPeriod.EndDate | Required (YYYYMMDD) | NOT validated |

### 3.5 Contact Objects — Partial Coverage

| Contact | Shipping.yaml | Validator Status |
|---------|---------------|-----------------|
| **Shipper.AttentionName** | Required if intl | Validated |
| **Shipper.Phone.Number** | Required if intl | Validated |
| **Shipper.EMailAddress** | Optional (max 50) | NOT validated |
| **ShipTo.AttentionName** | Required if intl/Early AM | Validated |
| **ShipTo.Phone.Number** | Required if intl | Validated |
| **ShipTo.EMailAddress** | Optional (max 50) | NOT validated |
| **Contacts.SoldTo** | Required for Invoice/USMCA | NOT validated |
| **Contacts.SoldTo.Name** | Required (max 35) | NOT validated |
| **Contacts.SoldTo.AttentionName** | Required (max 35) | NOT validated |
| **Contacts.SoldTo.Address** | Required | NOT validated |
| **Contacts.UltimateConsignee** | Required for EEI | NOT validated |
| **Contacts.ForwardAgent** | Required for EEI UPS Filed | NOT validated |
| **Contacts.IntermediateConsignee** | Optional for EEI | NOT validated |

### 3.6 Shipment-Level Fields — Partial Coverage

| Field | Shipping.yaml | Validator Status | Notes |
|-------|---------------|-----------------|-------|
| **Description** | Required for intl (max 50) | Validated | With UPS Letter + EU exemptions |
| **InvoiceLineTotal** | Required US→CA/PR | Validated | With return exemption |
| **ReturnService.Code** | Optional (2-20) | Loosely checked | TODO: tighten `is not None` to `isinstance` |
| **DocumentsOnlyIndicator** | Optional (empty tag) | NOT validated | |
| **ShipmentDate** | Optional (YYYYMMDD, +7 days) | NOT validated | |
| **Locale** | Optional (5 chars) | NOT validated | |
| **ReferenceNumber[]** | Optional (max 5) | NOT validated | |
| **MovementReferenceNumber** | Optional (18 chars, EU) | NOT validated | |
| **NumOfPiecesInShipment** | Freight only | NOT validated | |
| **ShipperType** | Required EU inbound (01/02/NA) | NOT validated | |
| **ConsigneeType** | Required EU inbound (01/02/NA) | NOT validated | |
| **ShipmentRiskEnteringEU** | Optional (01/02/03) | NOT validated | |

### 3.7 Package-Level Fields — Partial Coverage

| Field | Shipping.yaml | Validator Status |
|-------|---------------|-----------------|
| **Packaging.Code** | Required (8 codes) | Validated (7 codes — missing `30`/Pallet) |
| **PackageWeight.Weight** | Required | Validated (gt=0) |
| **PackageWeight.UnitOfMeasurement.Code** | Required (LBS/KGS) | Validated |
| **Dimensions** (L/W/H/Unit) | Optional | NOT validated |
| **Description** | Required for return shipments | NOT validated |
| **ReferenceNumber** | Optional (max 5) | NOT validated |
| **LargePackageIndicator** | Optional | NOT validated |
| **AdditionalHandlingIndicator** | Optional | NOT validated |
| **HazMatPackageInformation** | Optional (hazmat) | NOT validated |

### 3.8 Payment Fields — Detailed Coverage

| Field | Shipping.yaml | Validator Status |
|-------|---------------|-----------------|
| **ShipmentCharge[0].Type** | Required (01/02/03) | Validated (01/02 only — missing `03` Broker of Choice) |
| **BillShipper.AccountNumber** | Optional | Validated + env default |
| **BillShipper.CreditCard** | Optional | NOT validated |
| **BillShipper.AlternatePaymentMethod** | Optional (PayPal) | NOT validated |
| **BillReceiver.AccountNumber** | Required | Validated |
| **BillReceiver.Address.PostalCode** | Required for US/CA | NOT validated |
| **BillThirdParty.Address.CountryCode** | Required | NOT validated |
| **BillThirdParty.AccountNumber** | Optional | Validated |
| **ConsigneeBilledIndicator** | Optional (US/PR) | NOT validated |
| **SplitDutyVATIndicator** | Optional | NOT validated |
| **Duties payer (ShipmentCharge[1])** | Conditional | Validated (structural) |

### 3.9 Label Specification — ZERO Validation

| Field | Status |
|-------|--------|
| LabelImageFormat.Code | NOT validated |
| LabelStockSize (Height/Width) | NOT validated |
| HTTPUserAgent (required for GIF) | NOT validated |
| CharacterSet | NOT validated |

### 3.10 ShipmentServiceOptions — Minimal Coverage

| Option | Status |
|--------|--------|
| **InternationalForms** | Partially validated (see 3.1-3.4) |
| SaturdayDelivery/Pickup | NOT validated |
| COD | NOT validated |
| Notification | NOT validated |
| DeliveryConfirmation | NOT validated |
| Insurance | NOT validated |
| LabelDelivery | NOT validated |
| LabelMethod | NOT validated |
| All others | NOT validated |

### 3.11 Summary: Spec Coverage

| Category | Total Fields in Spec | Fields Validated | Coverage |
|----------|---------------------|-----------------|----------|
| Core (Shipper/ShipTo/Service) | ~25 | 19 | 76% |
| Package | ~15 | 3 | 20% |
| Payment | ~20 | 5 | 25% |
| InternationalForms (top-level) | ~15 | 6 | 40% |
| InternationalForms (Product) | ~15 | 0 (structural) | 0% |
| EEI | ~20 | 0 | 0% |
| CN22 | ~10 | 0 | 0% |
| USMCA | ~10 | 0 | 0% |
| Contacts (SoldTo/Producer/etc.) | ~15 | 0 | 0% |
| Label Specification | ~5 | 0 | 0% |
| ShipmentServiceOptions | ~25 | 1 | 4% |
| **TOTAL** | **~175** | **~34** | **~19%** |

**Note:** Many of the uncovered fields are optional or only required in specific form types. The validator correctly focuses on the most common paths (domestic + basic international). However, for professional-grade international coverage, the critical gaps are in Products, SoldTo, EEI, and USMCA.

---

## 4. Core Infrastructure Audit (elicitation.py)

### 4.1 High-Priority Issues

| # | Issue | Impact | Location |
|---|-------|--------|----------|
| 1 | **No retry on validation failure** | User must restart entire tool call if form data invalid | `elicit_and_rehydrate()` L513-520 |
| 2 | **Schema includes structural fields** | Non-elicitable fields passed to `build_elicitation_schema()` | L495 |
| 3 | **Weight validation accepts NaN/Infinity** | `float("inf") > 0` passes validation | `validate_elicited_values()` L330 |
| 4 | **`strict` in PYDANTIC_NATIVE_CONSTRAINTS** | Not a valid `Field()` kwarg; silently fails | L194 |
| 5 | **Misleading message when structural fields present** | Count includes structural in "Missing N fields" | L497 |

### 4.2 Medium-Priority Issues

| # | Issue | Impact | Location |
|---|-------|--------|----------|
| 6 | `_parse_path_segment()` no bracket validation | Malformed "Package[0" crashes | L73-79 |
| 7 | `_field_exists()` silently returns False on malformed paths | No distinction between missing and malformed | L82-102 |
| 8 | `enum_titles` length not validated at construction | Silently skips oneOf injection if mismatched | MissingField |
| 9 | `default` not validated against `enum_values` or `type_hint` | Invalid defaults possible | FieldRule |
| 10 | No transaction/rollback on partial rehydration | Inconsistent state if `_set_field()` fails midway | `rehydrate()` L379-407 |
| 11 | Postal code validation only for US/CA | All other countries silently pass | L351-359 |

### 4.3 Low-Priority Issues

| # | Issue | Location |
|---|-------|----------|
| 12 | Constraints format untyped (`tuple[tuple[str,Any],...]`) | FieldRule |
| 13 | `flat_key` not validated as Python identifier | build_elicitation_schema |
| 14 | Duplicate model names not cached | build_elicitation_schema |
| 15 | Unexpected flat keys silently ignored in rehydration | rehydrate() |
| 16 | Canonicalize called twice (server.py + elicit_and_rehydrate) | Redundant but harmless |

### 4.4 Design Strengths (Preserve These)

- Frozen dataclasses for rules (immutable, safe for module constants)
- Deep copy at every layer boundary (mutation protection)
- Type metadata carried through full pipeline (enum_values, type_hint, constraints)
- Clean separation: normalize → validate → rehydrate
- Capability detection with graceful fallback
- Structured JSON error payloads with 8 distinct error codes
- FieldRule → MissingField instantiation with per-item overrides

---

## 5. Shipment Validator Audit

### 5.1 What's Working Well

- **Core unconditional fields** (9 rules) properly defined with constraints
- **3-tier defaults** correctly prioritize env over built-in, never overwrite caller
- **Per-package validation** with 1-indexed flat keys for forms
- **Country-conditional** (US/CA/PR State + PostalCode) rules
- **International detection** (origin != destination) with ShipFrom precedence
- **InternationalForms structure** (FormType, Product presence, Currency, Invoice)
- **EU-to-EU Standard exemption** and **UPS Letter exemption**
- **Payment ambiguity detection** (multiple payers in one charge)

### 5.2 International-Specific Gaps

| # | Gap | Risk | Recommendation |
|---|-----|------|----------------|
| 1 | **SoldTo contact not validated** for Invoice/USMCA forms | High — UPS rejects without SoldTo | Add structural guidance or scalar rules for SoldTo.Name, Address |
| 2 | **EEI form requirements not validated** (FormType "11") | High — EEI shipments always fail | Add EEIFilingOption rules conditional on FormType="11" |
| 3 | **CN22 form requirements not validated** (FormType "09") | Medium — Mail Innovations fails | Add CN22Form rules conditional on FormType="09" |
| 4 | **USMCA requirements not validated** (FormType "04") | Medium — USMCA shipments fail | Add Producer, BlanketPeriod, NetCostCode rules |
| 5 | **Product sub-field validation is guidance-only** | Medium — Invalid Product data accepted | Consider partial scalar elicitation for single-product shipments |
| 6 | **ReturnService check too permissive** | Medium — `{}` treated as return | Tighten to `isinstance(dict) and .get("Code")` |
| 7 | **ShipperType/ConsigneeType not validated** for EU inbound | Medium — Required for EU-bound | Add conditional rules when destination in EU_COUNTRIES |
| 8 | **Email not validated** for international contacts | Low — Optional in spec | Could add as optional elicitable field |
| 9 | **Phone number format not validated** beyond maxLength | Low — Malformed phones pass | Add pattern constraint |
| 10 | **Shipper/ShipTo Name maxLength not enforced** | Low — UPS may reject >35 chars | Add constraints |
| 11 | **Packaging Code "30" (Pallet) missing** from enum | Low — Freight only | Add if freight support needed |
| 12 | **ShipmentCharge Type "03" (Broker of Choice) missing** | Low — Rare use case | Add to enum |

### 5.3 Conditional Logic Gaps

| Condition | Current Behavior | Gap |
|-----------|-----------------|-----|
| FormType "05" (Partial Invoice) | In enum, marked "returns only" | No enforcement that ReturnService is present |
| FormType "07" (User Created Forms) | In enum | No UserCreatedForm.DocumentID validation |
| FormType "10" (UPS Premium Care) | In enum | No UPSPremiumCareForm validation |
| FormType "11" (EEI) | In FORMS_REQUIRING_PRODUCTS | No EEI-specific field validation |
| EU inbound shipments | No special handling | Missing ShipperType/ConsigneeType requirement |
| DDP vs DDU (services 72/17) | No special handling | May have different duty/tax requirements |
| Return shipments (Package.Description) | Not checked | Spec says Required for returns |

---

## 6. Rating Validator Audit

### 6.1 Mirrors and Divergences from Shipment Validator

| Aspect | Shipment | Rating | Correct? |
|--------|----------|--------|----------|
| RequestOption in rules | Yes (unconditional) | No (not in Rating API body) | Yes |
| Service.Code conditional | Always required | Conditional on Shop mode | Yes |
| InternationalForms | Full validation | No validation | Yes (not needed for rating) |
| Duties payer (ShipmentCharge[1]) | Validated | Not validated | Acceptable |
| BillShipper env default | Conditional injection | **MISSING** | Bug |
| Packaging → PackagingType | Not needed | remap_packaging_for_rating() | Correct |

### 6.2 Key Gap: Missing BillShipper Environment Default

`apply_rate_defaults()` does NOT apply conditional `BillShipper.AccountNumber` from env when no payer object exists. `apply_defaults()` in shipment_validator does this. This means callers must always explicitly provide a payer for rate_shipment, while create_shipment can infer it from env.

**Recommendation:** Add the same conditional injection pattern to `apply_rate_defaults()`.

---

## 7. Server Wiring Audit

### 7.1 Consistency Between Elicitation-Enabled Tools

| Aspect | create_shipment | rate_shipment | Consistent? |
|--------|-----------------|---------------|-------------|
| `ctx: Context \| None = None` | Yes | Yes | Yes |
| Canonicalize before defaults | Yes | Yes | Yes |
| TypeError catch for malformed body | Yes | Yes | Yes |
| AmbiguousPayerError catch | Yes | Yes | Yes |
| find_missing_fn passed to elicit | Direct call | Lambda wrapper | Yes (rate has conditional) |
| elicit_and_rehydrate call | Yes | Yes | Yes |
| canonicalize_fn passed | Yes | Yes | Yes |

### 7.2 Tools NOT Wired for Elicitation

| Tool | Current State | Elicitation Candidate? | Complexity |
|------|---------------|----------------------|------------|
| **recover_label** | Raw request_body, no ctx | Yes — validate TrackingNumber, LabelSpec | Low |
| **get_time_in_transit** | Raw request_body, no ctx | Yes — validate origin/dest/weight/date | Low-Medium |
| **get_landed_cost_quote** | Explicit typed params | Maybe — commodity validation | Medium |
| void_shipment | Explicit params | No — simple | N/A |
| All pickup tools (4) | Explicit params | No — typed schemas sufficient | N/A |
| All locator tools (3) | Explicit params | No — typed schemas sufficient | N/A |
| All paperless tools (3) | Explicit params | No — typed schemas sufficient | N/A |

### 7.3 Redundant Canonicalization

Both `create_shipment` and `rate_shipment` canonicalize in server.py before calling `find_missing`, then pass `canonicalize_fn` to `elicit_and_rehydrate()` which calls it again. The second call is safe (idempotent) but redundant.

---

## 8. FastMCP Best Practices Compliance

### 8.1 Features We Should Leverage

| FastMCP Feature | Version | Our Usage | Status |
|-----------------|---------|-----------|--------|
| `ctx.elicit(response_type=Model)` | 2.10+ | We use `schema=` (raw dict) | Not leveraged |
| Pydantic BaseModel with `Field(default=...)` | 2.14+ | We use `create_model()` dynamically | Not leveraged |
| `AcceptedElicitation` / `DeclinedElicitation` pattern matching | 2.10+ | We check `result.action` string | Not leveraged |
| Titled options via dict format | 2.14+ | We use `json_schema_extra.oneOf` manually | Partially done |
| Multi-select via `list[Enum]` | 2.14+ | Not used | Not leveraged |
| `ctx.report_progress()` | 2.0+ | Not used during elicitation | Not leveraged |
| `ctx.info()` / `ctx.warning()` logging | 2.0+ | Not used | Not leveraged |
| `CurrentContext()` dependency injection | 2.14+ | We use `ctx: Context` type hint | Legacy pattern |
| Tool annotations (`readOnlyHint`, etc.) | 2.0+ | Not used | Not leveraged |
| `ToolError` with `mask_error_details` | 2.0+ | We use ToolError correctly | Correct |

### 8.2 Specific Improvements

**1. Use `response_type` instead of raw `schema`**

Current:
```python
schema = build_elicitation_schema(missing)
result = await ctx.elicit(message=msg, schema=schema)
```

Recommended:
```python
Model = build_elicitation_model(missing)  # Returns Pydantic BaseModel class
result = await ctx.elicit(message=msg, response_type=Model)
```

**2. Use typed result matching**

Current:
```python
if result.action == "accept":
    ...
elif result.action == "decline":
    ...
```

Recommended:
```python
from fastmcp.server.elicitation import AcceptedElicitation, DeclinedElicitation, CancelledElicitation

match result:
    case AcceptedElicitation(data=data):
        ...
    case DeclinedElicitation():
        ...
    case CancelledElicitation():
        ...
```

**3. Use Field(default=...) for pre-populated values**

Current: Defaults applied BEFORE elicitation, so missing fields don't show defaults in the form.

Recommended: Pass defaults as `Field(default=value)` in the Pydantic model so clients pre-populate form fields.

**4. Add progress reporting for multi-step flows**

```python
await ctx.report_progress(progress=1, total=3)  # "Validating fields"
await ctx.report_progress(progress=2, total=3)  # "Collecting missing data"
await ctx.report_progress(progress=3, total=3)  # "Sending to UPS"
```

**5. Add context logging**

```python
await ctx.info(f"Found {len(missing)} missing fields for {tool_label}")
await ctx.warning("International shipment detected — additional fields may be required")
```

### 8.3 Compliance Assessment

| Best Practice | Status |
|---------------|--------|
| Use `ctx.elicit()` for structured input | Compliant |
| Check action before accessing data | Compliant |
| Handle decline/cancel gracefully | Compliant |
| Use ToolError for controlled errors | Compliant |
| Use `response_type=` (not raw schema) | NOT compliant |
| Typed result matching | NOT compliant |
| Field(default=...) for pre-populated forms | NOT compliant |
| Progress reporting | NOT compliant |
| Context logging | NOT compliant |
| Tool annotations | NOT compliant |

---

## 9. Test Coverage Analysis

### 9.1 Overall Statistics

| File | Tests | Focus |
|------|-------|-------|
| test_elicitation.py | 36 | Core infrastructure |
| test_server_elicitation.py | 16 | create_shipment integration |
| test_server_rate_elicitation.py | 16 | rate_shipment integration |
| test_shipment_validator.py | 128 | Shipment rules + field detection |
| test_rating_validator.py | 128 | Rating rules + field detection |
| **TOTAL** | **324** | |

### 9.2 Coverage by Category

| Category | Tests | Grade | Notes |
|----------|-------|-------|-------|
| Capability detection | 7 | A | All context types covered |
| Accept/Decline/Cancel | 8 | A | All actions tested |
| Error payloads | 12 | A- | Structure validated |
| 3-tier defaults | 17 | A- | All tiers + conditionals |
| Field existence/navigation | 19 | A- | Arrays, nesting, edge cases |
| Canonicalization | 16 | B+ | Dict→list, type errors |
| Normalization | 15 | B+ | Uppercase, trim, empty removal |
| Validation (weight, codes) | 26 | B | Missing NaN, postal edge cases |
| International rules | 20 | B | Good route coverage, some gaps |
| InternationalForms structure | 20 | B- | FormType/Product/Currency tested, EEI/CN22/USMCA not |
| Structural fields | 4 | C+ | Basic coverage only |
| Multi-package scenarios | 10 | B | Indexed validation tested |
| Schema generation | 18 | B+ | Types, enums, constraints |
| Payment ambiguity | 8 | A- | Multiple payer detection |
| Packaging remap (Rating) | 7 | A | Complete |

### 9.3 Critical Test Gaps

| Gap | Priority | Description |
|-----|----------|-------------|
| **No retry/re-elicitation tests** | High | No test for validation failure → re-elicit loop |
| **No multi-round elicitation** | High | No test for sequential elicit() calls |
| **NaN/Infinity weight** | High | `float("inf")` passes validation |
| **InternationalForms FormType validation** | Medium | ReasonForExport enum values not validated in elicitation |
| **Adversarial input** | Medium | No tests for very large bodies, deeply nested corruption |
| **International rate_shipment** | Medium | No international scenario tests in rate elicitation suite |
| **Cross-tool workflow** | Medium | No rate → create_shipment data flow tests |
| **Postal code edge cases** | Low | Only US/CA tested |
| **Phone format** | Low | Only maxLength, no pattern |

---

## 10. Enhancement & Optimization Plan

### Phase 1: Critical Fixes (Immediate — No New Features)

**Goal:** Fix bugs and robustness issues in existing code.

#### 1.1 Fix Weight Validation (elicitation.py)
- Add `math.isfinite()` check in `validate_elicited_values()` to reject NaN/Infinity
- Add test cases for edge weights

#### 1.2 Fix `strict` in PYDANTIC_NATIVE_CONSTRAINTS (elicitation.py)
- Remove `"strict"` from `_PYDANTIC_NATIVE_CONSTRAINTS` frozenset — it's not a valid `Field()` kwarg

#### 1.3 Tighten ReturnService Check (shipment_validator.py + rating_validator.py)
- Change `shipment.get("ReturnService") is not None` to:
  ```python
  isinstance(shipment.get("ReturnService"), dict) and shipment.get("ReturnService", {}).get("Code") is not None
  ```
- Resolves existing TODO comment

#### 1.4 Add Missing BillShipper Env Default to Rating (rating_validator.py)
- Copy conditional `BillShipper.AccountNumber` injection from `apply_defaults()` to `apply_rate_defaults()`

#### 1.5 Filter Structural Fields from Schema (elicitation.py)
- Line 495: Pass only `elicitable` fields to `build_elicitation_schema()`, not all `missing`
- Currently harmless (structural fields are filtered elsewhere) but incorrect

#### 1.6 Validate enum_titles Length (elicitation.py)
- Add `__post_init__` to MissingField to assert `len(enum_titles) == len(enum_values)` when both are set

---

### Phase 2: International Robustness (High Priority)

**Goal:** Dramatically improve international shipment coverage to match the Shipping.yaml spec.

#### 2.1 Add SoldTo Contact Validation
- **When:** FormType in `{01, 04}` (Invoice, USMCA)
- **Fields:** SoldTo.Name, SoldTo.AttentionName, SoldTo.Address (AddressLine, City, CountryCode)
- **Type:** Structural (`elicitable=False`) with rich guidance prompt including example JSON
- **Impact:** Prevents the most common international Invoice rejection

#### 2.2 Add EEI Form Validation (FormType "11")
- **Conditional on:** FormType includes "11"
- **Scalar fields (elicitable):**
  - EEIFilingOption.Code (enum: 1/2/3)
  - ExportDate (YYYYMMDD pattern)
  - InBondCode (enum: 70/67/68)
  - PointOfOrigin (max 5 chars)
  - PointOfOriginType (enum: S/F)
  - ModeOfTransport (enum: 15 values)
- **Structural fields (elicitable=False):**
  - EEIFilingOption.UPSFiled/ShipperFiled (conditional sub-objects)
  - Contacts.UltimateConsignee
  - Contacts.ForwardAgent (if UPS Filed)
  - Product[].ScheduleB, ExportType, SEDTotalValue

#### 2.3 Add CN22 Form Validation (FormType "09")
- **Conditional on:** FormType includes "09"
- **Scalar fields (elicitable):**
  - CN22Form.LabelSize (enum: 6/1)
  - CN22Form.LabelPrintType (enum: pdf/png/gif/zpl/star/epl2/spl)
  - CN22Form.CN22Type (enum: 1/2/3/4 with titles)
- **Structural fields (elicitable=False):**
  - CN22Form.CN22Content[] (array with nested weight/value objects)

#### 2.4 Add USMCA Validation (FormType "04")
- **Conditional on:** FormType includes "04"
- **Scalar fields (elicitable):**
  - BlanketPeriod.BeginDate (YYYYMMDD)
  - BlanketPeriod.EndDate (YYYYMMDD)
  - ExportDate (YYYYMMDD)
- **Structural fields (elicitable=False):**
  - Contacts.Producer (unless Option provided)
  - Product[].NetCostCode, PreferenceCriteria, ProducerInfo

#### 2.5 Add EU Inbound Validation
- **Conditional on:** ShipTo.Address.CountryCode in EU_COUNTRIES
- **Scalar fields (elicitable):**
  - ShipperType (enum: 01/02/NA with titles Business/Consumer/N-A)
  - ConsigneeType (enum: 01/02/NA with titles)

#### 2.6 Add TermsOfShipment (Incoterms)
- **When:** InternationalForms.FormType includes "01" (Invoice)
- **Field:** TermsOfShipment (enum: 13 Incoterms codes with titles)
- **Elicitable:** Yes (scalar enum)

#### 2.7 Enhance Product Guidance Prompts
- Update the `elicitable=False` Product guidance to include:
  - FormType-specific required sub-fields
  - Example JSON per FormType (Invoice vs USMCA vs EEI)
  - Link to UPS docs for complex fields (ScheduleB, CommodityCode)

---

### Phase 3: FastMCP Modernization (Medium Priority)

**Goal:** Adopt FastMCP 2.14+ best practices for better UX and maintainability.

#### 3.1 Migrate to `response_type=` Pattern
- Replace `ctx.elicit(schema=...)` with `ctx.elicit(response_type=Model)`
- Use `build_elicitation_model()` that returns a proper Pydantic BaseModel class
- Enables FastMCP's automatic schema generation and data deserialization

#### 3.2 Adopt Typed Result Matching
- Replace string-based `result.action == "accept"` with pattern matching:
  ```python
  match result:
      case AcceptedElicitation(data=data): ...
      case DeclinedElicitation(): ...
      case CancelledElicitation(): ...
  ```

#### 3.3 Pre-Populate Form Defaults
- Use `Field(default=value)` in the Pydantic model for fields with known defaults
- Example: `weight_unit: str = Field(default="LBS")` pre-fills the form
- Makes elicitation forms smarter — users only change what's different

#### 3.4 Add Progress Reporting
- Report progress during elicitation flow:
  ```python
  await ctx.report_progress(1, 3)  # "Checking required fields"
  await ctx.report_progress(2, 3)  # "Collecting missing information"
  await ctx.report_progress(3, 3)  # "Sending to UPS API"
  ```

#### 3.5 Add Context Logging
- Use `ctx.info()` and `ctx.warning()` for operational visibility:
  ```python
  await ctx.info(f"International shipment: {effective_origin} → {ship_to_country}")
  await ctx.warning(f"InternationalForms required — {len(structural)} structural fields needed")
  ```

#### 3.6 Add Tool Annotations
- Add `readOnlyHint=False`, `destructiveHint=False` to create_shipment
- Add `readOnlyHint=True` to rate_shipment
- Helps clients render appropriate UI (e.g., confirmation dialogs)

---

### Phase 4: Elicitation Retry Loop (Medium Priority)

**Goal:** Allow users to correct validation errors without restarting the tool call.

#### 4.1 Implement Re-Elicitation on Validation Failure
- Current: Validation errors → immediate ToolError → user restarts
- Proposed: Validation errors → re-elicit with error messages in prompt → validate again
- Max retries: 2 (configurable)
- Error display: Include specific validation failures in the re-elicit message:
  ```
  "2 validation errors: Weight must be positive; Country code must be 2 letters.
   Please correct and resubmit."
  ```

#### 4.2 Implement Partial Completion
- Current: All-or-nothing elicitation (all fields in one form)
- Proposed: For large field sets (>8 fields), split into logical groups:
  1. Core info (shipper, recipient, service)
  2. Package details (weight, dimensions, packaging)
  3. Payment info
  4. International details (contacts, forms)

---

### Phase 5: Expand Elicitation to New Tools (Lower Priority)

**Goal:** Add elicitation to `recover_label` and `get_time_in_transit`.

#### 5.1 recover_label Elicitation
- Create `label_recovery_validator.py`:
  - TrackingNumber (required, pattern)
  - LabelSpecification.LabelImageFormat.Code (enum: GIF/ZPL/EPL/SPL/PNG/PDF)
  - LabelSpecification.LabelStockSize.Height (enum: 6/8)
  - LabelSpecification.LabelStockSize.Width (value: 4)
- Wire into server.py with `ctx: Context | None = None`
- Low complexity (4-6 scalar fields, no structural)

#### 5.2 get_time_in_transit Elicitation
- Create `time_in_transit_validator.py`:
  - originCountryCode (2 alpha, required)
  - originPostalCode (required)
  - destinationCountryCode (2 alpha, required)
  - destinationPostalCode (required)
  - weight (positive number, required)
  - weightUnitOfMeasure (enum: LBS/KGS)
  - shipDate (YYYYMMDD)
  - numberOfPackages (positive int)
- Wire into server.py with ctx
- Medium complexity (8 scalar fields)

---

### Phase 6: Test Hardening (Ongoing)

**Goal:** Close the identified test gaps.

| Test Area | Tests to Add | Priority |
|-----------|-------------|----------|
| NaN/Infinity weights | 3 tests | Phase 1 |
| ReturnService tightened check | 4 tests | Phase 1 |
| BillShipper rating default | 2 tests | Phase 1 |
| SoldTo validation (structural) | 5 tests | Phase 2 |
| EEI form validation | 10 tests | Phase 2 |
| CN22 form validation | 6 tests | Phase 2 |
| USMCA form validation | 6 tests | Phase 2 |
| EU inbound ShipperType/ConsigneeType | 4 tests | Phase 2 |
| Re-elicitation retry loop | 6 tests | Phase 4 |
| Multi-round elicitation | 4 tests | Phase 4 |
| Adversarial input (large bodies) | 3 tests | Phase 6 |
| Phone format validation | 3 tests | Phase 6 |
| Cross-tool workflow | 4 tests | Phase 6 |

---

### Implementation Priority Summary

| Phase | Effort | Impact | When |
|-------|--------|--------|------|
| **Phase 1: Critical Fixes** | Small (1-2 days) | High — fixes bugs | Immediate |
| **Phase 2: International Robustness** | Large (5-7 days) | Very High — major gap closure | Next sprint |
| **Phase 3: FastMCP Modernization** | Medium (3-4 days) | Medium — better UX/patterns | After Phase 2 |
| **Phase 4: Retry Loop** | Medium (2-3 days) | High — UX improvement | After Phase 3 |
| **Phase 5: New Tool Elicitation** | Medium (3-4 days) | Medium — coverage expansion | After Phase 4 |
| **Phase 6: Test Hardening** | Ongoing | High — confidence | Parallel with all phases |

---

## Appendix A: Complete Error Code Reference

| Code | Reason | Trigger | HTTP-like Status |
|------|--------|---------|-----------------|
| `STRUCTURAL_FIELDS_REQUIRED` | `structural` | Non-elicitable fields present | 400 |
| `ELICITATION_UNSUPPORTED` | `unsupported` | Client lacks form capability | 400 |
| `ELICITATION_FAILED` | `transport_error` | ctx.elicit() exception | 500 |
| `ELICITATION_INVALID_RESPONSE` | `validation_errors` | Post-elicit validation failed | 400 |
| `ELICITATION_INVALID_RESPONSE` | `rehydration_error` | Structural conflict during rehydration | 400 |
| `INCOMPLETE_SHIPMENT` | `still_missing` | Fields still missing after rehydration | 400 |
| `ELICITATION_DECLINED` | `declined` | User declined | 400 |
| `ELICITATION_CANCELLED` | `cancelled` | User cancelled | 400 |
| `MALFORMED_REQUEST` | `ambiguous_payer` | Multiple billing objects in one charge | 400 |

## Appendix B: FieldRule Complete Inventory

### Shipment Validator — 34 Rules

**Unconditional (10):** RequestOption, Shipper (Name, Number, AddressLine, City, CountryCode), ShipTo (Name, AddressLine, City, CountryCode), Service.Code

**Payment (4):** ChargeType, BillShipper.AccountNumber, BillReceiver.AccountNumber, BillThirdParty.AccountNumber

**Package (3 per package):** Packaging.Code, Weight.UnitOfMeasurement.Code, Weight

**Country-Conditional (2 per address):** StateProvinceCode, PostalCode

**International Contact (4):** Shipper.AttentionName, Shipper.Phone, ShipTo.AttentionName, ShipTo.Phone

**International Shipment (3):** Description, InvoiceLineTotal.CurrencyCode, InvoiceLineTotal.MonetaryValue

**InternationalForms (6):** FormType, CurrencyCode, ReasonForExport, InvoiceNumber, InvoiceDate, (Product as structural)

**Structural (3):** InternationalForms presence, Product array, Duties payer

### Rating Validator — 30 Rules

Same as shipment minus RequestOption, InternationalForms sub-fields, and duties payer. Plus conditional Service.Code for Shop mode.
