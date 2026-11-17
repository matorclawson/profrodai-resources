"""Reviewed class-only customer/chat binding, not public customer enrollment.

The transport owner must authenticate the Broker observation and persist its exact
response before calling this module. A typed object is not that authentication.
No chat ID, sender ID, principal or approval comes from model arguments.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


CLASS_END = datetime(2026, 11, 17, 23, 59, tzinfo=timezone.utc)


class FixtureRefused(ValueError):
    """A fixed reason suitable for a private bounded diagnostic."""


class Boundary(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class BrokerScope(Boundary):
    company_id: str = Field(min_length=1, max_length=128)
    connection_id: str = Field(min_length=1, max_length=128)
    connection_revision: str = Field(min_length=1, max_length=128)
    bot_binding: str = Field(min_length=1, max_length=256)


class MessageUpdate(Boundary):
    update_id: int = Field(ge=0, le=2**53)
    kind: Literal["message"]
    chat_id: int = Field(ge=-(10**15), le=10**15)
    from_user_id: int = Field(gt=0, le=10**15)
    text: str = Field(min_length=1, max_length=4096)
    message_id: int = Field(gt=0, le=2**53)
    date: int = Field(ge=0, le=2**53)

    @model_validator(mode="after")
    def require_unambiguous_text_bound(self):
        # The pinned Broker silently slices at 4096. A full-sized value might
        # be truncated; it cannot establish the exact original confirmation.
        if len(self.text) == 4096:
            raise ValueError("COMPLETE_TEXT_NOT_PROVED")
        return self


class PersistedObservation(Boundary):
    scope: BrokerScope
    update: MessageUpdate
    # Hash of the actual persisted Broker response; the transport owner must
    # verify its request, receipt, organization and connection independently.
    response_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class FixtureRow(Boundary):
    scope: BrokerScope
    erp_customer_id: str = Field(min_length=1, max_length=128)
    private_chat_id: int = Field(gt=0, le=10**15)
    from_user_id: int = Field(gt=0, le=10**15)
    valid_until: datetime
    source_update_id: int = Field(ge=0, le=2**53)
    source_observation_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def class_expiry(self):
        if self.valid_until.tzinfo is None or self.valid_until > CLASS_END:
            raise ValueError("CLASS_VALIDITY_EXCEEDED")
        return self


class FixtureMap(Boundary):
    schema_version: Literal[1] = 1
    rows: tuple[FixtureRow, ...]

    @model_validator(mode="after")
    def distinct_customers_and_chats(self):
        customers, chats = set(), set()
        for row in self.rows:
            scope = canonical(row.scope)
            customer = (scope, row.erp_customer_id)
            chat = (scope, row.private_chat_id)
            if customer in customers or chat in chats:
                raise ValueError("DUPLICATE_FIXTURE_BINDING")
            customers.add(customer)
            chats.add(chat)
        return self


class BoundClassMessage(Boundary):
    scope: BrokerScope
    erp_customer_id: str
    chat_id: int
    from_user_id: int
    update_id: int
    message_id: int
    text: str
    date: int
    observation_sha256: str
    valid_until: datetime


def canonical(value: BaseModel) -> str:
    return json.dumps(value.model_dump(mode="json"), sort_keys=True,
                      separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def observation_digest(observation: PersistedObservation) -> str:
    return hashlib.sha256(canonical(observation).encode()).hexdigest()


def propose_row(observation: PersistedObservation, *, erp_customer_id: str,
                known_private_chat: bool, valid_until: datetime = CLASS_END) -> FixtureRow:
    """Derive IDs only from the exact retained observation, never CLI fields.

    known_private_chat is an operator review assertion, not a provider-derived
    chat-type claim. This creates a PROPOSAL; it authorizes no message or action.
    Two independent reviewers and the operator must approve the final map hash.
    """
    if known_private_chat is not True or observation.update.chat_id <= 0:
        raise FixtureRefused("REVIEWED_PRIVATE_CHAT_REQUIRED")
    return FixtureRow(scope=observation.scope, erp_customer_id=erp_customer_id,
        private_chat_id=observation.update.chat_id,
        from_user_id=observation.update.from_user_id, valid_until=valid_until,
        source_update_id=observation.update.update_id,
        source_observation_sha256=observation_digest(observation))


class ClassFixtureBinding:
    """Consume once against a separately approved immutable map.

    approved_sha256 must come from the trusted launcher after both readers and
    Operator approval, never from the map itself or model input. The journal is
    private persistent class state. A consumed update stays consumed on failure;
    no automatic retry, cursor reset or claim of ERP draft approval is provided.
    """
    def __init__(self, mapping_path: Path, *, approved_sha256: str,
                 journal_path: Path, max_age_seconds: int, future_skew_seconds: int):
        raw = mapping_path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != approved_sha256:
            raise FixtureRefused("APPROVED_MAPPING_HASH_MISMATCH")
        self.mapping = FixtureMap.model_validate_json(raw)
        if type(max_age_seconds) is not int or not 1 <= max_age_seconds <= 900:
            raise FixtureRefused("INVALID_FRESHNESS_BOUND")
        if type(future_skew_seconds) is not int or not 0 <= future_skew_seconds <= 5:
            raise FixtureRefused("INVALID_FUTURE_CLOCK_BOUND")
        self.max_age, self.future_skew = max_age_seconds, future_skew_seconds
        self.db = sqlite3.connect(journal_path, timeout=5, isolation_level=None)
        self.db.execute("CREATE TABLE IF NOT EXISTS class_consumed_updates ("
                        "scope TEXT NOT NULL, update_id INTEGER NOT NULL, "
                        "observation_sha256 TEXT NOT NULL, PRIMARY KEY(scope,update_id))")

    def close(self):
        self.db.close()

    def consume(self, observation: PersistedObservation, *, now: datetime,
                deadline: datetime) -> BoundClassMessage:
        if now.tzinfo is None or deadline.tzinfo is None:
            raise FixtureRefused("UTC_TIME_REQUIRED")
        update = observation.update
        rows = [row for row in self.mapping.rows if row.scope == observation.scope
                and row.private_chat_id == update.chat_id
                and row.from_user_id == update.from_user_id]
        if len(rows) != 1:
            raise FixtureRefused("EXACT_CUSTOMER_CHAT_BINDING_REQUIRED")
        row = rows[0]
        if not now < deadline <= row.valid_until <= CLASS_END:
            raise FixtureRefused("FIXTURE_OR_DEADLINE_EXPIRED")
        age = now.timestamp() - update.date
        if age < -self.future_skew or age > self.max_age:
            raise FixtureRefused("MESSAGE_OUTSIDE_FRESHNESS_BOUND")
        # The enrollment message establishes the proposal only, never a fresh
        # customer command after the map is approved.
        if update.update_id <= row.source_update_id:
            raise FixtureRefused("ENROLLMENT_OR_OLDER_UPDATE_REFUSED")
        digest = observation_digest(observation)
        try:
            self.db.execute("INSERT INTO class_consumed_updates VALUES(?,?,?)",
                            (canonical(observation.scope), update.update_id, digest))
        except sqlite3.IntegrityError:
            raise FixtureRefused("UPDATE_ALREADY_CONSUMED") from None
        return BoundClassMessage(scope=row.scope, erp_customer_id=row.erp_customer_id,
            chat_id=update.chat_id, from_user_id=update.from_user_id,
            update_id=update.update_id, message_id=update.message_id, text=update.text,
            date=update.date, observation_sha256=digest, valid_until=row.valid_until)


class ClassNoticePermit(Boundary):
    company_id: str
    customer_id: str
    channel: str
    user_id: str
    valid_until: int
    binding_ref: str = Field(min_length=1, max_length=200)


class ClassNoticeAuthority:
    """Read-only approved-map lookup for ERP's injected NoticeAuthority port.

    The ERP journal's recipient user_id must already be the exact canonical
    recorded private chat ID string. It is never derived from from_user_id.
    The trusted composition supplies channel and authenticated connection scope.
    This lookup neither consumes an inbound update nor approves confirm_order.
    ERP's poller owns the shipped Status approval and durable once-per-order send.
    """
    def __init__(self, mapping_path: Path, *, approved_sha256: str,
                 scope: BrokerScope, channel: str, permit_factory=ClassNoticePermit):
        if not isinstance(scope, BrokerScope) or not channel or len(channel) > 32:
            raise FixtureRefused("EXPLICIT_NOTICE_SCOPE_REQUIRED")
        self.path, self.approved_sha256 = mapping_path, approved_sha256
        self.scope, self.channel, self.permit_factory = scope, channel, permit_factory

    def authorize_notice(self, *, company_id: str, customer_id: str, channel: str,
                         user_id: str, now: float):
        import math
        if type(now) not in {int, float} or not math.isfinite(now):
            raise FixtureRefused("INVALID_NOTICE_TIME")
        if company_id != self.scope.company_id or channel != self.channel:
            raise FixtureRefused("NOTICE_SCOPE_MISMATCH")
        raw = self.path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != self.approved_sha256:
            raise FixtureRefused("APPROVED_MAPPING_HASH_MISMATCH")
        mapping = FixtureMap.model_validate_json(raw)
        rows = [row for row in mapping.rows if row.scope == self.scope
                and row.erp_customer_id == customer_id
                and type(user_id) is str and str(row.private_chat_id) == user_id]
        if len(rows) != 1:
            raise FixtureRefused("EXACT_NOTICE_CUSTOMER_BINDING_REQUIRED")
        row = rows[0]
        if not now < row.valid_until.timestamp() <= CLASS_END.timestamp():
            raise FixtureRefused("NOTICE_FIXTURE_EXPIRED")
        permit = ClassNoticePermit(company_id=company_id, customer_id=customer_id,
            channel=channel, user_id=user_id, valid_until=int(row.valid_until.timestamp()),
            binding_ref="class-fixture-sha256:" + self.approved_sha256)
        return self.permit_factory(**permit.model_dump())
