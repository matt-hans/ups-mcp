import unittest

from ups_mcp.openapi_registry import default_spec_paths, OpenAPIRegistry


class OpenAPIRegistryTests(unittest.TestCase):
    def test_registry_exposes_expected_non_deprecated_operations(self) -> None:
        registry = OpenAPIRegistry.from_spec_files(default_spec_paths())
        operations = registry.list_operations(include_deprecated=False)
        operation_ids = {operation.operation_id for operation in operations}

        self.assertEqual(
            operation_ids,
            {"Rate", "Shipment", "VoidShipment", "LabelRecovery", "TimeInTransit"},
        )
        self.assertEqual(len(operations), 5)
        self.assertTrue(all(not operation.deprecated for operation in operations))

    def test_deprecated_operations_exist_but_are_filtered(self) -> None:
        registry = OpenAPIRegistry.from_spec_files(default_spec_paths())
        all_operations = registry.list_operations(include_deprecated=True)
        deprecated_operations = [operation for operation in all_operations if operation.deprecated]

        self.assertGreaterEqual(len(deprecated_operations), 1)
        self.assertIn("Deprecated Rate", {operation.operation_id for operation in deprecated_operations})



if __name__ == "__main__":
    unittest.main()
