from importlib import metadata
from typing import Any, Literal
from mcp.server.fastmcp import FastMCP, Context
from mcp.server.fastmcp.exceptions import ToolError
from dotenv import load_dotenv
import json
import os
import sys
import uuid
from . import tools
from . import constants
from .openapi_registry import OpenAPISpecLoadError
from .shipagent_normalization import (
    HOSTED_RESPONSE_FORMAT,
    RAW_RESPONSE_FORMAT,
    ShipAgentNormalizationError,
    build_shipagent_capabilities,
    normalize_address_result,
    normalize_create_shipment_result,
    normalize_rate_result,
    to_normalization_error,
    to_safe_error,
)

ResponseFormat = Literal["raw", "shipagent_v1"]
MAX_IDEMPOTENCY_KEY_LENGTH = 512
MAX_CUSTOMER_CONTEXT_LENGTH = 512

# Initialize FastMCP server
mcp = FastMCP("ups-mcp")

load_dotenv()
base_url = constants.CIE_URL
client_id: str | None = None
client_secret: str | None = None
tool_manager: tools.ToolManager | None = None


def _refresh_runtime_configuration() -> None:
    global base_url, client_id, client_secret
    if os.getenv("ENVIRONMENT") == "production":
        base_url = constants.PRODUCTION_URL
    else:
        base_url = constants.CIE_URL
    client_id = os.getenv("CLIENT_ID")
    client_secret = os.getenv("CLIENT_SECRET")


def _initialize_tool_manager() -> None:
    global tool_manager
    tool_manager = tools.ToolManager(
        base_url=base_url,
        client_id=client_id,
        client_secret=client_secret,
        account_number=os.getenv("UPS_ACCOUNT_NUMBER"),
    )


def _require_tool_manager() -> tools.ToolManager:
    if tool_manager is None:
        raise RuntimeError("Tool manager is not initialized. Start UPS MCP via server.main().")
    return tool_manager


def _validate_response_format(response_format: str) -> ResponseFormat:
    if response_format not in (RAW_RESPONSE_FORMAT, HOSTED_RESPONSE_FORMAT):
        raise ToolError(json.dumps({
            "code": "INVALID_RESPONSE_FORMAT",
            "allowed": [RAW_RESPONSE_FORMAT, HOSTED_RESPONSE_FORMAT],
        }))
    return response_format  # type: ignore[return-value]


def _has_ascii_control(value: str) -> bool:
    return any(ord(char) < 32 or ord(char) == 127 for char in value)


def _is_ascii_country_code(value: str) -> bool:
    return len(value) == 2 and value.isascii() and value.isalpha()


def _hosted_validation_error(correlation_id: str) -> dict[str, Any]:
    return {
        "success": False,
        "error": {
            "category": "validation",
            "code": "UPS_VALIDATION_ERROR",
            "message": "UPS request validation failed.",
            "correlation_id": correlation_id,
            "retryable": False,
        },
    }


def _hosted_unknown_error(correlation_id: str) -> dict[str, Any]:
    return {
        "success": False,
        "error": {
            "category": "unknown",
            "code": "UPS_UNKNOWN_ERROR",
            "message": "UPS request failed unexpectedly.",
            "correlation_id": correlation_id,
            "retryable": False,
        },
    }


def _hosted_correlation_id(trans_id: str) -> tuple[str, dict[str, Any] | None]:
    if _has_ascii_control(trans_id):
        correlation_id = f"corr_{uuid.uuid4().hex}"
        return (
            correlation_id,
            _hosted_validation_error(correlation_id),
        )

    stripped_trans_id = trans_id.strip()
    if stripped_trans_id:
        return stripped_trans_id, None
    return f"corr_{uuid.uuid4().hex}", None


def _hosted_transaction_src_error(
    transaction_src: str,
    correlation_id: str,
) -> dict[str, Any] | None:
    if _has_ascii_control(transaction_src):
        return _hosted_validation_error(correlation_id)
    return None


def _validate_hosted_customer_context(request_body: dict[str, Any]) -> None:
    if not isinstance(request_body, dict):
        return
    request = (
        request_body
        .get("ShipmentRequest", {})
        .get("Request", {})
    )
    if not isinstance(request, dict):
        return
    if "TransactionReference" not in request:
        return
    transaction_reference = request["TransactionReference"]
    if not isinstance(transaction_reference, dict):
        raise ToolError(json.dumps({
            "code": "VALIDATION_ERROR",
            "reason": "transaction_reference_must_be_object",
        }))
    if "CustomerContext" not in transaction_reference:
        return
    customer_context = transaction_reference["CustomerContext"]
    if not isinstance(customer_context, str):
        raise ToolError(json.dumps({
            "code": "VALIDATION_ERROR",
            "reason": "customer_context_must_be_string",
        }))
    if _has_ascii_control(customer_context):
        raise ToolError(json.dumps({
            "code": "VALIDATION_ERROR",
            "reason": "customer_context_contains_ascii_control",
        }))
    if len(customer_context) > MAX_CUSTOMER_CONTEXT_LENGTH:
        raise ToolError(json.dumps({
            "code": "VALIDATION_ERROR",
            "reason": "customer_context_too_long",
        }))


def _installed_server_version() -> str:
    try:
        return metadata.version("ups-mcp")
    except Exception:
        return "unknown"


@mcp.tool()
async def shipagent_capabilities() -> dict[str, Any]:
    """Return hosted ShipAgent capability metadata without requiring UPS credentials."""
    return build_shipagent_capabilities(_installed_server_version())



