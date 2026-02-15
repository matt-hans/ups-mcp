from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Any, Iterable
import os

import yaml

HTTP_METHODS = {"get", "post", "put", "delete", "patch", "head", "options"}
DEFAULT_SPEC_FILES = (
    "Rating.yaml",
    "Shipping.yaml",
    "TimeInTransit.yaml",
    "LandedCost.yaml",
    "Paperless.yaml",
    "Locator.yaml",
    "Pickup.yaml",
)


class OpenAPISpecLoadError(RuntimeError):
    def __init__(self, *, source: str, missing_files: Iterable[str]) -> None:
        missing = tuple(sorted(missing_files))
        self.source = source
        self.missing_files = missing
        required = ", ".join(DEFAULT_SPEC_FILES)
        missing_csv = ", ".join(missing)
        super().__init__(
            "OpenAPI specs are unavailable. "
            f"Missing from {source}: {missing_csv}. "
            "Reinstall ups-mcp with bundled specs or set UPS_MCP_SPECS_DIR "
            f"to a directory containing: {required}."
        )


@dataclass(frozen=True)
class ParameterSpec:
    name: str
    location: str
    required: bool
    default: Any = None


@dataclass(frozen=True)
class OperationSpec:
    source_file: str
    operation_id: str
    method: str
    path: str
    deprecated: bool
    summary: str
    request_body_required: bool
    path_params: tuple[ParameterSpec, ...]
    query_params: tuple[ParameterSpec, ...]
    header_params: tuple[ParameterSpec, ...]

    def default_path_values(self) -> dict[str, Any]:
        defaults: dict[str, Any] = {}
        for param in self.path_params:
            if param.default is not None:
                defaults[param.name] = param.default
        return defaults


class OpenAPIRegistry:
    def __init__(self, operations: dict[str, OperationSpec]) -> None:
        self._operations = operations

    @classmethod
    def from_spec_files(cls, spec_paths: Iterable[Path]) -> "OpenAPIRegistry":
        loaded_specs = []
        for spec_path in spec_paths:
            loaded_specs.append((spec_path.name, spec_path.read_text(encoding="utf-8")))
        return cls.from_spec_texts(loaded_specs)

    @classmethod
    def from_spec_texts(cls, specs: Iterable[tuple[str, str]]) -> "OpenAPIRegistry":
        operations: dict[str, OperationSpec] = {}
        for source_file, spec_text in specs:
            data = yaml.safe_load(spec_text) or {}
            for path, path_item in (data.get("paths") or {}).items():
                for method, operation in path_item.items():
                    method_lc = method.lower()
                    if method_lc not in HTTP_METHODS:
                        continue
                    operation_id = operation.get("operationId") or f"{method.upper()} {path}"
                    parsed = cls._parse_operation(
                        source_file=source_file,
                        operation=operation,
                        operation_id=operation_id,
                        method=method_lc.upper(),
                        path=path,
                    )
                    if operation_id in operations:
                        raise ValueError(f"Duplicate operationId detected: {operation_id}")
                    operations[operation_id] = parsed
        return cls(operations=operations)

    @staticmethod
    def _parse_operation(
        source_file: str,
        operation: dict[str, Any],
        operation_id: str,
        method: str,
        path: str,
    ) -> OperationSpec:
        path_params: list[ParameterSpec] = []
        query_params: list[ParameterSpec] = []
        header_params: list[ParameterSpec] = []
        for param in operation.get("parameters", []):
            spec = ParameterSpec(
                name=param.get("name", ""),
                location=param.get("in", ""),
                required=bool(param.get("required", False)),
                default=(param.get("schema") or {}).get("default"),
            )
            if spec.location == "path":
                path_params.append(spec)
            elif spec.location == "query":
                query_params.append(spec)
            elif spec.location == "header":
                header_params.append(spec)

        request_body = operation.get("requestBody") or {}
        request_body_required = bool(request_body.get("required", False))

        return OperationSpec(
            source_file=source_file,
            operation_id=operation_id,
            method=method,
            path=path,
            deprecated=bool(operation.get("deprecated", False)),
            summary=operation.get("summary", ""),
            request_body_required=request_body_required,
            path_params=tuple(path_params),
            query_params=tuple(query_params),
            header_params=tuple(header_params),
        )

    def get_operation(self, operation_id: str) -> OperationSpec:
        if operation_id not in self._operations:
            raise KeyError(f"Operation not found in registry: {operation_id}")
        return self._operations[operation_id]

    def list_operations(self, include_deprecated: bool = False) -> list[OperationSpec]:
        operations = self._operations.values()
        if include_deprecated:
            return sorted(operations, key=lambda item: item.operation_id)
        return sorted(
            (item for item in operations if not item.deprecated),
            key=lambda item: item.operation_id,
        )


def default_spec_paths(specs_dir: Path | None = None) -> list[Path]:
    resolved_specs_dir = specs_dir
    if resolved_specs_dir is None:
        configured = os.getenv("UPS_MCP_SPECS_DIR")
        if configured:
            resolved_specs_dir = Path(configured)
        else:
            resolved_specs_dir = Path(__file__).resolve().parent / "specs"
    return [resolved_specs_dir / file_name for file_name in DEFAULT_SPEC_FILES]


def _load_spec_texts_from_dir(specs_dir: Path) -> list[tuple[str, str]]:
    missing_files: list[str] = []
    loaded_specs: list[tuple[str, str]] = []
    for file_name in DEFAULT_SPEC_FILES:
        spec_path = specs_dir / file_name
        if not spec_path.is_file():
            missing_files.append(file_name)
            continue
        loaded_specs.append((file_name, spec_path.read_text(encoding="utf-8")))

    if missing_files:
        raise OpenAPISpecLoadError(
            source=f"UPS_MCP_SPECS_DIR={specs_dir}",
            missing_files=missing_files,
        )
    return loaded_specs


def _load_spec_texts_from_package() -> list[tuple[str, str]]:
    specs_dir = resources.files("ups_mcp").joinpath("specs")
    missing_files: list[str] = []
    loaded_specs: list[tuple[str, str]] = []
    for file_name in DEFAULT_SPEC_FILES:
        spec_resource = specs_dir.joinpath(file_name)
        if not spec_resource.is_file():
            missing_files.append(file_name)
            continue
        loaded_specs.append((file_name, spec_resource.read_text(encoding="utf-8")))

    if missing_files:
        raise OpenAPISpecLoadError(
            source="bundled package resources (ups_mcp/specs)",
            missing_files=missing_files,
        )
    return loaded_specs


@lru_cache(maxsize=1)
def load_default_registry() -> OpenAPIRegistry:
    configured = os.getenv("UPS_MCP_SPECS_DIR")
    if configured:
        loaded_specs = _load_spec_texts_from_dir(Path(configured))
    else:
        loaded_specs = _load_spec_texts_from_package()
    return OpenAPIRegistry.from_spec_texts(loaded_specs)
