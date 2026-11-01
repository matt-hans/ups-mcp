from __future__ import annotations

import json
from typing import Any
import re
import uuid
from urllib.parse import quote

import requests
from mcp.server.fastmcp.exceptions import ToolError

from .authorization import DelegatedTokenFile, TokenProvider
from .openapi_registry import OperationSpec


class UPSHTTPClient:
    def __init__(self, base_url: str, token_provider: TokenProvider, timeout: float = 30.0) -> None:
        self.base_url = base_url
        self.token_provider = token_provider
        self.timeout = timeout
        self._delegated = isinstance(token_provider, DelegatedTokenFile)

    def call_operation(
        self,
        operation: OperationSpec,
        *,
        operation_name: str,
        path_params: dict[str, Any],
        query_params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        trans_id: str | None = None,
        transaction_src: str | None = None,
        additional_headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        request_trans_id = trans_id or str(uuid.uuid4())
        request_transaction_src = transaction_src or "ups-mcp"
        safe_query = {key: value for key, value in (query_params or {}).items() if value is not None}

        try:
            rendered_path = _render_openapi_path(operation.path, path_params)
        except KeyError as exc:
            missing = exc.args[0]
            raise ToolError(json.dumps({
                "code": "VALIDATION_ERROR",
                "message": f"Missing required path parameter: {missing}",
            }))

        url = f"{self.base_url}/api{rendered_path}"

        token = ""
        try:
            # Delegated-token failures raise ToolError here, before any request.
            token = self.token_provider.get_access_token()
            headers = {
                "Authorization": f"Bearer {token}",
                "transId": request_trans_id,
                "transactionSrc": request_transaction_src,
            }
            if additional_headers:
                reserved = {k.lower() for k in headers}
                for k, v in additional_headers.items():
                    if v is not None and k.lower() not in reserved:
                        headers[k] = v
            response = requests.request(
                method=operation.method,
                url=url,
                headers=headers,
                params=safe_query,
                json=json_body,
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            message = str(exc)
            if self._delegated:
                message = _redact_secret(message, token)
            raise ToolError(json.dumps({
                "code": "REQUEST_ERROR",
                "message": message,
            }))

        payload = _parse_payload(response)
        if 200 <= response.status_code < 300:
            return payload if isinstance(payload, dict) else {"raw": payload}

        error_code = _extract_error_code(payload, response.status_code)
        error_message = _extract_error_message(payload, response.status_code)
        if self._delegated:
            # UPS refuses a bad bearer token before processing the request, so the
            # caller can safely refresh and retry; ups-mcp itself never retries.
            if response.status_code == 401:
                error_code = "UPS_DELEGATED_TOKEN_REJECTED"
            error_message = _redact_secret(error_message, token)
            payload = _redact_secret(payload, token)
        raise ToolError(json.dumps({
            "status_code": response.status_code,
            "code": error_code,
            "message": error_message,
            "details": payload,
        }))


def _parse_payload(response: requests.Response) -> dict[str, Any] | list[Any] | None:
    if not response.content:
        return None
    try:
        return response.json()
    except ValueError:
        text = response.text.strip()
        return {"raw": text} if text else None


def _extract_error_code(payload: Any, status_code: int) -> str:
    if isinstance(payload, dict):
        for key in ("code", "errorCode", "statusCode"):
            value = payload.get(key)
            if value:
                return str(value)
        nested = payload.get("response")
        if isinstance(nested, dict):
            status = nested.get("status")
            if isinstance(status, dict):
                candidate = status.get("code")
                if candidate:
                    return str(candidate)
    return str(status_code)


def _extract_error_message(payload: Any, status_code: int) -> str:
    if isinstance(payload, dict):
        for key in ("message", "error", "detail"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value
        nested = payload.get("response")
        if isinstance(nested, dict):
            errors = nested.get("errors")
            if isinstance(errors, list) and errors:
                first = errors[0]
                if isinstance(first, dict):
                    message = first.get("message")
                    if isinstance(message, str) and message.strip():
                        return message
                if isinstance(first, str) and first.strip():
                    return first
            status = nested.get("status")
            if isinstance(status, dict):
                description = status.get("description")
                if isinstance(description, str) and description.strip():
                    return description
    return f"UPS API returned HTTP {status_code}"


_REDACTED = "[REDACTED]"


def _redact_secret(value: Any, secret: str) -> Any:
    """Recursively replace occurrences of secret in strings, dict keys included."""
    if not secret:
        return value
    if isinstance(value, str):
        return value.replace(secret, _REDACTED)
    if isinstance(value, dict):
        return {_redact_secret(k, secret): _redact_secret(v, secret) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_secret(item, secret) for item in value]
    return value


_PATH_TOKEN_PATTERN = re.compile(r"{([^{}]+)}")


def _render_openapi_path(path_template: str, path_params: dict[str, Any]) -> str:
    def substitute(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in path_params:
            raise KeyError(key)
        value = path_params[key]
        return quote(str(value), safe="")

    return _PATH_TOKEN_PATTERN.sub(substitute, path_template)
