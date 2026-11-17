"""Pinned native MCP sessions for an explicitly supplied local ERP service.

Construction performs no import of MCP, socket operation or credential lookup.
The context selector must come from the independently verified request bridge;
putting it in a header does not authenticate a customer. This module supplies
transport and schema checks, not that bridge or a runnable shop agent.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from importlib.metadata import version
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator


class LocalERPSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True,
                              revalidate_instances="always")
    endpoint: str
    host: str = Field(pattern=r"^[A-Za-z0-9.-]+(?::[0-9]{1,5})?$")
    origin: str | None
    lifecycle_seconds: int = Field(ge=1, le=60)
    max_http_attempts: int = Field(ge=4, le=16)

    @field_validator("endpoint")
    @classmethod
    def local_endpoint(cls, value):
        parsed = urlsplit(value)
        if (parsed.scheme != "http" or parsed.hostname != "127.0.0.1"
                or parsed.username is not None or parsed.password is not None
                or parsed.port is None or not 1 <= parsed.port <= 65535
                or parsed.path not in {"/mcp", "/mcp/"}
                or "?" in value or "#" in value or "\r" in value or "\n" in value):
            raise ValueError("EXPLICIT_LOCAL_ERP_ENDPOINT_REQUIRED")
        return value

    @field_validator("origin")
    @classmethod
    def exact_origin(cls, value):
        if value is None:
            return value
        parsed = urlsplit(value)
        port = parsed.port
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                or parsed.username is not None or parsed.password is not None
                or parsed.path or parsed.query or parsed.fragment
                or "\r" in value or "\n" in value or (port is not None and port == 0)):
            raise ValueError("EXACT_ERP_ORIGIN_REQUIRED")
        return value


class NativeERPSessions:
    """Initialize and check all advertised schemas before exposing a session.

    Uses the existing MCP 1.28.1 consumer API. There is no version fallback,
    environment proxy, redirect, HTTP retry or termination DELETE. The outer
    caller's request deadline still applies to the complete tool operation.
    """
    def __init__(self, settings: LocalERPSettings, schemas):
        self.settings = LocalERPSettings.model_validate(settings)
        if not callable(getattr(schemas, "check_remote_tools", None)):
            raise TypeError("FROZEN_REMOTE_SCHEMAS_REQUIRED")
        self.schemas = schemas

    @asynccontextmanager
    async def __call__(self, *, context_header):
        if (type(context_header) is not str or not 0 < len(context_header) <= 256
                or any(not 32 <= ord(char) <= 126 for char in context_header)):
            raise ValueError("VERIFIED_CONTEXT_SELECTOR_REQUIRED")
        if version("mcp") != "1.28.1":
            raise RuntimeError("CONSUMER_MCP_PIN_CHANGED")
        import httpx
        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client

        settings = self.settings
        headers = {"Host": settings.host, "X-ZeoERP-Request-ID": context_header}
        if settings.origin is not None:
            headers["Origin"] = settings.origin
        attempts = 0

        async def check_request(request):
            nonlocal attempts
            attempts += 1
            if attempts > settings.max_http_attempts:
                raise PermissionError("ERP_HTTP_ATTEMPT_BOUND_REACHED")
            if (request.method != "POST" or str(request.url) != settings.endpoint
                    or request.headers.get("host") != settings.host
                    or request.headers.get("origin") != settings.origin
                    or request.headers.get("x-zeoerp-request-id") != context_header
                    or request.headers.get("authorization") is not None):
                raise PermissionError("ERP_REQUEST_LEFT_BOUND_ROUTE")

        def client_factory(*, headers=None, timeout=None, auth=None):
            if auth is not None:
                raise PermissionError("UNREVIEWED_ERP_AUTH_STRATEGY")
            return httpx.AsyncClient(
                transport=httpx.AsyncHTTPTransport(retries=0, trust_env=False),
                headers=headers, timeout=httpx.Timeout(settings.lifecycle_seconds),
                follow_redirects=False, trust_env=False,
                event_hooks={"request": [check_request]},
            )

        async with asyncio.timeout(settings.lifecycle_seconds):
            async with streamablehttp_client(
                settings.endpoint, headers=headers,
                httpx_client_factory=client_factory, terminate_on_close=False,
            ) as streams:
                async with ClientSession(streams[0], streams[1]) as session:
                    await session.initialize()
                    listed = await session.list_tools()
                    self.schemas.check_remote_tools(listed.tools)
                    yield session
