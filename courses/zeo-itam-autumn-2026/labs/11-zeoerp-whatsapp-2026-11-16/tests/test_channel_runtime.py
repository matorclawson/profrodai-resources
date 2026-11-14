"""Exercise the poller with synthetic transport messages, without a network."""

import asyncio
import hashlib
import json
import sys
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from channel_journal import BindingConflict, ChannelJournal
from channel_runtime import (
    HeldOutcome, IncomingMessage, IncomingPage, PollCursor, PollingRuntime,
    SendResult, current_binding, OutboundObservation, confirmed_send_sid,
)


class FakeBroker:
    def __init__(self):
        self.pages = []
        self.polls = []
        self.sends = []
        self.send_result = SendResult("confirmed", "a" * 64)

    async def inbound_list(self, *, after, limit):
        self.polls.append((after, limit))
        return self.pages.pop(0)

    async def send_text(self, **kwargs):
        self.sends.append(kwargs)
        if isinstance(self.send_result, BaseException):
            raise self.send_result
        return self.send_result


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.journal = ChannelJournal(Path(self.tmp.name) / "channel.sqlite3")
        self.broker = FakeBroker()
        self.now = datetime(2026, 11, 14, 12, tzinfo=timezone.utc)
        self.message = IncomingMessage(
            "synthetic-connection", "whatsapp:+15550000001", "whatsapp:+15550000002",
            "SM_synthetic_1", "execution-1", "show the shelf", self.now - timedelta(seconds=10),
        )
        self.runtime = self.new_runtime()

    def new_runtime(self):
        return PollingRuntime(
            self.broker, self.journal, scope="synthetic-demo",
            connection_id=self.message.connection_id,
            sandbox_recipient=self.message.recipient,
            allowed_senders=frozenset([self.message.sender]),
            not_before=self.now - timedelta(minutes=10), clock=lambda: self.now,
        )

    def page(self, *messages):
        self.broker.pages.append(IncomingPage(
            tuple(messages),
            PollCursor(messages[-1].sent_at, messages[-1].message_sid) if messages else self.runtime.after,
        ))

    def tearDown(self):
        self.journal.close()
        self.tmp.cleanup()

    async def test_restart_deduplicates_even_when_retrieval_execution_changes(self):
        delivered = []
        async def deliver(message):
            delivered.append(message.message_sid)
            await self.runtime.reply("Synthetic shelf")
        self.page(self.message)
        self.assertEqual(await self.runtime.poll_once(deliver), ["DONE"])
        self.runtime = self.new_runtime()
        self.page(replace(self.message, execution_id="execution-2"))
        self.assertEqual(await self.runtime.poll_once(deliver), ["DONE"])
        self.assertEqual(delivered, [self.message.message_sid])
        self.assertEqual(len(self.broker.sends), 1)
        self.assertEqual(self.broker.sends[0]["recipient"], self.message.sender)

    async def test_cursor_is_passed_back_and_empty_page_preserves_it(self):
        async def deliver(_message):
            pass
        self.page(self.message)
        await self.runtime.poll_once(deliver)
        cursor = self.runtime.after
        self.page()
        self.assertEqual(await self.runtime.poll_once(deliver), [])
        self.assertEqual(self.runtime.after, cursor)
        self.assertEqual(self.broker.polls, [(None, 50), (cursor, 50)])

    async def test_whole_page_validation_blocks_foreign_sender_before_any_turn(self):
        delivered = []
        async def deliver(message):
            delivered.append(message)
        self.page(self.message, replace(self.message, sender="whatsapp:+15550000003"))
        with self.assertRaises(PermissionError):
            await self.runtime.poll_once(deliver)
        self.assertEqual(delivered, [])
        self.assertIsNone(self.runtime.after)

    async def test_rejects_wrong_grant_old_messages_media_and_bad_cursor(self):
        async def deliver(_message):
            self.fail("Invalid page reached the agent")
        cases = [
            replace(self.message, connection_id="another-grant"),
            replace(self.message, recipient="whatsapp:+15550000003"),
            replace(self.message, sent_at=self.now - timedelta(hours=1)),
            replace(self.message, num_media=1),
        ]
        for message in cases:
            self.page(message)
            with self.assertRaises((ValueError, PermissionError)):
                await self.runtime.poll_once(deliver)
        self.broker.pages.append(IncomingPage((self.message,), None))
        with self.assertRaises(ValueError):
            await self.runtime.poll_once(deliver)

    async def test_unknown_send_holds_turn_and_does_not_resend_after_restart(self):
        self.broker.send_result = SendResult("ambiguous", "b" * 64)
        async def deliver(_message):
            await self.runtime.reply("Synthetic review")
        self.page(self.message)
        with self.assertRaises(HeldOutcome):
            await self.runtime.poll_once(deliver)
        self.assertIsNone(self.runtime.after)
        self.runtime = self.new_runtime()
        self.page(self.message)
        self.assertEqual(await self.runtime.poll_once(deliver), ["HELD"])
        self.assertEqual(len(self.broker.sends), 1)
        self.assertEqual(len(self.journal.held("synthetic-demo")), 2)

    async def test_provider_sid_cannot_be_accepted_as_confirmation_digest(self):
        self.broker.send_result = SendResult("confirmed", "SM_not_a_digest")
        async def deliver(_message):
            await self.runtime.reply("Synthetic review")
        self.page(self.message)
        with self.assertRaises(HeldOutcome):
            await self.runtime.poll_once(deliver)

    async def test_reply_outside_turn_and_inherited_context_after_close_are_refused(self):
        with self.assertRaises(PermissionError):
            await self.runtime.reply("No turn")
        release = asyncio.Event()
        tasks = []
        async def late_reply():
            await release.wait()
            with self.assertRaises(PermissionError):
                await self.runtime.reply("Too late")
        async def deliver(_message):
            tasks.append(asyncio.create_task(late_reply()))
        self.page(self.message)
        await self.runtime.poll_once(deliver)
        release.set()
        await asyncio.gather(*tasks)
        self.assertEqual(self.broker.sends, [])

    async def test_cancellation_preserves_claim_and_closes_context(self):
        entered = asyncio.Event()
        bindings = []
        async def deliver(_message):
            bindings.append(current_binding(self.now))
            entered.set()
            await asyncio.Event().wait()
        self.page(self.message)
        task = asyncio.create_task(self.runtime.poll_once(deliver))
        await entered.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertFalse(bindings[0].active)
        self.assertEqual(len(self.journal.held("synthetic-demo")), 1)

    async def test_changed_payload_under_same_sid_is_refused_after_restart(self):
        async def deliver(_message):
            pass
        self.page(self.message)
        await self.runtime.poll_once(deliver)
        self.runtime = self.new_runtime()
        self.page(replace(self.message, text="different order"))
        with self.assertRaises(BindingConflict):
            await self.runtime.poll_once(deliver)

    def test_confirmed_sid_digest_survives_status_change_and_equal_body_candidates(self):
        sid = "SM_original"
        digest = hashlib.sha256(json.dumps({"message_sid": sid}, separators=(",", ":")).encode()).hexdigest()
        candidates = [OutboundObservation(self.message.sender, "SM_other", "sent"),
                      OutboundObservation(self.message.sender, sid, "delivered")]
        self.assertEqual(confirmed_send_sid(SendResult("confirmed", digest), candidates,
                                            recipient=self.message.sender), sid)

    def test_unknown_or_missing_candidate_cannot_authorize_original_send(self):
        candidates = [OutboundObservation(self.message.sender, "SM_only_candidate", "sent")]
        for result in [SendResult("ambiguous"), SendResult("confirmed", "a" * 64)]:
            with self.assertRaises(HeldOutcome):
                confirmed_send_sid(result, candidates, recipient=self.message.sender)


if __name__ == "__main__":
    unittest.main()
