# Remaining PRs for Production-Grade International Pipeline

This note tracks the follow-up PRs after the international baseline validator.

## PR 2: InternationalForms Scaffolding
- Add required commercial invoice structure validation when forms are requested.
- Validate key fields (for example: `FormType`, `InvoiceNumber`, `InvoiceDate`, `ReasonForExport`, invoice currency).
- Validate required product-level form fields.
- Add forms-specific rule for `Shipper.AttentionName` when `ShipFrom` is absent.

## PR 3: Lane-Aware Service Discovery
- Replace static service-code selection with dynamic lane-based discovery via `rate_shipment` (Shop mode).
- Only present services that are valid for the shipment lane/account context.
- Use discovery output to reduce UPS hard rejects for invalid service/lane combinations.

## PR 4: Payload + Error Translation Hardening
- Ensure payload builders emit complete and valid international shipment payloads.
- Expand UPS error translation to actionable user-facing remediation.
- Add stronger preflight checks before API submission in interactive and batch flows.

## PR 5: Extended Service/Commodity Coverage
- Add freight and Mail Innovations service families with their required fields.
- Expand packaging/service compatibility rules.
- Add deeper commodity/customs support (for example HS/tariff assistance as available).
- Add dangerous-goods gating/validation tied to account capability.

## Cross-Cutting Quality Gates
- Add targeted end-to-end tests for representative international lanes.
- Add regression tests for return shipments, EU exceptions, and forms-enabled shipments.
- Add observability around UPS rejection categories to prioritize next validation improvements.
