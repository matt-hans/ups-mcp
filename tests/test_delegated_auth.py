import ast
import contextlib
import io
import json
import os
import shutil
import tempfile
import time
import traceback
import unittest
from unittest import mock

import dotenv
import requests
from mcp.server.fastmcp.exceptions import ToolError
from mcp.shared.memory import create_connected_server_and_client_session

import ups_mcp.server as server
from ups_mcp import constants
from ups_mcp.authorization import DelegatedTokenFile
from ups_mcp.http_client import UPSHTTPClient
from ups_mcp.tools import ToolManager
from tests.test_http_client import DummyOAuthManager, build_operation_spec, make_response

TOKEN = "delegated-customer-token-abc123"
ROTATED_TOKEN = "delegated-customer-token-rotated-xyz789"


class TokenFileTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp(prefix="ups-mcp-delegated-")
        self.addCleanup(shutil.rmtree, self.tmpdir, ignore_errors=True)
        self.token_path = os.path.join(self.tmpdir, "ups-token.json")

    def write_token_file(self, payload, mode: int = 0o600) -> None:  # noqa: ANN001
        """Write atomically (temp file plus rename), like ShipAgent does."""
        raw = payload if isinstance(payload, (str, bytes)) else json.dumps(payload)
        if isinstance(raw, str):
            raw = raw.encode("utf-8")
        temp_path = self.token_path + ".tmp"
        with open(temp_path, "wb") as handle:
            handle.write(raw)
        os.chmod(temp_path, mode)
        os.replace(temp_path, self.token_path)

    def write_valid_token(self, token: str = TOKEN, ttl: float = 3600) -> None:
        self.write_token_file({"access_token": token, "expires_at": time.time() + ttl})

    def assert_unchained(self, exc: BaseException, *secrets: str) -> None:
        """No chained exception (which could hold paths or file contents) and no secret in the traceback."""
        self.assertIsNone(exc.__cause__)
        self.assertIsNone(exc.__context__)
        rendered = "".join(traceback.format_exception(exc))
        for secret in secrets:
            self.assertNotIn(secret, rendered)

    def assert_tool_error_code(self, exc: ToolError, code: str) -> dict:
        payload = json.loads(str(exc))
        self.assertEqual(payload["code"], code)
        return payload


