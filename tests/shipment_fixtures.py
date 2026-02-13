def make_complete_body(
    shipper_country: str = "US",
    ship_to_country: str = "US",
    num_packages: int = 1,
) -> dict:
    """Return a minimal-but-complete ShipmentRequest body.

    Package is always returned as a list for internal consistency.
    """
    packages = []
    for _ in range(num_packages):
        packages.append({
            "Packaging": {"Code": "02"},
            "PackageWeight": {
                "UnitOfMeasurement": {"Code": "LBS"},
                "Weight": "5",
            },
        })
    body = {
        "ShipmentRequest": {
            "Request": {"RequestOption": "nonvalidate"},
            "Shipment": {
                "Shipper": {
                    "Name": "Test Shipper",
                    "ShipperNumber": "129D9Y",
                    "Address": {
                        "AddressLine": ["123 Main St"],
                        "City": "Timonium",
                        "StateProvinceCode": "MD",
                        "PostalCode": "21093",
                        "CountryCode": shipper_country,
                    },
                },
                "ShipTo": {
                    "Name": "Test Recipient",
                    "Address": {
                        "AddressLine": ["456 Oak Ave"],
                        "City": "New York",
                        "StateProvinceCode": "NY",
                        "PostalCode": "10001",
                        "CountryCode": ship_to_country,
                    },
                },
                "PaymentInformation": {
                    "ShipmentCharge": [{
                        "Type": "01",
                        "BillShipper": {"AccountNumber": "129D9Y"},
                    }],
                },
                "Service": {"Code": "03"},
                "Package": packages,
            },
        }
    }
    return body
