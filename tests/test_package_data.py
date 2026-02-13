from importlib import resources
import unittest

from ups_mcp.openapi_registry import DEFAULT_SPEC_FILES


class PackageDataTests(unittest.TestCase):
    def test_packaged_openapi_specs_are_available_as_resources(self) -> None:
        specs_dir = resources.files("ups_mcp").joinpath("specs")
        for file_name in DEFAULT_SPEC_FILES:
            spec_resource = specs_dir.joinpath(file_name)
            self.assertTrue(spec_resource.is_file(), f"Missing packaged spec resource: {file_name}")
            self.assertGreater(len(spec_resource.read_text(encoding="utf-8")), 0)


if __name__ == "__main__":
    unittest.main()
