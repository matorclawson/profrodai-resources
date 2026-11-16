"""Operator-fixture call issuance and repeatable producer-side resolution.

The injected observation reader must return only observations persisted by the
admitted Broker transport. This class does not authenticate arbitrary JSON or
turn a header into authority. Its private journal is a class-fixture boundary,
not protection against another process running as the same operating-system
user. The trusted launcher supplies the reviewed map and transport reader.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import stat
import threading
from typing import Literal
from urllib.parse import quote
import uuid

from pydantic import BaseModel, ConfigDict, Field, model_validator

from class_fixture_binding import (BrokerScope, ClassFixtureBinding, FixtureMap,
                                   MessageUpdate, PersistedObservation, canonical as fixture_canonical,
                                   observation_digest)
from core_binding import ApprovalEvidence, BoundRequest, CoreRequest, business_result
from mcp_port import CORE_TOOLS, canonical


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def finite_epoch(value):
    if type(value) not in {int, float} or not math.isfinite(value) or value <= 0:
        raise ValueError("FINITE_POSITIVE_TIME_REQUIRED")
    return value


def render_review(draft):
    """Canonical host wording from the exact observed priced draft, never an LLM."""
    if (draft.get("state") != "draft" or type(draft.get("version")) is not int
            or draft["version"] < 1 or type(draft.get("scale")) is not int
            or not 0 <= draft["scale"] <= 4
            or not re.fullmatch(r"[A-Z]{3}", draft.get("currency", ""))
            or type(draft.get("total_minor")) is not int or draft["total_minor"] < 0
            or not draft.get("lines")):
        raise ValueError("OBSERVED_PRICED_DRAFT_REQUIRED")
    scale, currency = draft["scale"], draft["currency"]

    def amount(minor):
        if type(minor) is not int or minor < 0:
            raise ValueError("EXACT_MINOR_AMOUNT_REQUIRED")
        whole, fraction = divmod(minor, 10 ** scale)
        return str(whole) + (f".{fraction:0{scale}d}" if scale else "")

    parts, total, ids = [], 0, set()
    for line in draft["lines"]:
        if (line.get("currency") != currency or line.get("scale") != scale
                or type(line.get("quantity")) is not int or line["quantity"] < 1
                or line.get("product_id") in ids):
            raise ValueError("DRAFT_PRICE_OR_PRODUCT_MISMATCH")
        ids.add(line["product_id"])
        price = amount(line["unit_price_minor"])
        total += line["quantity"] * line["unit_price_minor"]
        parts.append(f"{line['quantity']} x {line['product_id']} at {currency} {price} each.")
    if total != draft["total_minor"]:
        raise ValueError("DRAFT_TOTAL_MISMATCH")
    expiry = datetime.fromtimestamp(finite_epoch(draft["expires_at_epoch"]), timezone.utc).isoformat()
    text = "\n".join([f"Review order {draft['order_id']}, version {draft['version']}.", *parts,
        f"Total {currency} {amount(total)}.", f"Review expires {expiry}.",
        "Reply yes or confirm in a new message to confirm only this order. Anything else ends this review."])
    if len(text) > 4096:
        raise ValueError("COMPLETE_REVIEW_EXCEEDS_CHANNEL_BOUND")
    return text


class StrictBoundary(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True,
                              revalidate_instances="always")


class VerifiedDraftApproval(StrictBoundary):
    order_id: str = Field(min_length=1, max_length=128)
    draft_version: int = Field(gt=0)
    prompt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    prompt_receipt_ref: str = Field(min_length=1, max_length=256)
    prompt_confirmed_epoch: float
    reply_observation_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    expires_at_epoch: float

    @model_validator(mode="after")
    def times(self):
        if finite_epoch(self.prompt_confirmed_epoch) >= finite_epoch(self.expires_at_epoch):
            raise ValueError("APPROVAL_LIFETIME_REQUIRED")
        return self


class VerifiedCallClaim(StrictBoundary):
    v: Literal[1] = 1
    run_id: str = Field(min_length=1, max_length=128)
    selector: str = Field(pattern=r"^clm_[0-9a-f]{32}$")
    company_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    channel: Literal["telegram"]
    user_id: str = Field(pattern=r"^[1-9][0-9]{0,14}$")
    request_id: str = Field(min_length=1, max_length=128)
    action: Literal["list_products", "check_stock", "create_draft_order", "confirm_order",
                    "order_status", "cancel_order", "my_orders"]
    arguments_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    observation_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    fixture_map_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    grant_expires_at_epoch: float
    approval: VerifiedDraftApproval | None

    @model_validator(mode="before")
    @classmethod
    def strict_version(cls, value):
        if isinstance(value, dict) and "v" in value and type(value["v"]) is not int:
            raise ValueError("STRICT_CLAIM_VERSION_REQUIRED")
        return value

    @model_validator(mode="after")
    def approval_scope(self):
        finite_epoch(self.grant_expires_at_epoch)
        if (self.action == "confirm_order") != (self.approval is not None):
            raise ValueError("EXACT_CONFIRMATION_APPROVAL_REQUIRED")
        if self.approval is not None:
            if self.approval.expires_at_epoch > self.grant_expires_at_epoch:
                raise ValueError("APPROVAL_OUTLIVES_CLAIM")
            if self.approval.reply_observation_sha256 != self.observation_sha256:
                raise ValueError("APPROVAL_REPLY_MISMATCH")
        return self


class ClaimJournal:
    """One run's durable claims, original-turn links and confirmed prompt records.

    Resolution is a read: repeated context/authority checks never consume a
    message or approval. Inbound consumption happens once in register_turn.
    The caller's existing operation journal still owns mutation dispatch.
    """
    def __init__(self, path: Path, *, run_id: str, scope: BrokerScope,
                 mapping_path: Path, approved_map_sha256: str, run_expires_epoch: float,
                 observation_reader, prompt_receipt_reader, first_inbound_reader,
                 inbound_watermark_reader, clock, read_only=False):
        self.run_id, self.scope = run_id, BrokerScope.model_validate(scope)
        self.mapping_path, self.map_sha = mapping_path, approved_map_sha256
        self.run_expires = float(finite_epoch(run_expires_epoch))
        self.observations, self.receipts, self.clock = observation_reader, prompt_receipt_reader, clock
        self.first_inbound, self.watermark = first_inbound_reader, inbound_watermark_reader
        self.read_only = read_only
        self._lock = threading.RLock()
        if type(read_only) is not bool:
            raise ValueError("EXPLICIT_JOURNAL_MODE_REQUIRED")
        if not run_id or not all(callable(item) for item in
                (observation_reader, prompt_receipt_reader, first_inbound_reader, inbound_watermark_reader)):
            raise ValueError("ADMITTED_EVIDENCE_READERS_REQUIRED")
        self._row()
        parent = path.parent.stat(follow_symlinks=False)
        if (not stat.S_ISDIR(parent.st_mode) or parent.st_uid != os.getuid()
                or stat.S_IMODE(parent.st_mode) & 0o077):
            raise PermissionError("PRIVATE_CLAIM_DIRECTORY_REQUIRED")
        created = False
        if not read_only:
            try:
                fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                os.close(fd)
                created = True
            except FileExistsError:
                pass
        observed_file = path.stat(follow_symlinks=False)
        if (not stat.S_ISREG(observed_file.st_mode) or observed_file.st_nlink != 1
                or observed_file.st_uid != os.getuid() or stat.S_IMODE(observed_file.st_mode) != 0o600):
            raise PermissionError("PRIVATE_CLAIM_FILE_REQUIRED")
        uri = "file:" + quote(str(path.absolute()), safe="/") + ("?mode=ro" if read_only else "?mode=rw")
        self.db = sqlite3.connect(uri, uri=True, timeout=2, isolation_level=None, check_same_thread=False)
        binding = canonical({"run_id": run_id, "scope": json.loads(fixture_canonical(scope)),
                             "map_sha256": self.map_sha, "expires": self.run_expires})
        try:
            if created:
                self.db.execute("CREATE TABLE operator_run (id INTEGER PRIMARY KEY CHECK(id=1), binding TEXT NOT NULL)")
                self.db.execute("INSERT INTO operator_run VALUES(1,?)", (binding,))
            stored = self.db.execute("SELECT binding FROM operator_run WHERE id=1").fetchone()
            if stored is None or stored[0] != binding:
                raise ValueError("EXISTING_RUN_BINDING_MISMATCH")
        except BaseException:
            self.db.close()
            raise
        if not read_only:
            self.db.execute("CREATE TABLE IF NOT EXISTS operator_run_draft ("
                            "singleton INTEGER PRIMARY KEY CHECK(singleton=1), selector TEXT UNIQUE NOT NULL)")
            self.db.execute("CREATE TABLE IF NOT EXISTS operator_turns (request_id TEXT PRIMARY KEY, "
                        "observation_sha TEXT UNIQUE NOT NULL, update_id INTEGER NOT NULL, "
                        "request_json TEXT NOT NULL, bound_json TEXT NOT NULL)")
            self.db.execute("CREATE TABLE IF NOT EXISTS operator_calls (selector TEXT PRIMARY KEY, "
                        "request_id TEXT NOT NULL, action TEXT NOT NULL, approval_json TEXT, "
                        "arguments_sha TEXT, claim_json TEXT)")
            self.db.execute("CREATE TABLE IF NOT EXISTS operator_reviews (order_id TEXT PRIMARY KEY, "
                        "request_id TEXT NOT NULL, review_json TEXT NOT NULL)")
            self.db.execute("CREATE TABLE IF NOT EXISTS operator_drafts (order_id TEXT NOT NULL, version INTEGER NOT NULL, "
                            "request_id TEXT NOT NULL,payload_json TEXT NOT NULL, PRIMARY KEY(order_id,version,request_id))")
            self.db.execute("CREATE TABLE IF NOT EXISTS operator_results (selector TEXT PRIMARY KEY, payload_json TEXT NOT NULL)")
        self.binding = None if read_only else ClassFixtureBinding(mapping_path, approved_sha256=approved_map_sha256,
            journal_path=path, max_age_seconds=300, future_skew_seconds=0)

    def close(self):
        with self._lock:
            if self.binding is not None:
                self.binding.close()
            self.db.close()

    def _row(self):
        raw = self.mapping_path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != self.map_sha:
            raise PermissionError("APPROVED_MAP_CHANGED")
        mapping = FixtureMap.model_validate_json(raw)
        if len(mapping.rows) != 1 or mapping.rows[0].scope != self.scope:
            raise PermissionError("SINGLE_OPERATOR_SCOPE_REQUIRED")
        row = mapping.rows[0]
        if self.run_expires > row.valid_until.timestamp():
            raise PermissionError("RUN_OUTLIVES_MAP")
        return row

    def register_turn(self, observation_sha256: str, *, deadline: datetime) -> CoreRequest:
        if self.read_only:
            raise PermissionError("READ_ONLY_CLAIM_RESOLVER")
        observation = self.observations(observation_sha256)
        if not isinstance(observation, PersistedObservation) or observation_digest(observation) != observation_sha256:
            raise PermissionError("ADMITTED_ORIGINAL_OBSERVATION_REQUIRED")
        now = self.clock()
        if deadline.tzinfo is None or deadline.timestamp() > self.run_expires:
            raise PermissionError("BOUNDED_RUN_DEADLINE_REQUIRED")
        self._row()
        bound = self.binding.consume(observation, now=now, deadline=deadline)
        request_id = "tg:" + digest(json.loads(fixture_canonical(self.scope)))[:24] + ":" + str(bound.update_id)
        request = CoreRequest(self.scope.company_id, "telegram", str(bound.chat_id), request_id,
            bound.text, datetime.fromtimestamp(bound.date, timezone.utc), deadline)
        payload = self._request_json(request)
        # If persistence fails after consume, the message stays consumed. Never
        # reset the original update or manufacture a fresh request on restart.
        self.db.execute("INSERT INTO operator_turns VALUES(?,?,?,?,?)",
            (request_id, observation_sha256, bound.update_id, payload, fixture_canonical(bound)))
        return request

    @staticmethod
    def _request_json(request):
        return canonical({"company_id": request.company_id, "channel": request.channel,
            "user_id": request.user_id, "request_id": request.request_id, "text": request.text,
            "sent_at": request.sent_at.isoformat(), "deadline": request.deadline.isoformat()})

    def _turn(self, request):
        row = self.db.execute("SELECT observation_sha,request_json,bound_json FROM operator_turns "
                              "WHERE request_id=?", (request.request_id,)).fetchone()
        if row is None or row[1] != self._request_json(request):
            raise PermissionError("EXACT_REGISTERED_TURN_REQUIRED")
        self._row()
        original = self.observations(row[0])
        if (not isinstance(original, PersistedObservation) or observation_digest(original) != row[0]
                or original.scope != self.scope or original.update.text != request.text
                or str(original.update.chat_id) != request.user_id):
            raise PermissionError("ORIGINAL_TURN_CHANGED")
        now = self.clock().timestamp()
        if not now < min(request.deadline.timestamp(), self.run_expires):
            raise PermissionError("TURN_OR_RUN_EXPIRED")
        return row[0], json.loads(row[2])

    def observe_draft_result(self, selector, action, payload):
        if self.read_only:
            raise PermissionError("READ_ONLY_CLAIM_RESOLVER")
        row = self.db.execute("SELECT request_id FROM operator_calls WHERE selector=? AND action=?",
                              (selector, action)).fetchone()
        if row is None:
            raise PermissionError("BOUND_DRAFT_CALL_REQUIRED")
        # Preserve a known validated result even when the request deadline or
        # map changes during dispatch. Those changes forbid new actions; they
        # do not turn a known original result into a reason to send again.
        self.db.execute("INSERT OR IGNORE INTO operator_results VALUES(?,?)", (selector, canonical(payload)))
        original_result = self.db.execute("SELECT payload_json FROM operator_results WHERE selector=?", (selector,)).fetchone()
        if original_result[0] != canonical(payload):
            raise PermissionError("ORIGINAL_WIRE_RESULT_CHANGED")
        result = business_result(action, payload)
        if (action not in {"create_draft_order", "order_status"} or not result["ok"]
                or result["state"] != "completed" or result["projection"] != "confirmed"
                or result["data"].get("state") != "draft"):
            return
        draft = result["data"]
        render_review(draft)
        request = self._load_request(row[0])
        bound = json.loads(self.db.execute("SELECT bound_json FROM operator_turns WHERE request_id=?",
                                           (request.request_id,)).fetchone()[0])
        if draft["customer_id"] != bound["erp_customer_id"]:
            raise PermissionError("OBSERVED_DRAFT_OWNER_MISMATCH")
        self.db.execute("INSERT OR IGNORE INTO operator_drafts VALUES(?,?,?,?)",
            (draft["order_id"], draft["version"], request.request_id, canonical(draft)))
        stored = self.db.execute("SELECT payload_json FROM operator_drafts WHERE order_id=? AND version=? AND request_id=?",
            (draft["order_id"], draft["version"], request.request_id)).fetchone()
        if stored[0] != canonical(draft):
            raise PermissionError("OBSERVED_DRAFT_CHANGED")

    def record_prompt(self, request, *, draft: dict, text: str, receipt_ref: str,
                      confirmed_epoch: float, inbound_watermark: int):
        if self.read_only:
            raise PermissionError("READ_ONLY_CLAIM_RESOLVER")
        observation_sha, bound = self._turn(request)
        observed = self.db.execute("SELECT payload_json FROM operator_drafts WHERE order_id=? AND version=? AND request_id=?",
            (draft.get("order_id"), draft.get("version"), request.request_id)).fetchone()
        if observed is None or observed[0] != canonical(draft) or text != render_review(draft):
            raise PermissionError("OBSERVED_CANONICAL_DRAFT_REVIEW_REQUIRED")
        finite_epoch(confirmed_epoch)
        if (draft.get("state") != "draft" or draft.get("customer_id") != bound["erp_customer_id"]
                or type(draft.get("version")) is not int or draft["version"] < 1
                or type(inbound_watermark) is not int or inbound_watermark < bound["update_id"]
                or inbound_watermark != self.watermark(self.scope, bound["chat_id"])
                or not confirmed_epoch < finite_epoch(draft.get("expires_at_epoch"))
                or self.clock().timestamp() < confirmed_epoch):
            raise PermissionError("EXACT_DRAFT_PROMPT_REQUIRED")
        receipt = self.receipts(receipt_ref)
        expected = {"company_id": request.company_id, "user_id": request.user_id,
                    "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
                    "confirmed_epoch": confirmed_epoch}
        if receipt != expected:
            raise PermissionError("CONFIRMED_ORIGINAL_PROMPT_RECEIPT_REQUIRED")
        review = {"draft": draft, "prompt_sha256": expected["text_sha256"],
            "prompt_receipt_ref": receipt_ref, "prompt_confirmed_epoch": confirmed_epoch,
            "inbound_watermark": inbound_watermark, "source_observation_sha256": observation_sha,
            "user_id": request.user_id}
        self.db.execute("INSERT INTO operator_reviews VALUES(?,?,?)",
                        (draft["order_id"], request.request_id, canonical(review)))

    def _approval(self, request, order_id, draft_version):
        observation_sha, bound = self._turn(request)
        stored = self.db.execute("SELECT review_json FROM operator_reviews WHERE order_id=?", (order_id,)).fetchone()
        if stored is None:
            raise PermissionError("CONFIRMED_REVIEW_NOT_FOUND")
        review = json.loads(stored[0])
        first_raw = self.first_inbound(self.scope, bound["chat_id"], review["inbound_watermark"])
        try:
            first_message = MessageUpdate.model_validate(first_raw)
        except ValueError:
            raise PermissionError("FIRST_OPERATOR_REPLY_UNUSABLE") from None
        first = self.db.execute("SELECT request_id FROM operator_turns WHERE update_id>? ORDER BY update_id LIMIT 1",
                                (review["inbound_watermark"],)).fetchone()
        draft = review["draft"]
        # Telegram dates have whole-second precision. Reject an affirmative
        # whose ordering relative to confirmed prompt dispatch is ambiguous.
        if (first is None or first[0] != request.request_id or first_message.update_id != bound["update_id"]
                or first_message.model_dump() != self.observations(observation_sha).update.model_dump()
                or review["user_id"] != request.user_id
                or bound["date"] < math.ceil(review["prompt_confirmed_epoch"])
                or request.text.strip().casefold() not in {"yes", "confirm"}
                or draft["version"] != draft_version or type(draft_version) is not int
                or draft["customer_id"] != bound["erp_customer_id"]):
            raise PermissionError("SEPARATE_FIRST_EXACT_AFFIRMATIVE_REQUIRED")
        confirmed = review["prompt_confirmed_epoch"]
        if self.clock().timestamp() < max(confirmed, request.sent_at.timestamp()):
            raise PermissionError("APPROVAL_TIME_ORDER_NOT_PROVED")
        if self.receipts(review["prompt_receipt_ref"]) != {
            "company_id": request.company_id, "user_id": request.user_id,
            "text_sha256": review["prompt_sha256"], "confirmed_epoch": confirmed,
        }:
            raise PermissionError("ORIGINAL_PROMPT_RECEIPT_CHANGED")
        expiry = min(float(draft["expires_at_epoch"]), request.deadline.timestamp(), self.run_expires)
        if not self.clock().timestamp() < expiry:
            raise PermissionError("DRAFT_APPROVAL_EXPIRED")
        return VerifiedDraftApproval(order_id=order_id, draft_version=draft_version,
            prompt_sha256=review["prompt_sha256"], prompt_receipt_ref=review["prompt_receipt_ref"],
            prompt_confirmed_epoch=float(confirmed), reply_observation_sha256=observation_sha,
            expires_at_epoch=float(expiry))

    async def approval_for(self, request, *, order_id, draft_version):
        approval = self._approval(request, order_id, draft_version)
        return ApprovalEvidence(request.company_id, request.channel, request.user_id,
            request.request_id, order_id, draft_version, approval.prompt_receipt_ref,
            datetime.fromtimestamp(approval.expires_at_epoch, timezone.utc))

    async def bind(self, request, *, tool, approval):
        if self.read_only:
            raise PermissionError("READ_ONLY_CLAIM_RESOLVER")
        self._turn(request)
        if tool not in CORE_TOOLS:
            raise PermissionError("UNKNOWN_CLAIM_ACTION")
        verified = None
        if tool == "confirm_order":
            if not isinstance(approval, ApprovalEvidence):
                raise PermissionError("EXACT_DRAFT_APPROVAL_REQUIRED")
            verified = self._approval(request, approval.order_id, approval.draft_version)
            if ((approval.company_id, approval.channel, approval.user_id, approval.request_id)
                    != (request.company_id, request.channel, request.user_id, request.request_id)
                    or approval.prompt_reference != verified.prompt_receipt_ref
                    or approval.expires_at.timestamp() != verified.expires_at_epoch):
                raise PermissionError("EXACT_APPROVAL_EVIDENCE_REQUIRED")
        elif approval is not None:
            raise PermissionError("UNEXPECTED_APPROVAL")
        selector = "clm_" + uuid.uuid4().hex
        self.db.execute("INSERT INTO operator_calls VALUES(?,?,?,?,NULL,NULL)",
            (selector, request.request_id, tool, verified.model_dump_json() if verified else None))
        return BoundRequest(request.company_id, request.channel, request.user_id, request.request_id, selector)

    def bind_arguments(self, selector, action, arguments):
        if self.read_only:
            raise PermissionError("READ_ONLY_CLAIM_RESOLVER")
        if not self._lock.acquire(timeout=1):
            raise PermissionError("CLAIM_BIND_BUSY")
        try:
            return self._bind_arguments(selector, action, arguments)
        finally:
            self._lock.release()

    def _bind_arguments(self, selector, action, arguments):
        # One shared SQLite connection must not interleave statement sequences.
        # The reentrant lock also covers the existing claim-resolution lookup.
        row = self.db.execute("SELECT request_id,action,approval_json,arguments_sha,claim_json "
                              "FROM operator_calls WHERE selector=?", (selector,)).fetchone()
        hashed = digest(arguments)
        if row is None or row[1] != action or row[3] not in (None, hashed):
            raise PermissionError("EXACT_CLAIM_ARGUMENTS_REQUIRED")
        if row[4] is not None:
            return self.resolve_verified_call(selector, action, hashed, now_epoch=self.clock().timestamp())
        request = self._load_request(row[0])
        observed, _ = self._turn(request)
        if action == "create_draft_order":
            self.db.execute("INSERT OR IGNORE INTO operator_run_draft VALUES(1,?)", (selector,))
            if self.db.execute("SELECT selector FROM operator_run_draft WHERE singleton=1").fetchone() != (selector,):
                raise PermissionError("ONE_ORIGINAL_DRAFT_PER_OPERATOR_RUN")
        approval = VerifiedDraftApproval.model_validate_json(row[2]) if row[2] else None
        claim = VerifiedCallClaim(run_id=self.run_id, selector=selector, company_id=request.company_id,
            channel="telegram", user_id=request.user_id, request_id=request.request_id, action=action,
            arguments_sha256=hashed, observation_sha256=observed, fixture_map_sha256=self.map_sha,
            grant_expires_at_epoch=float(min(request.deadline.timestamp(), self.run_expires)), approval=approval)
        self.db.execute("UPDATE operator_calls SET arguments_sha=?,claim_json=? WHERE selector=? AND arguments_sha IS NULL",
                        (hashed, claim.model_dump_json(), selector))
        return self.resolve_verified_call(selector, action, hashed, now_epoch=self.clock().timestamp())

    def _load_request(self, request_id):
        row = self.db.execute("SELECT request_json FROM operator_turns WHERE request_id=?", (request_id,)).fetchone()
        if row is None:
            raise PermissionError("CLAIM_TURN_NOT_FOUND")
        value = json.loads(row[0])
        return CoreRequest(value["company_id"], value["channel"], value["user_id"], value["request_id"],
            value["text"], datetime.fromisoformat(value["sent_at"]), datetime.fromisoformat(value["deadline"]))

    def resolve_verified_call(self, selector, action, arguments_sha256, *, now_epoch):
        if not self._lock.acquire(timeout=1):
            raise PermissionError("CLAIM_LOOKUP_BUSY")
        try:
            return self._resolve(selector, action, arguments_sha256, now_epoch=now_epoch)
        finally:
            self._lock.release()

    def _resolve(self, selector, action, arguments_sha256, *, now_epoch):
        finite_epoch(now_epoch)
        row = self.db.execute("SELECT request_id,claim_json FROM operator_calls WHERE selector=?",
                              (selector,)).fetchone()
        if row is None or row[1] is None:
            raise PermissionError("BOUND_CALL_NOT_FOUND")
        claim = VerifiedCallClaim.model_validate_json(row[1])
        if (claim.selector != selector or claim.action != action
                or claim.arguments_sha256 != arguments_sha256 or claim.run_id != self.run_id
                or claim.fixture_map_sha256 != self.map_sha or claim.company_id != self.scope.company_id
                or not now_epoch < claim.grant_expires_at_epoch):
            raise PermissionError("CALL_SCOPE_OR_LIFETIME_MISMATCH")
        request = self._load_request(row[0])
        original_sha, _ = self._turn(request)
        if original_sha != claim.observation_sha256:
            raise PermissionError("CALL_ORIGINAL_CHANGED")
        if action == "confirm_order":
            current = self._approval(request, claim.approval.order_id, claim.approval.draft_version)
            if current != claim.approval:
                raise PermissionError("CALL_APPROVAL_CHANGED")
        return claim


class AuthorizedERPPort:
    """Freeze actual wire arguments before the native session opens."""
    def __init__(self, port, claims):
        self.port, self.claims = port, claims
        self.validate_schema = port.validate_schema

    async def call(self, tool, arguments, *, context_header):
        self.validate_schema(tool, "input", arguments)
        self.claims.bind_arguments(context_header, tool, arguments)
        payload = await self.port.call(tool, arguments, context_header=context_header)
        self.claims.observe_draft_result(context_header, tool, payload)
        return payload
