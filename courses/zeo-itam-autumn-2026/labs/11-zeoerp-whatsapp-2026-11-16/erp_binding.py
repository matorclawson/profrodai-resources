"""Bind shop tool calls to the current channel turn, before the MCP transport.

This is a mockable policy component. The admitted transport must additionally
validate the complete producer schemas and MCP structured/text agreement. The
ERP independently verifies the provider record and canonical prompt history;
the context header below is correlation input, never authentication.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Callable, Protocol

from channel_journal import ChannelJournal
from channel_runtime import HeldOutcome, current_binding

MUTATIONS = frozenset({
    "create_draft_order", "confirm_order", "cancel_order", "request_human_handoff",
})
READS = frozenset({"list_products", "check_stock", "order_status", "my_orders", "operation_status"})


class ERPPort(Protocol):
    """A paired transport that validates full MCP input/output schemas."""

    async def call(self, tool: str, arguments: dict, *, context_header: str) -> dict: ...


def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def arguments_for(tool: str, arguments: dict) -> dict:
    """Validate the nine closed input shapes without accepting model context."""
    fields = {
        "list_products": (set(), {"query", "limit", "cursor"}),
        "check_stock": ({"lines"}, {"lines"}),
        "create_draft_order": ({"lines"}, {"lines"}),
        "confirm_order": ({"order_id", "draft_version"}, {"order_id", "draft_version"}),
        "order_status": ({"order_id"}, {"order_id"}),
        "cancel_order": ({"order_id", "expected_version"}, {"order_id", "expected_version"}),
        "my_orders": (set(), {"limit", "cursor", "state"}),
        "request_human_handoff": (set(), {"order_id", "reason"}),
        "operation_status": ({"operation_id"}, {"operation_id"}),
    }
    if tool not in fields or type(arguments) is not dict:
        raise ValueError("Unknown tool or invalid arguments")
    required, allowed = fields[tool]
    if not required <= arguments.keys() or not arguments.keys() <= allowed:
        raise ValueError("Missing or unexpected tool arguments")
    # Copy before awaiting: the caller cannot change an admitted payload.
    value = json.loads(canonical(arguments))
    for key, item in value.items():
        if key in {"draft_version", "expected_version", "limit"}:
            maximum = 50 if key == "limit" else 2147483647
            if type(item) is not int or not 1 <= item <= maximum:
                raise ValueError("Invalid bounded integer")
        elif key in {"order_id", "operation_id"}:
            prefix = "ord" if key == "order_id" else "op"
            if not isinstance(item, str) or not re.fullmatch(prefix + r"_[0-9a-f]{24}", item):
                raise ValueError("Invalid object ID")
        elif key in {"query", "cursor"}:
            if not isinstance(item, str) or len(item) > (100 if key == "query" else 256):
                raise ValueError("Invalid bounded string")
        elif key == "state" and item not in {"draft", "confirmed", "fulfilled", "cancelled"}:
            raise ValueError("Invalid order state")
        elif key == "reason" and item not in {"customer_request", "order_exception", "delivery_question"}:
            raise ValueError("Invalid handoff reason")
        elif key == "lines":
            if not isinstance(item, list) or not 1 <= len(item) <= 25:
                raise ValueError("Invalid order lines")
            for line in item:
                if type(line) is not dict or set(line) != {"product_id", "quantity"}:
                    raise ValueError("Invalid order line")
                if not isinstance(line["product_id"], str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", line["product_id"]):
                    raise ValueError("Invalid product ID")
                if type(line["quantity"]) is not int or not 1 <= line["quantity"] <= 1000:
                    raise ValueError("Invalid quantity")
    return value


def business_envelope(tool: str, response: dict) -> dict:
    """Apply consumer invariants after the port's full schema validation."""
    if type(response) is not dict or set(response) != {"success", "data"} or response["success"] is not True:
        raise HeldOutcome("ERP adapter did not return a business envelope")
    envelope = response["data"]
    if type(envelope) is not dict or type(envelope.get("ok")) is not bool:
        raise HeldOutcome("Invalid business envelope")
    phase = envelope.get("state")
    if phase not in {"completed", "pending", "unknown", "refused"} or envelope["ok"] != (phase == "completed"):
        raise HeldOutcome("Inconsistent business completion")
    if phase in {"pending", "unknown"} or (phase == "completed" and tool in MUTATIONS):
        if not re.fullmatch(r"op_[0-9a-f]{24}", str(envelope.get("operation_id", ""))):
            raise HeldOutcome("Missing original operation ID")
    if phase == "refused":
        error = envelope.get("error", {})
        if type(error) is not dict:
            raise HeldOutcome("Invalid refusal")
        if error.get("code") in {"NOT_FOUND", "FORBIDDEN", "UNAUTHENTICATED"} and set(error) != {"code", "message"}:
            raise HeldOutcome("Refusal disclosed another customer's identifiers")
    if phase == "completed" and tool in {"create_draft_order", "confirm_order", "cancel_order"}:
        order = envelope.get("data", {})
        wanted = {"create_draft_order": "draft", "confirm_order": "confirmed", "cancel_order": "cancelled"}[tool]
        if order.get("state") != wanted or order.get("projection", {}).get("state") != "confirmed":
            raise HeldOutcome("Business mutation or projection is incomplete")
    if tool == "operation_status" and phase == "completed":
        original = envelope.get("data", {})
        if original.get("phase") not in {"completed", "pending", "unknown", "refused"}:
            raise HeldOutcome("Original operation phase is missing")
    return envelope


