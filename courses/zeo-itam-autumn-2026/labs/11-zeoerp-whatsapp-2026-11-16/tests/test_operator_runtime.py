"""Actual caller composition with synthetic admitted Broker/ERP/model ports."""
import asyncio
from datetime import timedelta
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import unittest
from types import SimpleNamespace

from broker_evidence import BrokerEvidence, BrokerEvidenceReader
from channel_journal import ChannelJournal
from class_fixture_binding import FixtureMap, propose_row
from core_binding import CoreBinding
from operator_claims import AuthorizedERPPort, ClaimJournal
from operator_runtime import OperatorRuntime, RunBounds, drain_worker
from test_broker_evidence import SCOPE, NOW, Client, page, response, update


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.now = NOW
        self.client = Client([page([update(10), update(11, text="products")])])
        self.evidence = BrokerEvidence(self.root / "broker.sqlite3", run_id="test_run", scope=SCOPE,
            admitted_client=self.client, clock=lambda: self.now, request_factory=lambda value: value)
        enrollment, self.command = self.evidence.poll(after_update_id=9)
        customer = "cus_" + hashlib.sha256(json.dumps([SCOPE.company_id, "telegram", "123"],
                          sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:24]
        row = propose_row(self.evidence.observation_reader(enrollment), erp_customer_id=customer,
                          known_private_chat=True, valid_until=NOW + timedelta(hours=1))
        mapping = self.root / "map.json"
        mapping.write_text(FixtureMap(rows=(row,)).model_dump_json())
        self.claims = ClaimJournal(self.root / "claims.sqlite3", run_id="test_run", scope=SCOPE,
            mapping_path=mapping, approved_map_sha256=hashlib.sha256(mapping.read_bytes()).hexdigest(),
            run_expires_epoch=(NOW + timedelta(minutes=10)).timestamp(), clock=lambda: self.now,
            observation_reader=self.evidence.observation_reader, prompt_receipt_reader=self.evidence.prompt_receipt_reader,
            first_inbound_reader=self.evidence.first_inbound_reader,
            inbound_watermark_reader=self.evidence.inbound_watermark_reader)
        self.journal = ChannelJournal(self.root / "operations.sqlite3")
        self.port_calls = []
        owner = self

        class Port:
            def validate_schema(self, *args):
                pass  # Synthetic port boundary; full schemas covered separately.

            async def call(self, tool, arguments, *, context_header):
                owner.port_calls.append((tool, arguments))
                return {"success": True, "data": {"ok": True, "state": "completed", "projection": "not_requested",
                    "data": [{"product_id": "tea", "name": "Tea", "price_minor": 123, "currency": "EUR",
                              "scale": 2, "available": 5}]}}
        self.binding = CoreBinding(AuthorizedERPPort(Port(), self.claims), self.journal, self.claims, clock=lambda: self.now)

        class Agent:
            async def turn(self, request):
                await owner.binding.call("list_products", {})
                return [{"text": "I confirmed your order for free."}]
        self.agent = Agent()
        self.bounds = RunBounds(max_inbound_turns=1, turn_seconds=30,
                                not_after_epoch=(NOW + timedelta(minutes=10)).timestamp())
        self.runtime = OperatorRuntime(claims=self.claims, evidence=self.evidence, operation_journal=self.journal, native_agent=self.agent,
                                      bounds=self.bounds, clock=lambda: self.now)

    async def asyncTearDown(self):
        self.journal.close()
        self.claims.close()
        self.evidence.close()
        self.tmp.cleanup()

    async def test_model_claim_cannot_replace_actual_erp_result_and_repeat_is_refused(self):
        self.client.responses.append(response({"confirmation": "recorded"}))
        ref = await self.runtime.handle(self.command)
        self.assertIn("EUR 1.23", self.client.calls[-1]["arguments"]["text"])
        self.assertNotIn("confirmed", self.client.calls[-1]["arguments"]["text"])
        self.assertEqual(self.port_calls, [("list_products", {})])
        self.assertEqual(self.claims.db.execute("SELECT state,reply_ref FROM native_turn_attempts").fetchone(), ("DONE", ref))
        with self.assertRaises(PermissionError):
            await self.runtime.handle(self.command)
        self.assertEqual(len(self.port_calls), 1)

    async def test_model_failure_is_held_and_restart_does_not_resume_new_turn(self):
        async def fail(request):
            raise TimeoutError("synthetic")
        self.agent.turn = fail
        with self.assertRaises(TimeoutError):
            await self.runtime.handle(self.command)
        self.assertEqual(len(self.client.calls), 1)  # initial read only, no send
        self.assertEqual(self.claims.db.execute("SELECT state FROM native_turn_attempts").fetchone()[0], "HELD")
        with self.assertRaisesRegex(PermissionError, "REQUIRES_AUDIT"):
            OperatorRuntime(claims=self.claims, evidence=self.evidence, operation_journal=self.journal, native_agent=self.agent,
                            bounds=self.bounds, clock=lambda: self.now)

    async def test_unknown_reply_remains_held_without_second_send(self):
        self.client.responses.append(TimeoutError("synthetic"))
        with self.assertRaises(RuntimeError):
            await self.runtime.handle(self.command)
        self.assertEqual(len(self.client.calls), 2)
        with self.assertRaises(PermissionError):
            await self.runtime.handle(self.command)
        self.assertEqual(len(self.client.calls), 2)

    async def test_producer_evidence_reader_has_no_transport_or_write_path(self):
        reader = BrokerEvidenceReader(self.evidence.path, run_id="test_run", scope=SCOPE)
        before = self.evidence.path.read_bytes()
        self.assertEqual(reader.observation_reader(self.command).update.text, "products")
        for method in [reader.poll, reader.send, reader._invoke]:
            with self.assertRaises(PermissionError):
                method()
        reader.close()
        self.assertEqual(self.evidence.path.read_bytes(), before)

    async def test_repeated_cancellation_drains_actual_effect_worker(self):
        entered, release, ended = threading.Event(), threading.Event(), threading.Event()

        def effect():
            entered.set()
            release.wait(2)
            ended.set()
            return "known"
        task = asyncio.create_task(drain_worker(effect))
        await asyncio.to_thread(entered.wait, 1)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        self.assertFalse(task.done())
        release.set()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(ended.is_set())

    async def test_model_cannot_hide_unknown_mutation_with_later_successful_read(self):
        original_call = self.binding.port.port.call

        async def port_call(tool, arguments, *, context_header):
            if tool == "create_draft_order":
                raise TimeoutError("synthetic unknown mutation")
            return await original_call(tool, arguments, context_header=context_header)
        self.binding.port.port.call = port_call

        async def continued_model_turn(request):
            try:
                await self.binding.call("create_draft_order", {"lines": [{"product_id": "tea", "quantity": 1}]})
            except Exception:
                pass  # Simulates the model continuing after a tool error.
            await self.binding.call("list_products", {})
        self.agent.turn = continued_model_turn
        self.client.responses.append(response({"confirmation": "recorded"}))
        await self.runtime.handle(self.command)
        self.assertIn("held or pending", self.client.calls[-1]["arguments"]["text"])
        self.assertNotIn("EUR 1.23", self.client.calls[-1]["arguments"]["text"])
        self.assertEqual(self.journal.db.execute("SELECT COUNT(*) FROM commerce_holds").fetchone()[0], 1)

    async def test_status_of_already_reviewed_draft_never_sends_another_review(self):
        self.runtime.bounds = RunBounds(max_inbound_turns=3, turn_seconds=30,
                                       not_after_epoch=(NOW + timedelta(minutes=10)).timestamp())
        draft = {"order_id": "ord_" + "1" * 24, "customer_id": self.claims._row().erp_customer_id,
            "state": "draft", "version": 1,
            "lines": [{"product_id": "tea", "quantity": 2, "unit_price_minor": 123,
                       "currency": "EUR", "scale": 2}], "currency": "EUR", "scale": 2,
            "total_minor": 246, "expires_at_epoch": (NOW + timedelta(minutes=5)).timestamp(),
            "operation_id": "test_operation"}

        async def port_call(tool, arguments, *, context_header):
            return {"success": True, "data": {"ok": True, "state": "completed", "projection": "confirmed",
                    "data": draft, "operation_id": "test_operation"}}
        self.binding.port.port.call = port_call

        async def create(request):
            await self.binding.call("create_draft_order", {"lines": [{"product_id": "tea", "quantity": 2}]})
        self.agent.turn = create
        self.client.responses.append(response({"confirmation": "recorded"}))
        await self.runtime.handle(self.command)
        original_review = self.claims.db.execute("SELECT review_json FROM operator_reviews").fetchone()[0]
        self.assertIn("Reply yes or confirm", self.client.calls[-1]["arguments"]["text"])
        self.now += timedelta(seconds=2)
        self.client.responses.append(page([update(12, text="status", date=int(self.now.timestamp()))]))
        status_sha = self.evidence.poll(after_update_id=11)[0]

        async def status(request):
            await self.binding.call("order_status", {"order_id": draft["order_id"]})
        self.agent.turn = status
        self.client.responses.append(response({"confirmation": "recorded"}))
        await self.runtime.handle(status_sha)
        status_reply = self.client.calls[-1]["arguments"]["text"]
        self.assertIn("version 1: draft", status_reply)
        self.assertNotIn("Reply yes or confirm", status_reply)
        self.assertEqual(self.claims.db.execute("SELECT review_json FROM operator_reviews").fetchall(), [(original_review,)])
        self.assertEqual(self.claims.db.execute("SELECT state FROM native_turn_attempts ORDER BY rowid").fetchall(), [("DONE",), ("DONE",)])
        self.now += timedelta(seconds=1)
        self.client.responses.append(page([update(13, text="yes", date=int(self.now.timestamp()))]))
        yes_sha = self.evidence.poll(after_update_id=12)[0]
        yes = self.claims.register_turn(yes_sha, deadline=self.now + timedelta(seconds=30))
        with self.assertRaisesRegex(PermissionError, "FIRST_EXACT"):
            await self.claims.approval_for(yes, order_id=draft["order_id"], draft_version=1)
