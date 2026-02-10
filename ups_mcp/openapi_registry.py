from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable
import os

import jsonschema
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT7
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
    request_body_schema: str | None
    response_schemas: dict[str, str | None]
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
    def __init__(self, operations: dict[str, OperationSpec], source_documents: dict[str, dict[str, Any]]) -> None:
        self._operations = operations
        self._source_documents = source_documents
        self._validator_cache: dict[tuple[str, str], jsonschema.Draft7Validator] = {}
        self._jsonschema_registry = Registry()
        for source_file, source_document in source_documents.items():
            self._jsonschema_registry = self._jsonschema_registry.with_resource(
                _source_uri(source_file),
                Resource(contents=source_document, specification=DRAFT7),
            )

    @classmethod
    def from_spec_files(cls, spec_paths: Iterable[Path]) -> "OpenAPIRegistry":
        operations: dict[str, OperationSpec] = {}
        source_documents: dict[str, dict[str, Any]] = {}
        for spec_path in spec_paths:
            data = yaml.safe_load(spec_path.read_text())
            source_documents[spec_path.name] = data
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
        return cls(operations=operations, source_documents=source_documents)

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
        json_schema = (
            ((request_body.get("content") or {}).get("application/json") or {}).get("schema")
            or {}
        )
        request_body_schema = json_schema.get("$ref")

        response_schemas: dict[str, str | None] = {}
        for status_code, response in (operation.get("responses") or {}).items():
            schema = (
                (((response or {}).get("content") or {}).get("application/json") or {}).get("schema")
                or {}
            )
            response_schemas[str(status_code)] = schema.get("$ref")

        return OperationSpec(
            source_file=source_file,
            operation_id=operation_id,
            method=method,
            path=path,
            deprecated=bool(operation.get("deprecated", False)),
            summary=operation.get("summary", ""),
            request_body_required=request_body_required,
            request_body_schema=request_body_schema,
            response_schemas=response_schemas,
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

    def validate_request_body(self, operation_id: str, request_body: Any) -> list[str]:
        operation = self.get_operation(operation_id)
        if not operation.request_body_schema:
            return []

        validator = self._get_validator(operation)
        errors = sorted(validator.iter_errors(request_body), key=lambda err: list(err.path))
        messages: list[str] = []
        for error in errors:
            location = ".".join(str(segment) for segment in error.path)
            if location:
                messages.append(f"{location}: {error.message}")
            else:
                messages.append(error.message)
        return messages

    def _get_validator(self, operation: OperationSpec) -> jsonschema.Draft7Validator:
        if not operation.request_body_schema:
            raise ValueError(f"Operation has no request body schema: {operation.operation_id}")

        cache_key = (operation.source_file, operation.request_body_schema)
        if cache_key in self._validator_cache:
            return self._validator_cache[cache_key]

        if operation.source_file not in self._source_documents:
            raise ValueError(f"Missing source document for operation: {operation.operation_id}")

        schema_wrapper = {"$ref": f"{_source_uri(operation.source_file)}{operation.request_body_schema}"}
        validator = jsonschema.Draft7Validator(schema_wrapper, registry=self._jsonschema_registry)
        self._validator_cache[cache_key] = validator
        return validator


def _source_uri(source_file: str) -> str:
    return f"urn:ups:{source_file}"


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
