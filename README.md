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
- ```UPS_MCP_SPECS_DIR``` - Optional absolute path to a directory containing `Rating.yaml`, `Shipping.yaml`, and `TimeInTransit.yaml`. If set, this override is used before bundled package specs.

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
    - dict: Structured response envelope with keys `ok`, `status_code`, `data`, `error`, etc.
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
    - dict: Structured response envelope with keys `ok`, `status_code`, `data`, `error`, etc.

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

### Structured Response Envelope

All tools return this shape:

```json
{
  "ok": true,
  "operation": "create_shipment",
  "status_code": 200,
  "trans_id": "f8b2f32d-5cde-4474-bbe3-bec6900f4ab8",
  "request": {
    "method": "POST",
    "path": "/shipments/v2409/ship",
    "query": {
      "additionaladdressvalidation": "city"
    }
  },
  "data": {},
  "error": null
}
```

For failed calls:
- `ok` is `false`
- `data` is `null`
- `error` contains `code`, `message`, and `details`

### Notes

- Deprecated endpoints defined in the OpenAPI specs are intentionally not exposed as MCP tools.
- Request bodies for spec-backed tools are validated against OpenAPI schemas before calling UPS.
