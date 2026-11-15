"""ERP-owned offline contract cases against Rasa's sole class binding source.
All mappings and observations here are synthetic; no live approval is implied.
"""
from datetime import datetime, timedelta, timezone
import hashlib
from pathlib import Path
import tempfile
import unittest

import class_fixture_binding as binding
NOW = datetime(2026, 11, 15, 13, 0, tzinfo=timezone.utc)


class ClassAuthority(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.scope = binding.BrokerScope(company_id="synthetic-company", connection_id="synthetic-connection",
            connection_revision="1", bot_binding="synthetic-bot")
        self.seed = self.observation(100)
        self.row = binding.propose_row(self.seed, erp_customer_id="synthetic-customer",
                                       known_private_chat=True)
        self.path = self.root / "mapping.json"
        self.path.write_text(binding.FixtureMap(rows=(self.row,)).model_dump_json())
        self.sha = hashlib.sha256(self.path.read_bytes()).hexdigest()
        self.instances = []
        self.verifier = self.open()

    def tearDown(self):
        for instance in self.instances:
            instance.close()
        self.tmp.cleanup()

    def observation(self, update_id=101, **overrides):
        fields = dict(update_id=update_id, kind="message", chat_id=123456, from_user_id=654321,
                      text="synthetic command", message_id=42, date=int(NOW.timestamp())-1)
        fields.update(overrides)
        return binding.PersistedObservation(scope=self.scope,
            update=binding.MessageUpdate(**fields), response_sha256="a"*64)

    def open(self):
        instance = binding.ClassFixtureBinding(self.path, approved_sha256=self.sha,
            journal_path=self.root/"consumed.sqlite", max_age_seconds=60, future_skew_seconds=2)
        self.instances.append(instance)
        return instance

    def consume(self, observation=None, **kwargs):
        return self.verifier.consume(observation or self.observation(),
            now=kwargs.get("now", NOW), deadline=kwargs.get("deadline", NOW+timedelta(seconds=30)))

    def test_valid_bound_message_keeps_separate_chat_and_sender(self):
        result = self.consume()
        self.assertEqual((result.chat_id, result.from_user_id), (123456, 654321))
        self.assertEqual(result.erp_customer_id, "synthetic-customer")
        self.assertEqual(result.update_id, 101)

    def test_company_connection_revision_and_bot_mismatch_refused(self):
        for key in ("company_id", "connection_id", "connection_revision", "bot_binding"):
            with self.subTest(key=key):
                observation = self.observation().model_copy(update={"scope": self.scope.model_copy(update={key: "different"})})
                with self.assertRaises(binding.FixtureRefused):
                    self.consume(observation)

    def test_exact_chat_and_sender_both_required(self):
        for change in ({"chat_id": 654321}, {"from_user_id": 123456}, {"chat_id": -123456}):
            with self.subTest(change=change), self.assertRaises(binding.FixtureRefused):
                self.consume(self.observation(**change))

    def test_map_expiry_and_request_deadline_refused(self):
        for now, deadline in ((binding.CLASS_END, binding.CLASS_END),
                              (NOW, NOW), (NOW, binding.CLASS_END+timedelta(seconds=1))):
            with self.subTest(now=now, deadline=deadline), self.assertRaises(binding.FixtureRefused):
                self.consume(now=now, deadline=deadline)

    def test_future_and_stale_messages_refused(self):
        for date in (int(NOW.timestamp())+3, int(NOW.timestamp())-61):
            with self.subTest(date=date), self.assertRaises(binding.FixtureRefused):
                self.consume(self.observation(date=date))

    def test_replayed_update_id_refused_after_restart(self):
        self.consume()
        restarted = self.open()
        with self.assertRaisesRegex(binding.FixtureRefused, "UPDATE_ALREADY_CONSUMED"):
            restarted.consume(self.observation(), now=NOW, deadline=NOW+timedelta(seconds=30))

    def test_changed_text_under_same_update_id_does_not_bypass_claim(self):
        self.consume()
        with self.assertRaisesRegex(binding.FixtureRefused, "UPDATE_ALREADY_CONSUMED"):
            self.consume(self.observation(text="changed command"))

    def test_enrollment_or_older_update_never_becomes_command(self):
        for update_id in (99, 100):
            with self.subTest(update_id=update_id), self.assertRaisesRegex(binding.FixtureRefused, "ENROLLMENT_OR_OLDER"):
                self.consume(self.observation(update_id))

    def test_callback_null_and_ambiguous_truncation_refused(self):
        for change in ({"kind": "callback_query"}, {"chat_id": None}, {"date": None},
                       {"from_user_id": None}, {"message_id": None}, {"text": None},
                       {"text": "x"*4096}, {"text": "x"*4097}):
            with self.subTest(field=list(change)), self.assertRaises(ValueError):
                self.observation(**change)

    def test_missing_private_chat_assertion_refused(self):
        with self.assertRaises(binding.FixtureRefused):
            binding.propose_row(self.seed, erp_customer_id="synthetic", known_private_chat=False)

    def test_tampered_map_rejected_by_approved_hash(self):
        self.path.write_bytes(self.path.read_bytes()+b" ")
        with self.assertRaisesRegex(binding.FixtureRefused, "APPROVED_MAPPING_HASH_MISMATCH"):
            self.open()

    def test_class_validity_cannot_be_extended(self):
        with self.assertRaises(ValueError):
            binding.propose_row(self.seed, erp_customer_id="synthetic", known_private_chat=True,
                               valid_until=binding.CLASS_END+timedelta(seconds=1))


if __name__ == "__main__":
    unittest.main(verbosity=2)
