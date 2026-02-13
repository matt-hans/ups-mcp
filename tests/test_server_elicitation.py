import unittest
from unittest.mock import MagicMock

from mcp.server.fastmcp import Context
from mcp.types import (
    ClientCapabilities,
    ElicitationCapability,
    FormElicitationCapability,
    UrlElicitationCapability,
    InitializeRequestParams,
    Implementation,
)

import ups_mcp.server as server


class CheckFormElicitationTests(unittest.TestCase):
    def _make_ctx(
        self,
        elicitation: ElicitationCapability | None = None,
    ) -> MagicMock:
        """Build a mock Context with the given elicitation capability."""
        ctx = MagicMock()
        caps = ClientCapabilities(elicitation=elicitation)
        params = InitializeRequestParams(
            protocolVersion="2025-03-26",
            capabilities=caps,
            clientInfo=Implementation(name="test", version="1.0"),
        )
        ctx.request_context.session._client_params = params
        ctx.request_context.session.client_params = params
        return ctx

    def test_none_ctx_returns_false(self) -> None:
        self.assertFalse(server._check_form_elicitation(None))

    def test_no_elicitation_capability_returns_false(self) -> None:
        ctx = self._make_ctx(elicitation=None)
        self.assertFalse(server._check_form_elicitation(ctx))

    def test_form_capability_returns_true(self) -> None:
        ctx = self._make_ctx(
            elicitation=ElicitationCapability(form=FormElicitationCapability())
        )
        self.assertTrue(server._check_form_elicitation(ctx))

    def test_empty_elicitation_object_returns_true(self) -> None:
        ctx = self._make_ctx(elicitation=ElicitationCapability())
        self.assertTrue(server._check_form_elicitation(ctx))

    def test_url_only_returns_false(self) -> None:
        ctx = self._make_ctx(
            elicitation=ElicitationCapability(url=UrlElicitationCapability())
        )
        self.assertFalse(server._check_form_elicitation(ctx))

    def test_both_form_and_url_returns_true(self) -> None:
        ctx = self._make_ctx(
            elicitation=ElicitationCapability(
                form=FormElicitationCapability(),
                url=UrlElicitationCapability(),
            )
        )
        self.assertTrue(server._check_form_elicitation(ctx))

    def test_attribute_error_returns_false(self) -> None:
        """Integration safety: if ctx has unexpected shape, return False."""
        ctx = MagicMock()
        ctx.request_context.session.client_params = None
        self.assertFalse(server._check_form_elicitation(ctx))

    def test_with_real_capability_objects(self) -> None:
        """Integration-style: use real Pydantic objects, minimal mocking."""
        ctx = MagicMock(spec=Context)
        caps = ClientCapabilities(
            elicitation=ElicitationCapability(form=FormElicitationCapability())
        )
        params = InitializeRequestParams(
            protocolVersion="2025-03-26",
            capabilities=caps,
            clientInfo=Implementation(name="real-client", version="2.0"),
        )
        ctx.request_context.session.client_params = params
        self.assertTrue(server._check_form_elicitation(ctx))


if __name__ == "__main__":
    unittest.main()
