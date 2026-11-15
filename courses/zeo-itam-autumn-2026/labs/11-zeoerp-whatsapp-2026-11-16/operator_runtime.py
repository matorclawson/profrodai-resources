"""One operator's serialized native Mantle turns, with host-owned review text.

No runtime is created on import. Real transport/producer/owner admission is an
explicit launcher input. Synthetic test clients are never live admission.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
import hashlib
import json

from pydantic import BaseModel, ConfigDict, Field

from core_binding import business_result, core_turn
from mcp_port import canonical
from operator_claims import render_review


class RunBounds(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    max_inbound_turns: int = Field(ge=1, le=8)
    turn_seconds: int = Field(ge=1, le=60)
    not_after_epoch: float = Field(gt=0, allow_inf_nan=False)


async def drain_worker(function, *args, **kwargs):
    """A cancellation never abandons a synchronous effect worker.

    The admitted transport itself must enforce its finite HTTP deadline. Caller
    cancellation shields this worker and waits for its actual terminal outcome
    before propagating, so journals cannot be closed beneath an in-flight send.
    """
    task = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                continue
            except Exception:
                break
        if task.done() and not task.cancelled():
            task.exception()  # Retrieve a retained failure without exposing it.
        raise


class OperatorRuntime:
    def __init__(self, *, claims, evidence, native_agent, bounds: RunBounds, clock):
        self.claims, self.evidence, self.agent = claims, evidence, native_agent
        self.bounds, self.clock = RunBounds.model_validate(bounds), clock
        if self.bounds.not_after_epoch > claims.run_expires:
            raise ValueError("RUN_DEADLINE_MUST_NOT_OUTLIVE_CLAIMS")
        self.busy = False
        claims.db.execute("CREATE TABLE IF NOT EXISTS native_turn_attempts ("
                          "request_id TEXT PRIMARY KEY, state TEXT NOT NULL, reply_ref TEXT)")
        if claims.db.execute("SELECT 1 FROM native_turn_attempts WHERE state<>'DONE'").fetchone():
            raise PermissionError("ORIGINAL_NATIVE_TURN_REQUIRES_AUDIT")

    def _draft_for(self, request):
        rows = self.claims.db.execute("SELECT payload_json FROM operator_drafts WHERE request_id=?",
                                      (request.request_id,)).fetchall()
        if len(rows) > 1:
            raise PermissionError("ONE_EXACT_DRAFT_REVIEW_PER_TURN")
        return json.loads(rows[0][0]) if rows else None

    def _safe_reply(self, request):
        """Business state is rendered from validated actual results, not prose.

        The model chooses tools and arguments. Host wording prevents a model
        response from asserting a commit that the actual ERP result did not show.
        """
        rows = self.claims.db.execute("SELECT c.action,r.payload_json FROM operator_calls c "
            "JOIN operator_results r ON r.selector=c.selector WHERE c.request_id=? ORDER BY c.rowid",
            (request.request_id,)).fetchall()
        if not rows:
            return "Please name the product and quantity, or ask for the available products. No order action was completed."
        action, raw = rows[-1]
        result = business_result(action, json.loads(raw))
        if not result["ok"]:
            return "The shop refused this request. No completion is claimed. Please ask the operator to inspect the retained refusal."
        if result["state"] != "completed":
            return "The original operation is pending. Its result is retained; do not submit it again."
        data = result["data"]
        if action == "list_products":
            lines = []
            for item in data:
                scale, minor = item["scale"], item["price_minor"]
                if type(scale) is not int or not 0 <= scale <= 4 or type(minor) is not int or minor < 0:
                    raise ValueError("EXACT_CATALOG_PRICE_REQUIRED")
                whole, fraction = divmod(minor, 10 ** scale)
                amount = str(whole) + (f".{fraction:0{scale}d}" if scale else "")
                lines.append(f"{item['product_id']}: {item['name']}, {item['currency']} {amount}; available {item['available']}.")
            return "\n".join(lines) or "No products are currently available."
        if action in {"confirm_order", "cancel_order", "order_status"}:
            return f"Order {data['order_id']}, version {data['version']}: {data['state']}. Sheet projection: {result['projection']}."
        # Exact validated reads remain bounded; no model-invented values/claims.
        return "Shop result: " + canonical(data)

    async def handle(self, observation_sha):
        if self.busy:
            raise PermissionError("SERIAL_OPERATOR_TURNS_REQUIRED")
        self.busy = True
        request = None
        try:
            count = self.claims.db.execute("SELECT COUNT(*) FROM native_turn_attempts").fetchone()[0]
            if count >= self.bounds.max_inbound_turns or self.clock().timestamp() >= self.bounds.not_after_epoch:
                raise PermissionError("RUN_TURN_OR_TIME_BOUND_REACHED")
            deadline = min(self.clock() + timedelta(seconds=self.bounds.turn_seconds),
                datetime.fromtimestamp(self.bounds.not_after_epoch, self.clock().tzinfo))
            request = self.claims.register_turn(observation_sha, deadline=deadline)
            self.claims.db.execute("INSERT INTO native_turn_attempts VALUES(?,'IN_FLIGHT',NULL)",
                                    (request.request_id,))
            with core_turn(request):
                async with asyncio.timeout(max(0, (deadline - self.clock()).total_seconds())):
                    # Native output is retained by the agent; host renders the
                    # actual ERP state and exact review for the channel.
                    await self.agent.turn(request)
            self.claims._turn(request)
            draft = self._draft_for(request)
            if draft:
                text, purpose = render_review(draft), "review"
            else:
                text, purpose = self._safe_reply(request), "reply"
            if len(text) > 4096:
                raise ValueError("COMPLETE_REPLY_EXCEEDS_CHANNEL_BOUND")
            receipt_ref = await drain_worker(self.evidence.send, request=request, claims=self.claims,
                                            text=text, purpose=purpose)
            if draft:
                receipt = self.evidence.prompt_receipt_reader(receipt_ref)
                self.claims.record_prompt(request, draft=draft, text=text, receipt_ref=receipt_ref,
                    confirmed_epoch=receipt["confirmed_epoch"],
                    inbound_watermark=self.evidence.inbound_watermark_reader(self.claims.scope, int(request.user_id)))
            self.claims.db.execute("UPDATE native_turn_attempts SET state='DONE',reply_ref=? WHERE request_id=?",
                                    (receipt_ref, request.request_id))
            return receipt_ref
        except BaseException:
            if request is not None:
                self.claims.db.execute("UPDATE native_turn_attempts SET state='HELD' WHERE request_id=? AND state='IN_FLIGHT'",
                                        (request.request_id,))
            raise
        finally:
            self.busy = False


async def run_customer_loop(runtime, *, stop_event, initial_after_update_id, max_polls):
    """One bounded poll loop; no cursor repair, repeated attempt or new actor."""
    if type(max_polls) is not int or not 1 <= max_polls <= 60:
        raise ValueError("BOUNDED_POLL_COUNT_REQUIRED")
    after = initial_after_update_id
    row = runtime.claims._row()
    for _ in range(max_polls):
        if stop_event.is_set() or runtime.clock().timestamp() >= runtime.bounds.not_after_epoch:
            return
        shas = await drain_worker(runtime.evidence.poll, after_update_id=after)
        # The recorded complete chain is the only source of the next cursor.
        after = runtime.evidence.db.execute("SELECT final_id FROM polls WHERE complete=1 ORDER BY rowid DESC LIMIT 1").fetchone()[0]
        for sha in shas:
            observation = runtime.evidence.observation_reader(sha)
            if (observation.update.chat_id != row.private_chat_id
                    or observation.update.from_user_id != row.from_user_id
                    or observation.update.update_id <= row.source_update_id):
                continue
            await runtime.handle(sha)
            if stop_event.is_set():
                return
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=2)
            return
        except TimeoutError:
            pass
