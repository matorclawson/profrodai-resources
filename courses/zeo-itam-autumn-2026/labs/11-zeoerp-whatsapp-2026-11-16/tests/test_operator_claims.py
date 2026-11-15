"""Synthetic evidence readers; these tests grant no live customer authority."""
import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from class_fixture_binding import (BrokerScope, FixtureMap, FixtureRefused, MessageUpdate,
    PersistedObservation, observation_digest, propose_row)
from operator_claims import (AuthorizedERPPort, ClaimJournal, VerifiedCallClaim,
                             digest, render_review)


class ClaimTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.now = datetime(2026, 11, 15, 20, tzinfo=timezone.utc)
        self.start = self.now
        self.scope = BrokerScope(company_id="demo", connection_id="synthetic-connection",
                                 connection_revision="1", bot_binding="synthetic-bot")
        self.observations, self.receipts, self.raw_updates = {}, {}, []
        enrollment = self.observation(10, "enroll")
        row = propose_row(enrollment, erp_customer_id="cus_" + "2" * 24,
            known_private_chat=True, valid_until=self.now + timedelta(hours=1))
        self.map_path = self.root / "approved-map.json"
        self.map_path.write_text(FixtureMap(rows=(row,)).model_dump_json())
        self.map_sha = hashlib.sha256(self.map_path.read_bytes()).hexdigest()
        self.options = dict(run_id="synthetic-run", scope=self.scope,
            mapping_path=self.map_path, approved_map_sha256=self.map_sha,
            run_expires_epoch=(self.now + timedelta(minutes=20)).timestamp(),
            observation_reader=lambda key: self.observations[key],
            prompt_receipt_reader=lambda key: self.receipts.get(key), clock=lambda: self.now)
        self.options.update(first_inbound_reader=lambda scope, chat, after:
            next((row for row in sorted(self.raw_updates, key=lambda row: row["update_id"])
                  if row["chat_id"] == chat and row["update_id"] > after), None),
            inbound_watermark_reader=lambda scope, chat:
                max((row["update_id"] for row in self.raw_updates if row["chat_id"] == chat), default=-1))
        self.path = self.root / "claims.sqlite3"
        self.claims = ClaimJournal(self.path, **self.options)
        self.draft = {"order_id": "ord_" + "1" * 24, "customer_id": row.erp_customer_id,
            "state": "draft", "version": 1,
            "lines": [{"product_id": "tea", "quantity": 2, "unit_price_minor": 123,
                       "currency": "EUR", "scale": 2}],
            "currency": "EUR", "scale": 2, "total_minor": 246,
            "expires_at_epoch": (self.now + timedelta(minutes=10)).timestamp(),
            "operation_id": "synthetic-operation"}

    def tearDown(self):
        self.claims.close()
        self.tmp.cleanup()

    def observation(self, update_id, text):
        value = PersistedObservation(scope=self.scope, update=MessageUpdate(
            update_id=update_id, kind="message", chat_id=123456, from_user_id=987654,
            text=text, message_id=update_id, date=int(self.now.timestamp())),
            response_sha256=hashlib.sha256(f"synthetic-response-{update_id}".encode()).hexdigest())
        self.observations[observation_digest(value)] = value
        self.raw_updates.append(value.update.model_dump())
        return value

    def turn(self, update_id, text):
        value = self.observation(update_id, text)
        return self.claims.register_turn(observation_digest(value), deadline=self.now + timedelta(seconds=60))

    async def draft_and_prompt(self):
        request = self.turn(11, "two teas")
        bound = await self.claims.bind(request, tool="create_draft_order", approval=None)
        self.claims.bind_arguments(bound.selector, "create_draft_order", {"lines": [{"product_id": "tea", "quantity": 2}]})
        payload = {"success": True, "data": {"ok": True, "state": "completed", "data": self.draft,
            "projection": "confirmed", "operation_id": "synthetic-operation"}}
        self.claims.observe_draft_result(bound.selector, "create_draft_order", payload)
        text = render_review(self.draft)
        confirmed = self.now.timestamp() + 0.25
        self.now += timedelta(seconds=1)
        self.receipts["synthetic-prompt"] = {"company_id": "demo", "user_id": "123456",
            "text_sha256": hashlib.sha256(text.encode()).hexdigest(), "confirmed_epoch": confirmed}
        self.claims.record_prompt(request, draft=self.draft, text=text, receipt_ref="synthetic-prompt",
                                  confirmed_epoch=confirmed, inbound_watermark=11)
        return request, bound, payload

    async def test_exact_claim_is_repeatable_and_reader_is_readonly_across_threads(self):
        request = self.turn(11, "catalog")
        bound = await self.claims.bind(request, tool="list_products", approval=None)
        initial = self.claims.bind_arguments(bound.selector, "list_products", {})
        reader = ClaimJournal(self.path, **self.options, read_only=True)
        try:
            def resolve():
                return reader.resolve_verified_call(bound.selector, "list_products", digest({}), now_epoch=self.now.timestamp())
            values = await asyncio.gather(*(asyncio.to_thread(resolve) for _ in range(8)))
            self.assertTrue(all(item == initial for item in values))
            self.assertEqual(reader.db.total_changes, 0)
            self.assertEqual(self.claims.db.execute("SELECT count(*) FROM class_consumed_updates").fetchone()[0], 1)
            with self.assertRaises(PermissionError):
                reader.bind_arguments(bound.selector, "list_products", {})
        finally:
            reader.close()

    async def test_exact_customer_turn_and_argument_digest_are_not_model_selectable(self):
        request = self.turn(11, "catalog")
        with self.assertRaises(PermissionError):
            await self.claims.bind(replace(request, user_id="987654"), tool="list_products", approval=None)
        bound = await self.claims.bind(request, tool="list_products", approval=None)
        self.claims.bind_arguments(bound.selector, "list_products", {})
        for action, args in [("my_orders", {}), ("list_products", {"customer": "other"})]:
            with self.assertRaises(PermissionError):
                self.claims.resolve_verified_call(bound.selector, action, digest(args), now_epoch=self.now.timestamp())
        with self.assertRaises(PermissionError):
            self.claims.bind_arguments(bound.selector, "list_products", {"different": True})

    async def test_unknown_selector_and_expiry_fail_closed(self):
        with self.assertRaises(PermissionError):
            self.claims.resolve_verified_call("clm_" + "0" * 32, "list_products", digest({}), now_epoch=self.now.timestamp())
        request = self.turn(11, "catalog")
        bound = await self.claims.bind(request, tool="list_products", approval=None)
        self.claims.bind_arguments(bound.selector, "list_products", {})
        self.now += timedelta(seconds=61)
        with self.assertRaises(PermissionError):
            self.claims.resolve_verified_call(bound.selector, "list_products", digest({}), now_epoch=self.now.timestamp())

    async def test_changed_approved_map_and_original_observation_refuse(self):
        request = self.turn(11, "catalog")
        bound = await self.claims.bind(request, tool="list_products", approval=None)
        claim = self.claims.bind_arguments(bound.selector, "list_products", {})
        original = self.observations[claim.observation_sha256]
        self.observations[claim.observation_sha256] = original.model_copy(update={"response_sha256": "a" * 64})
        with self.assertRaises(PermissionError):
            self.claims.resolve_verified_call(bound.selector, "list_products", digest({}), now_epoch=self.now.timestamp())
        self.observations[claim.observation_sha256] = original
        self.map_path.write_text(self.map_path.read_text() + "\n")
        with self.assertRaises(PermissionError):
            self.claims.resolve_verified_call(bound.selector, "list_products", digest({}), now_epoch=self.now.timestamp())

    async def test_exact_confirmed_review_and_distinct_first_affirmative_issue_approval(self):
        await self.draft_and_prompt()
        self.now += timedelta(seconds=1)
        reply = self.turn(12, "yes")
        approval = await self.claims.approval_for(reply, order_id=self.draft["order_id"], draft_version=1)
        bound = await self.claims.bind(reply, tool="confirm_order", approval=approval)
        args = {"order_id": self.draft["order_id"], "draft_version": 1}
        claim = self.claims.bind_arguments(bound.selector, "confirm_order", args)
        self.assertEqual(claim.user_id, "123456")
        self.assertNotEqual(claim.user_id, "987654")
        self.assertEqual(claim.approval.reply_observation_sha256, claim.observation_sha256)
        self.assertEqual(claim.approval.order_id, self.draft["order_id"])
        self.assertEqual(claim, self.claims.resolve_verified_call(bound.selector, "confirm_order", digest(args), now_epoch=self.now.timestamp()))

    async def test_intervening_answer_cannot_be_erased_by_a_later_yes(self):
        await self.draft_and_prompt()
        self.now += timedelta(seconds=1)
        self.turn(12, "what about coffee?")
        self.now += timedelta(seconds=1)
        reply = self.turn(13, "yes")
        with self.assertRaisesRegex(PermissionError, "FIRST_EXACT"):
            await self.claims.approval_for(reply, order_id=self.draft["order_id"], draft_version=1)

    async def test_unusable_unconsumed_first_reply_also_blocks_a_later_yes(self):
        await self.draft_and_prompt()
        self.raw_updates.append({"update_id": 12, "chat_id": 123456, "kind": "message", "text": ""})
        self.now += timedelta(seconds=1)
        reply = self.turn(13, "yes")
        with self.assertRaisesRegex(PermissionError, "FIRST_OPERATOR_REPLY_UNUSABLE"):
            await self.claims.approval_for(reply, order_id=self.draft["order_id"], draft_version=1)

    async def test_unobserved_or_modified_draft_never_becomes_a_review(self):
        request = self.turn(11, "two teas")
        with self.assertRaisesRegex(PermissionError, "OBSERVED_CANONICAL"):
            self.claims.record_prompt(request, draft=self.draft, text=render_review(self.draft),
                receipt_ref="invented", confirmed_epoch=self.now.timestamp(), inbound_watermark=11)

    async def test_changed_prompt_receipt_or_wrong_version_refuses_confirmation(self):
        await self.draft_and_prompt()
        self.now += timedelta(seconds=1)
        reply = self.turn(12, "confirm")
        with self.assertRaises(PermissionError):
            await self.claims.approval_for(reply, order_id=self.draft["order_id"], draft_version=2)
        self.receipts["synthetic-prompt"] = None
        with self.assertRaisesRegex(PermissionError, "RECEIPT_CHANGED"):
            await self.claims.approval_for(reply, order_id=self.draft["order_id"], draft_version=1)

    async def test_restart_retains_consumed_update_and_existing_call(self):
        request = self.turn(11, "catalog")
        bound = await self.claims.bind(request, tool="list_products", approval=None)
        claim = self.claims.bind_arguments(bound.selector, "list_products", {})
        self.claims.close()
        self.claims = ClaimJournal(self.path, **self.options)
        self.assertEqual(self.claims.resolve_verified_call(bound.selector, "list_products", digest({}), now_epoch=self.now.timestamp()), claim)
        with self.assertRaises(FixtureRefused):
            self.claims.register_turn(claim.observation_sha256, deadline=self.now + timedelta(seconds=60))

    async def test_original_known_result_is_retained_after_deadline(self):
        request = self.turn(11, "two teas")
        bound = await self.claims.bind(request, tool="create_draft_order", approval=None)
        self.claims.bind_arguments(bound.selector, "create_draft_order", {"lines": []})
        self.now += timedelta(seconds=61)
        payload = {"success": True, "data": {"ok": True, "state": "completed", "data": self.draft,
            "projection": "confirmed", "operation_id": "synthetic-operation"}}
        self.claims.observe_draft_result(bound.selector, "create_draft_order", payload)
        retained = self.claims.db.execute("SELECT payload_json FROM operator_results WHERE selector=?", (bound.selector,)).fetchone()
        self.assertEqual(json.loads(retained[0]), payload)
        with self.assertRaises(PermissionError):
            self.claims.record_prompt(request, draft=self.draft, text=render_review(self.draft),
                receipt_ref="invented", confirmed_epoch=self.now.timestamp(), inbound_watermark=11)

    async def test_authorized_port_refuses_before_transport_when_claim_missing(self):
        calls = []
        class Port:
            validate_schema = staticmethod(lambda *_: None)
            async def call(self, *args, **kwargs):
                calls.append((args, kwargs))
        with self.assertRaises(PermissionError):
            await AuthorizedERPPort(Port(), self.claims).call("list_products", {}, context_header="unknown")
        self.assertEqual(calls, [])

    def test_canonical_review_uses_exact_minor_amounts_and_rejects_changed_total(self):
        text = render_review(self.draft)
        self.assertIn("2 x tea at EUR 1.23 each.", text)
        self.assertIn("Total EUR 2.46.", text)
        with self.assertRaises(ValueError):
            render_review({**self.draft, "total_minor": 247})

    def test_claim_model_rejects_bool_version_and_customer_to_admin_upgrade(self):
        value = dict(v=True, run_id="synthetic-run", selector="clm_" + "0" * 32,
            company_id="demo", channel="telegram", user_id="123456", request_id="request",
            action="list_products", arguments_sha256=digest({}), observation_sha256="a" * 64,
            fixture_map_sha256=self.map_sha, grant_expires_at_epoch=float(self.now.timestamp() + 60), approval=None)
        with self.assertRaises(ValueError):
            VerifiedCallClaim.model_validate(value)
        with self.assertRaises(ValueError):
            VerifiedCallClaim.model_validate({**value, "v": 1, "role": "admin"})

    async def test_second_draft_in_same_run_refuses_before_native_dispatch(self):
        await self.draft_and_prompt()
        self.now += timedelta(seconds=2)
        request = self.turn(12, "another tea")
        bound = await self.claims.bind(request, tool="create_draft_order", approval=None)
        calls = []

        class Port:
            def validate_schema(self, *args):
                pass

            async def call(self, *args, **kwargs):
                calls.append(args)
                raise AssertionError("A second original draft must never dispatch")
        with self.assertRaisesRegex(PermissionError, "ONE_ORIGINAL_DRAFT"):
            await AuthorizedERPPort(Port(), self.claims).call("create_draft_order",
                {"lines": [{"product_id": "tea", "quantity": 1}]}, context_header=bound.selector)
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