@mcp.tool()
async def track_package(
    inquiryNumber: str,
    locale: str = "en_US",
    returnSignature: bool = False,
    returnMilestones: bool = False,
    returnPOD: bool = False,
    trans_id: str = "",
    transaction_src: str = "ups-mcp",
) -> dict[str, Any]:
    """
    The Track API retrieves current status of shipments such as Small Package 1Z, Infonotice, Mail Innovations, FGV, or UPS Freight shipments
    using the inquiry number. The tracking response data typically includes package movements/activities, destination UPS access point
    information, expected delivery dates/times, etc. The response returns an array of shipment objects containing detailed tracking information 
    and status for the package(s) associated with the inquiryNumber, including current status, activity history, delivery details, package details, and more.
    
    Args:
        inquiryNumber (str): the unique package identifier. Each inquiry number must be between 7 and 34 characters in length. Required.
        locale (str): Language and country code of the user, separated by an underscore. Default value is 'en_US'. Not required.
        returnSignature (bool): a boolean to indicate whether a signature is required, default is false. Not required.
        returnMilestones (bool): a boolean to indicate whether detailed information on a package's movements is required, default is false. Not required
        returnPOD (bool): a boolean to indicate whether a proof of delivery is required, default is false. Not required
        trans_id (str): Optional request id. If omitted, a UUID is generated.
        transaction_src (str): Optional caller source name. Default 'ups-mcp'.

    Returns:
        dict[str, Any]: Raw UPS Track API response (e.g. {"trackResponse": {...}}).
        On error, raises ToolError with JSON containing status_code, code, message, details.
    """
    tracking_data = _require_tool_manager().track_package(
        inquiryNum=inquiryNumber,
        locale=locale,
        returnSignature=returnSignature,
        returnMilestones=returnMilestones,
        returnPOD=returnPOD,
        trans_id=trans_id or None,
        transaction_src=transaction_src,
    )

    return tracking_data

@mcp.tool()
async def validate_address(
    addressLine1: str,
    politicalDivision1: str,
    politicalDivision2: str,
    zipPrimary: str,
    countryCode: str,
    addressLine2: str = "",
    urbanization: str = "",
    zipExtended: str = "",
    trans_id: str = "",
    transaction_src: str = "ups-mcp",
    response_format: ResponseFormat = "raw",
) -> dict[str, Any]:
    """
    Checks addresses against the United States Postal Service database of valid addresses in the U.S. and Puerto Rico.

    Args:
        addressLine1 (str): The primary address details including the house or building number and the street name, e.g. 123 Main St. Required.
        addressLine2 (str): Additional information like apartment or suite numbers. E.g. Apt 4B. Optional.
        politicalDivision1 (str): The two-letter state or province code e.g. GA for Georgia. Required.
        politicalDivision2 (str): The city or town name, e.g. Springfield. Required.
        zipPrimary (str): The postal code. Required.
        zipExtended (str): 4 digit Postal Code extension. For US use only. Optional.
        urbanization (str): Puerto Rico Political Division 3. Only valid for Puerto Rico. Optional.
        countryCode (str): The country code, e.g. US. Required.
        trans_id (str): Optional request id. If omitted, a UUID is generated.
        transaction_src (str): Optional caller source name. Default 'ups-mcp'.
        response_format (str): `raw` for the UPS payload, or `shipagent_v1`
            for the hosted-safe normalized response.

    Returns:
        dict[str, Any]: Raw UPS Address Validation response, or hosted-safe
        normalized payload when `response_format` is `shipagent_v1`. Raw UPS
        responses contain one of three indicators:
        - ValidAddressIndicator: Address is valid. Contains a 'Candidate' object with the corrected/standardized address.
        - AmbiguousAddressIndicator: Multiple possible address matches found. Review candidates.
        - NoCandidatesIndicator: Address could not be validated or does not exist in the USPS database.
        Raw errors raise ToolError. Hosted UPS and normalization errors return
        safe envelopes.
    """
    validated_response_format = _validate_response_format(response_format)

    if validated_response_format == RAW_RESPONSE_FORMAT:
        return _validate_address_execute(
            addressLine1=addressLine1,
            addressLine2=addressLine2,
            politicalDivision1=politicalDivision1,
            politicalDivision2=politicalDivision2,
            zipPrimary=zipPrimary,
            zipExtended=zipExtended,
            urbanization=urbanization,
            countryCode=countryCode,
            trans_id=trans_id or None,
            transaction_src=transaction_src,
        )

    correlation_id, correlation_error = _hosted_correlation_id(trans_id)
    if correlation_error is not None:
        return correlation_error

    transaction_src_error = _hosted_transaction_src_error(
        transaction_src,
        correlation_id,
    )
    if transaction_src_error is not None:
        return transaction_src_error

    hosted_country_code = countryCode.strip().upper()
    if not hosted_country_code or not _is_ascii_country_code(hosted_country_code):
        return _hosted_validation_error(correlation_id)
    if hosted_country_code not in {"US", "PR"}:
        return {
            "success": True,
            "correlationId": correlation_id,
            "status": "unsupported",
            "candidates": [],
        }

    required_fields = (
        addressLine1,
        politicalDivision1,
        politicalDivision2,
        zipPrimary,
    )
    if any(not value.strip() for value in required_fields):
        return _hosted_validation_error(correlation_id)

    try:
        raw_result = _validate_address_execute(
            addressLine1=addressLine1,
            addressLine2=addressLine2,
            politicalDivision1=politicalDivision1,
            politicalDivision2=politicalDivision2,
            zipPrimary=zipPrimary,
            zipExtended=zipExtended,
            urbanization=urbanization,
            countryCode=countryCode,
            trans_id=correlation_id,
            transaction_src=transaction_src,
        )
        return normalize_address_result(raw_result, correlation_id)
    except ShipAgentNormalizationError:
        return to_normalization_error(correlation_id)
    except ToolError as exc:
        return to_safe_error(exc, correlation_id)
    except Exception:
        return {
            "success": False,
            "error": {
                "category": "unknown",
                "code": "UPS_UNKNOWN_ERROR",
                "message": "UPS request failed unexpectedly.",
                "correlation_id": correlation_id,
                "retryable": False,
            },
        }


