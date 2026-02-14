from typing import Any
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
    )


def _require_tool_manager() -> tools.ToolManager:
    if tool_manager is None:
        raise RuntimeError("Tool manager is not initialized. Start UPS MCP via server.main().")
    return tool_manager


def _check_form_elicitation(ctx: Context | None) -> bool:
    """Check if the connected client supports form-mode elicitation."""
    if ctx is None:
        return False
    try:
        params = ctx.request_context.session.client_params
        if params is None:
            return False
        caps = params.capabilities
        if caps.elicitation is None:
            return False
        # Form supported if .form is explicitly present
        if caps.elicitation.form is not None:
            return True
        # Backward compat: empty elicitation object (neither form nor url set)
        if caps.elicitation.url is None:
            return True
        # Only url is set — form not supported
        return False
    except AttributeError:
        return False


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
) -> dict[str, Any]:
    """
    Rate or shop a shipment using UPS Rating API (`POST /rating/{version}/{requestoption}`).

    Args:
        requestoption (str): One of Rate, Shop, Ratetimeintransit, Shoptimeintransit.
        request_body (dict): JSON object matching `RATERequestWrapper`.
            Minimum practical shape:
            - RateRequest.Request
            - RateRequest.Shipment.Shipper (Name, Address, often ShipperNumber)
            - RateRequest.Shipment.ShipTo (Address)
            - RateRequest.Shipment.Package (PackagingType, Dimensions, PackageWeight)
        version (str): API version. Default `v2409`.
        additionalinfo (str): Optional query param. Supports `timeintransit`.
        trans_id (str): Optional request id.
        transaction_src (str): Optional caller source name. Default `ups-mcp`.

    Returns:
        dict[str, Any]: Raw UPS API response payload. On error, raises ToolError.
    """
    return _require_tool_manager().rate_shipment(
        requestoption=requestoption,
        request_body=request_body,
        version=version,
        additionalinfo=additionalinfo or None,
        trans_id=trans_id or None,
        transaction_src=transaction_src,
    )

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
        build_elicitation_schema,
        normalize_elicited_values,
        validate_elicited_values,
        rehydrate,
        canonicalize_body,
        RehydrationError,
        AmbiguousPayerError,
    )

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

    # Helper: build structured missing payload
    def _missing_payload(fields):
        return [
            {"dot_path": mf.dot_path, "flat_key": mf.flat_key, "prompt": mf.prompt}
            for mf in fields
        ]

    # 4. Check form-mode elicitation support
    if _check_form_elicitation(ctx):
        schema = build_elicitation_schema(missing)
        try:
            result = await ctx.elicit(
                message=f"Missing {len(missing)} required field(s) for shipment creation.",
                schema=schema,
            )
        except ToolError:
            raise  # re-raise ToolErrors as-is
        except Exception as exc:
            raise ToolError(json.dumps({
                "code": "ELICITATION_FAILED",
                "message": f"Elicitation request failed: {exc}",
                "reason": "transport_error",
                "missing": _missing_payload(missing),
            }))

        if result.action == "accept":
            normalized = normalize_elicited_values(result.data.model_dump())
            validation_errors = validate_elicited_values(normalized, missing)
            if validation_errors:
                raise ToolError(json.dumps({
                    "code": "ELICITATION_INVALID_RESPONSE",
                    "message": "; ".join(validation_errors),
                    "reason": "validation_errors",
                    "missing": _missing_payload(missing),
                }))
            try:
                merged_body = rehydrate(merged_body, normalized, missing)
            except RehydrationError as exc:
                raise ToolError(json.dumps({
                    "code": "ELICITATION_INVALID_RESPONSE",
                    "message": f"Elicited data conflicts with request structure: {exc}",
                    "reason": "rehydration_error",
                    "missing": _missing_payload(missing),
                }))
            still_missing = find_missing_fields(merged_body)
            if still_missing:
                raise ToolError(json.dumps({
                    "code": "INCOMPLETE_SHIPMENT",
                    "message": "Still missing required fields after elicitation",
                    "reason": "still_missing",
                    "missing": _missing_payload(still_missing),
                }))
            return _send_to_ups(merged_body)

        elif result.action == "decline":
            raise ToolError(json.dumps({
                "code": "ELICITATION_DECLINED",
                "message": "User declined to provide missing shipment fields",
                "reason": "declined",
                "missing": _missing_payload(missing),
            }))

        else:  # cancel
            raise ToolError(json.dumps({
                "code": "ELICITATION_CANCELLED",
                "message": "User cancelled shipment field elicitation",
                "reason": "cancelled",
                "missing": _missing_payload(missing),
            }))

    # 5. No form elicitation — structured ToolError for agent fallback
    raise ToolError(json.dumps({
        "code": "ELICITATION_UNSUPPORTED",
        "message": f"Missing {len(missing)} required field(s) and client does not support form elicitation",
        "reason": "unsupported",
        "missing": _missing_payload(missing),
    }))

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