class DelegatedTokenFileTests(TokenFileTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.provider = DelegatedTokenFile(self.token_path)

    def assert_provider_fails(self, code: str) -> dict:
        with self.assertRaises(ToolError) as ctx:
            self.provider.get_access_token()
        payload = self.assert_tool_error_code(ctx.exception, code)
        message = str(ctx.exception)
        self.assertNotIn(TOKEN, message)
        self.assertNotIn(self.tmpdir, message)
        self.assert_unchained(ctx.exception, TOKEN, self.tmpdir)
        return payload

    def test_returns_token_from_valid_file(self) -> None:
        self.write_valid_token()
        self.assertEqual(self.provider.get_access_token(), TOKEN)

    def test_ignores_extra_keys_and_accepts_float_expiry(self) -> None:
        self.write_token_file({
            "access_token": TOKEN,
            "expires_at": time.time() + 3600.5,
            "refresh_hint": "ignored",
        })
        self.assertEqual(self.provider.get_access_token(), TOKEN)

    def test_missing_file_is_unavailable(self) -> None:
        payload = self.assert_provider_fails("UPS_DELEGATED_TOKEN_UNAVAILABLE")
        self.assertIn("ups-token.json", payload["message"])

    def test_group_or_other_readable_file_is_insecure(self) -> None:
        for mode in (0o644, 0o640, 0o604, 0o660):
            with self.subTest(mode=oct(mode)):
                self.write_valid_token()
                os.chmod(self.token_path, mode)
                self.assert_provider_fails("UPS_DELEGATED_TOKEN_INSECURE")

    def test_file_owned_by_another_user_is_insecure(self) -> None:
        self.write_valid_token()
        other_uid = os.stat(self.token_path).st_uid + 1
        with mock.patch("ups_mcp.authorization.os.getuid", return_value=other_uid):
            self.assert_provider_fails("UPS_DELEGATED_TOKEN_INSECURE")

    def test_unopenable_file_owned_by_another_user_is_insecure(self) -> None:
        # A 0600 file owned by someone else fails os.open with EACCES; it must still
        # be classified as INSECURE, not UNAVAILABLE.
        self.write_valid_token()
        other_uid = os.stat(self.token_path).st_uid + 1
        with mock.patch("ups_mcp.authorization.os.open", side_effect=PermissionError(13, "denied", self.token_path)), \
                mock.patch("ups_mcp.authorization.os.getuid", return_value=other_uid):
            self.assert_provider_fails("UPS_DELEGATED_TOKEN_INSECURE")

    def test_unopenable_own_file_is_unavailable(self) -> None:
        self.write_valid_token()
        with mock.patch("ups_mcp.authorization.os.open", side_effect=PermissionError(13, "denied", self.token_path)):
            self.assert_provider_fails("UPS_DELEGATED_TOKEN_UNAVAILABLE")

    def test_rfc6750_token_alphabet_is_accepted(self) -> None:
        token = "eyJhbGciOi.JIUzI1-NiJ9_~+/abc=="
        self.write_valid_token(token)
        self.assertEqual(self.provider.get_access_token(), token)

    def test_invalid_contents_are_invalid(self) -> None:
        future = time.time() + 3600
        cases = {
            "bad_json": "{not json",
            "not_utf8": b"\xff\xfe\x00",
            "not_object": json.dumps([TOKEN, future]),
            "missing_token": {"expires_at": future},
            "empty_token": {"access_token": "", "expires_at": future},
            "non_string_token": {"access_token": 12345, "expires_at": future},
            "whitespace_token": {"access_token": f"{TOKEN}\r\nX-Injected: 1", "expires_at": future},
            "space_token": {"access_token": f"{TOKEN} {TOKEN}", "expires_at": future},
            "non_ascii_token": {"access_token": f"{TOKEN}\u03bb", "expires_at": future},
            "quote_token": {"access_token": f'{TOKEN}"x', "expires_at": future},
            "backslash_token": {"access_token": f"{TOKEN}\\x", "expires_at": future},
            "padding_not_at_end": {"access_token": f"{TOKEN}=x", "expires_at": future},
            "missing_expiry": {"access_token": TOKEN},
            "string_expiry": {"access_token": TOKEN, "expires_at": str(future)},
            "bool_expiry": {"access_token": TOKEN, "expires_at": True},
            "nan_expiry": '{"access_token": "%s", "expires_at": NaN}' % TOKEN,
            "nan_in_extra_key": '{"access_token": "%s", "expires_at": 4000000000, "extra": NaN}' % TOKEN,
            "infinity_in_extra_key": '{"access_token": "%s", "expires_at": 4000000000, "extra": -Infinity}' % TOKEN,
        }
        for name, payload in cases.items():
            with self.subTest(case=name):
                self.write_token_file(payload)
                self.assert_provider_fails("UPS_DELEGATED_TOKEN_INVALID")

    def test_unreadable_token_file_is_unavailable(self) -> None:
        os.mkdir(self.token_path)  # opening succeeds on macOS/Linux, reading raises IsADirectoryError
        os.chmod(self.token_path, 0o700)
        self.assert_provider_fails("UPS_DELEGATED_TOKEN_UNAVAILABLE")

    def test_expired_or_nearly_expired_token_is_expired(self) -> None:
        now = 1_800_000_000.0
        for expires_at in (now - 100, now, now + 29, now + 30):
            with self.subTest(expires_at=expires_at):
                self.write_token_file({"access_token": TOKEN, "expires_at": expires_at})
                with mock.patch("ups_mcp.authorization.time.time", return_value=now):
                    self.assert_provider_fails("UPS_DELEGATED_TOKEN_EXPIRED")

        self.write_token_file({"access_token": TOKEN, "expires_at": now + 31})
        with mock.patch("ups_mcp.authorization.time.time", return_value=now):
            self.assertEqual(self.provider.get_access_token(), TOKEN)

    def test_rotated_file_is_picked_up_without_restart(self) -> None:
        self.write_valid_token(TOKEN)
        self.assertEqual(self.provider.get_access_token(), TOKEN)
        self.write_valid_token(ROTATED_TOKEN)
        self.assertEqual(self.provider.get_access_token(), ROTATED_TOKEN)

    def test_repr_names_basename_only(self) -> None:
        self.write_valid_token()
        self.provider.get_access_token()
        text = repr(self.provider)
        self.assertIn("ups-token.json", text)
        self.assertNotIn(self.tmpdir, text)
        self.assertNotIn(TOKEN, text)


@mock.patch("requests.post")
@mock.patch("requests.request")
class DelegatedHTTPClientTests(TokenFileTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.client = UPSHTTPClient(
            base_url="https://wwwcie.ups.com",
            token_provider=DelegatedTokenFile(self.token_path),
        )
        self.operation = build_operation_spec()

    def call(self) -> dict:
        return self.client.call_operation(
            self.operation,
            operation_name="create_shipment",
            path_params={"version": "v2409"},
            json_body={"ShipmentRequest": {}},
        )

    def test_sends_file_token_as_bearer(self, mock_request: mock.Mock, mock_post: mock.Mock) -> None:
        self.write_valid_token()
        mock_request.return_value = make_response(200, {"ok": True})

        self.assertEqual(self.call(), {"ok": True})

        headers = mock_request.call_args.kwargs["headers"]
        self.assertEqual(headers["Authorization"], f"Bearer {TOKEN}")
        mock_post.assert_not_called()

    def test_token_file_failures_make_no_http_calls(
        self, mock_request: mock.Mock, mock_post: mock.Mock
    ) -> None:
        future = time.time() + 3600
        cases = [
            ("missing", None, 0o600, "UPS_DELEGATED_TOKEN_UNAVAILABLE"),
            ("world_readable", {"access_token": TOKEN, "expires_at": future}, 0o644,
             "UPS_DELEGATED_TOKEN_INSECURE"),
            ("bad_json", "{oops", 0o600, "UPS_DELEGATED_TOKEN_INVALID"),
            ("empty_token", {"access_token": "", "expires_at": future}, 0o600,
             "UPS_DELEGATED_TOKEN_INVALID"),
            ("expired", {"access_token": TOKEN, "expires_at": time.time() - 1}, 0o600,
             "UPS_DELEGATED_TOKEN_EXPIRED"),
        ]
        for name, payload, mode, code in cases:
            with self.subTest(case=name):
                if os.path.exists(self.token_path):
                    os.remove(self.token_path)
                if payload is not None:
                    self.write_token_file(payload, mode=mode)
                with self.assertRaises(ToolError) as ctx:
                    self.call()
                self.assert_tool_error_code(ctx.exception, code)
                self.assertNotIn(TOKEN, str(ctx.exception))
        mock_request.assert_not_called()
        mock_post.assert_not_called()

    def test_rotation_between_calls_uses_new_token(
        self, mock_request: mock.Mock, mock_post: mock.Mock
    ) -> None:
        mock_request.return_value = make_response(200, {"ok": True})

        self.write_valid_token(TOKEN)
        self.call()
        self.write_valid_token(ROTATED_TOKEN)
        self.call()

        sent = [c.kwargs["headers"]["Authorization"] for c in mock_request.call_args_list]
        self.assertEqual(sent, [f"Bearer {TOKEN}", f"Bearer {ROTATED_TOKEN}"])
        mock_post.assert_not_called()

    def test_ups_401_is_rejected_and_scrubbed(self, mock_request: mock.Mock, mock_post: mock.Mock) -> None:
        self.write_valid_token()
        mock_request.return_value = make_response(401, {
            "response": {
                "errors": [{"code": "250002", "message": f"Invalid Authentication Information: {TOKEN}"}],
            },
            "echo": {"Authorization": f"Bearer {TOKEN}", TOKEN: [f"prefix-{TOKEN}"]},
        })

        with self.assertRaises(ToolError) as ctx:
            self.call()

        raised = str(ctx.exception)
        self.assertNotIn(TOKEN, raised)
        self.assertNotIn(TOKEN, repr(ctx.exception))
        payload = json.loads(raised)
        self.assertEqual(payload["status_code"], 401)
        self.assertEqual(payload["code"], "UPS_DELEGATED_TOKEN_REJECTED")
        self.assertEqual(payload["message"], "Invalid Authentication Information: [REDACTED]")
        self.assertEqual(payload["details"]["echo"]["Authorization"], "Bearer [REDACTED]")
        self.assertEqual(mock_request.call_count, 1)  # no retry inside ups-mcp
        mock_post.assert_not_called()

    def test_request_exception_is_scrubbed_and_unchained(
        self, mock_request: mock.Mock, mock_post: mock.Mock
    ) -> None:
        self.write_valid_token()
        failure = requests.ConnectionError(f"connection reset; Authorization: Bearer {TOKEN}")
        failure.request = mock.Mock(headers={"Authorization": f"Bearer {TOKEN}"})
        mock_request.side_effect = failure

        with self.assertRaises(ToolError) as ctx:
            self.call()

        payload = self.assert_tool_error_code(ctx.exception, "REQUEST_ERROR")
        self.assertIn("[REDACTED]", payload["message"])
        self.assert_unchained(ctx.exception, TOKEN)

    def test_numeric_token_echoed_as_number_is_scrubbed(
        self, mock_request: mock.Mock, mock_post: mock.Mock
    ) -> None:
        numeric_token = "8675309123456"
        self.write_valid_token(numeric_token)
        mock_request.return_value = make_response(401, {"echo": int(numeric_token), "code": int(numeric_token)})

        with self.assertRaises(ToolError) as ctx:
            self.call()

        self.assertNotIn(numeric_token, str(ctx.exception))
        self.assertEqual(json.loads(str(ctx.exception))["code"], "UPS_DELEGATED_TOKEN_REJECTED")

    def test_token_inside_longer_number_is_scrubbed(
        self, mock_request: mock.Mock, mock_post: mock.Mock
    ) -> None:
        numeric_token = "1234567890123456"
        self.write_valid_token(numeric_token)
        mock_request.return_value = make_response(401, {"echo": int("9" + numeric_token + "8")})

        with self.assertRaises(ToolError) as ctx:
            self.call()

        self.assertNotIn(numeric_token, str(ctx.exception))

    def test_non_string_error_code_echoing_token_is_scrubbed(
        self, mock_request: mock.Mock, mock_post: mock.Mock
    ) -> None:
        self.write_valid_token()
        mock_request.return_value = make_response(400, {"code": {"echo": f"Bearer {TOKEN}"}})

        with self.assertRaises(ToolError) as ctx:
            self.call()

        payload = json.loads(str(ctx.exception))
        self.assertNotIn(TOKEN, str(ctx.exception))
        self.assertIn("[REDACTED]", payload["code"])

    def test_token_matching_a_response_key_keeps_ups_message(
        self, mock_request: mock.Mock, mock_post: mock.Mock
    ) -> None:
        self.write_valid_token("message")
        mock_request.return_value = make_response(401, {"message": "Invalid Authentication Information."})

        with self.assertRaises(ToolError) as ctx:
            self.call()

        payload = json.loads(str(ctx.exception))
        self.assertEqual(payload["message"], "Invalid Authentication Information.")
        self.assertEqual(payload["code"], "UPS_DELEGATED_TOKEN_REJECTED")

    def test_token_inside_redaction_marker_uses_fallback(
        self, mock_request: mock.Mock, mock_post: mock.Mock
    ) -> None:
        self.write_valid_token("REDACTED")
        mock_request.return_value = make_response(401, {"message": "Bad token REDACTED"})

        with self.assertRaises(ToolError) as ctx:
            self.call()

        payload = json.loads(str(ctx.exception))
        self.assertNotIn("REDACTED", payload["message"])
        self.assertNotIn("REDACTED", json.dumps(payload["details"]))

    def test_token_echoed_as_json_literal_is_scrubbed(
        self, mock_request: mock.Mock, mock_post: mock.Mock
    ) -> None:
        for literal_token, echoed in (("true", True), ("null", None)):
            with self.subTest(token=literal_token):
                self.write_valid_token(literal_token)
                mock_request.return_value = make_response(401, {"echo": echoed})

                with self.assertRaises(ToolError) as ctx:
                    self.call()

                self.assertEqual(json.loads(str(ctx.exception))["details"]["echo"], "[REDACTED]")

    def test_provider_reassigned_mid_request_keeps_delegated_handling(
        self, mock_request: mock.Mock, mock_post: mock.Mock
    ) -> None:
        self.write_valid_token()

        def swap_provider_then_reject(**kwargs):  # noqa: ANN003
            self.client.oauth_manager = DummyOAuthManager()
            return make_response(401, {"message": f"Invalid token {TOKEN}"})

        mock_request.side_effect = swap_provider_then_reject

        with self.assertRaises(ToolError) as ctx:
            self.call()

        payload = json.loads(str(ctx.exception))
        self.assertEqual(payload["code"], "UPS_DELEGATED_TOKEN_REJECTED")
        self.assertNotIn(TOKEN, str(ctx.exception))

    def test_token_overlapping_rejected_code_leaves_code_intact(
        self, mock_request: mock.Mock, mock_post: mock.Mock
    ) -> None:
        self.write_valid_token("TOKEN")
        mock_request.return_value = make_response(401, {"message": "Invalid token TOKEN"})

        with self.assertRaises(ToolError) as ctx:
            self.call()

        payload = json.loads(str(ctx.exception))
        self.assertEqual(payload["code"], "UPS_DELEGATED_TOKEN_REJECTED")
        self.assertEqual(payload["message"], "Invalid token [REDACTED]")

    def test_non_401_errors_keep_ups_code_but_are_scrubbed(
        self, mock_request: mock.Mock, mock_post: mock.Mock
    ) -> None:
        self.write_valid_token()
        mock_request.return_value = make_response(400, {
            "response": {"errors": [{"code": "120100", "message": f"Bad request {TOKEN}"}]},
        })

        with self.assertRaises(ToolError) as ctx:
            self.call()

        payload = json.loads(str(ctx.exception))
        self.assertEqual(payload["code"], "400")
        self.assertNotIn(TOKEN, str(ctx.exception))

    def test_extracted_error_code_echoing_token_is_scrubbed(
        self, mock_request: mock.Mock, mock_post: mock.Mock
    ) -> None:
        self.write_valid_token()
        mock_request.return_value = make_response(403, {"code": TOKEN, "message": "Forbidden"})

        with self.assertRaises(ToolError) as ctx:
            self.call()

        self.assertNotIn(TOKEN, str(ctx.exception))
        self.assertEqual(json.loads(str(ctx.exception))["code"], "[REDACTED]")


class DelegatedNetrcTests(TokenFileTestCase):
    """Exercises real request preparation, which mocking requests.request would skip."""

    def setUp(self) -> None:
        super().setUp()
        self.write_valid_token()
        netrc_path = os.path.join(self.tmpdir, "netrc")
        with open(netrc_path, "w") as handle:
            handle.write("machine wwwcie.ups.com login netrc-user password netrc-pass\n")
        os.chmod(netrc_path, 0o600)
        self.netrc_path = netrc_path
        self.client = UPSHTTPClient("https://wwwcie.ups.com", token_provider=DelegatedTokenFile(self.token_path))

    def send_with_netrc(self, status_code: int, headers: dict[str, str] | None = None):  # noqa: ANN201
        sent: list[requests.PreparedRequest] = []

        def fake_send(adapter, request, **kwargs):  # noqa: ANN001, ANN003
            sent.append(request)
            response = requests.Response()
            response.status_code = status_code
            response.headers.update(headers or {})
            response._content = b'{"ok": true}'
            response.request = request
            response.url = request.url
            return response

        with mock.patch.dict(os.environ, {"NETRC": self.netrc_path}), \
                mock.patch("requests.adapters.HTTPAdapter.send", fake_send), \
                mock.patch("requests.post") as mock_post:
            try:
                result = self.client.call_operation(build_operation_spec(), operation_name="create_shipment",
                                                    path_params={"version": "v2409"}, json_body={})
            except ToolError as exc:
                result = exc
        mock_post.assert_not_called()
        return sent, result

    def test_netrc_credentials_do_not_replace_bearer_token(self) -> None:
        sent, result = self.send_with_netrc(200)

        self.assertEqual(result, {"ok": True})
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0].headers["Authorization"], f"Bearer {TOKEN}")

    def test_same_host_redirect_is_not_followed(self) -> None:
        sent, result = self.send_with_netrc(307, {"Location": "https://wwwcie.ups.com/api/shipments/v2409/ship2"})

        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0].headers["Authorization"], f"Bearer {TOKEN}")
        self.assertIsInstance(result, ToolError)
        self.assertEqual(json.loads(str(result))["status_code"], 307)


