# International Shipping Support — Client Integration Guide

> **Version:** 1.0
> **Date:** 2026-02-16
> **Audience:** Downstream MCP client developers integrating with the UPS MCP server
> **Scope:** New validation, elicitation, and error-handling behavior for `create_shipment` and `rate_shipment` tools

---

## Table of Contents

1. [Overview](#1-overview)
2. [What Changed](#2-what-changed)
3. [International Detection Logic](#3-international-detection-logic)
4. [New Validated Fields — `create_shipment`](#4-new-validated-fields--create_shipment)
5. [New Validated Fields — `rate_shipment`](#5-new-validated-fields--rate_shipment)
6. [Elicitation Behavior Changes](#6-elicitation-behavior-changes)
7. [New Error Code: `STRUCTURAL_FIELDS_REQUIRED`](#7-new-error-code-structural_fields_required)
8. [Complete Error Code Reference](#8-complete-error-code-reference)
9. [InternationalForms Reference](#9-internationalforms-reference)
10. [Minimal International Shipment Example](#10-minimal-international-shipment-example)
11. [Minimal International Rate Request Example](#11-minimal-international-rate-request-example)
12. [Validation Exemptions](#12-validation-exemptions)
13. [Duties & Taxes Payment](#13-duties--taxes-payment)
14. [Currency Code Handling](#14-currency-code-handling)
15. [Migration Checklist](#15-migration-checklist)
16. [FAQ](#16-faq)

---

## 1. Overview

The UPS MCP server now performs **preflight validation** for international shipments and rate requests. Previously, international fields were passed through to the UPS API without validation, resulting in cryptic UPS API errors. The server now:

- **Detects** international shipments automatically (origin ≠ destination country)
- **Validates** required international fields before calling the UPS API
- **Elicits** simple scalar fields (contact names, phone numbers, currency codes) via MCP form-mode elicitation when supported
- **Rejects with guidance** complex structural fields (InternationalForms, Product arrays) that cannot be collected via flat forms

**Backward compatibility:** Domestic shipments (same origin and destination country) are completely unaffected. No existing domestic workflows, request shapes, or error codes have changed.

---

## 2. What Changed

| Area | Before | After |
|------|--------|-------|
| International field validation | None — passed through to UPS API | Server-side preflight validation with actionable error messages |
| `create_shipment` InternationalForms | Silent UPS API failure | Validated: FormType, Product[], CurrencyCode, ReasonForExport, InvoiceNumber, InvoiceDate |
| `rate_shipment` international fields | No validation | Validated: contacts, Description, InvoiceLineTotal |
| Elicitation for structural fields | N/A | New `STRUCTURAL_FIELDS_REQUIRED` error code with guidance |
| Currency code normalization | Not normalized | Uppercased during elicitation (`usd` → `USD`) |
| Currency code validation | Not validated | Must be 3-letter uppercase alpha (ISO 4217) |
| Tool descriptions | Domestic-only documentation | Comprehensive international field documentation with examples |

### New Constants Available for Reference

| Constant | Values |
|----------|--------|
| `INTERNATIONAL_FORM_TYPES` | `01`=Invoice, `03`=Certificate of Origin, `04`=USMCA, `05`=Partial Invoice, `06`=Packing List, `07`=Customer Generated, `08`=Air Freight Packing List, `09`=CN22, `10`=Premium Care, `11`=EEI |
| `REASON_FOR_EXPORT_VALUES` | `SALE`, `GIFT`, `SAMPLE`, `RETURN`, `REPAIR`, `INTERCOMPANYDATA` |
| `INCOTERMS` | `CFR`, `CIF`, `CIP`, `CPT`, `DAF`, `DDP`, `DAP`, `DEQ`, `DES`, `EXW`, `FAS`, `FCA`, `FOB` |
| `SHIPMENT_CHARGE_TYPES` | `01`=Transportation, `02`=Duties and Taxes, `03`=Broker of Choice |
| `EEI_FILING_OPTION_CODES` | `1`=Shipper Filed, `2`=AES Direct, `3`=UPS Filed |

---

## 3. International Detection Logic

A shipment or rate request is considered **international** when:

```
effective_origin ≠ ship_to_country
```

Where:
- `effective_origin` = `ShipFrom.Address.CountryCode` if present, otherwise `Shipper.Address.CountryCode`
- `ship_to_country` = `ShipTo.Address.CountryCode`

Both values are trimmed and uppercased before comparison. If either value is missing or empty, the shipment is treated as **domestic** (no international validation).

> **Note:** `ShipFrom` takes precedence over `Shipper` for origin determination. This matters when the shipper's billing address differs from the physical ship-from location.

---

## 4. New Validated Fields — `create_shipment`

When a shipment is detected as international, the following fields are now validated. Fields marked **elicitable** will be prompted via form-mode elicitation if supported by the client. Fields marked **structural** require the client to build the structure in `request_body` directly.

### Scalar Fields (Elicitable)

| Field | `dot_path` | `flat_key` | Condition | Constraints |
|-------|-----------|------------|-----------|-------------|
| Shipper attention name | `ShipmentRequest.Shipment.Shipper.AttentionName` | `shipper_attention_name` | International | maxLength: 35 |
| Shipper phone | `ShipmentRequest.Shipment.Shipper.Phone.Number` | `shipper_phone` | International | maxLength: 15 |
| Recipient attention name | `ShipmentRequest.Shipment.ShipTo.AttentionName` | `ship_to_attention_name` | International OR service "14" | maxLength: 35 |
| Recipient phone | `ShipmentRequest.Shipment.ShipTo.Phone.Number` | `ship_to_phone` | International OR service "14" | maxLength: 15 |
| Description of goods | `ShipmentRequest.Shipment.Description` | `shipment_description` | International (with exemptions) | maxLength: 50 |
| Invoice currency code | `ShipmentRequest.Shipment.InvoiceLineTotal.CurrencyCode` | `invoice_currency_code` | US→CA/PR forward only | 3-letter alpha |
| Invoice monetary value | `ShipmentRequest.Shipment.InvoiceLineTotal.MonetaryValue` | `invoice_monetary_value` | US→CA/PR forward only | maxLength: 11, numeric |
| Form type | `...InternationalForms.FormType` | `intl_forms_form_type` | InternationalForms present, FormType missing | Enum (see §9) |
| Forms currency code | `...InternationalForms.CurrencyCode` | `intl_forms_currency_code` | FormType `01` or `05` | 3-letter alpha |
| Reason for export | `...InternationalForms.ReasonForExport` | `intl_forms_reason_for_export` | FormType `01` | Enum (see §9) |
| Invoice number | `...InternationalForms.InvoiceNumber` | `intl_forms_invoice_number` | FormType `01` | maxLength: 35 |
| Invoice date | `...InternationalForms.InvoiceDate` | `intl_forms_invoice_date` | FormType `01`, not a return | YYYYMMDD, 8 digits |

### Structural Fields (Non-Elicitable — Error with Guidance)

| Field | `flat_key` | Condition | Guidance Provided |
|-------|-----------|-----------|-------------------|
| InternationalForms container | `intl_forms_required` | International, forms missing (with exemptions) | Full JSON example structure |
| Product array | `intl_forms_product_required` | FormType requires products, Product missing | JSON array example with required sub-fields |
| Duties/taxes payer | `duties_payer_required` | ShipmentCharge[1] Type "02" has no payer object | Must add BillShipper, BillReceiver, or BillThirdParty |

---

## 5. New Validated Fields — `rate_shipment`

Rating validation mirrors shipment validation for contact and description fields, but does **NOT** validate InternationalForms (not required for rate requests).

| Field | `dot_path` | `flat_key` | Condition | Constraints |
|-------|-----------|------------|-----------|-------------|
| Shipper attention name | `RateRequest.Shipment.Shipper.AttentionName` | `shipper_attention_name` | International | maxLength: 35 |
| Shipper phone | `RateRequest.Shipment.Shipper.Phone.Number` | `shipper_phone` | International | maxLength: 15 |
| Recipient attention name | `RateRequest.Shipment.ShipTo.AttentionName` | `ship_to_attention_name` | International OR service "14" | maxLength: 35 |
| Recipient phone | `RateRequest.Shipment.ShipTo.Phone.Number` | `ship_to_phone` | International OR service "14" | maxLength: 15 |
| Description of goods | `RateRequest.Shipment.Description` | `shipment_description` | International (with exemptions) | maxLength: 50 |
| Invoice currency code | `RateRequest.Shipment.InvoiceLineTotal.CurrencyCode` | `invoice_currency_code` | US→CA/PR forward only | 3-letter alpha |
| Invoice monetary value | `RateRequest.Shipment.InvoiceLineTotal.MonetaryValue` | `invoice_monetary_value` | US→CA/PR forward only | maxLength: 11, numeric |

> **Key difference from `create_shipment`:** No InternationalForms, Product array, or duties payer validation is performed for rate requests. For duties/taxes estimates, use the `get_landed_cost_quote` tool.

---

## 6. Elicitation Behavior Changes

### Two-Tier Missing Field Classification

Missing fields are now classified into two tiers:

1. **Elicitable fields** (`elicitable=True`, default) — Simple scalar values (names, phone numbers, currency codes, enum selections) that can be collected via flat key→value MCP forms.

2. **Structural fields** (`elicitable=False`) — Complex nested structures (InternationalForms dict, Product array, payment objects) that **cannot** be meaningfully collected through flat forms. These always trigger an immediate `STRUCTURAL_FIELDS_REQUIRED` error.

### Processing Order

```
find_missing_fields(body)
    │
    ├── Structural fields found?
    │   └── YES → Raise STRUCTURAL_FIELDS_REQUIRED (with guidance prompts)
    │            Elicitation is NEVER attempted.
    │
    ├── Client supports form elicitation?
    │   └── NO → Raise ELICITATION_UNSUPPORTED (with missing field list)
    │
    └── YES → Build schema → ctx.elicit() → normalize → validate → rehydrate
              → re-check → INCOMPLETE_SHIPMENT if still missing
```

### Impact on Clients

- **LLM-based clients:** The `prompt` field in structural errors contains full JSON examples. LLMs should parse the guidance and construct the required structure in `request_body` before retrying.
- **UI-based clients:** Structural errors should be displayed to users as guidance. The `missing[].prompt` contains human-readable instructions.
- **Programmatic clients:** Check for `STRUCTURAL_FIELDS_REQUIRED` as a new error code and handle accordingly.

---

## 7. New Error Code: `STRUCTURAL_FIELDS_REQUIRED`

This is the only new error code introduced. It is raised **before** any elicitation attempt when the missing fields include non-elicitable structural requirements.

### Error Payload Shape

```json
{
  "code": "STRUCTURAL_FIELDS_REQUIRED",
  "message": "Missing 1 structural field(s) that must be added directly to request_body (cannot be elicited via form)",
  "reason": "structural",
  "missing": [
    {
      "dot_path": "ShipmentRequest.Shipment.ShipmentServiceOptions.InternationalForms",
      "flat_key": "intl_forms_required",
      "prompt": "International shipments require InternationalForms. Add ShipmentServiceOptions.InternationalForms to request_body with at least: FormType (e.g. '01' for Invoice), CurrencyCode, ReasonForExport, and a Product array. Example structure: {\"ShipmentServiceOptions\": {\"InternationalForms\": {\"FormType\": \"01\", \"CurrencyCode\": \"USD\", ...}}}"
    }
  ]
}
```

### When It Fires

| `flat_key` | Trigger Condition |
|-----------|-------------------|
| `intl_forms_required` | International shipment, no UPS Letter or EU-to-EU Standard exemption, and `ShipmentServiceOptions.InternationalForms` is missing from request body |
| `intl_forms_product_required` | InternationalForms present with a FormType that requires products (`01`, `03`, `04`, `05`, `06`, `08`, `11`), but `Product` is missing |
| `duties_payer_required` | `ShipmentCharge[1]` has `Type: "02"` (Duties and Taxes) but no `BillShipper`, `BillReceiver`, or `BillThirdParty` |

### Recommended Client Handling

```
IF error.code == "STRUCTURAL_FIELDS_REQUIRED":
    FOR each field in error.missing:
        // Parse field.prompt for structural guidance
        // Build the required nested structure
        // Add it to request_body
    RETRY the tool call with the updated request_body
```

---

## 8. Complete Error Code Reference

All ToolError payloads are JSON strings with this shape:

```json
{
  "code": "<ERROR_CODE>",
  "message": "<human-readable message>",
  "reason": "<machine-readable reason>",
  "missing": [{"dot_path": "...", "flat_key": "...", "prompt": "..."}]
}
```

| Code | Reason | When Raised | Client Action |
|------|--------|-------------|---------------|
| `STRUCTURAL_FIELDS_REQUIRED` | `structural` | **NEW.** Missing fields are complex structures that can't be flat-form elicited | Parse `missing[].prompt` for guidance, build structures in `request_body`, retry |
| `ELICITATION_UNSUPPORTED` | `unsupported` | Missing scalar fields, client lacks form-mode elicitation capability | Populate missing fields in `request_body` manually, retry |
| `ELICITATION_FAILED` | `transport_error` | `ctx.elicit()` threw a non-ToolError exception | Retry or fall back to manual field population |
| `ELICITATION_INVALID_RESPONSE` | `validation_errors` | Elicited values failed semantic validation (bad format, out of enum range) | Show validation errors to user, retry elicitation |
| `ELICITATION_INVALID_RESPONSE` | `rehydration_error` | Elicited values conflict with existing request structure | Inspect request body for structural issues |
| `INCOMPLETE_SHIPMENT` | `still_missing` | Fields are still missing after elicitation round completed | Re-check `missing[]` list and populate remaining fields |
| `ELICITATION_DECLINED` | `declined` | User declined the elicitation form | Abort or retry with pre-populated fields |
| `ELICITATION_CANCELLED` | `cancelled` | User cancelled the elicitation form | Abort the operation |
| `MALFORMED_REQUEST` | `malformed_structure` | Request body has structural type conflicts (e.g., string where dict expected) | Fix request body structure |
| `MALFORMED_REQUEST` | `ambiguous_payer` | Multiple payer objects in the same ShipmentCharge (e.g. both BillShipper and BillReceiver) | Use exactly one payer object per ShipmentCharge |

---

## 9. InternationalForms Reference

### FormType Codes

| Code | Name | Requires Product[] | Requires CurrencyCode | Additional Requirements |
|------|------|-------------------|----------------------|------------------------|
| `01` | Invoice | Yes | Yes | ReasonForExport, InvoiceNumber, InvoiceDate (unless return) |
| `03` | Certificate of Origin | Yes | No | — |
| `04` | USMCA | Yes | No | — |
| `05` | Partial Invoice (returns) | Yes | Yes | — |
| `06` | Packing List | Yes | No | — |
| `07` | Customer Generated Forms | No | No | — |
| `08` | Air Freight Packing List | Yes | No | — |
| `09` | CN22 Form | No | No | Postal shipments |
| `10` | UPS Premium Care Form | No | No | — |
| `11` | EEI | Yes | No | US exports >$2,500 or embargoed destinations |

### ReasonForExport Values

| Value | Description |
|-------|-------------|
| `SALE` | Commercial sale |
| `GIFT` | Gift |
| `SAMPLE` | Sample |
| `RETURN` | Returned goods |
| `REPAIR` | Goods for repair |
| `INTERCOMPANYDATA` | Intercompany transfer |

### Product Array Structure (Required Sub-Fields)

```json
{
  "Product": [
    {
      "Description": "Electronics",
      "Unit": {
        "Number": "1",
        "Value": "100",
        "UnitOfMeasurement": { "Code": "PCS" }
      },
      "CommodityCode": "8471.30",
      "OriginCountryCode": "US"
    }
  ]
}
```

> **Note:** `Product` may also be a single dict (UPS accepts both). The server does not normalize this.

---

## 10. Minimal International Shipment Example

US → GB shipment with Commercial Invoice:

```json
{
  "ShipmentRequest": {
    "Request": { "RequestOption": "nonvalidate" },
    "Shipment": {
      "Shipper": {
        "Name": "ACME Corp",
        "AttentionName": "John Smith",
        "ShipperNumber": "YOUR_ACCOUNT",
        "Phone": { "Number": "5551234567" },
        "Address": {
          "AddressLine": ["123 Main St"],
          "City": "Timonium",
          "StateProvinceCode": "MD",
          "PostalCode": "21093",
          "CountryCode": "US"
        }
      },
      "ShipTo": {
        "Name": "London Office",
        "AttentionName": "Jane Doe",
        "Phone": { "Number": "4401234567" },
        "Address": {
          "AddressLine": ["10 Downing St"],
          "City": "London",
          "PostalCode": "SW1A 2AA",
          "CountryCode": "GB"
        }
      },
      "Service": { "Code": "07" },
      "Description": "Electronics",
      "Package": [{
        "Packaging": { "Code": "02" },
        "PackageWeight": {
          "UnitOfMeasurement": { "Code": "LBS" },
          "Weight": "5"
        }
      }],
      "PaymentInformation": {
        "ShipmentCharge": [{
          "Type": "01",
          "BillShipper": { "AccountNumber": "YOUR_ACCOUNT" }
        }]
      },
      "ShipmentServiceOptions": {
        "InternationalForms": {
          "FormType": "01",
          "CurrencyCode": "USD",
          "ReasonForExport": "SALE",
          "InvoiceNumber": "INV-001",
          "InvoiceDate": "20260216",
          "Product": [{
            "Description": "Electronics",
            "Unit": {
              "Number": "1",
              "Value": "100",
              "UnitOfMeasurement": { "Code": "PCS" }
            },
            "CommodityCode": "8471.30",
            "OriginCountryCode": "US"
          }]
        }
      }
    }
  }
}
```

### What Gets Validated

If you omit fields from the above, the server will:

| Omission | Server Response |
|----------|----------------|
| Missing `AttentionName` or `Phone.Number` | Elicitation prompt (scalar) |
| Missing `Description` | Elicitation prompt (scalar) |
| Missing entire `InternationalForms` | `STRUCTURAL_FIELDS_REQUIRED` error with JSON example |
| `InternationalForms` present but missing `FormType` | Elicitation prompt with enum choices |
| `FormType: "01"` but missing `Product` | `STRUCTURAL_FIELDS_REQUIRED` error with array example |
| `FormType: "01"` but missing `CurrencyCode` | Elicitation prompt (scalar) |
| `FormType: "01"` but missing `ReasonForExport` | Elicitation prompt with enum choices |

---

## 11. Minimal International Rate Request Example

US → GB rate request:

```json
{
  "RateRequest": {
    "Shipment": {
      "Shipper": {
        "Name": "ACME Corp",
        "AttentionName": "John Smith",
        "ShipperNumber": "YOUR_ACCOUNT",
        "Phone": { "Number": "5551234567" },
        "Address": {
          "AddressLine": ["123 Main St"],
          "City": "Timonium",
          "StateProvinceCode": "MD",
          "PostalCode": "21093",
          "CountryCode": "US"
        }
      },
      "ShipTo": {
        "Name": "London Office",
        "AttentionName": "Jane Doe",
        "Phone": { "Number": "4401234567" },
        "Address": {
          "AddressLine": ["10 Downing St"],
          "City": "London",
          "PostalCode": "SW1A 2AA",
          "CountryCode": "GB"
        }
      },
      "Service": { "Code": "07" },
      "Description": "Electronics",
      "Package": [{
        "Packaging": { "Code": "02" },
        "PackageWeight": {
          "UnitOfMeasurement": { "Code": "LBS" },
          "Weight": "5"
        }
      }],
      "PaymentInformation": {
        "ShipmentCharge": [{
          "Type": "01",
          "BillShipper": { "AccountNumber": "YOUR_ACCOUNT" }
        }]
      }
    }
  }
}
```

> **Key difference:** No `InternationalForms`, no `ShipmentServiceOptions` needed for rating. The server validates contacts, Description, and InvoiceLineTotal only. For duties/taxes estimates, use `get_landed_cost_quote`.

---

## 12. Validation Exemptions

Certain field requirements are **waived** under specific conditions:

### UPS Letter Exemption

When **all** packages use Packaging Code `"01"` (UPS Letter), the following are **not required**:
- `Shipment.Description`
- `ShipmentServiceOptions.InternationalForms` (create_shipment only)

This applies to both `create_shipment` and `rate_shipment`.

### EU-to-EU UPS Standard Exemption

When **all** of these conditions are true:
- Origin country is in the EU (AT, BE, BG, HR, CY, CZ, DK, EE, FI, FR, DE, GR, HU, IE, IT, LV, LT, LU, MT, NL, PL, PT, RO, SK, SI, ES, SE)
- Destination country is in the EU
- Service Code is `"11"` (UPS Standard)

The following are **not required**:
- `Shipment.Description`
- `ShipmentServiceOptions.InternationalForms` (create_shipment only)

### InvoiceLineTotal Scope

`InvoiceLineTotal` (CurrencyCode + MonetaryValue) is only required for:
- **Origin:** US
- **Destination:** CA or PR
- **Direction:** Forward shipments only (not returns — `ReturnService` is absent)

### ShipTo Contact Rules for Service "14"

ShipTo contact fields (`AttentionName` and `Phone.Number`) are required for:
- All international shipments, **OR**
- Service Code `"14"` (UPS Express Early) even for domestic shipments

---

## 13. Duties & Taxes Payment

To bill duties and taxes separately from transportation, include a second `ShipmentCharge` with `Type: "02"`:

```json
{
  "PaymentInformation": {
    "ShipmentCharge": [
      {
        "Type": "01",
        "BillShipper": { "AccountNumber": "SHIPPER_ACCT" }
      },
      {
        "Type": "02",
        "BillReceiver": { "AccountNumber": "RECEIVER_ACCT" }
      }
    ]
  }
}
```

**Validation rules:**
- If `ShipmentCharge[1]` has `Type: "02"`, it **must** contain exactly one of: `BillShipper`, `BillReceiver`, or `BillThirdParty`
- Missing payer triggers a `STRUCTURAL_FIELDS_REQUIRED` error (not elicitable — the payer object is a nested dict with an AccountNumber)
- Charge Type codes: `01` = Transportation, `02` = Duties and Taxes, `03` = Broker of Choice

---

## 14. Currency Code Handling

Currency codes are now normalized and validated during elicitation:

### Normalization (Automatic)
- All fields matching `*_currency_code` are uppercased: `usd` → `USD`, `eur` → `EUR`
- Applied during `normalize_elicited_values()` before validation

### Validation
- Must be exactly 3 uppercase alphabetic characters (ISO 4217 format)
- Invalid examples: `US` (too short), `USDD` (too long), `123` (numeric)
- Validation error message: `"must be a 3-letter currency code (e.g. USD, EUR, GBP)"`

### Affected Fields
- `intl_forms_currency_code` — InternationalForms.CurrencyCode
- `invoice_currency_code` — InvoiceLineTotal.CurrencyCode

---

## 15. Migration Checklist

### For All Clients

- [ ] **Handle `STRUCTURAL_FIELDS_REQUIRED` error code.** This is new and will fire for international shipments missing InternationalForms, Product arrays, or duties payers. Parse the `missing[].prompt` for guidance on what to add to `request_body`.
- [ ] **No changes needed for domestic shipments.** All domestic validation is unchanged.
- [ ] **Test with international origin/destination pairs.** Verify your client handles the new validation for at least: US→GB (general international), US→CA (InvoiceLineTotal), EU→EU with service "11" (exemption path).

### For Clients Supporting Form-Mode Elicitation

- [ ] **Structural fields will never appear in elicitation forms.** They are filtered out before schema generation. If you were handling all `missing` fields as form inputs, no change needed — you'll get fewer fields in the form, and structural issues will come as errors instead.
- [ ] **New elicitable fields will appear in forms.** If international fields are missing, your elicitation forms may now include: `intl_forms_form_type` (enum), `intl_forms_currency_code` (text), `intl_forms_reason_for_export` (enum), `intl_forms_invoice_number` (text), `intl_forms_invoice_date` (text), plus contact/description fields.
- [ ] **Enum fields have `oneOf` metadata.** Fields like `intl_forms_form_type` and `intl_forms_reason_for_export` include `json_schema_extra.oneOf` with `const`+`title` pairs for human-readable labels (e.g., `{"const": "01", "title": "Invoice"}`).

### For LLM-Based Clients

- [ ] **Tool descriptions now include international guidance.** The `create_shipment` and `rate_shipment` docstrings have expanded sections documenting international requirements, FormType codes, example JSON, and exemptions. LLMs reading tool descriptions will have the context to build correct international payloads.
- [ ] **Structural error prompts are LLM-friendly.** The `prompt` field in `STRUCTURAL_FIELDS_REQUIRED` errors contains full JSON examples that LLMs can parse and use to construct the required structures.

### For Programmatic Clients

- [ ] **Add `STRUCTURAL_FIELDS_REQUIRED` to your error code switch/map.** This sits alongside existing codes like `ELICITATION_UNSUPPORTED` and `INCOMPLETE_SHIPMENT`.
- [ ] **The `missing` array in error payloads is unchanged in shape.** Each entry still has `dot_path`, `flat_key`, and `prompt`. The `flat_key` values for new structural fields are: `intl_forms_required`, `intl_forms_product_required`, `duties_payer_required`.

---

## 16. FAQ

**Q: Will this break my existing domestic shipment flows?**
A: No. International validation only activates when origin ≠ destination country. All domestic behavior is unchanged.

**Q: What if my client doesn't support MCP form-mode elicitation?**
A: Scalar field validation will raise `ELICITATION_UNSUPPORTED` with the full list of missing fields in `missing[]`. Structural field validation will raise `STRUCTURAL_FIELDS_REQUIRED`. In both cases, your client should populate the fields in `request_body` and retry.

**Q: Why can't InternationalForms be elicited via forms?**
A: MCP form-mode elicitation uses flat key→value pairs. InternationalForms contains deeply nested structures (Product arrays with Unit objects, multiple form types, etc.) that can't be meaningfully decomposed into flat inputs. The server provides detailed JSON examples in the error prompt instead.

**Q: Do I need InternationalForms for rate requests?**
A: No. `rate_shipment` validates contacts, Description, and InvoiceLineTotal for international, but not InternationalForms. You only need InternationalForms when creating the actual shipment via `create_shipment`.

**Q: What happens if I include InternationalForms in a rate request anyway?**
A: It's ignored by the validator and passed through to the UPS API. UPS may or may not accept it — no harm in including it.

**Q: How do I get duties/taxes estimates before shipping?**
A: Use the `get_landed_cost_quote` tool, which is specifically designed for duties, taxes, and fee estimation.

**Q: My international shipment passed server validation but UPS API still rejected it. Why?**
A: The server validates the most common required fields but intentionally does not validate deeply nested sub-fields (CN22 details, USMCA specifics, EEI sub-fields, contacts within InternationalForms, etc.). These are validated by the UPS API. Check the UPS API error response for specifics.

**Q: What EU countries are in the exemption list?**
A: AT, BE, BG, HR, CY, CZ, DK, EE, FI, FR, DE, GR, HU, IE, IT, LV, LT, LU, MT, NL, PL, PT, RO, SK, SI, ES, SE (27 member states). The UK is **not** included.