def _validate_address_execute(
    *,
    addressLine1: str,
    addressLine2: str,
    politicalDivision1: str,
    politicalDivision2: str,
    zipPrimary: str,
    zipExtended: str,
    urbanization: str,
    countryCode: str,
    trans_id: str | None,
    transaction_src: str,
) -> dict[str, Any]:
    return _require_tool_manager().validate_address(
        addressLine1=addressLine1,
        addressLine2=addressLine2,
        politicalDivision1=politicalDivision1,
        politicalDivision2=politicalDivision2,
        zipPrimary=zipPrimary,
        zipExtended=zipExtended,
        urbanization=urbanization,
        countryCode=countryCode,
        trans_id=trans_id or None,
        transaction_src=transaction_src,
    )

@mcp.tool()
async def rate_shipment(
    requestoption: str,
    request_body: dict[str, Any],
    version: str = "v2409",
    additionalinfo: str = "",
    trans_id: str = "",
    transaction_src: str = "ups-mcp",
    response_format: ResponseFormat = "raw",
    ctx: Context | None = None,
) -> dict[str, Any]:
    """
    Rate or shop a shipment using UPS Rating API (`POST /rating/{version}/{requestoption}`).

    If required fields are missing and the client supports form-mode elicitation,
    the server will prompt for the missing information. Otherwise, a structured
    ToolError is raised listing the missing fields.

    When requestoption is "Shop" or "Shoptimeintransit", Service.Code is not
    required — UPS returns rates for all available services.

    ## International Rate Requests

    When origin and destination countries differ, the following additional fields
    are validated and elicited:

    - **Shipper.AttentionName** and **Shipper.Phone.Number** — required for international
    - **ShipTo.AttentionName** and **ShipTo.Phone.Number** — required for international or service "14"
    - **Shipment.Description** — description of goods (max 50 chars); exempt for UPS Letter packages and EU-to-EU UPS Standard
    - **InvoiceLineTotal** (CurrencyCode + MonetaryValue) — required for US→CA/PR forward shipments

    InternationalForms is NOT required for rating — use `create_shipment` for the full
    international forms workflow. For duties/taxes estimates, see `get_landed_cost_quote`.

    Args:
        requestoption (str): One of Rate, Shop, Ratetimeintransit, Shoptimeintransit.
        request_body (dict): JSON object matching `RATERequestWrapper`.
            Minimum practical shape:
            - RateRequest.Shipment.Shipper (Name, ShipperNumber, Address)
            - RateRequest.Shipment.ShipTo (Name, Address)
            - RateRequest.Shipment.Service (Code) — not required for Shop mode
            - RateRequest.Shipment.Package (Packaging, PackageWeight)
            - RateRequest.Shipment.PaymentInformation (ShipmentCharge)
            For international, also include:
            - Shipper.AttentionName, Shipper.Phone.Number
            - ShipTo.AttentionName, ShipTo.Phone.Number
            - Shipment.Description
        version (str): API version. Default `v2409`.
        additionalinfo (str): Optional query param. Supports `timeintransit`.
        trans_id (str): Optional request id.
        transaction_src (str): Optional caller source name. Default `ups-mcp`.
        response_format (str): `raw` for the UPS payload, or `shipagent_v1`
            for the hosted-safe normalized response.
        ctx: MCP Context (injected by FastMCP, not provided by callers).

    Returns:
        dict[str, Any]: Raw UPS API response payload, or hosted-safe normalized
        payload when `response_format` is `shipagent_v1`. Raw errors raise
        ToolError; hosted UPS and normalization errors return safe envelopes.
    """
    validated_response_format = _validate_response_format(response_format)

    if validated_response_format == RAW_RESPONSE_FORMAT:
        return await _rate_shipment_execute(
            requestoption=requestoption,
            request_body=request_body,
            version=version,
            additionalinfo=additionalinfo,
            trans_id=trans_id or None,
            transaction_src=transaction_src,
            ctx=ctx,
            allow_elicitation=True,
        )

    correlation_id, correlation_error = _hosted_correlation_id(trans_id)
    if correlation_error is not None:
        return correlation_error

    transaction_src_error = _hosted_transaction_src_error(
        transaction_src,
        correlation_id,
    )
    if transaction_src_error is not None:
        return transaction_src_error

    try:
        raw_result = await _rate_shipment_execute(
            requestoption=requestoption,
            request_body=request_body,
            version=version,
            additionalinfo=additionalinfo,
            trans_id=correlation_id,
            transaction_src=transaction_src,
            ctx=None,
            allow_elicitation=False,
        )
        return normalize_rate_result(raw_result, requestoption, correlation_id)
    except ShipAgentNormalizationError:
        return to_normalization_error(correlation_id)
    except ToolError as exc:
        return to_safe_error(exc, correlation_id)
    except Exception:
        return {
            "success": False,
            "error": {
                "category": "unknown",
                "code": "UPS_UNKNOWN_ERROR",
                "message": "UPS request failed unexpectedly.",
                "correlation_id": correlation_id,
                "retryable": False,
            },
        }


