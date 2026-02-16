CIE_URL = "https://wwwcie.ups.com"
PRODUCTION_URL = "https://onlinetools.ups.com"

LOCATOR_OPTIONS = {
    "access_point": "64",
    "retail": "32",
    "general": "1",
    "services": "8",
}

PICKUP_CANCEL_OPTIONS = {
    "account": "01",
    "prn": "02",
}

PAPERLESS_VALID_FORMATS = frozenset({
    "pdf", "doc", "docx", "xls", "xlsx", "txt", "rtf", "tif", "jpg",
})

# ---------------------------------------------------------------------------
# International shipping constants
# ---------------------------------------------------------------------------

INTERNATIONAL_FORM_TYPES = {
    "01": "Invoice",
    "03": "CO (Certificate of Origin)",
    "04": "USMCA",
    "05": "Partial Invoice (returns only)",
    "06": "Packing List",
    "07": "Customer Generated Forms",
    "08": "Air Freight Packing List",
    "09": "CN22 Form",
    "10": "UPS Premium Care Form",
    "11": "EEI",
}

# Subsets for conditional validation
FORMS_REQUIRING_PRODUCTS = frozenset({"01", "03", "04", "05", "06", "08", "11"})
FORMS_REQUIRING_CURRENCY = frozenset({"01", "05"})

# Incoterms (TermsOfShipment)
INCOTERMS = ("CFR", "CIF", "CIP", "CPT", "DAF", "DDP", "DAP", "DEQ", "DES", "EXW", "FAS", "FCA", "FOB")

# ReasonForExport valid values
REASON_FOR_EXPORT_VALUES = ("SALE", "GIFT", "SAMPLE", "RETURN", "REPAIR", "INTERCOMPANYDATA")

# Shipment charge types
SHIPMENT_CHARGE_TYPES = {"01": "Transportation", "02": "Duties and Taxes", "03": "Broker of Choice"}

# EEI filing option codes
EEI_FILING_OPTION_CODES = {"1": "Shipper Filed", "2": "AES Direct", "3": "UPS Filed"}