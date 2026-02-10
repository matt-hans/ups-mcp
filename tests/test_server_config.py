import unittest

import ups_mcp.server as server


class ServerConfigTests(unittest.TestCase):
    def test_validate_runtime_configuration_requires_credentials(self) -> None:
        original_client_id = server.client_id
        original_client_secret = server.client_secret
        try:
            server.client_id = None
            server.client_secret = None
            with self.assertRaises(RuntimeError):
                server._validate_runtime_configuration()
        finally:
            server.client_id = original_client_id
            server.client_secret = original_client_secret


if __name__ == "__main__":
    unittest.main()
