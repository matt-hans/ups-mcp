# UPS MCP Server
A Model Context Protocol (MCP) server for UPS shipping and logistics capabilities. This server enables AI systems to seamlessly integrate with UPS API tools. 

Users can integrate with the MCP server to allow AI agents to facilitate tracking events on their behalf, including tracking the status of a shipment, the latest transit screen, and expected delivery date and time. Agents will be authenticated using OAuth client credentials provided by the user after application creation on the UPS Developer Portal.  

## Usage
**Prerequisites**
- Obtain a Client ID and Client Secret: Create an application on the UPS Developer Portal to obtain your OAuth credentials – Client ID and Client Secret. (https://developer.ups.com/get-started?loc=en_US)
- Python 3.12 or higher
- Install uv (Python Package)

**Environment Variables**
- ```CLIENT_ID``` - UPS Client ID
- ```CLIENT_SECRET``` - UPS Client Secret
- ```ENVIRONMENT``` - Whether to point to Test (CIE) or Production (Accepted values: test, production)
- ```UPS_ACCOUNT_NUMBER``` - UPS Account/Shipper Number (used for Paperless, Landed Cost, and Pickup tools). Optional — can also be provided per-call.
- ```UPS_MCP_SPECS_DIR``` - Optional absolute path to a directory containing OpenAPI spec overrides. Required files: `Rating.yaml`, `Shipping.yaml`, `TimeInTransit.yaml`. Optional files: `LandedCost.yaml`, `Paperless.yaml`, `Locator.yaml`, `Pickup.yaml` — if absent, the corresponding tools are unavailable. If set, this override is used instead of bundled package specs.

**Note**: Your API credentials are sensitive. Do not commit them to version control. We recommend managing secrets securely using GitHub Secrets, a vault, or a password manager.

**Execution**

You can run the package using uvx:

```uvx --from git+https://github.com/UPS-API/ups-mcp ups-mcp```

To use an older version, you can specify the version number like so:

```uvx --from git+https://github.com/UPS-API/ups-mcp@v1.0.0 ups-mcp```

## Popular Integrations
Here are sample config files for popular integrations. Different MCP Clients may require modification.

### Claude Desktop
```json
{
  "mcpServers": {
    "ups-mcp": {
      "type": "stdio",
      "command": "uvx",
      "args": ["--from", "git+https://github.com/UPS-API/ups-mcp", "ups-mcp"],
      "env": {
        "CLIENT_ID": "**********",
        "CLIENT_SECRET": "**********",
        "ENVIRONMENT": "test"
      }
    }
  }
}
```

### GitHub Copilot in VS Code
```json
{
  "servers": {
    "ups-mcp": {
      "type": "stdio",
      "command": "uvx",
      "args": ["--from", "git+https://github.com/UPS-API/ups-mcp", "ups-mcp"],
      "env": {
        "CLIENT_ID": "**********",
        "CLIENT_SECRET": "**********",
        "ENVIRONMENT": "test"
      }
    }
  }
}
```

## Available Tools

- ```track_package```: Track a package using the UPS Tracking API
    
    Args:
     - inquiryNumber (str): the unique package identifier. Each inquiry number must be between 7 and 34 characters in length. Required.
    - locale (str): Language and country code of the user, separated by an underscore. Default value is 'en_US'. Not required.
    - returnSignature (bool): a boolean to indicate whether a signature is required, default is false. Not required.
    - returnMilestones (bool): a boolean to indicate whether detailed information on a package's movements is required, default is false. Not required
    - returnPOD (bool): a boolean to indicate whether a proof of delivery is required, default is false. Not required

    Returns:
    - dict: Raw UPS Track API response.
- ```validate_address```: Validate an address using the UPS Address Validation API for the U.S. or Puerto Rico

    Args:
     - addressLine1 (str): The primary address details including the house or building number and the street name, e.g. 123 Main St. Required.
     - addressLine2 (str): Additional information like apartment or suite numbers, e.g. Apt 4B. Not required.
    - politicalDivision1 (str): The two-letter state or province code, e.g. GA for Georgia. Required.
    - politicalDivision2 (str): The city or town name, e.g. Springfield. Required.
    - zipPrimary (str): The postal code. Required.
    - zipExtended (str): 4 digit Postal Code extension. For US use only. Not required.
    - urbanization (str): Puerto Rico Political Division 3. Only valid for Puerto Rico. Not required.
    - countryCode (str): The country code, e.g. US. Required.

    Returns:
    - dict: Raw UPS Address Validation response.

- `rate_shipment`: Rate or shop a shipment via `POST /rating/{version}/{requestoption}`
  - Args:
    - `requestoption` (str, required): `Rate`, `Shop`, `Ratetimeintransit`, `Shoptimeintransit`
    - `request_body` (object, required): JSON body matching `RATERequestWrapper`
    - `version` (str, optional, default `v2409`)
    - `additionalinfo` (str, optional)
    - `trans_id` (str, optional)
    - `transaction_src` (str, optional, default `ups-mcp`)

- `create_shipment`: Create a shipment via `POST /shipments/{version}/ship`
  - Args:
    - `request_body` (object, required): JSON body matching `SHIPRequestWrapper`
    - `version` (str, optional, default `v2409`)
    - `additionaladdressvalidation` (str, optional)
    - `trans_id` (str, optional)
    - `transaction_src` (str, optional, default `ups-mcp`)

- `void_shipment`: Void a shipment via `DELETE /shipments/{version}/void/cancel/{shipmentidentificationnumber}`
  - Args:
    - `shipmentidentificationnumber` (str, required)
    - `version` (str, optional, default `v2409`)
    - `trackingnumber` (str | list[str], optional)
    - `trans_id` (str, optional)
    - `transaction_src` (str, optional, default `ups-mcp`)

- `recover_label`: Recover a label via `POST /labels/{version}/recovery`
  - Args:
    - `request_body` (object, required): JSON body matching `LABELRECOVERYRequestWrapper`
    - `version` (str, optional, default `v1`)
    - `trans_id` (str, optional)
    - `transaction_src` (str, optional, default `ups-mcp`)

- `get_time_in_transit`: Get transit-time estimates via `POST /shipments/{version}/transittimes`
  - Args:
    - `request_body` (object, required): JSON body matching `TimeInTransitRequest`
    - `version` (str, optional, default `v1`)
    - `trans_id` (str, optional)
    - `transaction_src` (str, optional, default `ups-mcp`)

- `get_landed_cost_quote`: Get landed cost quote for international shipments via `POST /landedcost/v1/quotes`
  - Args:
    - `currency_code` (str, required): ISO currency code (e.g. USD, EUR)
    - `export_country_code` (str, required): ISO country code of origin
    - `import_country_code` (str, required): ISO country code of destination
    - `commodities` (list[dict], required): List of commodity dicts with `price`, `quantity`, and optional `hs_code`, `description`, `weight`, `weight_unit`
    - `shipment_type` (str, optional, default `Sale`)
    - `account_number` (str, optional): Falls back to `UPS_ACCOUNT_NUMBER`

- `upload_paperless_document`: Upload a paperless document via `POST /paperlessdocuments/v2/upload`
  - Args:
    - `file_content_base64` (str, required): Base64-encoded file content
    - `file_name` (str, required): Original file name
    - `file_format` (str, required): One of `pdf`, `doc`, `docx`, `xls`, `xlsx`, `txt`, `rtf`, `tif`, `jpg`
    - `document_type` (str, required): UPS document type code (e.g. `002` for invoice)
    - `shipper_number` (str, optional): Falls back to `UPS_ACCOUNT_NUMBER`

- `push_document_to_shipment`: Push an uploaded document to a shipment via `POST /paperlessdocuments/v2/image`
  - Args:
    - `document_id` (str, required): Document ID from a prior upload
    - `shipment_identifier` (str, required): UPS tracking number (1Z...)
    - `shipment_type` (str, optional, default `1`): `1` for forward, `2` for return
    - `shipper_number` (str, optional): Falls back to `UPS_ACCOUNT_NUMBER`

- `delete_paperless_document`: Delete a paperless document via `DELETE /paperlessdocuments/{version}/DocumentId/ShipperNumber`
  - Args:
    - `document_id` (str, required)
    - `shipper_number` (str, optional): Falls back to `UPS_ACCOUNT_NUMBER`

- `find_locations`: Find UPS locations near an address via `POST /locations/v3/search/availabilities/{reqOption}`
  - Args:
    - `location_type` (str, required): `access_point`, `retail`, `general`, or `services`
    - `address_line` (str, required), `city` (str, required), `state` (str, required), `postal_code` (str, required), `country_code` (str, required)
    - `radius` (float, optional, default `15.0`)
    - `unit_of_measure` (str, optional, default `MI`): `MI` or `KM`

- `rate_pickup`: Get pickup rate estimate via `POST /shipments/{version}/pickup/{pickuptype}`
  - Args:
    - `pickup_type` (str, required): `oncall`, `smart`, or `both`
    - `address_line`, `city`, `state`, `postal_code`, `country_code` (str, required)
    - `pickup_date` (str, required): YYYYMMDD format
    - `ready_time` (str, required): HHMM 24hr format
    - `close_time` (str, required): HHMM 24hr format
    - `service_date_option` (str, optional, default `02`)
    - `residential_indicator` (str, optional, default `Y`): `Y` or `N`

- `schedule_pickup`: Schedule a pickup via `POST /pickupcreation/{version}/pickup`
  - Args:
    - `pickup_date`, `ready_time`, `close_time` (str, required)
    - `address_line`, `city`, `state`, `postal_code`, `country_code` (str, required)
    - `contact_name` (str, required), `phone_number` (str, required)
    - `payment_method` (str, optional, default `01`): `01` = shipper account, `00` = no payment
    - `account_number` (str, optional): Falls back to `UPS_ACCOUNT_NUMBER`. Required when `payment_method=01`.

- `cancel_pickup`: Cancel a scheduled pickup via `DELETE /shipments/{version}/pickup/{CancelBy}`
  - Args:
    - `cancel_by` (str, required): `account` or `prn`
    - `prn` (str): Required when `cancel_by=prn`

- `get_pickup_status`: Get pending pickup status via `GET /shipments/{version}/pickup/{pickuptype}`
  - Args:
    - `pickup_type` (str, required): `oncall`, `smart`, or `both`
    - `account_number` (str, optional): Falls back to `UPS_ACCOUNT_NUMBER`

- `get_political_divisions`: Get states/provinces for a country via `GET /pickup/{version}/countries/{countrycode}`
  - Args:
    - `country_code` (str, required): ISO country code

- `get_service_center_facilities`: Get UPS service center facilities via `POST /pickup/{version}/servicecenterlocations`
  - Args:
    - `city`, `state`, `postal_code`, `country_code` (str, required)
    - `pickup_pieces` (int, optional, default `1`)
    - `container_code` (str, optional, default `03`)

### Response Format

All tools return raw UPS API response dicts on success. On failure, tools raise `ToolError` with a JSON payload containing `status_code`, `code`, `message`, and `details`.

### Notes

- Deprecated endpoints defined in the OpenAPI specs are intentionally not exposed as MCP tools.
- OpenAPI specs are used for operation discovery and path routing only — not for request/response schema validation.
