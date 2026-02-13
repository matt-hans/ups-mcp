import os
from pathlib import Path
import tempfile
import textwrap
import unittest

from ups_mcp.openapi_registry import OpenAPISpecLoadError, load_default_registry


class OpenAPIRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_specs_dir = os.environ.get("UPS_MCP_SPECS_DIR")
        load_default_registry.cache_clear()

    def tearDown(self) -> None:
        if self.original_specs_dir is None:
            os.environ.pop("UPS_MCP_SPECS_DIR", None)
        else:
            os.environ["UPS_MCP_SPECS_DIR"] = self.original_specs_dir
        load_default_registry.cache_clear()

    def test_registry_exposes_expected_non_deprecated_operations_from_bundled_specs(self) -> None:
        os.environ.pop("UPS_MCP_SPECS_DIR", None)
        registry = load_default_registry()
        operations = registry.list_operations(include_deprecated=False)
        operation_ids = {operation.operation_id for operation in operations}

        self.assertEqual(
            operation_ids,
            {"Rate", "Shipment", "VoidShipment", "LabelRecovery", "TimeInTransit"},
        )
        self.assertEqual(len(operations), 5)
        self.assertTrue(all(not operation.deprecated for operation in operations))

    def test_deprecated_operations_exist_but_are_filtered_in_bundled_specs(self) -> None:
        os.environ.pop("UPS_MCP_SPECS_DIR", None)
        registry = load_default_registry()
        all_operations = registry.list_operations(include_deprecated=True)
        deprecated_operations = [operation for operation in all_operations if operation.deprecated]

        self.assertGreaterEqual(len(deprecated_operations), 1)
        self.assertIn("Deprecated Rate", {operation.operation_id for operation in deprecated_operations})

    def test_registry_uses_override_specs_dir_when_configured(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            self._write_override_specs(Path(tmp_dir), rate_summary="Override Rate")
            os.environ["UPS_MCP_SPECS_DIR"] = tmp_dir
            load_default_registry.cache_clear()

            registry = load_default_registry()

        self.assertEqual(registry.get_operation("Rate").summary, "Override Rate")
        self.assertEqual(
            {operation.operation_id for operation in registry.list_operations(include_deprecated=False)},
            {"Rate", "Shipment", "VoidShipment", "LabelRecovery", "TimeInTransit"},
        )

    def test_incomplete_override_specs_dir_raises_actionable_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            self._write_override_specs(Path(tmp_dir), include_time_in_transit=False)
            os.environ["UPS_MCP_SPECS_DIR"] = tmp_dir
            load_default_registry.cache_clear()

            with self.assertRaises(OpenAPISpecLoadError) as ctx:
                load_default_registry()

        message = str(ctx.exception)
        self.assertIn("UPS_MCP_SPECS_DIR=", message)
        self.assertIn("TimeInTransit.yaml", message)

    def _write_override_specs(
        self,
        output_dir: Path,
        *,
        rate_summary: str = "Rate operation",
        include_time_in_transit: bool = True,
    ) -> None:
        (output_dir / "Rating.yaml").write_text(
            textwrap.dedent(
                f"""
                openapi: 3.0.1
                info:
                  title: Rating
                  version: 1.0.0
                paths:
                  /rating/{{version}}/{{requestoption}}:
                    post:
                      operationId: Rate
                      summary: {rate_summary}
                      parameters:
                        - in: path
                          name: version
                          required: true
                          schema:
                            type: string
                        - in: path
                          name: requestoption
                          required: true
                          schema:
                            type: string
                """
            ).strip()
            + "\n",
            encoding="utf-8",
        )
        (output_dir / "Shipping.yaml").write_text(
            textwrap.dedent(
                """
                openapi: 3.0.1
                info:
                  title: Shipping
                  version: 1.0.0
                paths:
                  /shipments/{version}/ship:
                    post:
                      operationId: Shipment
                      summary: Create shipment
                      parameters:
                        - in: path
                          name: version
                          required: true
                          schema:
                            type: string
                  /shipments/{version}/void/cancel/{shipmentidentificationnumber}:
                    delete:
                      operationId: VoidShipment
                      summary: Void shipment
                      parameters:
                        - in: path
                          name: version
                          required: true
                          schema:
                            type: string
                        - in: path
                          name: shipmentidentificationnumber
                          required: true
                          schema:
                            type: string
                  /labels/{version}/recovery:
                    post:
                      operationId: LabelRecovery
                      summary: Recover label
                      parameters:
                        - in: path
                          name: version
                          required: true
                          schema:
                            type: string
                """
            ).strip()
            + "\n",
            encoding="utf-8",
        )
        if include_time_in_transit:
            (output_dir / "TimeInTransit.yaml").write_text(
                textwrap.dedent(
                    """
                    openapi: 3.0.1
                    info:
                      title: TimeInTransit
                      version: 1.0.0
                    paths:
                      /shipments/{version}/transittimes:
                        post:
                          operationId: TimeInTransit
                          summary: Time in transit
                          parameters:
                            - in: path
                              name: version
                              required: true
                              schema:
                                type: string
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )


if __name__ == "__main__":
    unittest.main()