async def _rate_shipment_execute(
    requestoption: str,
    request_body: dict[str, Any],
    version: str = "v2409",
    additionalinfo: str = "",
    trans_id: str | None = None,
    transaction_src: str = "ups-mcp",
    ctx: Context | None = None,
    allow_elicitation: bool = True,
) -> dict[str, Any]:
    from .rating_validator import (
        apply_rate_defaults,
        find_missing_rate_fields,
        canonicalize_rate_body,
        remap_packaging_for_rating,
    )
    from .elicitation import elicit_and_rehydrate
    from .shipment_validator import AmbiguousPayerError

    # Helper: canonicalize, remap Packaging→PackagingType, and send to UPS
    def _send_to_ups(body):
        canonical = canonicalize_rate_body(body)
        api_body = remap_packaging_for_rating(canonical)
        return _require_tool_manager().rate_shipment(
            requestoption=requestoption,
            request_body=api_body,
            version=version,
            additionalinfo=additionalinfo or None,
            trans_id=trans_id,
            transaction_src=transaction_src,
        )

    # 1. Canonicalize then apply 3-tier defaults
    env_config = {"UPS_ACCOUNT_NUMBER": os.getenv("UPS_ACCOUNT_NUMBER", "")}
    try:
        canonical_input = canonicalize_rate_body(request_body)
        merged_body = apply_rate_defaults(canonical_input, env_config)
    except TypeError as exc:
        raise ToolError(json.dumps({
            "code": "MALFORMED_REQUEST",
            "message": f"Request body has structural conflicts: {exc}",
            "reason": "malformed_structure",
            "missing": [],
        }))

    # 2. Preflight: find missing required fields
    try:
        find_fn = lambda body: find_missing_rate_fields(body, requestoption)
        missing = find_fn(merged_body)
    except AmbiguousPayerError as exc:
        raise ToolError(json.dumps({
            "code": "MALFORMED_REQUEST",
            "message": str(exc),
            "reason": "ambiguous_payer",
            "missing": [],
        }))

    # 3. Happy path — all fields present
    if not missing:
        return _send_to_ups(merged_body)

    if not allow_elicitation:
        raise ToolError(json.dumps({
            "code": "VALIDATION_ERROR",
            "message": "Missing required field(s) for rate request.",
            "reason": "missing_rate_required_fields",
            "missing": [field.flat_key for field in missing],
        }))

    # 4. Elicitation flow
    merged_body = await elicit_and_rehydrate(
        ctx, merged_body, missing,
        find_missing_fn=find_fn,
        tool_label="rate request",
        canonicalize_fn=canonicalize_rate_body,
    )
    return _send_to_ups(merged_body)

@mcp.tool()
async def create_shipment(
    request_body: dict[str, Any],
    version: str = "v2409",
    additionaladdressvalidation: str = "",
    trans_id: str = "",
    transaction_src: str = "ups-mcp",
    response_format: ResponseFormat = "raw",
    idempotency_key: str = "",
    ctx: Context | None = None,
) -> dict[str, Any]:
    """
    Create a shipment using UPS Shipping API (`POST /shipments/{version}/ship`).

    If required fields are missing and the client supports form-mode elicitation,
    the server will prompt for the missing information. Otherwise, a structured
    ToolError is raised listing the missing fields.

    ## International Shipments

    When origin and destination countries differ, additional fields are validated:

    - **Shipper.AttentionName** and **Shipper.Phone.Number**
    - **ShipTo.AttentionName** and **ShipTo.Phone.Number**
    - **Shipment.Description** — description of goods (exempt for UPS Letter, EU-to-EU Standard)
    - **InvoiceLineTotal** — required for US→CA/PR forward shipments
    - **ShipmentServiceOptions.InternationalForms** — required for most international
      shipments (exempt for UPS Letter packages and EU-to-EU UPS Standard)

    ### InternationalForms Structure

    FormType codes: 01=Invoice, 03=Certificate of Origin, 04=USMCA, 05=Partial Invoice,
    06=Packing List, 07=Customer Generated, 08=Air Freight Packing List, 09=CN22, 10=Premium Care, 11=EEI.

    Example Commercial Invoice (FormType "01"):
    ```json
    {"ShipmentServiceOptions": {"InternationalForms": {
        "FormType": "01",
        "CurrencyCode": "USD",
        "ReasonForExport": "SALE",
        "InvoiceNumber": "INV-001",
        "InvoiceDate": "20260216",
        "Product": [{"Description": "Electronics", "Unit": {"Number": "1",
            "Value": "100", "UnitOfMeasurement": {"Code": "PCS"}},
            "CommodityCode": "8471.30", "OriginCountryCode": "US"}]
    }}}
    ```

    ReasonForExport: SALE, GIFT, SAMPLE, RETURN, REPAIR, INTERCOMPANYDATA.
    Incoterms (TermsOfShipment): CFR, CIF, CIP, CPT, DAF, DDP, DAP, DEQ, DES, EXW, FAS, FCA, FOB.

    ### Duties & Taxes Payment

    To bill duties/taxes separately, add a second ShipmentCharge with Type "02":
    ```json
    {"PaymentInformation": {"ShipmentCharge": [
        {"Type": "01", "BillShipper": {"AccountNumber": "..."}},
        {"Type": "02", "BillReceiver": {"AccountNumber": "..."}}
    ]}}
    ```

    ### EEI (Electronic Export Information)

    Required for US exports valued >$2,500 or to embargoed destinations. Include
    EEIFilingOption in InternationalForms (codes: 1=Shipper Filed, 2=AES Direct, 3=UPS Filed).

    Args:
        request_body (dict): JSON object matching `SHIPRequestWrapper`.
            Minimum practical shape:
            - ShipmentRequest.Request
            - ShipmentRequest.Shipment.Shipper
            - ShipmentRequest.Shipment.ShipTo
            - ShipmentRequest.Shipment.Service
            - ShipmentRequest.Shipment.Package
            - ShipmentRequest.Shipment.PaymentInformation
            For international, also include:
            - Shipper.AttentionName, Shipper.Phone.Number
            - ShipTo.AttentionName, ShipTo.Phone.Number
            - Shipment.Description
            - ShipmentServiceOptions.InternationalForms (FormType, Product[], CurrencyCode, etc.)
        version (str): API version. Default `v2409`.
        additionaladdressvalidation (str): Optional query param (for example `city`).
        trans_id (str): Optional request id.
        transaction_src (str): Optional caller source name. Default `ups-mcp`.
        response_format (str): `raw` for the UPS payload, or `shipagent_v1`
            for the hosted-safe normalized response.
        idempotency_key (str): Required only for hosted create shipment.
            Hosted mode strips this value, requires it to be non-empty, at
            most 512 characters, and free of ASCII control characters.
        ctx: MCP Context (injected by FastMCP, not provided by callers).

    Returns:
        dict[str, Any]: Raw UPS API response payload, or hosted-safe normalized
        payload when `response_format` is `shipagent_v1`. Raw errors raise
        ToolError; hosted UPS and normalization errors return safe envelopes.
    """
    validated_response_format = _validate_response_format(response_format)

    if validated_response_format == RAW_RESPONSE_FORMAT:
        return await _create_shipment_execute(
            request_body=request_body,
            version=version,
            additionaladdressvalidation=additionaladdressvalidation,
            trans_id=trans_id or None,
            transaction_src=transaction_src,
            idempotency_key=None,
            ctx=ctx,
            allow_elicitation=True,
        )

    correlation_id, correlation_error = _hosted_correlation_id(trans_id)
    if correlation_error is not None:
        return correlation_error

    transaction_src_error = _hosted_transaction_src_error(
        transaction_src,
        correlation_id,
    )
    if transaction_src_error is not None:
        return transaction_src_error

    hosted_idempotency_key = idempotency_key.strip() if isinstance(idempotency_key, str) else ""
    if not hosted_idempotency_key:
        return _hosted_validation_error(correlation_id)
    if len(hosted_idempotency_key) > MAX_IDEMPOTENCY_KEY_LENGTH:
        return _hosted_validation_error(correlation_id)
    if _has_ascii_control(hosted_idempotency_key):
        return _hosted_validation_error(correlation_id)

    try:
        raw_result = await _create_shipment_execute(
            request_body=request_body,
            version=version,
            additionaladdressvalidation=additionaladdressvalidation,
            trans_id=correlation_id,
            transaction_src=transaction_src,
            idempotency_key=hosted_idempotency_key,
            ctx=None,
            allow_elicitation=False,
        )
        return normalize_create_shipment_result(
            raw_result,
            hosted_idempotency_key,
            correlation_id,
        )
    except ShipAgentNormalizationError:
        return to_normalization_error(correlation_id)
    except ToolError as exc:
        return to_safe_error(exc, correlation_id)
    except Exception:
        return _hosted_unknown_error(correlation_id)


