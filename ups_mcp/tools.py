from __future__ import annotations

import uuid
from typing import Any

from mcp.server.fastmcp.exceptions import ToolError

from . import constants
from .authorization import OAuthManager
from .http_client import UPSHTTPClient
from .openapi_registry import OpenAPIRegistry, OperationSpec, load_default_registry

RATE_OPERATION_ID = "Rate"
SHIPMENT_OPERATION_ID = "Shipment"
VOID_SHIPMENT_OPERATION_ID = "VoidShipment"
LABEL_RECOVERY_OPERATION_ID = "LabelRecovery"
TIME_IN_TRANSIT_OPERATION_ID = "TimeInTransit"

LANDED_COST_OPERATION_ID = "LandedCost"
LOCATOR_OPERATION_ID = "Locator"
PICKUP_RATE_OPERATION_ID = "Pickup Rate"
PICKUP_PENDING_STATUS_OPERATION_ID = "Pickup Pending Status"
PICKUP_CANCEL_OPERATION_ID = "Pickup Cancel"
PICKUP_CREATION_OPERATION_ID = "Pickup Creation"
PICKUP_POLITICAL_DIVISIONS_OPERATION_ID = "Pickup Get Political Division1 List"
PICKUP_SERVICE_CENTER_OPERATION_ID = "Pickup Get Service Center Facilities"
PAPERLESS_UPLOAD_OPERATION_ID = "Upload"
PAPERLESS_PUSH_OPERATION_ID = "PushToImageRepository"
PAPERLESS_DELETE_OPERATION_ID = "Delete"

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
        account_number: str | None = None,
        registry: OpenAPIRegistry | None = None,
    ) -> None:
        self.base_url = base_url
        self.account_number = account_number
        self.token_manager = OAuthManager(
            token_url=f"{self.base_url}/security/v1/oauth/token",
            client_id=client_id,
            client_secret=client_secret,
        )
        self.registry = registry or load_default_registry()
        self.http_client = UPSHTTPClient(base_url=self.base_url, oauth_manager=self.token_manager)

    def _resolve_account(self, explicit: str | None = None) -> str | None:
        """Resolve account number: explicit arg > self.account_number > None."""
        return explicit or self.account_number

    def _require_account(self, explicit: str | None = None, header_name: str = "AccountNumber") -> str:
        """Resolve account number or raise ToolError if unavailable."""
        resolved = self._resolve_account(explicit)
        if not resolved:
            raise ToolError(f"{header_name} is required via argument or UPS_ACCOUNT_NUMBER env var")
        return resolved

    @staticmethod
    def _build_transaction_ref(context: str = "ups-mcp") -> dict[str, Any]:
        """Build the standard TransactionReference object."""
        return {"TransactionReference": {"CustomerContext": context}}

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

    def get_landed_cost_quote(
        self,
        currency_code: str,
        export_country_code: str,
        import_country_code: str,
        commodities: list[dict[str, Any]],
        shipment_type: str = "Sale",
        account_number: str | None = None,
        trans_id: str | None = None,
        transaction_src: str = "ups-mcp",
    ) -> dict[str, Any]:
        effective_account = self._resolve_account(account_number)

        shipment_items = []
        for idx, item in enumerate(commodities):
            if "price" not in item:
                raise ToolError(f"Commodity at index {idx} missing required key 'price'")
            if "quantity" not in item:
                raise ToolError(f"Commodity at index {idx} missing required key 'quantity'")

            ups_item: dict[str, Any] = {
                "commodityId": str(idx + 1),
                "priceEach": str(item["price"]),
                "quantity": int(item["quantity"]),
                "commodityCurrencyCode": currency_code,
                "originCountryCode": export_country_code,
                "UOM": item.get("uom", "EA"),
                "hsCode": item.get("hs_code", ""),
                "description": item.get("description", ""),
            }
            if "weight" in item and "weight_unit" in item:
                ups_item["grossWeight"] = str(item["weight"])
                ups_item["grossWeightUnit"] = item["weight_unit"]
            shipment_items.append(ups_item)

        request_body = {
            "LandedCostRequest": {
                "currencyCode": currency_code,
                "transID": str(uuid.uuid4()),
                "allowPartialLandedCostResult": True,
                "alversion": 1,
                "shipment": {
                    "id": str(uuid.uuid4()),
                    "importCountryCode": import_country_code,
                    "exportCountryCode": export_country_code,
                    "shipmentItems": shipment_items,
                    "shipmentType": shipment_type,
                },
            }
        }

        return self._execute_operation(
            operation_id=LANDED_COST_OPERATION_ID,
            operation_name="get_landed_cost_quote",
            path_params={"version": "v1"},
            query_params=None,
            request_body=request_body,
            trans_id=trans_id,
            transaction_src=transaction_src,
            additional_headers={"AccountNumber": effective_account} if effective_account else None,
        )

    def upload_paperless_document(
        self,
        file_content_base64: str,
        file_name: str,
        file_format: str,
        document_type: str,
        shipper_number: str | None = None,
        trans_id: str | None = None,
        transaction_src: str = "ups-mcp",
    ) -> dict[str, Any]:
        effective_shipper = self._require_account(shipper_number, "ShipperNumber")
        normalized_format = file_format.lower()
        if normalized_format not in constants.PAPERLESS_VALID_FORMATS:
            raise ToolError(
                f"Invalid file_format '{file_format}'. "
                f"Supported: {', '.join(sorted(constants.PAPERLESS_VALID_FORMATS))}"
            )

        request_body = {
            "UploadRequest": {
                "Request": self._build_transaction_ref(transaction_src),
                "ShipperNumber": effective_shipper,
                "UserCreatedForm": [{
                    "UserCreatedFormFileName": file_name,
                    "UserCreatedFormFileFormat": normalized_format,
                    "UserCreatedFormDocumentType": document_type,
                    "UserCreatedFormFile": file_content_base64,
                }],
            }
        }
        return self._execute_operation(
            operation_id=PAPERLESS_UPLOAD_OPERATION_ID,
            operation_name="upload_paperless_document",
            path_params={"version": "v2"},
            query_params=None, request_body=request_body,
            trans_id=trans_id, transaction_src=transaction_src,
            additional_headers={"ShipperNumber": effective_shipper},
        )

    def push_document_to_shipment(
        self,
        document_id: str,
        shipment_identifier: str,
        shipment_type: str = "1",
        shipper_number: str | None = None,
        trans_id: str | None = None,
        transaction_src: str = "ups-mcp",
    ) -> dict[str, Any]:
        effective_shipper = self._require_account(shipper_number, "ShipperNumber")
        request_body = {
            "PushToImageRepositoryRequest": {
                "Request": self._build_transaction_ref(transaction_src),
                "ShipperNumber": effective_shipper,
                "FormsHistoryDocumentID": {"DocumentID": [document_id]},
                "ShipmentIdentifier": shipment_identifier,
                "ShipmentType": shipment_type,
            }
        }
        return self._execute_operation(
            operation_id=PAPERLESS_PUSH_OPERATION_ID,
            operation_name="push_document_to_shipment",
            path_params={"version": "v2"},
            query_params=None, request_body=request_body,
            trans_id=trans_id, transaction_src=transaction_src,
            additional_headers={"ShipperNumber": effective_shipper},
        )

    def delete_paperless_document(
        self,
        document_id: str,
        shipper_number: str | None = None,
        trans_id: str | None = None,
        transaction_src: str = "ups-mcp",
    ) -> dict[str, Any]:
        effective_shipper = self._require_account(shipper_number, "ShipperNumber")
        return self._execute_operation(
            operation_id=PAPERLESS_DELETE_OPERATION_ID,
            operation_name="delete_paperless_document",
            path_params={"version": "v2"},
            query_params=None, request_body=None,
            trans_id=trans_id, transaction_src=transaction_src,
            additional_headers={"ShipperNumber": effective_shipper, "DocumentId": document_id},
        )

    def find_locations(
        self,
        location_type: str,
        address_line: str,
        city: str,
        state: str,
        postal_code: str,
        country_code: str,
        radius: float = 15.0,
        unit_of_measure: str = "MI",
        trans_id: str | None = None,
        transaction_src: str = "ups-mcp",
    ) -> dict[str, Any]:
        req_option = constants.LOCATOR_OPTIONS.get(location_type)
        if not req_option:
            allowed = ", ".join(sorted(constants.LOCATOR_OPTIONS.keys()))
            raise ToolError(f"Invalid location_type '{location_type}'. Must be one of: {allowed}")

        search_criteria: dict[str, Any] = {"SearchRadius": str(radius)}
        if req_option == "64":
            search_criteria["AccessPointSearch"] = {"AccessPointStatus": "01"}

        request_body = {
            "LocatorRequest": {
                "Request": {"RequestAction": "Locator"},
                "OriginAddress": {
                    "AddressKeyFormat": {
                        "AddressLine": address_line,
                        "PoliticalDivision2": city,
                        "PoliticalDivision1": state,
                        "PostcodePrimaryLow": postal_code,
                        "CountryCode": country_code,
                    }
                },
                "Translate": {"Locale": "en_US"},
                "UnitOfMeasurement": {"Code": unit_of_measure},
                "LocationSearchCriteria": search_criteria,
            }
        }

        return self._execute_operation(
            operation_id=LOCATOR_OPERATION_ID,
            operation_name="find_locations",
            path_params={"version": "v3", "reqOption": req_option},
            query_params=None, request_body=request_body,
            trans_id=trans_id, transaction_src=transaction_src,
        )

    def rate_pickup(
        self,
        pickup_type: str,
        address_line: str,
        city: str,
        state: str,
        postal_code: str,
        country_code: str,
        pickup_date: str,
        ready_time: str,
        close_time: str,
        service_date_option: str = "02",
        residential_indicator: str = "Y",
        service_code: str = "001",
        container_code: str = "01",
        quantity: int = 1,
        destination_country_code: str = "US",
        trans_id: str | None = None,
        transaction_src: str = "ups-mcp",
    ) -> dict[str, Any]:
        request_body = {
            "PickupRateRequest": {
                "Request": self._build_transaction_ref(transaction_src),
                "ServiceDateOption": service_date_option,
                "AlternateAddressIndicator": "N",
                "PickupAddress": {
                    "AddressLine": address_line,
                    "City": city,
                    "StateProvince": state,
                    "PostalCode": postal_code,
                    "CountryCode": country_code,
                    "ResidentialIndicator": residential_indicator,
                },
                "PickupDateInfo": {
                    "PickupDate": pickup_date,
                    "ReadyTime": ready_time,
                    "CloseTime": close_time,
                },
                "PickupPiece": [{
                    "ServiceCode": service_code,
                    "Quantity": str(quantity),
                    "DestinationCountryCode": destination_country_code,
                    "ContainerCode": container_code,
                }],
            }
        }
        return self._execute_operation(
            operation_id=PICKUP_RATE_OPERATION_ID,
            operation_name="rate_pickup",
            path_params={"version": "v2409", "pickuptype": pickup_type},
            query_params=None, request_body=request_body,
            trans_id=trans_id, transaction_src=transaction_src,
        )

    def schedule_pickup(
        self,
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
        residential_indicator: str = "N",
        service_code: str = "001",
        container_code: str = "01",
        quantity: int = 1,
        weight: float = 5.0,
        weight_unit: str = "LBS",
        payment_method: str = "01",
        rate_pickup_indicator: str = "N",
        account_number: str | None = None,
        trans_id: str | None = None,
        transaction_src: str = "ups-mcp",
    ) -> dict[str, Any]:
        if ready_time >= close_time:
            raise ToolError(f"ready_time ({ready_time}) must be before close_time ({close_time})")

        effective_account = self._resolve_account(account_number)

        # Spec: payment_method '01' (pay by shipper account) requires account number
        if payment_method == "01" and not effective_account:
            raise ToolError(
                "Account number is required when payment_method='01' (pay by shipper account). "
                "Provide account_number argument or set UPS_ACCOUNT_NUMBER env var."
            )

        creation_request: dict[str, Any] = {
            "Request": self._build_transaction_ref(transaction_src),
            "RatePickupIndicator": rate_pickup_indicator,
            "AlternateAddressIndicator": "N",
            "PaymentMethod": payment_method,
        }
        if effective_account:
            creation_request["Shipper"] = {
                "Account": {
                    "AccountNumber": effective_account,
                    "AccountCountryCode": country_code,
                },
            }

        creation_request["PickupDateInfo"] = {
            "CloseTime": close_time,
            "ReadyTime": ready_time,
            "PickupDate": pickup_date,
        }
        creation_request["PickupAddress"] = {
            "CompanyName": contact_name,
            "ContactName": contact_name,
            "AddressLine": address_line,
            "City": city,
            "StateProvince": state,
            "PostalCode": postal_code,
            "CountryCode": country_code,
            "ResidentialIndicator": residential_indicator,
            "Phone": {"Number": phone_number},
        }
        creation_request["PickupPiece"] = [{
            "ServiceCode": service_code,
            "Quantity": str(quantity),
            "DestinationCountryCode": country_code,
            "ContainerCode": container_code,
        }]
        creation_request["TotalWeight"] = {
            "Weight": str(weight),
            "UnitOfMeasurement": weight_unit,
        }

        request_body = {"PickupCreationRequest": creation_request}
        return self._execute_operation(
            operation_id=PICKUP_CREATION_OPERATION_ID,
            operation_name="schedule_pickup",
            path_params={"version": "v2409"},
            query_params=None, request_body=request_body,
            trans_id=trans_id, transaction_src=transaction_src,
        )

    def cancel_pickup(
        self,
        cancel_by: str,
        prn: str | None = None,
        trans_id: str | None = None,
        transaction_src: str = "ups-mcp",
    ) -> dict[str, Any]:
        cancel_code = constants.PICKUP_CANCEL_OPTIONS.get(cancel_by)
        if not cancel_code:
            allowed = ", ".join(sorted(constants.PICKUP_CANCEL_OPTIONS.keys()))
            raise ToolError(f"Invalid cancel_by '{cancel_by}'. Must be one of: {allowed}")

        additional_headers: dict[str, str] | None = None
        if cancel_by == "prn":
            if not prn:
                raise ToolError("prn is required when cancel_by='prn'")
            additional_headers = {"Prn": prn}

        return self._execute_operation(
            operation_id=PICKUP_CANCEL_OPERATION_ID,
            operation_name="cancel_pickup",
            path_params={"version": "v2409", "CancelBy": cancel_code},
            query_params=None, request_body=None,
            trans_id=trans_id, transaction_src=transaction_src,
            additional_headers=additional_headers,
        )

    def get_pickup_status(
        self,
        pickup_type: str,
        account_number: str | None = None,
        trans_id: str | None = None,
        transaction_src: str = "ups-mcp",
    ) -> dict[str, Any]:
        effective_account = self._require_account(account_number, "AccountNumber")
        return self._execute_operation(
            operation_id=PICKUP_PENDING_STATUS_OPERATION_ID,
            operation_name="get_pickup_status",
            path_params={"version": "v2409", "pickuptype": pickup_type},
            query_params=None, request_body=None,
            trans_id=trans_id, transaction_src=transaction_src,
            additional_headers={"AccountNumber": effective_account},
        )

    def get_political_divisions(
        self,
        country_code: str,
        trans_id: str | None = None,
        transaction_src: str = "ups-mcp",
    ) -> dict[str, Any]:
        return self._execute_operation(
            operation_id=PICKUP_POLITICAL_DIVISIONS_OPERATION_ID,
            operation_name="get_political_divisions",
            path_params={"version": "v2409", "countrycode": country_code},
            query_params=None, request_body=None,
            trans_id=trans_id, transaction_src=transaction_src,
        )

    def get_service_center_facilities(
        self,
        city: str,
        state: str,
        postal_code: str,
        country_code: str,
        pickup_pieces: int = 1,
        container_code: str = "01",
        trans_id: str | None = None,
        transaction_src: str = "ups-mcp",
    ) -> dict[str, Any]:
        request_body = {
            "PickupGetServiceCenterFacilitiesRequest": {
                "Request": self._build_transaction_ref(transaction_src),
                "PickupPiece": {
                    "ServiceCode": "001",
                    "Quantity": str(pickup_pieces),
                    "ContainerCode": container_code,
                },
                "DestinationAddress": {
                    "City": city,
                    "StateProvince": state,
                    "PostalCode": postal_code,
                    "CountryCode": country_code,
                },
            }
        }
        return self._execute_operation(
            operation_id=PICKUP_SERVICE_CENTER_OPERATION_ID,
            operation_name="get_service_center_facilities",
            path_params={"version": "v2409"},
            query_params=None, request_body=request_body,
            trans_id=trans_id, transaction_src=transaction_src,
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
        additional_headers: dict[str, str] | None = None,
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

        return self.http_client.call_operation(
            operation,
            operation_name=operation_name,
            path_params=resolved_path_params,
            query_params=query_params,
            json_body=request_body,
            trans_id=trans_id,
            transaction_src=transaction_src,
            additional_headers=additional_headers,
        )
