"""Explicit composition of admitted transport, verified claims and native Mantle.

No defaults select company, chat, key, paired device, sheet or admin principal.
The operator launcher receives actual owner inputs and reviewed source pins.
A settings file alone does not authenticate or admit a transport.
"""
from __future__ import annotations

from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import stat

from pydantic import BaseModel, ConfigDict, Field

from broker_evidence import BrokerEvidence, BrokerEvidenceReader
from channel_journal import ChannelJournal
from class_fixture_binding import BrokerScope, FixtureMap
from commerce_schema import FrozenCommerceSchemas
from core_binding import CoreBinding
from mcp_port import SessionERPPort
from native_mantle import NativeModelSource, native_mantle
from native_sessions import LocalERPSettings, NativeERPSessions
from operator_admin import AdminCapabilityIssuer, CLASS_DAY_END_EPOCH
from operator_claims import AuthorizedERPPort, ClaimJournal, digest
from operator_runtime import OperatorRuntime, RunBounds


class OperatorSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    run_id: str = Field(pattern=r"^[\x20-\x7e]{1,100}$")
    scope: BrokerScope
    state_directory: Path
    approved_mapping: Path
    approved_map_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    launcher_identity: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    erp: LocalERPSettings
    model: NativeModelSource
    bounds: RunBounds


def private_state(path):
    info = path.stat(follow_symlinks=False)
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) & 0o077):
        raise PermissionError("EXISTING_PRIVATE_RUN_DIRECTORY_REQUIRED")


def source_identity():
    root = Path(__file__).parent
    names = ("broker_evidence.py", "channel_journal.py", "channel_runtime.py", "class_fixture_binding.py",
             "commerce_schema.py", "core_binding.py", "mantle_tools.py", "mcp_port.py",
             "native_sessions.py", "native_mantle.py", "operator_admin.py", "operator_claims.py",
             "operator_composition.py", "operator_runtime.py", "producer_owner.py", "contracts/commerce-mcp-v1.json",
             "native-agent/agent.yml", "native-agent/integrations.yml", "native-agent/tools/commerce.py")
    manifest = "\n".join(f"{hashlib.sha256((root / name).read_bytes()).hexdigest()}  {name}" for name in names) + "\n"
    return "sha256:" + hashlib.sha256(manifest.encode()).hexdigest()


def check_mapping(settings, clock):
    if settings.launcher_identity != source_identity():
        raise PermissionError("REVIEWED_LAUNCHER_SOURCE_CHANGED")
    private_state(settings.state_directory)
    raw = settings.approved_mapping.read_bytes()
    if hashlib.sha256(raw).hexdigest() != settings.approved_map_sha256:
        raise PermissionError("APPROVED_OPERATOR_MAP_CHANGED")
    mapping = FixtureMap.model_validate_json(raw)
    if len(mapping.rows) != 1 or mapping.rows[0].scope != settings.scope:
        raise PermissionError("ONE_APPROVED_OPERATOR_REQUIRED")
    row = mapping.rows[0]
    expected_customer = "cus_" + digest([settings.scope.company_id, "telegram", str(row.private_chat_id)])[:24]
    if row.erp_customer_id != expected_customer:
        raise PermissionError("EXACT_PRODUCER_CUSTOMER_DERIVATION_REQUIRED")
    if not clock().timestamp() < settings.bounds.not_after_epoch <= min(row.valid_until.timestamp(), CLASS_DAY_END_EPOCH):
        raise PermissionError("LIVE_BOUNDED_OPERATOR_RUN_REQUIRED")
    if settings.model.model_directory.parent != settings.state_directory:
        raise PermissionError("ISOLATED_RUN_MODEL_DIRECTORY_REQUIRED")
    return row


def check_enrollment(row, evidence):
    original = evidence.observation_reader(row.source_observation_sha256)
    if ((original.scope, original.update.chat_id, original.update.from_user_id, original.update.update_id) !=
            (row.scope, row.private_chat_id, row.from_user_id, row.source_update_id)):
        raise PermissionError("ORIGINAL_ENROLLMENT_BINDING_REQUIRED")


def claim_options(settings, evidence, clock):
    return dict(run_id=settings.run_id, scope=settings.scope,
        mapping_path=settings.approved_mapping, approved_map_sha256=settings.approved_map_sha256,
        run_expires_epoch=settings.bounds.not_after_epoch, clock=clock,
        observation_reader=evidence.observation_reader, prompt_receipt_reader=evidence.prompt_receipt_reader,
        first_inbound_reader=evidence.first_inbound_reader,
        inbound_watermark_reader=evidence.inbound_watermark_reader)


@contextmanager
def producer_claim_resolver(settings: OperatorSettings, *, clock):
    """Same retained claims, readonly original evidence; never another issuer."""
    settings = OperatorSettings.model_validate(settings)
    row = check_mapping(settings, clock)
    evidence = BrokerEvidenceReader(settings.state_directory / "broker.sqlite3",
                                   run_id=settings.run_id, scope=settings.scope)
    check_enrollment(row, evidence)
    claims = ClaimJournal(settings.state_directory / "claims.sqlite3",
                          **claim_options(settings, evidence, clock), read_only=True)
    try:
        yield claims
    finally:
        claims.close()
        evidence.close()


@contextmanager
def launcher_admin_capability(settings: OperatorSettings, *, clock):
    """Only in the producer/poll process's admitted owner launch path.

    The opaque object stays in this process. Only the readonly customer resolver
    uses shared journals across processes. No admin object is serialized.
    """
    settings = OperatorSettings.model_validate(settings)
    check_mapping(settings, clock)
    issuer = AdminCapabilityIssuer(launcher_identity=settings.launcher_identity,
        company_id=settings.scope.company_id, run_id=settings.run_id,
        expires_at_epoch=settings.bounds.not_after_epoch, clock=clock)
    capability = issuer.issue()
    try:
        yield issuer, capability
    finally:
        issuer.close()


@asynccontextmanager
async def customer_runtime(settings: OperatorSettings, *, admitted_broker_client,
                           clock=lambda: datetime.now(timezone.utc)):
    """Build once; caller owns the admitted client and its transport timeout.

    Producer listener/poll lifecycle is the same operator launcher's separate
    explicit process path. This context creates no listener or fake owner client.
    """
    settings = OperatorSettings.model_validate(settings)
    row = check_mapping(settings, clock)
    evidence = BrokerEvidence(settings.state_directory / "broker.sqlite3", run_id=settings.run_id,
        scope=settings.scope, admitted_client=admitted_broker_client, clock=clock)
    claims = journal = None
    try:
        check_enrollment(row, evidence)
        claims = ClaimJournal(settings.state_directory / "claims.sqlite3", **claim_options(settings, evidence, clock))
        journal = ChannelJournal(settings.state_directory / "operations.sqlite3")
        schemas = FrozenCommerceSchemas(Path(__file__).parent / "contracts/commerce-mcp-v1.json")
        sessions = NativeERPSessions(settings.erp, schemas)
        port = AuthorizedERPPort(SessionERPPort(sessions, schemas), claims)
        binding = CoreBinding(port, journal, claims, clock=clock)
        async with native_mantle(settings.model, binding=binding, clock=clock) as agent:
            yield OperatorRuntime(claims=claims, evidence=evidence, native_agent=agent,
                                  bounds=settings.bounds, clock=clock)
    finally:
        if journal is not None:
            journal.close()
        if claims is not None:
            claims.close()
        evidence.close()
