from typing import Any
from mcp.server.fastmcp import FastMCP
from dotenv import load_dotenv
import os
from . import tools
from . import constants

# Initialize FastMCP server
mcp = FastMCP("ups-mcp")

# Initialize tool manager
load_dotenv()
if os.getenv("ENVIRONMENT") == "production":
    base_url = constants.PRODUCTION_URL
else:
    base_url = constants.CIE_URL

client_id = os.getenv("CLIENT_ID")
client_secret = os.getenv("CLIENT_SECRET")

tool_manager = tools.ToolManager(base_url=base_url, client_id=client_id, client_secret=client_secret)

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
    tracking_data = tool_manager.track_package(
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
    validation_data = tool_manager.validate_address(
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
    return tool_manager.rate_shipment(
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
) -> dict[str, Any]:
    """
    Create a shipment using UPS Shipping API (`POST /shipments/{version}/ship`).

    Args:
        request_body (dict): JSON object matching `SHIPRequestWrapper`.
            Minimum practical shape:
            - ShipmentRequest.Request
            - ShipmentRequest.Shipment.Shipper
            - ShipmentRequest.Shipment.ShipTo
            - ShipmentRequest.Shipment.ShipFrom
            - ShipmentRequest.Shipment.Service
            - ShipmentRequest.Shipment.Package
        version (str): API version. Default `v2409`.
        additionaladdressvalidation (str): Optional query param (for example `city`).
        trans_id (str): Optional request id.
        transaction_src (str): Optional caller source name. Default `ups-mcp`.

    Returns:
        dict[str, Any]: Raw UPS API response payload. On error, raises ToolError.
    """
    return tool_manager.create_shipment(
        request_body=request_body,
        version=version,
        additionaladdressvalidation=additionaladdressvalidation or None,
        trans_id=trans_id or None,
        transaction_src=transaction_src,
    )

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
    return tool_manager.void_shipment(
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
    return tool_manager.recover_label(
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
    return tool_manager.get_time_in_transit(
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
    _validate_runtime_configuration()
    try:
        mcp.run(transport='stdio')
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    main()