class ERPBinding:
    def __init__(self, port: ERPPort, journal: ChannelJournal, *, scope: str,
                 clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
        if not scope:
            raise ValueError("An admitted company/grant scope is required")
        self.port, self.journal, self.scope, self.clock = port, journal, scope, clock
        self.journal.db.execute(
            "CREATE TABLE IF NOT EXISTS reviews (customer TEXT PRIMARY KEY, snapshot TEXT NOT NULL, source_sid TEXT NOT NULL)"
        )
        self.journal.db.execute(
            "CREATE TABLE IF NOT EXISTS mutation_holds (customer TEXT PRIMARY KEY, operation TEXT NOT NULL, operation_id TEXT)"
        )

    def _customer(self, turn) -> str:
        return hashlib.sha256(f"{self.scope}:{turn.message.sender}".encode()).hexdigest()

    def _confirmation(self, turn, arguments: dict) -> dict:
        if turn.message.text.strip().casefold() not in {"yes", "confirm"}:
            raise PermissionError("A separate exact affirmative reply is required")
        row = self.journal.db.execute(
            "SELECT snapshot, source_sid FROM reviews WHERE customer=?", (self._customer(turn),)
        ).fetchone()
        if row is None or row[1] == turn.message.message_sid:
            raise PermissionError("No prior draft review is available for this customer")
        order = json.loads(row[0])
        if order["order_id"] != arguments["order_id"] or order["version"] != arguments["draft_version"]:
            raise PermissionError("The exact reviewed draft version is required")
        prompt = order["prompt"]
        expiry = datetime.fromisoformat(order["quote"]["expires_at"].replace("Z", "+00:00"))
        if expiry.tzinfo is None or expiry <= self.clock() or prompt["delivery_state"] != "confirmed" or not prompt["send_receipt"]:
            raise PermissionError("The review prompt is unsent, uncertain, or expired")
        return {"draft_id": order["order_id"], "draft_version": order["version"],
                "prompt_event_id": prompt["event_id"], "prompt_send_receipt": prompt["send_receipt"]}

    async def call(self, tool: str, arguments: dict) -> dict:
        turn = current_binding(self.clock())
        arguments = arguments_for(tool, arguments)
        context = {
            "schema": "zeoerp.trusted-channel-context/v1", "mode": "broker_poll",
            "message_sid": turn.message.message_sid,
            "broker_execution_id": turn.message.execution_id, "tool": tool,
            "operation_discriminator": "turn-mutation" if tool in MUTATIONS else "read",
            "issued_at": self.clock().isoformat(), "deadline": turn.deadline.isoformat(),
        }
        if tool == "confirm_order":
            context["confirmation"] = self._confirmation(turn, arguments)
        operation = "erp-mutation:" + turn.message.message_sid
        attempt = None
        if tool in MUTATIONS:
            if self.journal.db.execute(
                "SELECT 1 FROM mutation_holds WHERE customer=?", (self._customer(turn),)
            ).fetchone():
                raise HeldOutcome("An earlier mutation requires original-result lookup")
            if self.clock() - turn.message.sent_at > timedelta(seconds=300):
                raise PermissionError("Message is too old for a new mutation")
            # Reserve the customer first. A crash before the message claim
            # leaves a conservative hold; no later message can bypass it.
            self.journal.db.execute(
                "INSERT INTO mutation_holds VALUES (?, ?, NULL)", (self._customer(turn), operation)
            )
            try:
                attempt = self.journal.claim(self.scope, operation, binding={
                    "customer": self._customer(turn), "tool": tool, "arguments": canonical(arguments),
                })
                if attempt.state != "START":
                    raise HeldOutcome("This message already has a mutation; look up the original outcome")
            except BaseException:
                # Nothing was dispatched by this caller. Preserve the original
                # message claim while removing only this new pre-dispatch hold.
                self.journal.db.execute(
                    "DELETE FROM mutation_holds WHERE customer=? AND operation=?",
                    (self._customer(turn), operation),
                )
                raise
        header = base64.urlsafe_b64encode(canonical(context).encode()).decode().rstrip("=")
        try:
            timeout = min(20, (turn.deadline - self.clock()).total_seconds())
            if timeout <= 0:
                raise PermissionError("Channel turn expired")
            response = await asyncio.wait_for(
                self.port.call(tool, arguments, context_header=header), timeout
            )
            current_binding(self.clock())
            envelope = business_envelope(tool, response)
            if tool == "operation_status" and envelope["state"] == "completed":
                if envelope["data"]["target_operation_id"] != arguments["operation_id"]:
                    raise HeldOutcome("Lookup returned a different operation")
                if envelope["data"]["phase"] in {"completed", "refused"}:
                    self.journal.db.execute(
                        "DELETE FROM mutation_holds WHERE customer=? AND operation_id=?",
                        (self._customer(turn), arguments["operation_id"]),
                    )
            if attempt is not None:
                if envelope["state"] == "completed":
                    self.journal.complete(self.scope, operation, attempt.ticket, envelope["operation_id"])
                else:
                    self.journal.uncertain(self.scope, operation, attempt.ticket)
                if envelope["state"] in {"completed", "refused"}:
                    self.journal.db.execute(
                        "DELETE FROM mutation_holds WHERE customer=? AND operation=?",
                        (self._customer(turn), operation),
                    )
                else:
                    self.journal.db.execute(
                        "UPDATE mutation_holds SET operation_id=? WHERE customer=? AND operation=?",
                        (envelope["operation_id"], self._customer(turn), operation),
                    )
            # ERP alone establishes authoritative prompt time, first-reply
            # ordering and provider binding. This snapshot cannot replace it.
            if tool in {"create_draft_order", "order_status"} and envelope["state"] == "completed":
                order = envelope["data"]
                if order["state"] == "draft":
                    self.journal.db.execute(
                        "INSERT OR REPLACE INTO reviews VALUES (?, ?, ?)",
                        (self._customer(turn), canonical(order), turn.message.message_sid),
                    )
            return envelope
        except BaseException:
            if attempt is not None:
                # Preserve a completed claim if subsequent local processing
                # failed; never overwrite it or mask the original exception.
                try:
                    self.journal.uncertain(self.scope, operation, attempt.ticket)
                except ValueError:
                    pass
            raise
