from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable
import os

import yaml

HTTP_METHODS = {"get", "post", "put", "delete", "patch", "head", "options"}
DEFAULT_SPEC_FILES = ("Rating.yaml", "Shipping.yaml", "TimeInTransit.yaml")


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
        operations: dict[str, OperationSpec] = {}
        for spec_path in spec_paths:
            data = yaml.safe_load(spec_path.read_text())
            for path, path_item in (data.get("paths") or {}).items():
                for method, operation in path_item.items():
                    method_lc = method.lower()
                    if method_lc not in HTTP_METHODS:
                        continue
                    operation_id = operation.get("operationId") or f"{method.upper()} {path}"
                    parsed = cls._parse_operation(
                        source_file=spec_path.name,
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
    if specs_dir is None:
        configured = os.getenv("UPS_MCP_SPECS_DIR")
        if configured:
            specs_dir = Path(configured)
        else:
            specs_dir = Path(__file__).resolve().parent.parent / "docs"
    return [specs_dir / file_name for file_name in DEFAULT_SPEC_FILES]


@lru_cache(maxsize=1)
def load_default_registry() -> OpenAPIRegistry:
    return OpenAPIRegistry.from_spec_files(default_spec_paths())
