from __future__ import annotations

from typing import Any

from mcp.server.fastmcp.exceptions import ToolError

from .authorization import OAuthManager
from .http_client import UPSHTTPClient
from .openapi_registry import OpenAPIRegistry, OperationSpec, load_default_registry

RATE_OPERATION_ID = "Rate"
SHIPMENT_OPERATION_ID = "Shipment"
VOID_SHIPMENT_OPERATION_ID = "VoidShipment"
LABEL_RECOVERY_OPERATION_ID = "LabelRecovery"
TIME_IN_TRANSIT_OPERATION_ID = "TimeInTransit"

RATE_REQUEST_OPTIONS = {
    "rate": "Rate",
    "shop": "Shop",
    "ratetimeintransit": "Ratetimeintransit",
    "shoptimeintransit": "Shoptimeintransit",
}

TRACK_OPERATION = OperationSpec(
    source_file="legacy",
    operation_id="TrackPackage",
    method="GET",
    path="/track/v1/details/{inquiryNum}",
    deprecated=False,
    summary="Track package",
    request_body_required=False,
    request_body_schema=None,
    response_schemas={},
    path_params=(),
    query_params=(),
    header_params=(),
)

ADDRESS_VALIDATION_OPERATION = OperationSpec(
    source_file="legacy",
    operation_id="ValidateAddress",
    method="POST",
    path="/addressvalidation/v1/1",
    deprecated=False,
    summary="Validate address",
    request_body_required=True,
    request_body_schema=None,
    response_schemas={},
    path_params=(),
    query_params=(),
    header_params=(),
)