class ClientCredentialsHTTPClientTests(unittest.TestCase):
    @mock.patch("requests.request")
    def test_top_level_errors_message_unchanged(self, mock_request: mock.Mock) -> None:
        mock_request.return_value = make_response(401, {"errors": [{"message": "Invalid token"}]})
        client = UPSHTTPClient("https://wwwcie.ups.com", token_provider=DummyOAuthManager())

        with self.assertRaises(ToolError) as ctx:
            client.call_operation(build_operation_spec(), operation_name="create_shipment",
                                  path_params={"version": "v2409"})

        self.assertEqual(json.loads(str(ctx.exception))["message"], "UPS API returned HTTP 401")

    @mock.patch("requests.request")
    def test_plain_text_401_message_unchanged(self, mock_request: mock.Mock) -> None:
        mock_request.return_value = make_response(401, "Token expired")
        client = UPSHTTPClient("https://wwwcie.ups.com", token_provider=DummyOAuthManager())

        with self.assertRaises(ToolError) as ctx:
            client.call_operation(build_operation_spec(), operation_name="create_shipment",
                                  path_params={"version": "v2409"})

        self.assertEqual(json.loads(str(ctx.exception))["message"], "UPS API returned HTTP 401")

    @mock.patch("requests.request")
    def test_request_error_still_chains_original_exception(self, mock_request: mock.Mock) -> None:
        failure = requests.ConnectionError("connection refused")
        mock_request.side_effect = failure
        client = UPSHTTPClient("https://wwwcie.ups.com", token_provider=DummyOAuthManager())

        with self.assertRaises(ToolError) as ctx:
            client.call_operation(build_operation_spec(), operation_name="create_shipment",
                                  path_params={"version": "v2409"})

        self.assertEqual(json.loads(str(ctx.exception)), {"code": "REQUEST_ERROR", "message": "connection refused"})
        self.assertIs(ctx.exception.__context__, failure)

    def test_oauth_manager_keyword_and_attribute_still_work(self) -> None:
        manager = DummyOAuthManager()
        client = UPSHTTPClient("https://wwwcie.ups.com", oauth_manager=manager)
        self.assertIs(client.oauth_manager, manager)
        self.assertIs(client.token_provider, manager)

    @mock.patch("requests.request")
    def test_assigning_oauth_manager_replaces_provider(self, mock_request: mock.Mock) -> None:
        mock_request.return_value = make_response(200, {"ok": True})
        client = UPSHTTPClient("https://wwwcie.ups.com", oauth_manager=DummyOAuthManager("old-token"))

        client.oauth_manager = DummyOAuthManager("new-token")
        client.call_operation(build_operation_spec(), operation_name="create_shipment",
                              path_params={"version": "v2409"})

        self.assertEqual(mock_request.call_args.kwargs["headers"]["Authorization"], "Bearer new-token")


    @mock.patch("requests.request")
    def test_401_keeps_existing_error_shape(self, mock_request: mock.Mock) -> None:
        details = {"response": {"errors": [{"code": "250002", "message": "Invalid Authentication Information."}]}}
        mock_request.return_value = make_response(401, details)
        client = UPSHTTPClient(base_url="https://wwwcie.ups.com", token_provider=DummyOAuthManager())

        with self.assertRaises(ToolError) as ctx:
            client.call_operation(build_operation_spec(), operation_name="create_shipment",
                                  path_params={"version": "v2409"})

        self.assertEqual(json.loads(str(ctx.exception)), {
            "status_code": 401,
            "code": "401",
            "message": "Invalid Authentication Information.",
            "details": details,
        })


