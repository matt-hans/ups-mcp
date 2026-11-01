import json
import math
import os
import re
import time
import threading
from typing import Protocol

import requests
from mcp.server.fastmcp.exceptions import ToolError


class TokenProvider(Protocol):
    def get_access_token(self) -> str: ...


class OAuthManager:
    def __init__(self, token_url: str, client_id: str | None, client_secret: str | None, timeout: float = 30.0):
        self.token_url = token_url
        self.client_id = client_id
        self.client_secret = client_secret
        self.timeout = timeout
        self.access_token: str | None = None
        self.token_expiry: float = 0
        self._lock = threading.Lock()

    def get_access_token(self) -> str:
        if self._token_is_fresh():
            return self.access_token  # type: ignore[return-value]

        with self._lock:
            if self._token_is_fresh():
                return self.access_token  # type: ignore[return-value]
            if not self.client_id or not self.client_secret:
                raise ValueError("CLIENT_ID and CLIENT_SECRET must be set in environment variables.")

            data = {"grant_type": "client_credentials"}

            response = requests.post(
                self.token_url,
                data=data,
                auth=(self.client_id, self.client_secret),
                timeout=self.timeout,
            )
            response.raise_for_status()
            token_data = response.json()
            self.access_token = token_data["access_token"]
            self.token_expiry = time.time() + int(token_data.get("expires_in", 0))
            return self.access_token

    def _token_is_fresh(self) -> bool:
        return bool(self.access_token and time.time() < self.token_expiry - 60)


DELEGATED_TOKEN_EXPIRY_SKEW_SECONDS = 30

# RFC 6750 b64token. It has no quote, backslash, whitespace, or bracket, so JSON or
# repr escaping can never disguise an echoed token from literal redaction.
_BEARER_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9\-._~+/]+=*")


class DelegatedTokenFile:
    """Reads a caller-managed UPS access token from a JSON file on every call.

    The file holds {"access_token": "<opaque>", "expires_at": <epoch seconds>}
    and is rotated atomically by its owner. Failures raise ToolError without
    contacting UPS; messages name only the file's basename, never its contents.
    """

    def __init__(self, path: str) -> None:
        self.path = path
        self._label = os.path.basename(path)

    def __repr__(self) -> str:
        return f"DelegatedTokenFile({self._label!r})"

    # Every ToolError below is raised outside its except block, so it carries no
    # __context__ chaining back to OS/JSON exceptions that hold the full path or
    # the file contents.
    def get_access_token(self) -> str:
        access_token, expires_at = self._parse(self._read())
        if expires_at <= time.time() + DELEGATED_TOKEN_EXPIRY_SKEW_SECONDS:
            raise _delegated_error(
                "UPS_DELEGATED_TOKEN_EXPIRED",
                f"Delegated UPS access token in '{self._label}' is expired or about to expire.",
            )
        return access_token

    def _read(self) -> bytes:
        failure: str | None = None
        try:
            fd = os.open(self.path, os.O_RDONLY)
        except FileNotFoundError:
            failure = "does not exist"
        except OSError:
            failure = "could not be opened"
        if failure is not None:
            # A file we cannot open may still be another user's: report that as
            # INSECURE, per the contract, rather than UNAVAILABLE.
            if failure != "does not exist" and self._path_is_insecure():
                raise self._insecure()
            raise self._unavailable(failure)

        handle = None
        try:
            handle = os.fdopen(fd, "rb")
        except OSError:  # e.g. the path is a directory
            os.close(fd)
        if handle is None:
            raise self._unavailable("could not be read")

        with handle:
            # fstat the opened descriptor so the checks apply to the bytes we read.
            if _stat_is_insecure(os.fstat(handle.fileno())):
                raise self._insecure()
            raw: bytes | None = None
            try:
                raw = handle.read()
            except OSError:
                pass
        if raw is None:
            raise self._unavailable("could not be read")
        return raw

    def _path_is_insecure(self) -> bool:
        stat_result = None
        try:
            stat_result = os.stat(self.path)
        except OSError:
            pass
        return stat_result is not None and _stat_is_insecure(stat_result)

    def _insecure(self) -> ToolError:
        return _delegated_error(
            "UPS_DELEGATED_TOKEN_INSECURE",
            f"Delegated UPS access token file '{self._label}' must be owned by the "
            "server user and must not be accessible by group or others (use mode 0600).",
        )

    def _unavailable(self, reason: str) -> ToolError:
        return _delegated_error(
            "UPS_DELEGATED_TOKEN_UNAVAILABLE",
            f"Delegated UPS access token file '{self._label}' {reason}.",
        )

    def _parse(self, raw: bytes) -> tuple[str, float]:
        data: object = None
        try:
            data = json.loads(raw.decode("utf-8"))
        except ValueError:  # includes UnicodeDecodeError and JSONDecodeError
            pass
        if not isinstance(data, dict):
            raise self._invalid()

        access_token = data.get("access_token")
        if not isinstance(access_token, str) or not _BEARER_TOKEN_PATTERN.fullmatch(access_token):
            raise self._invalid()

        expires_at = data.get("expires_at")
        # bool is an int subclass; JSON true/false is not a timestamp.
        if (
            isinstance(expires_at, bool)
            or not isinstance(expires_at, (int, float))
            or not math.isfinite(expires_at)
        ):
            raise self._invalid()
        return access_token, float(expires_at)

    def _invalid(self) -> ToolError:
        return _delegated_error(
            "UPS_DELEGATED_TOKEN_INVALID",
            f"Delegated UPS access token file '{self._label}' must be UTF-8 JSON with a "
            "non-empty RFC 6750 bearer token 'access_token' and a numeric 'expires_at'.",
        )


def _stat_is_insecure(stat_result: os.stat_result) -> bool:
    return bool(stat_result.st_mode & 0o077) or stat_result.st_uid != os.getuid()


def _delegated_error(code: str, message: str) -> ToolError:
    return ToolError(json.dumps({"code": code, "message": message}))