class ToolManager:
    def __init__(
        self,
        base_url: str,
        client_id: str | None,
        client_secret: str | None,
        registry: OpenAPIRegistry | None = None,
    ) -> None:
        self.base_url = base_url
        self.token_manager = OAuthManager(
            token_url=f"{self.base_url}/security/v1/oauth/token",
            client_id=client_id,
            client_secret=client_secret,
        )
        self.registry = registry or load_default_registry()
        self.http_client = UPSHTTPClient(base_url=self.base_url, oauth_manager=self.token_manager)

    def track_package(
        self,
        inquiryNum: str,
        locale: str,
        returnSignature: bool,
        returnMilestones: bool,
        returnPOD: bool,
        trans_id: str | None = None,
        transaction_src: str = "ups-mcp",
    ) -> dict[str, Any]:
        return self.http_client.call_operation(
            TRACK_OPERATION,
            operation_name="track_package",
            path_params={"inquiryNum": inquiryNum},
            query_params={
                "locale": locale,
                "returnSignature": returnSignature,
                "returnMilestones": returnMilestones,
                "returnPOD": returnPOD,
            },
            json_body=None,
            trans_id=trans_id,
            transaction_src=transaction_src,
        )

    def validate_address(
        self,
        addressLine1: str,
        addressLine2: str,
        politicalDivision1: str,
        politicalDivision2: str,
        zipPrimary: str,
        zipExtended: str,
        urbanization: str,
        countryCode: str,
        trans_id: str | None = None,
        transaction_src: str = "ups-mcp",
    ) -> dict[str, Any]:
        address_line_list = [addressLine1]
        if addressLine2:
            address_line_list.append(addressLine2)

        address_key_format: dict[str, Any] = {
            "AddressLine": address_line_list,
            "PoliticalDivision2": politicalDivision2,
            "PoliticalDivision1": politicalDivision1,
            "PostcodePrimaryLow": zipPrimary,
            "CountryCode": countryCode,
        }
        if urbanization:
            address_key_format["Urbanization"] = urbanization
        if zipExtended:
            address_key_format["PostcodeExtendedLow"] = zipExtended

        address_payload = {"XAVRequest": {"AddressKeyFormat": address_key_format}}
        return self.http_client.call_operation(
            ADDRESS_VALIDATION_OPERATION,
            operation_name="validate_address",
            path_params={},
            query_params={
                "regionalrequestindicator": False,
                "maximumcandidatelistsize": 3,
            },
            json_body=address_payload,
            trans_id=trans_id,
            transaction_src=transaction_src,
        )

    def rate_shipment(
        self,
        requestoption: str,
        request_body: dict[str, Any],
        version: str = "v2409",
        additionalinfo: str | None = None,
        trans_id: str | None = None,
        transaction_src: str = "ups-mcp",
    ) -> dict[str, Any]:
        normalized_option = RATE_REQUEST_OPTIONS.get(str(requestoption).lower())
        if not normalized_option:
            allowed = ", ".join(sorted(RATE_REQUEST_OPTIONS.values()))
            raise ToolError(f"Invalid requestoption '{requestoption}'. Allowed values: {allowed}")
        if not isinstance(request_body, dict):
            raise ToolError("request_body must be a JSON object")

        return self._execute_operation(
            operation_id=RATE_OPERATION_ID,
            operation_name="rate_shipment",
            path_params={"version": version, "requestoption": normalized_option},
            query_params={"additionalinfo": additionalinfo},
            request_body=request_body,
            trans_id=trans_id,
            transaction_src=transaction_src,
        )

    def create_shipment(
        self,
        request_body: dict[str, Any],
        version: str = "v2409",
        additionaladdressvalidation: str | None = None,
        trans_id: str | None = None,
        transaction_src: str = "ups-mcp",
    ) -> dict[str, Any]:
        if not isinstance(request_body, dict):
            raise ToolError("request_body must be a JSON object")
        return self._execute_operation(
            operation_id=SHIPMENT_OPERATION_ID,
            operation_name="create_shipment",
            path_params={"version": version},
            query_params={"additionaladdressvalidation": additionaladdressvalidation},
            request_body=request_body,
            trans_id=trans_id,
            transaction_src=transaction_src,
        )

    def void_shipment(
        self,
        shipmentidentificationnumber: str,
        version: str = "v2409",
        trackingnumber: str | list[str] | None = None,
        trans_id: str | None = None,
        transaction_src: str = "ups-mcp",
    ) -> dict[str, Any]:
        query_tracking_number: str | list[str] | None = None
        if trackingnumber is not None:
            if isinstance(trackingnumber, str):
                query_tracking_number = trackingnumber
            elif isinstance(trackingnumber, list) and all(isinstance(item, str) for item in trackingnumber):
                query_tracking_number = trackingnumber
            else:
                raise ToolError("trackingnumber must be a string or a list of strings")

        return self._execute_operation(
            operation_id=VOID_SHIPMENT_OPERATION_ID,
            operation_name="void_shipment",
            path_params={
                "version": version,
                "shipmentidentificationnumber": shipmentidentificationnumber,
            },
            query_params={"trackingnumber": query_tracking_number},
            request_body=None,
            trans_id=trans_id,
            transaction_src=transaction_src,
        )

    def recover_label(
        self,
        request_body: dict[str, Any],
        version: str = "v1",
        trans_id: str | None = None,
        transaction_src: str = "ups-mcp",
    ) -> dict[str, Any]:
        if not isinstance(request_body, dict):
            raise ToolError("request_body must be a JSON object")
        return self._execute_operation(
            operation_id=LABEL_RECOVERY_OPERATION_ID,
            operation_name="recover_label",
            path_params={"version": version},
            query_params={},
            request_body=request_body,
            trans_id=trans_id,
            transaction_src=transaction_src,
        )

    def get_time_in_transit(
        self,
        request_body: dict[str, Any],
        version: str = "v1",
        trans_id: str | None = None,
        transaction_src: str = "ups-mcp",
    ) -> dict[str, Any]:
        if not isinstance(request_body, dict):
            raise ToolError("request_body must be a JSON object")
        return self._execute_operation(
            operation_id=TIME_IN_TRANSIT_OPERATION_ID,
            operation_name="get_time_in_transit",
            path_params={"version": version},
            query_params={},
            request_body=request_body,
            trans_id=trans_id,
            transaction_src=transaction_src,
        )

    def _execute_operation(
        self,
        *,
        operation_id: str,
        operation_name: str,
        path_params: dict[str, Any],
        query_params: dict[str, Any] | None,
        request_body: dict[str, Any] | None,
        trans_id: str | None,
        transaction_src: str,
    ) -> dict[str, Any]:
        try:
            operation = self.registry.get_operation(operation_id)
        except KeyError as exc:
            raise ToolError(str(exc))

        if operation.deprecated:
            raise ToolError(f"Operation is deprecated and not exposed: {operation.operation_id}")

        resolved_path_params = dict(operation.default_path_values())
        resolved_path_params.update(path_params)
        if operation.request_body_required and request_body is None:
            raise ToolError(f"request_body is required for operation {operation.operation_id}")

        if request_body is not None and operation.request_body_schema:
            validation_errors = self.registry.validate_request_body(operation_id, request_body)
            if validation_errors:
                raise ToolError(
                    f"request_body validation failed for {operation.operation_id}: "
                    + "; ".join(validation_errors[:25])
                )

        return self.http_client.call_operation(
            operation,
            operation_name=operation_name,
            path_params=resolved_path_params,
            query_params=query_params,
            json_body=request_body,
            trans_id=trans_id,
            transaction_src=transaction_src,
        )
