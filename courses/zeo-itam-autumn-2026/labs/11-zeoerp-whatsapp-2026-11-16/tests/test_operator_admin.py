"""Synthetic launcher capability checks; no actual admin operation."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import copy
import pickle
import unittest
from operator_admin import AdminCapabilityIssuer, OperatorAdminCapability


class AdminTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 15, 20, tzinfo=timezone.utc)
        self.args = dict(launcher_identity="sha256:" + "a" * 64, company_id="test_company",
                         action="fulfill_order", run_id="test_run", now_epoch=self.now.timestamp())
        self.issuer = AdminCapabilityIssuer(**{k: v for k, v in self.args.items() if k not in {"action", "now_epoch"}},
            expires_at_epoch=(self.now + timedelta(minutes=10)).timestamp(), clock=lambda: self.now)
        self.capability = self.issuer.issue()

    def test_only_original_object_is_authority(self):
        for fake in ["admin", "clm_" + "a" * 32, {}, OperatorAdminCapability(), None]:
            with self.assertRaises(PermissionError):
                self.issuer.verify_admin_capability(fake, **self.args)
        for operation in [copy.copy, copy.deepcopy, pickle.dumps]:
            with self.assertRaises(TypeError):
                operation(self.capability)
        with self.assertRaises(PermissionError):
            self.issuer.issue()

    def test_each_binding_and_expiry_refuses(self):
        for field, bad in [("launcher_identity", "sha256:" + "b" * 64), ("company_id", "other"),
                           ("action", "confirm_order"), ("run_id", "other"),
                           ("now_epoch", float("nan")), ("now_epoch", float("inf")),
                           ("now_epoch", True), ("now_epoch", self.now.timestamp() + 601)]:
            with self.subTest(field=field, bad=bad), self.assertRaises(PermissionError):
                self.issuer.verify_admin_capability(self.capability, **{**self.args, field: bad})
        self.now += timedelta(minutes=11)
        with self.assertRaises(PermissionError):
            self.issuer.verify_admin_capability(self.capability, **self.args)

    def test_repeatable_threads_and_revocation(self):
        with ThreadPoolExecutor(4) as pool:
            values = list(pool.map(lambda _: self.issuer.verify_admin_capability(self.capability, **self.args), range(8)))
        self.assertTrue(all(value == values[0] for value in values))
        self.assertEqual(values[0].action, "fulfill_order")
        self.issuer.close()
        self.issuer.close()
        with self.assertRaises(PermissionError):
            self.issuer.verify_admin_capability(self.capability, **self.args)
        with self.assertRaises(PermissionError):
            self.issuer.issue()
