from typing import Any, Literal
from mcp.server.fastmcp import FastMCP, Context
from mcp.server.fastmcp.exceptions import ToolError
from dotenv import load_dotenv
import json
import os
import sys
from . import tools
from . import constants
from .openapi_registry import OpenAPISpecLoadError

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

    Returns:
        dict[str, Any]: Raw UPS Address Validation response containing one of three indicators:
        - ValidAddressIndicator: Address is valid. Contains a 'Candidate' object with the corrected/standardized address.
        - AmbiguousAddressIndicator: Multiple possible address matches found. Review candidates.
        - NoCandidatesIndicator: Address could not be validated or does not exist in the USPS database.
        On error, raises ToolError with JSON containing status_code, code, message, details.
    """
    validation_data = _require_tool_manager().validate_address(
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

    return validation_data

@mcp.tool()
async def rate_shipment(
    requestoption: str,
    request_body: dict[str, Any],
    version: str = "v2409",
    additionalinfo: str = "",
    trans_id: str = "",
    transaction_src: str = "ups-mcp",
    ctx: Context | None = None,
) -> dict[str, Any]:
    """
    Rate or shop a shipment using UPS Rating API (`POST /rating/{version}/{requestoption}`).

    If required fields are missing and the client supports form-mode elicitation,
    the server will prompt for the missing information. Otherwise, a structured
    ToolError is raised listing the missing fields.

    When requestoption is "Shop" or "Shoptimeintransit", Service.Code is not
    required — UPS returns rates for all available services.

    Args:
        requestoption (str): One of Rate, Shop, Ratetimeintransit, Shoptimeintransit.
        request_body (dict): JSON object matching `RATERequestWrapper`.
            Minimum practical shape:
            - RateRequest.Shipment.Shipper (Name, ShipperNumber, Address)
            - RateRequest.Shipment.ShipTo (Name, Address)
            - RateRequest.Shipment.Service (Code) — not required for Shop mode
            - RateRequest.Shipment.Package (Packaging, PackageWeight)
            - RateRequest.Shipment.PaymentInformation (ShipmentCharge)
        version (str): API version. Default `v2409`.
        additionalinfo (str): Optional query param. Supports `timeintransit`.
        trans_id (str): Optional request id.
        transaction_src (str): Optional caller source name. Default `ups-mcp`.
        ctx: MCP Context (injected by FastMCP, not provided by callers).

    Returns:
        dict[str, Any]: Raw UPS API response payload. On error, raises ToolError.
    """
    from .rating_validator import (
        apply_rate_defaults,
        find_missing_rate_fields,
        canonicalize_rate_body,
    )
    from .elicitation import elicit_and_rehydrate
    from .shipment_validator import AmbiguousPayerError

    # Helper: canonicalize and send to UPS
    def _send_to_ups(body):
        canonical = canonicalize_rate_body(body)
        return _require_tool_manager().rate_shipment(
            requestoption=requestoption,
            request_body=canonical,
            version=version,
            additionalinfo=additionalinfo or None,
            trans_id=trans_id or None,
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
    ctx: Context | None = None,
) -> dict[str, Any]:
    """
    Create a shipment using UPS Shipping API (`POST /shipments/{version}/ship`).

    If required fields are missing and the client supports form-mode elicitation,
    the server will prompt for the missing information. Otherwise, a structured
    ToolError is raised listing the missing fields.

    Args:
        request_body (dict): JSON object matching `SHIPRequestWrapper`.
            Minimum practical shape:
            - ShipmentRequest.Request
            - ShipmentRequest.Shipment.Shipper
            - ShipmentRequest.Shipment.ShipTo
            - ShipmentRequest.Shipment.Service
            - ShipmentRequest.Shipment.Package
            - ShipmentRequest.Shipment.PaymentInformation
        version (str): API version. Default `v2409`.
        additionaladdressvalidation (str): Optional query param (for example `city`).
        trans_id (str): Optional request id.
        transaction_src (str): Optional caller source name. Default `ups-mcp`.
        ctx: MCP Context (injected by FastMCP, not provided by callers).

    Returns:
        dict[str, Any]: Raw UPS API response payload. On error, raises ToolError.
    """
    from .shipment_validator import (
        apply_defaults,
        find_missing_fields,
        canonicalize_body,
        AmbiguousPayerError,
    )
    from .elicitation import elicit_and_rehydrate

    # Helper: canonicalize and send to UPS
    def _send_to_ups(body):
        canonical = canonicalize_body(body)
        return _require_tool_manager().create_shipment(
            request_body=canonical,
            version=version,
            additionaladdressvalidation=additionaladdressvalidation or None,
            trans_id=trans_id or None,
            transaction_src=transaction_src,
        )

    # 1. Canonicalize then apply 3-tier defaults (may raise TypeError on malformed bodies)
    env_config = {"UPS_ACCOUNT_NUMBER": os.getenv("UPS_ACCOUNT_NUMBER", "")}
    try:
        canonical_input = canonicalize_body(request_body)
        merged_body = apply_defaults(canonical_input, env_config)
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

    # 4. Elicitation flow (checks support, builds schema, validates, rehydrates)
    merged_body = await elicit_and_rehydrate(
        ctx, merged_body, missing,
        find_missing_fn=find_missing_fields,
        tool_label="shipment creation",
        canonicalize_fn=canonicalize_body,
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
