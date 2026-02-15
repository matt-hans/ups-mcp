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