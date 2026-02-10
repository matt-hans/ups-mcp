from __future__ import annotations

from typing import Any
import re
import uuid
from urllib.parse import quote

import requests

from .authorization import OAuthManager
from .openapi_registry import OperationSpec


class UPSHTTPClient:
    def __init__(self, base_url: str, oauth_manager: OAuthManager, timeout: float = 30.0) -> None:
        self.base_url = base_url
        self.oauth_manager = oauth_manager
        self.timeout = timeout

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
    ) -> dict[str, Any]:
        request_trans_id = trans_id or str(uuid.uuid4())
        request_transaction_src = transaction_src or "ups-mcp"
        safe_query = {key: value for key, value in (query_params or {}).items() if value is not None}

        try:
            rendered_path = _render_openapi_path(operation.path, path_params)
        except KeyError as exc:
            missing = exc.args[0]
            return validation_error_envelope(
                operation_name=operation_name,
                message=f"Missing required path parameter: {missing}",
                trans_id=request_trans_id,
            )

        url = f"{self.base_url}/api{rendered_path}"

        try:
            token = self.oauth_manager.get_access_token()
            headers = {
                "Authorization": f"Bearer {token}",
                "transId": request_trans_id,
                "transactionSrc": request_transaction_src,
            }
            response = requests.request(
                method=operation.method,
                url=url,
                headers=headers,
                params=safe_query,
                json=json_body,
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            return {
                "ok": False,
                "operation": operation_name,
                "status_code": 0,
                "trans_id": request_trans_id,
                "request": {
                    "method": operation.method,
                    "path": rendered_path,
                    "query": safe_query,
                },
                "data": None,
                "error": {
                    "code": "REQUEST_ERROR",
                    "message": str(exc),
                    "details": None,
                },
            }

        payload = _parse_payload(response)
        if 200 <= response.status_code < 300:
            return {
                "ok": True,
                "operation": operation_name,
                "status_code": response.status_code,
                "trans_id": request_trans_id,
                "request": {
                    "method": operation.method,
                    "path": rendered_path,
                    "query": safe_query,
                },
                "data": payload,
                "error": None,
            }

        return {
            "ok": False,
            "operation": operation_name,
            "status_code": response.status_code,
            "trans_id": request_trans_id,
            "request": {
                "method": operation.method,
                "path": rendered_path,
                "query": safe_query,
            },
            "data": None,
            "error": {
                "code": _extract_error_code(payload, response.status_code),
                "message": _extract_error_message(payload, response.status_code),
                "details": payload,
            },
        }


def validation_error_envelope(
    *,
    operation_name: str,
    message: str,
    trans_id: str | None = None,
    details: Any = None,
) -> dict[str, Any]:
    return {
        "ok": False,
        "operation": operation_name,
        "status_code": 0,
        "trans_id": trans_id,
        "request": {
            "method": None,
            "path": None,
            "query": {},
        },
        "data": None,
        "error": {
            "code": "VALIDATION_ERROR",
            "message": message,
            "details": details,
        },
    }


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


_PATH_TOKEN_PATTERN = re.compile(r"{([^{}]+)}")


def _render_openapi_path(path_template: str, path_params: dict[str, Any]) -> str:
    def substitute(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in path_params:
            raise KeyError(key)
        value = path_params[key]
        return quote(str(value), safe="")

    return _PATH_TOKEN_PATTERN.sub(substitute, path_template)
