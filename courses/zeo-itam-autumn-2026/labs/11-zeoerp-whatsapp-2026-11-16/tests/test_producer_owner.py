"""Synthetic SDK type; owner independently reruns the actual receiving SDK."""
import sys
from types import SimpleNamespace, ModuleType
import unittest
from unittest.mock import patch
from pydantic import BaseModel, ConfigDict
from class_fixture_binding import BrokerScope
from producer_owner import check_notice_fence


class ExpectedBinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    external_identity: str
    connection_revision: str


class NoticeFenceTests(unittest.TestCase):
    def test_wrong_bot_or_revision_is_refused_independently(self):
        scope = BrokerScope(company_id="test", connection_id="test_connection",
                            connection_revision="7", bot_binding="test_bot")
        module = ModuleType("zeo_core.integrations.hosted.client")
        module.HostedExpectedBinding = ExpectedBinding
        with patch.dict(sys.modules, {module.__name__: module}):
            for identity, revision in [("wrong_bot", "7"), ("test_bot", "8")]:
                with self.subTest(identity=identity, revision=revision), self.assertRaises(PermissionError):
                    check_notice_fence(scope, ExpectedBinding(external_identity=identity, connection_revision=revision))
            for absent in [None, {}, "test_bot", SimpleNamespace(external_identity="test_bot", connection_revision="7")]:
                with self.assertRaises(PermissionError):
                    check_notice_fence(scope, absent)
            check_notice_fence(scope, ExpectedBinding(external_identity="test_bot", connection_revision="7"))