@mock.patch("requests.post")
@mock.patch("requests.request")
class DelegatedToolManagerTests(TokenFileTestCase):
    """Rate and ship both go through the shared HTTP path with the delegated token."""

    def setUp(self) -> None:
        super().setUp()
        self.write_valid_token()
        with mock.patch("ups_mcp.tools.OAuthManager") as mock_oauth:
            self.manager = ToolManager(
                base_url=constants.CIE_URL,
                client_id="app-client-id",
                client_secret=None,
                account_number="129D9Y",
                token_provider=DelegatedTokenFile(self.token_path),
            )
        mock_oauth.assert_not_called()

    def assert_single_delegated_call(self, mock_request: mock.Mock, mock_post: mock.Mock, path: str) -> None:
        self.assertEqual(mock_request.call_count, 1)
        kwargs = mock_request.call_args.kwargs
        self.assertEqual(kwargs["url"], f"{constants.CIE_URL}/api{path}")
        self.assertEqual(kwargs["headers"]["Authorization"], f"Bearer {TOKEN}")
        mock_post.assert_not_called()

    def test_rate_shipment_uses_delegated_token(self, mock_request: mock.Mock, mock_post: mock.Mock) -> None:
        mock_request.return_value = make_response(200, {"RateResponse": {}})

        self.manager.rate_shipment(requestoption="shop", request_body={"RateRequest": {}})

        self.assert_single_delegated_call(mock_request, mock_post, "/rating/v2409/Shop")

    def test_create_shipment_uses_delegated_token(self, mock_request: mock.Mock, mock_post: mock.Mock) -> None:
        mock_request.return_value = make_response(200, {"ShipmentResponse": {}})

        self.manager.create_shipment(request_body={"ShipmentRequest": {}})

        self.assert_single_delegated_call(mock_request, mock_post, "/shipments/v2409/ship")