async def _create_shipment_execute(
    *,
    request_body: dict[str, Any],
    version: str,
    additionaladdressvalidation: str,
    trans_id: str | None,
    transaction_src: str,
    idempotency_key: str | None,
    ctx: Context | None,
    allow_elicitation: bool,
) -> dict[str, Any]:
    from .shipment_validator import (
        apply_defaults,
        find_missing_fields,
        canonicalize_body,
        AmbiguousPayerError,
        PRODUCT_ARRAY_RULE,
    )
    from .elicitation import elicit_and_rehydrate

    # Helper: canonicalize and send to UPS
    def _send_to_ups(body: dict[str, Any]) -> dict[str, Any]:
        canonical = canonicalize_body(body)
        return _require_tool_manager().create_shipment(
            request_body=canonical,
            version=version,
            additionaladdressvalidation=additionaladdressvalidation or None,
            trans_id=trans_id,
            transaction_src=transaction_src,
            idempotency_key=idempotency_key,
        )

    # 1. Canonicalize then apply 3-tier defaults (may raise TypeError on malformed bodies)
    env_config = {"UPS_ACCOUNT_NUMBER": os.getenv("UPS_ACCOUNT_NUMBER", "")}
    try:
        canonical_input = canonicalize_body(request_body)
        merged_body = apply_defaults(canonical_input, env_config)
        if idempotency_key is not None:
            _validate_hosted_customer_context(merged_body)
    except TypeError as exc:
        raise ToolError(json.dumps({
            "code": "MALFORMED_REQUEST",
            "message": f"Request body has structural conflicts: {exc}",
            "reason": "malformed_structure",
            "missing": [],
        }))

    # 2. Preflight: find missing required fields
    try:
        missing = find_missing_fields(merged_body)
    except AmbiguousPayerError as exc:
        raise ToolError(json.dumps({
            "code": "MALFORMED_REQUEST",
            "message": str(exc),
            "reason": "ambiguous_payer",
            "missing": [],
        }))

    # 3. Happy path — all fields present
    if not missing:
        return _send_to_ups(merged_body)

    if not allow_elicitation:
        raise ToolError(json.dumps({
            "code": "VALIDATION_ERROR",
            "message": "Missing required field(s) for shipment creation.",
            "reason": "missing_shipment_required_fields",
            "missing": [field.flat_key for field in missing],
        }))

    # 4. Elicitation flow (checks support, builds schema, validates, rehydrates)
    merged_body = await elicit_and_rehydrate(
        ctx, merged_body, missing,
        find_missing_fn=find_missing_fields,
        tool_label="shipment creation",
        canonicalize_fn=canonicalize_body,
        array_rules=[PRODUCT_ARRAY_RULE],
    )
    return _send_to_ups(merged_body)

@mcp.tool()
async def void_shipment(
    shipmentidentificationnumber: str,
    version: str = "v2409",
    trackingnumber: str | list[str] | None = None,
    trans_id: str = "",
    transaction_src: str = "ups-mcp",
) -> dict[str, Any]:
    """
    Void a shipment using UPS Shipping API (`DELETE /shipments/{version}/void/cancel/{shipmentidentificationnumber}`).

    Args:
        shipmentidentificationnumber (str): UPS shipment id (1Z...).
        version (str): API version. Default `v2409`.
        trackingnumber (str | list[str] | None): Optional tracking number(s).
        trans_id (str): Optional request id.
        transaction_src (str): Optional caller source name. Default `ups-mcp`.

    Returns:
        dict[str, Any]: Raw UPS API response payload. On error, raises ToolError.
    """
    return _require_tool_manager().void_shipment(
        shipmentidentificationnumber=shipmentidentificationnumber,
        version=version,
        trackingnumber=trackingnumber,
        trans_id=trans_id or None,
        transaction_src=transaction_src,
    )

