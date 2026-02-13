import contextlib
import io
import os
import unittest
from unittest import mock

import ups_mcp.server as server
from ups_mcp.openapi_registry import OpenAPISpecLoadError


class ServerConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_base_url = server.base_url
        self.original_client_id = server.client_id
        self.original_client_secret = server.client_secret
        self.original_tool_manager = server.tool_manager

    def tearDown(self) -> None:
        server.base_url = self.original_base_url
        server.client_id = self.original_client_id
        server.client_secret = self.original_client_secret
        server.tool_manager = self.original_tool_manager

    def test_validate_runtime_configuration_requires_credentials(self) -> None:
        server.client_id = None
        server.client_secret = None
        with self.assertRaises(RuntimeError):
            server._validate_runtime_configuration()

    @mock.patch("ups_mcp.server.mcp.run")
    @mock.patch("ups_mcp.server.tools.ToolManager")
    def test_main_exits_with_actionable_error_when_specs_are_missing(
        self,
        mock_tool_manager: mock.Mock,
        mock_run: mock.Mock,
    ) -> None:
        mock_tool_manager.side_effect = OpenAPISpecLoadError(
            source="bundled package resources (ups_mcp/specs)",
            missing_files=["Rating.yaml"],
        )
        stderr = io.StringIO()

        with mock.patch.dict(
            os.environ,
            {"CLIENT_ID": "client-id", "CLIENT_SECRET": "client-secret", "ENVIRONMENT": "test"},
            clear=False,
        ):
            with contextlib.redirect_stderr(stderr):
                with self.assertRaises(SystemExit) as ctx:
                    server.main()

        self.assertEqual(ctx.exception.code, 1)
        self.assertIn("OpenAPI specs are unavailable", stderr.getvalue())
        mock_run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
