"""Synthetic admitted-client contract tests; no SDK/provider or live identity."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import os
from types import SimpleNamespace

import unittest
import tempfile
from pathlib import Path

from broker_evidence import BrokerEvidence, BrokerEvidenceReader, HeldBrokerOutcome
from class_fixture_binding import BrokerScope, MessageUpdate, PersistedObservation, observation_digest


SCOPE = BrokerScope(company_id="test_erp", connection_id="test_connection",
                    connection_revision="7", bot_binding="test_bot")
NOW = datetime(2026, 11, 15, 20, 0, tzinfo=timezone.utc)


def update(number, **changes):
    return {"update_id": number, "kind": "message", "chat_id": 123,
            "from_user_id": 456, "text": "hello", "message_id": number,
            "date": int(NOW.timestamp()), **changes}


def response(result, **changes):
    return {"status": "confirmed", "execution_id": "test_execution",
            "result": result, "receipt": {"binding": {
                "connection_id": SCOPE.connection_id, "external_identity": SCOPE.bot_binding,
                "connection_revision": SCOPE.connection_revision, "connector_revision": "test_source"}},
            **changes}


class Client:
    def __init__(self, responses):
        self.responses, self.calls = list(responses), []

    def invoke(self, request):
        self.calls.append(request)
        value = self.responses.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


def store(tmp_path, responses):
    os.chmod(tmp_path, 0o700)
    client = Client(responses)
    evidence = BrokerEvidence(tmp_path / "broker.sqlite3", run_id="test_run", scope=SCOPE,
        admitted_client=client, clock=lambda: NOW, request_factory=lambda value: value)
    return evidence, client


def page(rows, complete=True):
    return response({"updates": rows, "next_after": {"update_id": rows[-1]["update_id"]} if rows else None,
                     "complete": complete})



def request_and_claims():
    return SimpleNamespace(company_id=SCOPE.company_id, channel="telegram", user_id="123",
                           request_id="test_turn"), SimpleNamespace(_turn=lambda request: None)


class BrokerEvidenceTests(unittest.TestCase):
    def test_chat_type_keeps_strict_validation_and_original_field_presence(self):
        originals = [update(10)] + [update(10, chat_type=value) for value in
                     (None, "private", "group", "supergroup", "channel")]
        hashes = []
        for raw in originals:
            with self.subTest(raw=raw):
                typed = MessageUpdate.model_validate(raw)
                self.assertEqual(typed.model_dump(mode="json"), raw)
                observed = PersistedObservation(scope=SCOPE, update=typed,
                                                response_sha256="1" * 64)
                restored = PersistedObservation.model_validate_json(observed.model_dump_json())
                self.assertEqual(restored.update.model_dump(mode="json"), raw)
                hashes.append(observation_digest(restored))
        self.assertEqual(hashes[0], "467754177d931e974482b7df527bc6aad891cc1f8bbae1a4da3d52a129c00bde")
        self.assertEqual(len(set(hashes)), len(originals))
        for value in ("PRIVATE", "future", 1, True, {}, []):
            with self.subTest(invalid=value), self.assertRaises(ValueError):
                MessageUpdate.model_validate(update(10, chat_type=value))
        with self.assertRaises(ValueError):
            MessageUpdate.model_validate(update(10, chat_type="private", unexpected=True))

    def test_chat_type_rows_and_legacy_rows_survive_durable_reader(self):
        originals = [update(10)] + [update(10, chat_type=value) for value in
                     (None, "private", "group", "supergroup", "channel")]
        for number, raw in enumerate(originals):
            with self.subTest(raw=raw):
                directory = self.root / str(number)
                directory.mkdir()
                evidence, client = store(directory, [page([raw])])
                try:
                    shas = evidence.poll(after_update_id=9)
                    self.assertEqual(len(shas), 1)
                    self.assertEqual(len(client.calls), 1)
                finally:
                    evidence.close()
                reader = BrokerEvidenceReader(directory / "broker.sqlite3",
                    run_id="test_run", scope=SCOPE)
                try:
                    original = reader.observation_reader(shas[0])
                    self.assertEqual(original.update.model_dump(mode="json"), raw)
                    self.assertEqual(observation_digest(original), shas[0])
                finally:
                    reader.close()

    def test_observed_private_type_does_not_replace_operator_fixture_review(self):
        from class_fixture_binding import propose_row
        observation = PersistedObservation(scope=SCOPE,
            update=MessageUpdate.model_validate(update(10, chat_type="private")),
            response_sha256="1" * 64)
        with self.assertRaisesRegex(ValueError, "REVIEWED_PRIVATE_CHAT_REQUIRED"):
            propose_row(observation, erp_customer_id="test_customer",
                        known_private_chat=False)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_complete_paged_originals_are_repeatably_read_only_across_threads(self):
        tmp_path = self.root
        evidence, client = store(tmp_path, [page([update(10)], False), page([update(11)])])
        try:
            shas = evidence.poll(after_update_id=9)
            assert len(shas) == 2
            assert client.calls[0]["arguments"] == {"after": {"update_id": 9}, "limit": 50}
            assert client.calls[1]["arguments"] == {"after": {"update_id": 10}, "limit": 50}
            assert client.calls[0]["expect"]["connection_revision"] == "7"
            before = evidence.path.read_bytes()
            with ThreadPoolExecutor(4) as pool:
                originals = list(pool.map(evidence.observation_reader, shas * 4))
            assert [observation_digest(item) for item in originals] == shas * 4
            assert evidence.path.read_bytes() == before
            assert evidence.inbound_watermark_reader(SCOPE, 123) == 11
            assert evidence.first_inbound_reader(SCOPE, 123, 10) == update(11)
        finally:
            evidence.close()


    def test_partial_window_retained_but_no_authority_and_no_retry(self):
        tmp_path = self.root
        evidence, client = store(tmp_path, [page([update(10)], False)])
        try:
            with self.assertRaisesRegex(HeldBrokerOutcome, "BOUNDED_POLL_INCOMPLETE"):
                evidence.poll(after_update_id=9, max_pages=1)
            sha = evidence.db.execute("SELECT sha FROM observations").fetchone()[0]
            with self.assertRaisesRegex(PermissionError, "COMPLETE_ORIGINAL"):
                evidence.observation_reader(sha)
            with self.assertRaisesRegex(PermissionError, "INCOMPLETE"):
                evidence.inbound_watermark_reader(SCOPE, 123)
            with self.assertRaisesRegex(HeldBrokerOutcome, "INCOMPLETE_POLL"):
                evidence.poll(after_update_id=10)
            assert len(client.calls) == 1
            assert evidence.db.execute("SELECT COUNT(*) FROM updates").fetchone()[0] == 1
        finally:
            evidence.close()


    def test_unusable_first_reply_is_retained_before_later_yes(self):
        tmp_path = self.root
        malformed = update(11, text="x" * 4096)
        evidence, _ = store(tmp_path, [page([update(10), malformed, update(12, text="yes")])])
        try:
            shas = evidence.poll(after_update_id=9)
            assert len(shas) == 2
            assert evidence.first_inbound_reader(SCOPE, 123, 10) == malformed
        finally:
            evidence.close()


    def test_original_response_or_request_mutation_refuses_scope(self):
        tmp_path = self.root
        damage = 'scope'
        evidence, _ = store(tmp_path, [page([update(10)])])
        try:
            sha = evidence.poll(after_update_id=9)[0]
            key, req, raw = evidence.db.execute("SELECT key,request,response FROM calls").fetchone()
            value = json.loads(raw)
            if damage == "scope":
                value["receipt"]["binding"]["connection_revision"] = "8"
            elif damage == "body":
                value["result"]["updates"][0]["text"] = "yes"
            else:
                req = json.loads(req)
                req["expect"]["external_identity"] = "other_bot"
                evidence.db.execute("UPDATE calls SET request=? WHERE key=?", (json.dumps(req), key))
            if damage != "request":
                evidence.db.execute("UPDATE calls SET response=? WHERE key=?", (json.dumps(value), key))
            with self.assertRaises((PermissionError, HeldBrokerOutcome)):
                evidence.observation_reader(sha)
        finally:
            evidence.close()


    def test_original_response_or_request_mutation_refuses_body(self):
        tmp_path = self.root
        damage = 'body'
        evidence, _ = store(tmp_path, [page([update(10)])])
        try:
            sha = evidence.poll(after_update_id=9)[0]
            key, req, raw = evidence.db.execute("SELECT key,request,response FROM calls").fetchone()
            value = json.loads(raw)
            if damage == "scope":
                value["receipt"]["binding"]["connection_revision"] = "8"
            elif damage == "body":
                value["result"]["updates"][0]["text"] = "yes"
            else:
                req = json.loads(req)
                req["expect"]["external_identity"] = "other_bot"
                evidence.db.execute("UPDATE calls SET request=? WHERE key=?", (json.dumps(req), key))
            if damage != "request":
                evidence.db.execute("UPDATE calls SET response=? WHERE key=?", (json.dumps(value), key))
            with self.assertRaises((PermissionError, HeldBrokerOutcome)):
                evidence.observation_reader(sha)
        finally:
            evidence.close()


    def test_original_response_or_request_mutation_refuses_request(self):
        tmp_path = self.root
        damage = 'request'
        evidence, _ = store(tmp_path, [page([update(10)])])
        try:
            sha = evidence.poll(after_update_id=9)[0]
            key, req, raw = evidence.db.execute("SELECT key,request,response FROM calls").fetchone()
            value = json.loads(raw)
            if damage == "scope":
                value["receipt"]["binding"]["connection_revision"] = "8"
            elif damage == "body":
                value["result"]["updates"][0]["text"] = "yes"
            else:
                req = json.loads(req)
                req["expect"]["external_identity"] = "other_bot"
                evidence.db.execute("UPDATE calls SET request=? WHERE key=?", (json.dumps(req), key))
            if damage != "request":
                evidence.db.execute("UPDATE calls SET response=? WHERE key=?", (json.dumps(value), key))
            with self.assertRaises((PermissionError, HeldBrokerOutcome)):
                evidence.observation_reader(sha)
        finally:
            evidence.close()


    def test_wrong_fence_response_keeps_original_and_exposes_nothing(self):
        tmp_path = self.root
        value = page([update(10)])
        value["receipt"]["binding"]["external_identity"] = "other_bot"
        evidence, _ = store(tmp_path, [value])
        try:
            with self.assertRaisesRegex(HeldBrokerOutcome, "FENCED"):
                evidence.poll(after_update_id=9)
            assert evidence.db.execute("SELECT response FROM calls").fetchone()[0]
            assert evidence.db.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 0
        finally:
            evidence.close()


    def test_confirmed_send_replays_only_retained_receipt_with_fixed_chat(self):
        tmp_path = self.root
        evidence, client = store(tmp_path, [response({"confirmation": "recorded"})])
        request, claims = request_and_claims()
        try:
            key = evidence.send(request=request, claims=claims, text="Review exact draft", purpose="review")
            assert evidence.send(request=request, claims=claims, text="Review exact draft", purpose="review") == key
            assert len(client.calls) == 1
            assert client.calls[0]["arguments"] == {"chat_id": 123, "text": "Review exact draft"}
            receipt = evidence.prompt_receipt_reader(key)
            assert receipt["user_id"] == "123"
            assert receipt["confirmed_epoch"] == NOW.timestamp()
            with self.assertRaisesRegex(HeldBrokerOutcome, "CHANGED"):
                evidence.send(request=request, claims=claims, text="Different review", purpose="review")
            assert len(client.calls) == 1
        finally:
            evidence.close()


    def test_unknown_send_survives_restart_without_redispatch(self):
        tmp_path = self.root
        evidence, client = store(tmp_path, [TimeoutError("synthetic")])
        request, claims = request_and_claims()
        try:
            with self.assertRaisesRegex(HeldBrokerOutcome, "AUDIT"):
                evidence.send(request=request, claims=claims, text="Review", purpose="review")
        finally:
            evidence.close()
        restarted = BrokerEvidence(tmp_path / "broker.sqlite3", run_id="test_run", scope=SCOPE,
            admitted_client=client, clock=lambda: NOW, request_factory=lambda value: value)
        try:
            with self.assertRaisesRegex(HeldBrokerOutcome, "HELD"):
                restarted.send(request=request, claims=claims, text="Review", purpose="review")
            assert len(client.calls) == 1
        finally:
            restarted.close()


    def test_changed_run_and_nonprivate_store_refused(self):
        tmp_path = self.root
        evidence, client = store(tmp_path, [])
        evidence.close()
        with self.assertRaisesRegex(PermissionError, "RUN_SCOPE"):
            BrokerEvidence(tmp_path / "broker.sqlite3", run_id="other", scope=SCOPE,
                admitted_client=client, clock=lambda: NOW, request_factory=lambda value: value)
        os.chmod(tmp_path, 0o755)
        with self.assertRaisesRegex(PermissionError, "PRIVATE_EVIDENCE_DIRECTORY"):
            BrokerEvidence(tmp_path / "other.sqlite3", run_id="test", scope=SCOPE,
                admitted_client=client, clock=lambda: NOW)


    def test_real_backer_to_claim_journal_preserves_confirmed_prompt_and_first_yes(self):
        tmp_path = self.root
        import asyncio
        from datetime import timedelta
        import hashlib
        from class_fixture_binding import FixtureMap, propose_row
        from operator_claims import ClaimJournal, digest, render_review

        current = [NOW]
        evidence, client = store(tmp_path, [page([update(10), update(11, text="two teas")]),
            response({"confirmation": "recorded"}), page([update(12, text="yes", date=int(NOW.timestamp()) + 2)])])
        evidence.clock = lambda: current[0]
        claims = reader = None
        try:
            enrollment_sha, command_sha = evidence.poll(after_update_id=9)
            customer = "cus_" + hashlib.sha256(json.dumps([SCOPE.company_id, "telegram", "123"],
                              sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:24]
            row = propose_row(evidence.observation_reader(enrollment_sha), erp_customer_id=customer,
                              known_private_chat=True, valid_until=NOW + timedelta(hours=1))
            mapping = tmp_path / "map.json"
            mapping.write_text(FixtureMap(rows=(row,)).model_dump_json())
            options = dict(run_id="test_run", scope=SCOPE, mapping_path=mapping,
                approved_map_sha256=hashlib.sha256(mapping.read_bytes()).hexdigest(),
                run_expires_epoch=(NOW + timedelta(minutes=10)).timestamp(), clock=lambda: current[0],
                observation_reader=evidence.observation_reader, prompt_receipt_reader=evidence.prompt_receipt_reader,
                first_inbound_reader=evidence.first_inbound_reader,
                inbound_watermark_reader=evidence.inbound_watermark_reader)
            claims = ClaimJournal(tmp_path / "claims.sqlite3", **options)
            command = claims.register_turn(command_sha, deadline=NOW + timedelta(seconds=60))
            draft = {"order_id": "ord_" + "1" * 24, "customer_id": customer, "state": "draft", "version": 1,
                "lines": [{"product_id": "tea", "quantity": 2, "unit_price_minor": 123,
                           "currency": "EUR", "scale": 2}], "currency": "EUR", "scale": 2,
                "total_minor": 246, "expires_at_epoch": (NOW + timedelta(minutes=5)).timestamp(),
                "operation_id": "test_operation"}

            async def prepare():
                bound = await claims.bind(command, tool="create_draft_order", approval=None)
                claims.bind_arguments(bound.selector, "create_draft_order", {"lines": [{"product_id": "tea", "quantity": 2}]})
                # A synthetic ERP result exercises actual issuer/backer composition.
                claims.observe_draft_result(bound.selector, "create_draft_order", {"success": True, "data": {
                    "ok": True, "state": "completed", "data": draft, "projection": "confirmed",
                    "operation_id": "test_operation"}})
            asyncio.run(prepare())
            current[0] += timedelta(seconds=0.25)
            text = render_review(draft)
            receipt_ref = evidence.send(request=command, claims=claims, text=text, purpose="review")
            receipt = evidence.prompt_receipt_reader(receipt_ref)
            claims.record_prompt(command, draft=draft, text=text, receipt_ref=receipt_ref,
                confirmed_epoch=receipt["confirmed_epoch"], inbound_watermark=evidence.inbound_watermark_reader(SCOPE, 123))
            current[0] = NOW + timedelta(seconds=2)
            yes_sha = evidence.poll(after_update_id=11)[0]
            yes = claims.register_turn(yes_sha, deadline=current[0] + timedelta(seconds=60))

            async def approve():
                approval = await claims.approval_for(yes, order_id=draft["order_id"], draft_version=1)
                bound = await claims.bind(yes, tool="confirm_order", approval=approval)
                arguments = {"order_id": draft["order_id"], "draft_version": 1}
                claim = claims.bind_arguments(bound.selector, "confirm_order", arguments)
                return bound, arguments, claim
            bound, arguments, claim = asyncio.run(approve())
            reader = ClaimJournal(tmp_path / "claims.sqlite3", **options, read_only=True)
            before = evidence.path.read_bytes()
            with ThreadPoolExecutor(4) as pool:
                results = list(pool.map(lambda _: reader.resolve_verified_call(bound.selector, "confirm_order",
                    digest(arguments), now_epoch=current[0].timestamp()), range(8)))
            assert all(item == claim for item in results)
            assert reader.db.total_changes == 0
            assert evidence.path.read_bytes() == before
            assert len(client.calls) == 3
            assert claim.user_id == "123"  # not sender456
            assert claim.approval.prompt_receipt_ref == receipt_ref
        finally:
            if reader:
                reader.close()
            if claims:
                claims.close()
            evidence.close()


    def test_empty_complete_page_keeps_actual_broker_cursor(self):
        value = response({"updates": [], "next_after": {"update_id": 9}, "complete": True})
        evidence, client = store(self.root, [value])
        try:
            self.assertEqual(evidence.poll(after_update_id=9), [])
            self.assertEqual(evidence.db.execute("SELECT final_id FROM polls").fetchone()[0], 9)
            self.assertEqual(len(client.calls), 1)
        finally:
            evidence.close()