@mcp.tool()
async def recover_label(
    request_body: dict[str, Any],
    version: str = "v1",
    trans_id: str = "",
    transaction_src: str = "ups-mcp",
) -> dict[str, Any]:
    """
    Recover forward or return labels (`POST /labels/{version}/recovery`).

    Args:
        request_body (dict): JSON object matching `LABELRECOVERYRequestWrapper`.
            Minimum practical shape:
            - LabelRecoveryRequest.Request
            - LabelRecoveryRequest.TrackingNumber OR related lookup fields
            - LabelRecoveryRequest.LabelSpecification
        version (str): API version. Default `v1`.
        trans_id (str): Optional request id.
        transaction_src (str): Optional caller source name. Default `ups-mcp`.

    Returns:
        dict[str, Any]: Raw UPS API response payload. On error, raises ToolError.
    """
    return _require_tool_manager().recover_label(
        request_body=request_body,
        version=version,
        trans_id=trans_id or None,
        transaction_src=transaction_src,
    )

@mcp.tool()
async def get_time_in_transit(
    request_body: dict[str, Any],
    version: str = "v1",
    trans_id: str = "",
    transaction_src: str = "ups-mcp",
) -> dict[str, Any]:
    """
    Get transit-time estimates (`POST /shipments/{version}/transittimes`).

    Args:
        request_body (dict): JSON object matching `TimeInTransitRequest`.
            Common fields include:
            - originCountryCode, originPostalCode
            - destinationCountryCode, destinationPostalCode
            - weight, weightUnitOfMeasure
            - shipDate, numberOfPackages
        version (str): API version. Default `v1`.
        trans_id (str): Optional request id.
        transaction_src (str): Optional caller source name. Default `ups-mcp`.

    Returns:
        dict[str, Any]: Raw UPS API response payload. On error, raises ToolError.
    """
    return _require_tool_manager().get_time_in_transit(
        request_body=request_body,
        version=version,
        trans_id=trans_id or None,
        transaction_src=transaction_src,
    )

@mcp.tool()
async def get_landed_cost_quote(
    currency_code: str,
    export_country_code: str,
    import_country_code: str,
    commodities: list[dict[str, Any]],
    shipment_type: str = "Sale",
    account_number: str = "",
    trans_id: str = "",
    transaction_src: str = "ups-mcp",
) -> dict[str, Any]:
    """
    Get landed cost quote for international shipments (`POST /landedcost/v1/quotes`).

    Calculates duties, taxes, and fees for cross-border shipments.

    Args:
        currency_code (str): ISO currency code (e.g. USD, EUR, GBP). Required.
        export_country_code (str): ISO country code of origin (e.g. US). Required.
        import_country_code (str): ISO country code of destination (e.g. GB). Required.
        commodities (list[dict]): List of commodity dicts, each with at minimum:
            - price (float): Unit price. Required.
            - quantity (int): Number of units. Required.
            - hs_code (str): Harmonized System code. Optional.
            - description (str): Item description. Optional.
            - weight (float): Gross weight per item. Optional (requires weight_unit).
            - weight_unit (str): Weight unit (LBS, KGS). Optional (requires weight).
        shipment_type (str): Type of shipment (e.g. Sale, Gift). Default 'Sale'.
        account_number (str): UPS account number. Optional, falls back to UPS_ACCOUNT_NUMBER env var.
        trans_id (str): Optional request id.
        transaction_src (str): Optional caller source name. Default 'ups-mcp'.

    Returns:
        dict[str, Any]: Raw UPS Landed Cost API response. On error, raises ToolError.
    """
    return _require_tool_manager().get_landed_cost_quote(
        currency_code=currency_code,
        export_country_code=export_country_code,
        import_country_code=import_country_code,
        commodities=commodities,
        shipment_type=shipment_type,
        account_number=account_number or None,
        trans_id=trans_id or None,
        transaction_src=transaction_src,
    )

@mcp.tool()
async def upload_paperless_document(
    file_content_base64: str,
    file_name: str,
    file_format: str,
    document_type: str,
    shipper_number: str = "",
    trans_id: str = "",
    transaction_src: str = "ups-mcp",
) -> dict[str, Any]:
    """
    Upload a paperless document (`POST /paperlessdocuments/v2/upload`).

    Args:
        file_content_base64 (str): Base64-encoded file content. Required.
        file_name (str): Original file name. Required.
        file_format (str): File format (pdf, doc, docx, xls, xlsx, txt, rtf, tif, jpg). Required.
        document_type (str): UPS document type code (e.g. '002' for invoice). Required.
        shipper_number (str): UPS shipper/account number. Optional, falls back to UPS_ACCOUNT_NUMBER.
        trans_id (str): Optional request id.
        transaction_src (str): Optional caller source name. Default 'ups-mcp'.

    Returns:
        dict[str, Any]: Raw UPS Paperless API response. On error, raises ToolError.
    """
    return _require_tool_manager().upload_paperless_document(
        file_content_base64=file_content_base64,
        file_name=file_name,
        file_format=file_format,
        document_type=document_type,
        shipper_number=shipper_number or None,
        trans_id=trans_id or None,
        transaction_src=transaction_src,
    )

@mcp.tool()
async def push_document_to_shipment(
    document_id: str,
    shipment_identifier: str,
    shipment_type: Literal["1", "2"] = "1",
    shipper_number: str = "",
    trans_id: str = "",
    transaction_src: str = "ups-mcp",
) -> dict[str, Any]:
    """
    Push a previously uploaded document to a shipment (`POST /paperlessdocuments/v2/image`).

    Args:
        document_id (str): Document ID from a prior upload. Required.
        shipment_identifier (str): UPS tracking number (1Z...). Required.
        shipment_type (str): '1' for forward, '2' for return. Default '1'.
        shipper_number (str): UPS shipper/account number. Optional, falls back to UPS_ACCOUNT_NUMBER.
        trans_id (str): Optional request id.
        transaction_src (str): Optional caller source name. Default 'ups-mcp'.

    Returns:
        dict[str, Any]: Raw UPS Paperless API response. On error, raises ToolError.
    """
    return _require_tool_manager().push_document_to_shipment(
        document_id=document_id,
        shipment_identifier=shipment_identifier,
        shipment_type=shipment_type,
        shipper_number=shipper_number or None,
        trans_id=trans_id or None,
        transaction_src=transaction_src,
    )