class DelegatedServerConfigTests(unittest.TestCase):
    _GLOBALS = ("base_url", "client_id", "client_secret", "auth_mode", "access_token_file", "tool_manager")

    def setUp(self) -> None:
        saved = {name: getattr(server, name) for name in self._GLOBALS}
        self.addCleanup(lambda: [setattr(server, k, v) for k, v in saved.items()])

    def configure(self, env: dict[str, str]) -> None:
        with mock.patch.dict(os.environ, env, clear=True):
            server._refresh_runtime_configuration()

    def assert_startup_rejected(self, env: dict[str, str], expected_message: str) -> None:
        stderr = io.StringIO()
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch("ups_mcp.server.mcp.run") as mock_run, \
                mock.patch("ups_mcp.server.tools.ToolManager") as mock_tool_manager, \
                contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as ctx:
                server.main()
        self.assertEqual(ctx.exception.code, 1)
        self.assertIn(expected_message, stderr.getvalue())
        mock_tool_manager.assert_not_called()
        mock_run.assert_not_called()

    def test_default_mode_is_client_credentials(self) -> None:
        self.configure({"CLIENT_ID": "id", "CLIENT_SECRET": "secret"})
        self.assertEqual(server.auth_mode, constants.AUTH_MODE_CLIENT_CREDENTIALS)
        server._validate_runtime_configuration()

    def test_client_credentials_mode_still_requires_credentials(self) -> None:
        self.configure({"UPS_AUTH_MODE": "client_credentials"})
        with self.assertRaises(RuntimeError):
            server._validate_runtime_configuration()

    def test_delegated_with_client_secret_is_rejected(self) -> None:
        self.assert_startup_rejected(
            {"UPS_AUTH_MODE": "delegated", "UPS_ACCESS_TOKEN_FILE": "/run/ups/token.json",
             "CLIENT_SECRET": "app-secret"},
            "delegated mode must not receive CLIENT_SECRET",
        )

    def test_delegated_with_empty_client_secret_is_rejected(self) -> None:
        self.assert_startup_rejected(
            {"UPS_AUTH_MODE": "delegated", "UPS_ACCESS_TOKEN_FILE": "/run/ups/token.json",
             "CLIENT_SECRET": ""},
            "delegated mode must not receive CLIENT_SECRET",
        )

    def test_empty_mode_is_rejected(self) -> None:
        self.assert_startup_rejected(
            {"UPS_AUTH_MODE": "", "CLIENT_ID": "id", "CLIENT_SECRET": "secret"},
            "Unknown UPS_AUTH_MODE",
        )

    def test_client_secret_reported_before_bad_token_path(self) -> None:
        for path_env in ({}, {"UPS_ACCESS_TOKEN_FILE": "relative/token.json"}):
            with self.subTest(path_env=path_env):
                self.assert_startup_rejected(
                    {"UPS_AUTH_MODE": "delegated", "CLIENT_SECRET": "app-secret", **path_env},
                    "delegated mode must not receive CLIENT_SECRET",
                )

    def test_delegated_without_token_file_is_rejected(self) -> None:
        self.assert_startup_rejected({"UPS_AUTH_MODE": "delegated"}, "UPS_ACCESS_TOKEN_FILE")

    def test_delegated_with_relative_token_file_is_rejected(self) -> None:
        self.assert_startup_rejected(
            {"UPS_AUTH_MODE": "delegated", "UPS_ACCESS_TOKEN_FILE": "run/ups/token.json"},
            "absolute path",
        )

    def test_unknown_mode_is_rejected(self) -> None:
        self.assert_startup_rejected(
            {"UPS_AUTH_MODE": "authorization_code", "CLIENT_ID": "id", "CLIENT_SECRET": "secret"},
            "Unknown UPS_AUTH_MODE",
        )

    def test_importing_server_does_not_read_dotenv(self) -> None:
        with open(server.__file__) as handle:
            tree = ast.parse(handle.read())
        module_level_calls = [
            node.value.func.id
            for node in tree.body
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
        ]
        self.assertNotIn("load_dotenv", module_level_calls)

    def test_delegated_startup_ignores_dotenv_with_client_secret(self) -> None:
        tmpdir = tempfile.mkdtemp(prefix="ups-mcp-dotenv-")
        self.addCleanup(shutil.rmtree, tmpdir, ignore_errors=True)
        dotenv_path = os.path.join(tmpdir, ".env")
        with open(dotenv_path, "w") as handle:
            handle.write("CLIENT_SECRET=leaked-app-secret\nUPS_MCP_DOTENV_SENTINEL=1\n")
        real_load = mock.Mock(side_effect=lambda *a, **k: dotenv.load_dotenv(dotenv_path))
        env = {
            "UPS_AUTH_MODE": "delegated",
            "UPS_ACCESS_TOKEN_FILE": "/nonexistent/ups-mcp/token.json",
            "CLIENT_ID": "app-client-id",
        }
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch("ups_mcp.server.load_dotenv", real_load), \
                mock.patch("ups_mcp.server.mcp.run") as mock_run, \
                contextlib.redirect_stdout(io.StringIO()):
            server.main()
            self.assertNotIn("CLIENT_SECRET", os.environ)
            self.assertNotIn("UPS_MCP_DOTENV_SENTINEL", os.environ)

        real_load.assert_not_called()
        mock_run.assert_called_once()

    def test_client_credentials_startup_still_loads_dotenv(self) -> None:
        env = {"CLIENT_ID": "id", "CLIENT_SECRET": "secret"}
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch("ups_mcp.server.load_dotenv") as mock_load, \
                mock.patch("ups_mcp.server.mcp.run"), \
                mock.patch("ups_mcp.server.tools.ToolManager"), \
                contextlib.redirect_stdout(io.StringIO()):
            server.main()
        mock_load.assert_called_once_with()

    def test_client_credentials_startup_uses_credentials_from_real_dotenv(self) -> None:
        tmpdir = tempfile.mkdtemp(prefix="ups-mcp-dotenv-")
        self.addCleanup(shutil.rmtree, tmpdir, ignore_errors=True)
        dotenv_path = os.path.join(tmpdir, ".env")
        with open(dotenv_path, "w") as handle:
            handle.write("CLIENT_ID=dotenv-client-id\nCLIENT_SECRET=dotenv-client-secret\n")
        # Point main()'s load_dotenv() at a real file; parsing and os.environ
        # population are python-dotenv's real code.
        load_from_tmp = mock.Mock(side_effect=lambda *a, **k: dotenv.load_dotenv(dotenv_path))
        with mock.patch.dict(os.environ, {}, clear=True), \
                mock.patch("ups_mcp.server.load_dotenv", load_from_tmp), \
                mock.patch("ups_mcp.server.mcp.run") as mock_run, \
                mock.patch("ups_mcp.server.tools.ToolManager") as mock_tool_manager, \
                contextlib.redirect_stdout(io.StringIO()):
            server.main()

        load_from_tmp.assert_called_once_with()
        mock_run.assert_called_once()
        kwargs = mock_tool_manager.call_args.kwargs
        self.assertEqual(kwargs["client_id"], "dotenv-client-id")
        self.assertEqual(kwargs["client_secret"], "dotenv-client-secret")
        self.assertNotIn("token_provider", kwargs)

    def test_delegated_starts_without_token_file_and_never_builds_oauth(self) -> None:
        env = {
            "UPS_AUTH_MODE": "delegated",
            "UPS_ACCESS_TOKEN_FILE": "/nonexistent/ups-mcp/token.json",
            "CLIENT_ID": "app-client-id",
            "ENVIRONMENT": "production",
            "UPS_ACCOUNT_NUMBER": "129D9Y",
        }
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch("ups_mcp.server.mcp.run") as mock_run, \
                mock.patch("ups_mcp.tools.OAuthManager") as mock_oauth, \
                contextlib.redirect_stdout(io.StringIO()):
            server.main()

        mock_run.assert_called_once()
        mock_oauth.assert_not_called()
        self.assertEqual(server.tool_manager.base_url, constants.PRODUCTION_URL)
        self.assertEqual(server.tool_manager.account_number, "129D9Y")
        provider = server.tool_manager.http_client.token_provider
        self.assertIsInstance(provider, DelegatedTokenFile)
        self.assertEqual(provider.path, "/nonexistent/ups-mcp/token.json")



