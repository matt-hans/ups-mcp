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
    def __init__(
        self,
        base_url: str,
        token_provider: TokenProvider | None = None,
        timeout: float = 30.0,
        *,
        oauth_manager: TokenProvider | None = None,
    ) -> None:
        # oauth_manager is the pre-seam keyword, kept for existing callers.
        if token_provider is None:
            token_provider = oauth_manager
        if token_provider is None:
            raise TypeError("UPSHTTPClient requires a token_provider")
        self.base_url = base_url
        self.token_provider = token_provider
        self.timeout = timeout

    @property
    def oauth_manager(self) -> TokenProvider:
        return self.token_provider

    @oauth_manager.setter
    def oauth_manager(self, value: TokenProvider) -> None:
        self.token_provider = value

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

        # Snapshot the provider so a concurrent reassignment can't change how this
        # call's errors are handled.
        token_provider = self.token_provider
        delegated = isinstance(token_provider, DelegatedTokenFile)
        token = ""
        request_error: str | None = None
        try:
            # Delegated-token failures raise ToolError here, before any request.
            token = token_provider.get_access_token()
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
            request_kwargs: dict[str, Any] = {}
            if delegated:
                # An explicit auth object stops requests from replacing the Bearer
                # header with ~/.netrc Basic credentials for the UPS host. Redirects
                # are not followed: requests re-applies netrc credentials on each
                # redirect, and UPS APIs don't redirect, so a 3xx fails closed.
                request_kwargs["auth"] = _BearerAuth(token)
                request_kwargs["allow_redirects"] = False
            response = requests.request(
                method=operation.method,
                url=url,
                headers=headers,
                params=safe_query,
                json=json_body,
                timeout=self.timeout,
                **request_kwargs,
            )
        except requests.RequestException as exc:
            if not delegated:
                raise ToolError(json.dumps({
                    "code": "REQUEST_ERROR",
                    "message": str(exc),
                }))
            request_error = _redact_secret(str(exc), token)
        if request_error is not None:
            # Delegated errors are raised outside the except block so they don't
            # chain to the RequestException, whose .request carries the token.
            raise ToolError(json.dumps({
                "code": "REQUEST_ERROR",
                "message": request_error,
            }))

        payload = _parse_payload(response)
        if 200 <= response.status_code < 300:
            return payload if isinstance(payload, dict) else {"raw": payload}

        error_code = _extract_error_code(payload, response.status_code)
        error_message = _extract_error_message(payload, response.status_code)
        if delegated:
            # Delegated errors keep UPS's message, including body shapes the shared
            # extractor doesn't read: a top-level "errors" list (e.g. Time in
            # Transit) or a plain-text body.
            if error_message == _fallback_error_message(response.status_code):
                error_message = _extract_delegated_fallback_message(payload) or error_message
            # Extract from the original structure, then scrub what is emitted. The
            # token alphabet (see DelegatedTokenFile) survives str()/JSON escaping
            # unchanged, so literal replacement catches every echo.
            error_code = _redact_secret(error_code, token)
            error_message = _redact_secret(error_message, token)
            payload = _redact_secret(payload, token)
            if response.status_code == 401:
                # UPS refuses a bad bearer token before processing the request, so
                # the caller can safely refresh and retry; ups-mcp never retries.
                # Set after redaction so a token that overlaps this code can't alter it.
                error_code = "UPS_DELEGATED_TOKEN_REJECTED"
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
    return _fallback_error_message(status_code)


def _fallback_error_message(status_code: int) -> str:
    return f"UPS API returned HTTP {status_code}"


class _BearerAuth(requests.auth.AuthBase):
    def __init__(self, token: str) -> None:
        self._token = token

    def __call__(self, request: requests.PreparedRequest) -> requests.PreparedRequest:
        request.headers["Authorization"] = f"Bearer {self._token}"
        return request

    def __repr__(self) -> str:
        return "_BearerAuth(<redacted>)"


def _extract_delegated_fallback_message(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    errors = payload.get("errors")
    if isinstance(errors, list) and errors:
        first = errors[0]
        message = first.get("message") if isinstance(first, dict) else first
        if isinstance(message, str) and message.strip():
            return message
    raw = payload.get("raw")  # non-JSON body, see _parse_payload
    if isinstance(raw, str) and raw.strip():
        return raw
    return None


_REDACTED = "[REDACTED]"
# Used when the secret is a substring of _REDACTED; "*" is outside the token alphabet.
_REDACTED_FALLBACK = "********"


def _redact_secret(value: Any, secret: str) -> Any:
    """Recursively replace occurrences of secret in strings, dict keys included."""
    if not secret:
        return value
    if isinstance(value, str):
        return value.replace(secret, _REDACTED if secret not in _REDACTED else _REDACTED_FALLBACK)
    if isinstance(value, dict):
        return {_redact_secret(k, secret): _redact_secret(v, secret) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_secret(item, secret) for item in value]
    # A token echoed back as a JSON number, true/false, or null.
    if isinstance(value, (bool, int, float)) or value is None:
        if secret in json.dumps(value):
            return _REDACTED if secret not in _REDACTED else _REDACTED_FALLBACK
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
