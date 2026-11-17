"""ERP-owned notice cases using the local permit; ERP tests the real type separately."""
from datetime import datetime, timedelta, timezone
import hashlib
from pathlib import Path
import tempfile
import unittest


import class_fixture_binding as binding

NoticePermit = binding.ClassNoticePermit
NOW = datetime(2026, 11, 15, 13, 0, tzinfo=timezone.utc)


class NoticeAuthorityContract(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.scope = binding.BrokerScope(company_id="synthetic", connection_id="synthetic-connection",
            connection_revision="1", bot_binding="synthetic-bot")
        seed = binding.PersistedObservation(scope=self.scope,
            update=binding.MessageUpdate(update_id=100, kind="message", chat_id=123456,
                from_user_id=654321, text="synthetic enrollment", message_id=42, date=int(NOW.timestamp())),
            response_sha256="a"*64)
        self.row = binding.propose_row(seed, erp_customer_id="synthetic-customer", known_private_chat=True)
        self.path = self.root/"mapping.json"
        self.path.write_text(binding.FixtureMap(rows=(self.row,)).model_dump_json())
        self.sha = hashlib.sha256(self.path.read_bytes()).hexdigest()
        self.authority = self.make_authority(self.scope)
        self.fields = dict(company_id="synthetic", customer_id="synthetic-customer", channel="telegram",
                           user_id="123456", now=NOW.timestamp())

    def tearDown(self):
        self.tmp.cleanup()

    def make_authority(self, scope):
        return binding.ClassNoticeAuthority(self.path, approved_sha256=self.sha,
            scope=scope, channel="telegram", permit_factory=NoticePermit)

    def lookup(self, **changes):
        return self.authority.authorize_notice(**{**self.fields, **changes})

    def test_local_permit_type_and_exact_identity(self):
        permit = self.lookup()
        self.assertIsInstance(permit, NoticePermit)
        self.assertEqual((permit.company_id, permit.customer_id, permit.channel, permit.user_id),
                         ("synthetic", "synthetic-customer", "telegram", "123456"))
        self.assertEqual(permit.valid_until, int(binding.CLASS_END.timestamp()))
        self.assertEqual(permit.binding_ref, "class-fixture-sha256:"+self.sha)

    def test_company_customer_channel_mismatch_refused(self):
        for key in ("company_id", "customer_id", "channel"):
            with self.subTest(key=key), self.assertRaises(binding.FixtureRefused):
                self.lookup(**{key: "other"})

    def test_sender_group_tracker_and_noncanonical_chat_refused(self):
        for user_id in ("654321", "-123456", "shop-opaque", "0123456", "+123456", 123456):
            with self.subTest(user_id=user_id), self.assertRaises(binding.FixtureRefused):
                self.lookup(user_id=user_id)

    def test_exact_connection_revision_and_bot_scope_required(self):
        for key in ("connection_id", "connection_revision", "bot_binding"):
            authority = self.make_authority(self.scope.model_copy(update={key: "other"}))
            with self.subTest(key=key), self.assertRaises(binding.FixtureRefused):
                authority.authorize_notice(**self.fields)

    def test_expiry_at_boundary_and_after_refused(self):
        for now in (binding.CLASS_END.timestamp(), binding.CLASS_END.timestamp()+1):
            with self.subTest(now=now), self.assertRaises(binding.FixtureRefused):
                self.lookup(now=now)

    def test_nonfinite_and_boolean_times_refused(self):
        for now in (float("nan"), float("inf"), True, "1794747600"):
            with self.subTest(now=now), self.assertRaises(binding.FixtureRefused):
                self.lookup(now=now)

    def test_tampered_map_rechecked_on_every_lookup(self):
        self.lookup()
        self.path.write_bytes(self.path.read_bytes()+b" ")
        with self.assertRaisesRegex(binding.FixtureRefused, "APPROVED_MAPPING_HASH_MISMATCH"):
            self.lookup()

    def test_repeated_outbound_lookup_never_consumes_inbound_update(self):
        verifier = binding.ClassFixtureBinding(self.path, approved_sha256=self.sha,
            journal_path=self.root/"consumed.sqlite", max_age_seconds=60, future_skew_seconds=2)
        try:
            self.lookup(); self.lookup()
            self.assertEqual(verifier.db.execute("SELECT COUNT(*) FROM class_consumed_updates").fetchone()[0], 0)
            observation = binding.PersistedObservation(scope=self.scope,
                update=binding.MessageUpdate(update_id=101, kind="message", chat_id=123456,
                    from_user_id=654321, text="synthetic command", message_id=43, date=int(NOW.timestamp())),
                response_sha256="b"*64)
            verifier.consume(observation, now=NOW, deadline=NOW+timedelta(seconds=30))
            self.lookup()
            self.assertEqual(verifier.db.execute("SELECT COUNT(*) FROM class_consumed_updates").fetchone()[0], 1)
        finally:
            verifier.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