@mock.patch("requests.post")
@mock.patch("requests.request")
class DelegatedMCPBoundaryTests(TokenFileTestCase, unittest.IsolatedAsyncioTestCase):
    """Errors as an MCP client sees them over tools/call."""

    def setUp(self) -> None:
        super().setUp()
        saved = server.tool_manager
        self.addCleanup(setattr, server, "tool_manager", saved)
        server.tool_manager = ToolManager(
            base_url=constants.CIE_URL,
            client_id=None,
            client_secret=None,
            token_provider=DelegatedTokenFile(self.token_path),
        )

    async def call_tool_text(self, name: str, arguments: dict) -> str:
        async with create_connected_server_and_client_session(server.mcp._mcp_server) as client:
            result = await client.call_tool(name, arguments)
        self.assertTrue(result.isError)
        return result.content[0].text

    async def test_missing_token_file_returns_parseable_json(
        self, mock_request: mock.Mock, mock_post: mock.Mock
    ) -> None:
        text = await self.call_tool_text("track_package", {"inquiryNumber": "1Z12345E0205271688"})

        self.assertEqual(json.loads(text)["code"], "UPS_DELEGATED_TOKEN_UNAVAILABLE")
        mock_request.assert_not_called()
        mock_post.assert_not_called()

    async def test_ups_401_returns_parseable_scrubbed_json(
        self, mock_request: mock.Mock, mock_post: mock.Mock
    ) -> None:
        self.write_valid_token()
        mock_request.return_value = make_response(401, {
            "response": {"errors": [{"code": "250002", "message": f"Invalid token {TOKEN}"}]},
        })

        text = await self.call_tool_text("track_package", {"inquiryNumber": "1Z12345E0205271688"})

        payload = json.loads(text)
        self.assertEqual(payload["status_code"], 401)
        self.assertEqual(payload["code"], "UPS_DELEGATED_TOKEN_REJECTED")
        self.assertNotIn(TOKEN, text)
        mock_post.assert_not_called()

    async def test_ups_401_with_top_level_errors_keeps_ups_message(
        self, mock_request: mock.Mock, mock_post: mock.Mock
    ) -> None:
        self.write_valid_token()
        mock_request.return_value = make_response(401, {
            "errors": [{"code": "250002", "message": f"Invalid customer token {TOKEN}"}],
        })

        text = await self.call_tool_text("track_package", {"inquiryNumber": "1Z12345E0205271688"})

        payload = json.loads(text)
        self.assertEqual(payload["code"], "UPS_DELEGATED_TOKEN_REJECTED")
        self.assertEqual(payload["message"], "Invalid customer token [REDACTED]")
        self.assertNotIn(TOKEN, text)

    async def test_ups_401_with_plain_text_body_keeps_ups_message(
        self, mock_request: mock.Mock, mock_post: mock.Mock
    ) -> None:
        self.write_valid_token()
        mock_request.return_value = make_response(401, f"Token expired or invalid: {TOKEN}")

        text = await self.call_tool_text("track_package", {"inquiryNumber": "1Z12345E0205271688"})

        payload = json.loads(text)
        self.assertEqual(payload["code"], "UPS_DELEGATED_TOKEN_REJECTED")
        self.assertEqual(payload["message"], "Token expired or invalid: [REDACTED]")
        self.assertNotIn(TOKEN, text)

    async def test_ups_401_message_found_past_entries_without_one(
        self, mock_request: mock.Mock, mock_post: mock.Mock
    ) -> None:
        self.write_valid_token()
        for body in (
            {"response": {"errors": [{"code": "250002"}, {"message": "Token expired"}]}},
            {"errors": [{"code": "250002"}, {"message": "Token expired"}]},
            {"response": {
                "errors": [{"code": "250002"}, {"message": "Token expired"}],
                "status": {"description": "Failure"},
            }},
        ):
            with self.subTest(body=body):
                mock_request.return_value = make_response(401, body)

                text = await self.call_tool_text("track_package", {"inquiryNumber": "1Z12345E0205271688"})

                self.assertEqual(json.loads(text)["message"], "Token expired")

    async def test_ups_401_with_json_string_body_keeps_ups_message(
        self, mock_request: mock.Mock, mock_post: mock.Mock
    ) -> None:
        self.write_valid_token()
        response = requests.Response()  # real Response, so .json() really parses the string
        response.status_code = 401
        response._content = json.dumps(f"Invalid Authentication Information. {TOKEN}").encode()
        mock_request.return_value = response

        text = await self.call_tool_text("track_package", {"inquiryNumber": "1Z12345E0205271688"})

        payload = json.loads(text)
        self.assertEqual(payload["code"], "UPS_DELEGATED_TOKEN_REJECTED")
        self.assertEqual(payload["message"], "Invalid Authentication Information. [REDACTED]")
        self.assertNotIn(TOKEN, text)

    async def test_other_errors_keep_fastmcp_prefix(
        self, mock_request: mock.Mock, mock_post: mock.Mock
    ) -> None:
        self.write_valid_token()
        mock_request.return_value = make_response(404, {"message": "Not found"})

        text = await self.call_tool_text("track_package", {"inquiryNumber": "1Z12345E0205271688"})

        self.assertTrue(text.startswith("Error executing tool track_package: "))


if __name__ == "__main__":
    unittest.main()
