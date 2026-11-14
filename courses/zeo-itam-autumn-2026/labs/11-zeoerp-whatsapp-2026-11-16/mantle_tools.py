"""Native Mantle tool functions; installed only by the paired worker launcher.

The module is an adapter source, not an installed skill or runnable launcher.
Business inputs are checked again by ERPBinding before transport dispatch.
"""

from rasa.mantle.tools.decorator import tool
from rasa.mantle.tools.result import ToolResult

from erp_binding import ERPBinding

_binding: ERPBinding | None = None


def install_binding(binding: ERPBinding) -> None:
    global _binding
    if _binding is not None or not isinstance(binding, ERPBinding):
        raise RuntimeError("An admitted ERP binding must be installed exactly once")
    _binding = binding


async def _call(name: str, arguments: dict) -> ToolResult:
    if _binding is None:
        raise RuntimeError("The paired worker has not installed an ERP transport")
    result = await _binding.call(name, arguments)
    return ToolResult(llm_response=result)


@tool(description="List available shop products and prices. This does not reserve stock.")
async def list_products(query: str = "", limit: int = 20, cursor: str | None = None) -> ToolResult:
    arguments = {"query": query, "limit": limit}
    if cursor is not None:
        arguments["cursor"] = cursor
    return await _call("list_products", arguments)


@tool(description="Check available quantities for requested products without reserving them.")
async def check_stock(lines: list[dict]) -> ToolResult:
    return await _call("check_stock", {"lines": lines})


@tool(description="Prepare a priced draft and its customer review prompt. This does not confirm the order.")
async def create_draft_order(lines: list[dict]) -> ToolResult:
    return await _call("create_draft_order", {"lines": lines})


@tool(description="Confirm the exact reviewed draft after the customer's separate affirmative reply.")
async def confirm_order(order_id: str, draft_version: int) -> ToolResult:
    return await _call("confirm_order", {"order_id": order_id, "draft_version": draft_version})


@tool(description="Read this customer's order and its current revision.")
async def order_status(order_id: str) -> ToolResult:
    return await _call("order_status", {"order_id": order_id})


@tool(description="Cancel this customer's order at the exact observed revision, if permitted.")
async def cancel_order(order_id: str, expected_version: int) -> ToolResult:
    return await _call("cancel_order", {"order_id": order_id, "expected_version": expected_version})


@tool(description="Read this customer's orders, following only their returned cursor.")
async def my_orders(limit: int = 20, cursor: str | None = None, state: str | None = None) -> ToolResult:
    arguments = {"limit": limit}
    if cursor is not None:
        arguments["cursor"] = cursor
    if state is not None:
        arguments["state"] = state
    return await _call("my_orders", arguments)


@tool(description="Request a human handoff; acceptance means notification, not a human response.")
async def request_human_handoff(order_id: str | None = None, reason: str = "customer_request") -> ToolResult:
    arguments = {"reason": reason}
    if order_id is not None:
        arguments["order_id"] = order_id
    return await _call("request_human_handoff", arguments)


@tool(description="Read the original operation's outcome. This never dispatches or retries it.")
async def operation_status(operation_id: str) -> ToolResult:
    return await _call("operation_status", {"operation_id": operation_id})