@mcp.tool()
async def delete_paperless_document(
    document_id: str,
    shipper_number: str = "",
    trans_id: str = "",
    transaction_src: str = "ups-mcp",
) -> dict[str, Any]:
    """
    Delete a previously uploaded paperless document (`DELETE /paperlessdocuments/{version}/DocumentId/ShipperNumber`).

    Args:
        document_id (str): Document ID to delete. Required.
        shipper_number (str): UPS shipper/account number. Optional, falls back to UPS_ACCOUNT_NUMBER.
        trans_id (str): Optional request id.
        transaction_src (str): Optional caller source name. Default 'ups-mcp'.

    Returns:
        dict[str, Any]: Raw UPS Paperless API response. On error, raises ToolError.
    """
    return _require_tool_manager().delete_paperless_document(
        document_id=document_id,
        shipper_number=shipper_number or None,
        trans_id=trans_id or None,
        transaction_src=transaction_src,
    )

@mcp.tool()
async def find_locations(
    location_type: Literal["access_point", "retail", "general", "services"],
    address_line: str,
    city: str,
    state: str,
    postal_code: str,
    country_code: str,
    radius: float = 15.0,
    unit_of_measure: Literal["MI", "KM"] = "MI",
    max_results: int = 10,
    trans_id: str = "",
    transaction_src: str = "ups-mcp",
) -> dict[str, Any]:
    """
    Find UPS locations near an address (`POST /locations/v3/search/availabilities/{reqOption}`).

    Args:
        location_type (str): Type of location: access_point, retail, general, or services. Required.
        address_line (str): Street address. Required.
        city (str): City name. Required.
        state (str): State/province code. Required.
        postal_code (str): Postal/ZIP code. Required.
        country_code (str): ISO country code (e.g. US). Required.
        radius (float): Search radius. Default 15.0.
        unit_of_measure (str): MI (miles) or KM (kilometers). Default MI.
        max_results (int): Maximum number of locations to return (1-50). Default 10.
        trans_id (str): Optional request id.
        transaction_src (str): Optional caller source name. Default 'ups-mcp'.

    Returns:
        dict[str, Any]: Raw UPS Locator API response. On error, raises ToolError.
    """
    return _require_tool_manager().find_locations(
        location_type=location_type,
        address_line=address_line,
        city=city,
        state=state,
        postal_code=postal_code,
        country_code=country_code,
        radius=radius,
        unit_of_measure=unit_of_measure,
        max_results=max_results,
        trans_id=trans_id or None,
        transaction_src=transaction_src,
    )

@mcp.tool()
async def rate_pickup(
    pickup_type: Literal["oncall", "smart", "both"],
    address_line: str,
    city: str,
    state: str,
    postal_code: str,
    country_code: str,
    pickup_date: str,
    ready_time: str,
    close_time: str,
    service_date_option: Literal["01", "02", "03"] = "02",
    residential_indicator: Literal["Y", "N"] = "Y",
    service_code: str = "001",
    container_code: str = "01",
    quantity: int = 1,
    destination_country_code: str = "US",
    trans_id: str = "",
    transaction_src: str = "ups-mcp",
) -> dict[str, Any]:
    """
    Get pickup rate estimate (`POST /shipments/{version}/pickup/{pickuptype}`).

    Args:
        pickup_type (str): oncall, smart, or both. Required.
        address_line (str): Pickup street address. Required.
        city (str): City. Required.
        state (str): State/province code. Required.
        postal_code (str): Postal/ZIP code. Required.
        country_code (str): ISO country code. Required.
        pickup_date (str): Date in YYYYMMDD format. Required.
        ready_time (str): Ready time in HHMM 24hr format. Required.
        close_time (str): Close time in HHMM 24hr format. Required.
        service_date_option (str): 01, 02, or 03. Default 02.
        residential_indicator (str): Y or N. Default Y.
        service_code (str): UPS service code. Default 001.
        container_code (str): Container type. Default 01.
        quantity (int): Number of pieces. Default 1.
        destination_country_code (str): Destination country. Default US.
        trans_id (str): Optional request id.
        transaction_src (str): Optional caller source name. Default 'ups-mcp'.

    Returns:
        dict[str, Any]: Raw UPS Pickup Rate API response. On error, raises ToolError.
    """
    return _require_tool_manager().rate_pickup(
        pickup_type=pickup_type,
        address_line=address_line,
        city=city,
        state=state,
        postal_code=postal_code,
        country_code=country_code,
        pickup_date=pickup_date,
        ready_time=ready_time,
        close_time=close_time,
        service_date_option=service_date_option,
        residential_indicator=residential_indicator,
        service_code=service_code,
        container_code=container_code,
        quantity=quantity,
        destination_country_code=destination_country_code,
        trans_id=trans_id or None,
        transaction_src=transaction_src,
    )

