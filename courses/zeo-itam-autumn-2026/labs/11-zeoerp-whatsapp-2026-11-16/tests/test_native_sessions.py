"""Offline session-boundary controls, with no MCP import or socket operation."""
import asyncio
from contextlib import asynccontextmanager
import sys
import types
import unittest
from unittest.mock import patch

from native_sessions import LocalERPSettings, NativeERPSessions


class SessionsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.events = []
        self.request_changes = {}
        self.extra_attempts = 0
        self.settings = LocalERPSettings(endpoint="http://127.0.0.1:41234/mcp/",
            host="erp.local", origin=None, lifecycle_seconds=1, max_http_attempts=4)
        owner = self

        class Schemas:
            def check_remote_tools(self, tools):
                owner.events.append("schemas")
                if tools != ["frozen-seven-tools"]:
                    raise ValueError("remote schema changed")

        self.schemas = Schemas()
        self.advertised = ["frozen-seven-tools"]

        class Session:
            def __init__(self, read, write):
                owner.assertEqual((read, write), ("read", "write"))

            async def __aenter__(self):
                owner.events.append("session_enter")
                return self

            async def __aexit__(self, *_):
                owner.events.append("session_closed")

            async def initialize(self):
                owner.events.append("initialize")

            async def list_tools(self):
                owner.events.append("list_tools")
                return types.SimpleNamespace(tools=owner.advertised)

        class Client:
            def __init__(self, **kwargs):
                owner.client_kwargs = kwargs

        def transport(**kwargs):
            owner.transport_kwargs = kwargs
            return "offline-transport"

        @asynccontextmanager
        async def stream(url, **kwargs):
            owner.events.append("stream_enter")
            owner.stream_kwargs = kwargs
            kwargs["httpx_client_factory"](headers=kwargs["headers"])
            request = types.SimpleNamespace(method="POST", url=url,
                headers={k.lower(): v for k, v in kwargs["headers"].items()})
            for name, value in owner.request_changes.items():
                setattr(request, name, value)
            try:
                for _ in range(1 + owner.extra_attempts):
                    await owner.client_kwargs["event_hooks"]["request"][0](request)
                yield "read", "write"
            finally:
                owner.events.append("stream_closed")

        self.modules = {
            "httpx": types.SimpleNamespace(AsyncClient=Client,
                AsyncHTTPTransport=transport, Timeout=lambda value: value),
            "mcp": types.SimpleNamespace(ClientSession=Session),
            "mcp.client": types.ModuleType("mcp.client"),
            "mcp.client.streamable_http": types.SimpleNamespace(streamablehttp_client=stream),
        }

    async def test_checks_remote_schemas_before_exposing_session_and_closes(self):
        with patch.dict(sys.modules, self.modules), patch("native_sessions.version", return_value="1.28.1"):
            async with NativeERPSessions(self.settings, self.schemas)(context_header="verified-turn"):
                self.events.append("caller")
        self.assertLess(self.events.index("schemas"), self.events.index("caller"))
        self.assertEqual(self.events[-2:], ["session_closed", "stream_closed"])
        self.assertFalse(self.client_kwargs["follow_redirects"])
        self.assertFalse(self.client_kwargs["trust_env"])
        self.assertEqual(self.transport_kwargs, {"retries": 0, "trust_env": False})
        self.assertFalse(self.stream_kwargs["terminate_on_close"])

    async def test_schema_mismatch_never_exposes_session_and_closes_both_resources(self):
        self.advertised = ["changed-schema"]
        with patch.dict(sys.modules, self.modules), patch("native_sessions.version", return_value="1.28.1"):
            with self.assertRaisesRegex(ValueError, "remote schema"):
                async with NativeERPSessions(self.settings, self.schemas)(context_header="verified-turn"):
                    self.fail("A changed remote schema reached the caller")
        self.assertEqual(self.events[-2:], ["session_closed", "stream_closed"])

    async def test_wrong_route_or_method_refuses_before_initialize(self):
        for changes in [{"url": "http://127.0.0.1:41235/mcp/"},
                        {"url": "https://unrelated.invalid/mcp/"}, {"method": "GET"},
                        {"headers": {"host": "other.local"}}]:
            self.events.clear()
            self.request_changes = changes
            with patch.dict(sys.modules, self.modules), patch("native_sessions.version", return_value="1.28.1"):
                with self.assertRaisesRegex(PermissionError, "BOUND_ROUTE"):
                    async with NativeERPSessions(self.settings, self.schemas)(context_header="verified-turn"):
                        self.fail("An unbound request reached the caller")
            self.assertNotIn("initialize", self.events)
            self.assertEqual(self.events[-1], "stream_closed")

    async def test_attempt_cap_stops_sdk_repetition(self):
        self.extra_attempts = 4
        with patch.dict(sys.modules, self.modules), patch("native_sessions.version", return_value="1.28.1"):
            with self.assertRaisesRegex(PermissionError, "ATTEMPT_BOUND"):
                async with NativeERPSessions(self.settings, self.schemas)(context_header="verified-turn"):
                    self.fail("Repeated transport attempts reached the caller")
        self.assertNotIn("initialize", self.events)

    async def test_whole_session_deadline_closes_resources(self):
        with patch.dict(sys.modules, self.modules), patch("native_sessions.version", return_value="1.28.1"):
            with self.assertRaises(TimeoutError):
                async with NativeERPSessions(self.settings, self.schemas)(context_header="verified-turn"):
                    await asyncio.sleep(2)
        self.assertEqual(self.events[-2:], ["session_closed", "stream_closed"])

    async def test_selector_and_version_refuse_before_transport(self):
        for selector in [None, "", "line\nnext", "x" * 257]:
            with patch("native_sessions.version") as version:
                with self.assertRaises(ValueError):
                    async with NativeERPSessions(self.settings, self.schemas)(context_header=selector):
                        self.fail("Invalid selector reached the caller")
                version.assert_not_called()
        with patch.dict(sys.modules, self.modules), patch("native_sessions.version", return_value="2.3.0"):
            with self.assertRaisesRegex(RuntimeError, "PIN_CHANGED"):
                async with NativeERPSessions(self.settings, self.schemas)(context_header="verified-turn"):
                    self.fail("A different MCP API reached the caller")
        self.assertEqual(self.events, [])

    def test_settings_refuse_remote_or_credential_bearing_endpoints(self):
        for endpoint in ["https://unrelated.invalid/mcp/", "http://localhost:12/mcp/",
                         "http://user:password@127.0.0.1:12/mcp/", "http://127.0.0.1:12/mcp/?token=x",
                         "http://127.0.0.1:12/mcp/#fragment", "http://127.0.0.1:12/other"]:
            with self.assertRaises(ValueError):
                LocalERPSettings.model_validate({**self.settings.model_dump(), "endpoint": endpoint})


if __name__ == "__main__":
    unittest.main()