@mcp.tool()
async def schedule_pickup(
    pickup_date: str,
    ready_time: str,
    close_time: str,
    address_line: str,
    city: str,
    state: str,
    postal_code: str,
    country_code: str,
    contact_name: str,
    phone_number: str,
    residential_indicator: Literal["Y", "N"] = "N",
    service_code: str = "001",
    container_code: str = "01",
    quantity: int = 1,
    weight: float = 5.0,
    weight_unit: Literal["LBS", "KGS"] = "LBS",
    payment_method: str = "01",
    rate_pickup_indicator: Literal["Y", "N"] = "N",
    account_number: str = "",
    trans_id: str = "",
    transaction_src: str = "ups-mcp",
) -> dict[str, Any]:
    """
    Schedule a pickup (`POST /pickupcreation/{version}/pickup`).

    Args:
        pickup_date (str): Date in YYYYMMDD format. Required.
        ready_time (str): Ready time in HHMM 24hr format. Required.
        close_time (str): Close time in HHMM 24hr format. Must be after ready_time. Required.
        address_line (str): Pickup street address. Required.
        city (str): City. Required.
        state (str): State/province code. Required.
        postal_code (str): Postal/ZIP code. Required.
        country_code (str): ISO country code. Required.
        contact_name (str): Contact person name. Required.
        phone_number (str): Contact phone number. Required.
        residential_indicator (str): Y or N. Default N.
        service_code (str): UPS service code. Default 001.
        container_code (str): Container type. Default 01.
        quantity (int): Number of pieces. Default 1.
        weight (float): Total weight. Default 5.0.
        weight_unit (str): LBS or KGS. Default LBS.
        payment_method (str): Payment method code (01=shipper account, 00=no payment). Default 01.
        rate_pickup_indicator (str): Y or N. Default N.
        account_number (str): UPS account number. Optional, falls back to UPS_ACCOUNT_NUMBER.
        trans_id (str): Optional request id.
        transaction_src (str): Optional caller source name. Default 'ups-mcp'.

    Returns:
        dict[str, Any]: Raw UPS Pickup Creation API response. On error, raises ToolError.
    """
    return _require_tool_manager().schedule_pickup(
        pickup_date=pickup_date,
        ready_time=ready_time,
        close_time=close_time,
        address_line=address_line,
        city=city,
        state=state,
        postal_code=postal_code,
        country_code=country_code,
        contact_name=contact_name,
        phone_number=phone_number,
        residential_indicator=residential_indicator,
        service_code=service_code,
        container_code=container_code,
        quantity=quantity,
        weight=weight,
        weight_unit=weight_unit,
        payment_method=payment_method,
        rate_pickup_indicator=rate_pickup_indicator,
        account_number=account_number or None,
        trans_id=trans_id or None,
        transaction_src=transaction_src,
    )

@mcp.tool()
async def cancel_pickup(
    cancel_by: Literal["account", "prn"],
    prn: str = "",
    trans_id: str = "",
    transaction_src: str = "ups-mcp",
) -> dict[str, Any]:
    """
    Cancel a scheduled pickup (`DELETE /shipments/{version}/pickup/{CancelBy}`).

    Args:
        cancel_by (str): Cancel method — 'account' (by account) or 'prn' (by PRN). Required.
        prn (str): Pickup Request Number. Required when cancel_by='prn'.
        trans_id (str): Optional request id.
        transaction_src (str): Optional caller source name. Default 'ups-mcp'.

    Returns:
        dict[str, Any]: Raw UPS Pickup Cancel API response. On error, raises ToolError.
    """
    return _require_tool_manager().cancel_pickup(
        cancel_by=cancel_by,
        prn=prn or None,
        trans_id=trans_id or None,
        transaction_src=transaction_src,
    )

@mcp.tool()
async def get_pickup_status(
    pickup_type: Literal["oncall", "smart", "both"],
    account_number: str = "",
    trans_id: str = "",
    transaction_src: str = "ups-mcp",
) -> dict[str, Any]:
    """
    Get pending pickup status (`GET /shipments/{version}/pickup/{pickuptype}`).

    Args:
        pickup_type (str): oncall, smart, or both. Required.
        account_number (str): UPS account number. Optional, falls back to UPS_ACCOUNT_NUMBER.
        trans_id (str): Optional request id.
        transaction_src (str): Optional caller source name. Default 'ups-mcp'.

    Returns:
        dict[str, Any]: Raw UPS Pickup Pending Status API response. On error, raises ToolError.
    """
    return _require_tool_manager().get_pickup_status(
        pickup_type=pickup_type,
        account_number=account_number or None,
        trans_id=trans_id or None,
        transaction_src=transaction_src,
    )

@mcp.tool()
async def get_political_divisions(
    country_code: str,
    trans_id: str = "",
    transaction_src: str = "ups-mcp",
) -> dict[str, Any]:
    """
    Get political divisions (states/provinces) for a country (`GET /pickup/{version}/countries/{countrycode}`).

    Args:
        country_code (str): ISO country code (e.g. US, CA, GB). Required.
        trans_id (str): Optional request id.
        transaction_src (str): Optional caller source name. Default 'ups-mcp'.

    Returns:
        dict[str, Any]: Raw UPS Political Division API response. On error, raises ToolError.
    """
    return _require_tool_manager().get_political_divisions(
        country_code=country_code,
        trans_id=trans_id or None,
        transaction_src=transaction_src,
    )

@mcp.tool()
async def get_service_center_facilities(
    city: str,
    state: str,
    postal_code: str,
    country_code: str,
    pickup_pieces: int = 1,
    container_code: str = "03",
    trans_id: str = "",
    transaction_src: str = "ups-mcp",
) -> dict[str, Any]:
    """
    Get UPS service center facilities (`POST /pickup/{version}/servicecenterlocations`).

    Args:
        city (str): City name. Required.
        state (str): State/province code. Required.
        postal_code (str): Postal/ZIP code. Required.
        country_code (str): ISO country code. Required.
        pickup_pieces (int): Number of pieces. Default 1.
        container_code (str): Container type. Default 03.
        trans_id (str): Optional request id.
        transaction_src (str): Optional caller source name. Default 'ups-mcp'.

    Returns:
        dict[str, Any]: Raw UPS Service Center Facilities API response. On error, raises ToolError.
    """
    return _require_tool_manager().get_service_center_facilities(
        city=city,
        state=state,
        postal_code=postal_code,
        country_code=country_code,
        pickup_pieces=pickup_pieces,
        container_code=container_code,
        trans_id=trans_id or None,
        transaction_src=transaction_src,
    )

def _validate_runtime_configuration() -> None:
    if not client_id or not client_secret:
        raise RuntimeError("Missing required env vars: CLIENT_ID and CLIENT_SECRET must be set before starting the server.")


def main():
    print("Starting UPS MCP Server...")
    _refresh_runtime_configuration()
    _validate_runtime_configuration()
    try:
        _initialize_tool_manager()
    except OpenAPISpecLoadError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc

    try:
        mcp.run(transport='stdio')
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    main()
