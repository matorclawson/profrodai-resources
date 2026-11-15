"""Durable evidence from an explicitly admitted Core hosted connection client.

The owner supplies the authenticated client and independently reviewed connection
scope. No JSON field or local file authenticates that client. This private
operator fixture is not a production customer identity boundary.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import threading
import uuid

from pydantic import BaseModel, ConfigDict

from class_fixture_binding import (BrokerScope, MessageUpdate, PersistedObservation,
                                   observation_digest)
from mcp_port import canonical


class HeldBrokerOutcome(RuntimeError):
    """The retained original needs owner inspection; never resend automatically."""


class ReadPage(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    updates: list[dict]
    next_after: dict | None
    complete: bool


def _json(value):
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json", exclude_none=True)
    return json.loads(canonical(value))


def _hash(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def hosted_request(value):
    # Lazy import: offline policy imports neither credentials nor a transport.
    from zeo_core.integrations.hosted.client import HostedOperationRequest
    return HostedOperationRequest.model_validate(value)


class BrokerEvidence:
    """Single writer, independent read connections for producer worker threads.

    Persist a request claim BEFORE invoking the admitted client, and persist its
    returned SDK representation BEFORE interpreting it. A crash or exception
    leaves the claim held. Even read polling is never retried under a new key.
    Original response bytes here mean the SDK's exact serialized representation,
    not unexposed HTTP bytes or a provider message identifier.
    """
    def __init__(self, path: Path, *, run_id: str, scope: BrokerScope,
                 admitted_client, clock, request_factory=hosted_request):
        if (not run_id or len(run_id) > 128 or not callable(clock)
                or not callable(getattr(admitted_client, "invoke", None))):
            raise ValueError("ADMITTED_CLIENT_AND_RUN_REQUIRED")
        self.path, self.scope, self.run_id = Path(path), BrokerScope.model_validate(scope), run_id
        self.client, self.clock, self.request_factory = admitted_client, clock, request_factory
        if not re.fullmatch(r"[1-9][0-9]{0,18}", scope.connection_revision):
            raise ValueError("FENCED_CONNECTION_REVISION_REQUIRED")
        parent = self.path.parent.stat(follow_symlinks=False)
        if (not stat.S_ISDIR(parent.st_mode) or parent.st_uid != os.getuid()
                or stat.S_IMODE(parent.st_mode) & 0o077):
            raise PermissionError("PRIVATE_EVIDENCE_DIRECTORY_REQUIRED")
        created = False
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            os.close(fd)
            created = True
        except FileExistsError:
            pass
        info = self.path.stat(follow_symlinks=False)
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o600):
            raise PermissionError("PRIVATE_EVIDENCE_FILE_REQUIRED")
        self._lock = threading.RLock()
        self.db = sqlite3.connect(self.path, isolation_level=None, timeout=1, check_same_thread=False)
        self.db.execute("PRAGMA synchronous=FULL")
        if created:
            self.db.executescript("""
                CREATE TABLE meta (identity TEXT NOT NULL);
                CREATE TABLE calls (key TEXT PRIMARY KEY, request TEXT NOT NULL,
                    response TEXT, response_sha TEXT, observed_epoch REAL);
                CREATE TABLE polls (id TEXT PRIMARY KEY, after_id INTEGER,
                    final_id INTEGER, complete INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE updates (id INTEGER PRIMARY KEY, poll TEXT NOT NULL,
                    call_key TEXT NOT NULL, raw TEXT NOT NULL);
                CREATE TABLE observations (sha TEXT PRIMARY KEY, update_id INTEGER NOT NULL,
                    call_key TEXT NOT NULL, payload TEXT NOT NULL);
            """)
            self.db.execute("INSERT INTO meta VALUES(?)", (self._identity(),))
        if self.db.execute("SELECT identity FROM meta").fetchall() != [(self._identity(),)]:
            self.db.close()
            raise PermissionError("EXACT_BROKER_RUN_SCOPE_REQUIRED")

    def _identity(self):
        return canonical({"run_id": self.run_id, "scope": self.scope.model_dump(mode="json")})

    def close(self):
        self.db.close()

    @contextmanager
    def _reader(self):
        db = sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True, timeout=1)
        try:
            db.execute("PRAGMA query_only=ON")
            if db.execute("SELECT identity FROM meta").fetchall() != [(self._identity(),)]:
                raise PermissionError("EVIDENCE_SCOPE_CHANGED")
            yield db
        finally:
            db.close()

    def _request(self, operation, arguments, key):
        return {"connection_id": self.scope.connection_id, "operation_id": operation,
                "arguments": arguments, "idempotency_key": key,
                "expect": {"external_identity": self.scope.bot_binding,
                           "connection_revision": self.scope.connection_revision}}

    def _confirmed(self, request, response):
        binding = response.get("receipt", {}).get("binding")
        if (response.get("status") != "confirmed" or not response.get("execution_id")
                or response.get("artifact") is not None or response.get("approval_url") is not None
                or response.get("normalized_error") is not None or type(binding) is not dict
                or binding.get("connection_id") != self.scope.connection_id
                or binding.get("external_identity") != self.scope.bot_binding
                or binding.get("connection_revision") != self.scope.connection_revision
                or not isinstance(binding.get("connector_revision"), str)
                or not binding["connector_revision"]
                or request.get("expect") != {"external_identity": self.scope.bot_binding,
                       "connection_revision": self.scope.connection_revision}):
            raise HeldBrokerOutcome("ORIGINAL_CONFIRMED_FENCED_RESPONSE_REQUIRED")
        return response.get("result")

    def _invoke(self, operation, arguments, key):
        request = self._request(operation, arguments, key)
        raw = canonical(request)
        previous = self.db.execute("SELECT request,response,response_sha,observed_epoch FROM calls WHERE key=?",
                                   (key,)).fetchone()
        if previous is not None:
            if previous[0] != raw or previous[1] is None:
                raise HeldBrokerOutcome("ORIGINAL_BROKER_CALL_HELD_OR_CHANGED")
            response = json.loads(previous[1])
            if _hash(response) != previous[2]:
                raise HeldBrokerOutcome("ORIGINAL_RESPONSE_CHANGED")
            self._confirmed(request, response)
            return response, previous[2], previous[3]
        # Validate the installed SDK request before claiming or dispatching.
        typed_request = self.request_factory(request)
        self.db.execute("INSERT INTO calls(key,request) VALUES(?,?)", (key, raw))
        try:
            response = _json(self.client.invoke(typed_request))
            serialized = canonical(response)
            observed = self.clock().timestamp()
            self.db.execute("UPDATE calls SET response=?,response_sha=?,observed_epoch=? WHERE key=?",
                            (serialized, _hash(response), observed, key))
        except Exception:
            raise HeldBrokerOutcome("ORIGINAL_BROKER_CALL_REQUIRES_AUDIT") from None
        self._confirmed(request, response)
        return response, _hash(response), observed

    def poll(self, *, after_update_id: int | None, max_pages: int = 3):
        with self._lock:
            return self._poll(after_update_id=after_update_id, max_pages=max_pages)

    def _poll(self, *, after_update_id: int | None, max_pages: int = 3):
        """Persist a complete bounded poll chain before exposing ANY observation.

        A partial/refused/window-truncated chain remains retained but is not a
        source of customer authority. No cursor reset or automatic second poll
        recovers an incomplete original.
        """
        if (after_update_id is not None and (type(after_update_id) is not int or after_update_id < 0)
                or type(max_pages) is not int or not 1 <= max_pages <= 3):
            raise ValueError("BOUNDED_CURSOR_REQUIRED")
        if self.db.execute("SELECT 1 FROM polls WHERE complete=0").fetchone():
            raise HeldBrokerOutcome("ORIGINAL_INCOMPLETE_POLL_REQUIRES_AUDIT")
        # Never skip an unretained prefix after this run has begun.
        latest = self.db.execute("SELECT MAX(final_id) FROM polls WHERE complete=1").fetchone()[0]
        if latest is not None and after_update_id != latest:
            raise PermissionError("EXACT_RETAINED_CURSOR_REQUIRED")
        poll_id = uuid.uuid4().hex
        self.db.execute("INSERT INTO polls(id,after_id) VALUES(?,?)", (poll_id, after_update_id))
        cursor, found = after_update_id, []
        for page_no in range(max_pages):
            args = {"limit": 50}
            if cursor is not None:
                args["after"] = {"update_id": cursor}
            key = f"{self.run_id}:poll:{poll_id}:{page_no}"
            response, response_sha, _ = self._invoke("telegram.updates.read", args, key)
            page = ReadPage.model_validate(response["result"])
            if len(page.updates) > 50:
                raise HeldBrokerOutcome("POLL_PAGE_EXCEEDS_LIMIT")
            for raw in page.updates:
                update_id = raw.get("update_id")
                if (type(update_id) is not int or not 0 <= update_id <= 2**53
                        or cursor is not None and update_id <= cursor
                        or found and update_id <= found[-1]):
                    raise HeldBrokerOutcome("ORIGINAL_UPDATE_ORDER_INVALID")
                self.db.execute("INSERT INTO updates VALUES(?,?,?,?)",
                                (update_id, poll_id, key, canonical(raw)))
                found.append(update_id)
                try:
                    update = MessageUpdate.model_validate(raw)
                except ValueError:
                    continue  # Raw input still blocks a later confirmation.
                observation = PersistedObservation(scope=self.scope, update=update,
                                                   response_sha256=response_sha)
                self.db.execute("INSERT INTO observations VALUES(?,?,?,?)",
                    (observation_digest(observation), update_id, key, observation.model_dump_json()))
            expected_next = ({"update_id": found[-1]} if page.updates else
                             ({"update_id": cursor} if cursor is not None else None))
            if page.next_after != expected_next:
                raise HeldBrokerOutcome("POLL_CURSOR_NOT_PROVED")
            if page.complete:
                final = found[-1] if found else after_update_id
                self.db.execute("UPDATE polls SET final_id=?,complete=1 WHERE id=?", (final, poll_id))
                return [item[0] for item in self.db.execute(
                    "SELECT o.sha FROM observations o JOIN updates u ON u.id=o.update_id WHERE u.poll=? ORDER BY u.id",
                    (poll_id,))]
            if not page.updates:
                raise HeldBrokerOutcome("INCOMPLETE_POLL_CANNOT_ADVANCE")
            cursor = found[-1]
        raise HeldBrokerOutcome("BOUNDED_POLL_INCOMPLETE")

    def _retained_response(self, db, key):
        row = db.execute("SELECT request,response,response_sha,observed_epoch FROM calls WHERE key=?", (key,)).fetchone()
        if row is None or row[1] is None:
            raise PermissionError("ORIGINAL_RESPONSE_MISSING")
        request, response = json.loads(row[0]), json.loads(row[1])
        if _hash(response) != row[2] or request != self._request(
                request.get("operation_id"), request.get("arguments"), key):
            raise PermissionError("ORIGINAL_RESPONSE_OR_REQUEST_CHANGED")
        self._confirmed(request, response)
        return request, response, row[2], row[3]

    def observation_reader(self, sha):
        with self._reader() as db:
            row = db.execute("SELECT o.payload,o.call_key,u.raw,p.complete FROM observations o "
                "JOIN updates u ON u.id=o.update_id JOIN polls p ON p.id=u.poll WHERE o.sha=?", (sha,)).fetchone()
            if row is None or row[3] != 1:
                raise PermissionError("COMPLETE_ORIGINAL_POLL_REQUIRED")
            request, response, response_sha, _ = self._retained_response(db, row[1])
            observation = PersistedObservation.model_validate_json(row[0])
            raw = json.loads(row[2])
            if (request["operation_id"] != "telegram.updates.read"
                    or raw not in response["result"]["updates"]
                    or observation.update.model_dump() != raw
                    or observation.response_sha256 != response_sha or observation.scope != self.scope
                    or observation_digest(observation) != sha):
                raise PermissionError("ORIGINAL_OBSERVATION_CHANGED")
            return observation

    def first_inbound_reader(self, scope, chat_id, after_update_id):
        if scope != self.scope:
            raise PermissionError("EXACT_BROKER_SCOPE_REQUIRED")
        with self._reader() as db:
            rows = db.execute("SELECT u.raw,u.call_key,p.complete FROM updates u JOIN polls p ON p.id=u.poll "
                              "WHERE u.id>? ORDER BY u.id", (after_update_id,)).fetchall()
            for raw_json, key, complete in rows:
                raw = json.loads(raw_json)
                if raw.get("chat_id") != chat_id:
                    continue
                if complete != 1:
                    raise PermissionError("INCOMPLETE_OPERATOR_INPUT_HELD")
                _, response, _, _ = self._retained_response(db, key)
                if raw not in response["result"]["updates"]:
                    raise PermissionError("ORIGINAL_OPERATOR_INPUT_CHANGED")
                return raw
        return None

    def inbound_watermark_reader(self, scope, chat_id):
        if scope != self.scope:
            raise PermissionError("EXACT_BROKER_SCOPE_REQUIRED")
        with self._reader() as db:
            if db.execute("SELECT 1 FROM polls WHERE complete=0").fetchone():
                raise PermissionError("INCOMPLETE_OPERATOR_INPUT_HELD")
            rows = db.execute("SELECT raw,call_key FROM updates ORDER BY id DESC").fetchall()
            for raw, key in rows:
                value = json.loads(raw)
                if value.get("chat_id") == chat_id:
                    _, response, _, _ = self._retained_response(db, key)
                    if value not in response["result"]["updates"]:
                        raise PermissionError("ORIGINAL_OPERATOR_INPUT_CHANGED")
                    return value["update_id"]
        raise PermissionError("ORIGINAL_OPERATOR_INPUT_REQUIRED")

    def send(self, *, request, claims, text, purpose):
        """Only a retained registered request determines the recipient.

        purpose is fixed host policy (reply/review), never model-selected. Same
        request+purpose replays the stored original; uncertainty never resends.
        """
        if purpose not in {"reply", "review"} or type(text) is not str or not 1 <= len(text) <= 4096:
            raise ValueError("BOUNDED_HOST_REPLY_REQUIRED")
        claims._turn(request)
        if request.company_id != self.scope.company_id or request.channel != "telegram":
            raise PermissionError("EXACT_OPERATOR_REQUEST_REQUIRED")
        key = self.run_id + ":send:" + _hash([request.request_id, purpose])
        with self._lock:
            response, _, _ = self._invoke("telegram.message.send",
                                         {"chat_id": int(request.user_id), "text": text}, key)
        # Telegram's effect API exposes recorded confirmation, not message_id.
        if response.get("result") != {"confirmation": "recorded"}:
            raise HeldBrokerOutcome("ORIGINAL_SEND_CONFIRMATION_REQUIRED")
        return key

    def prompt_receipt_reader(self, key):
        with self._reader() as db:
            request, response, _, observed = self._retained_response(db, key)
            args = request["arguments"]
            if (request["operation_id"] != "telegram.message.send"
                    or response.get("result") != {"confirmation": "recorded"}
                    or type(args.get("chat_id")) is not int or args["chat_id"] <= 0
                    or type(args.get("text")) is not str):
                raise PermissionError("ORIGINAL_CONFIRMED_PROMPT_REQUIRED")
            return {"company_id": self.scope.company_id, "user_id": str(args["chat_id"]),
                    "text_sha256": hashlib.sha256(args["text"].encode()).hexdigest(),
                    "confirmed_epoch": observed}


class BrokerEvidenceReader(BrokerEvidence):
    """No client, writes, polling or send in a producer's receiving process."""
    def __init__(self, path: Path, *, run_id: str, scope: BrokerScope):
        self.path, self.run_id, self.scope = Path(path), run_id, BrokerScope.model_validate(scope)
        for path in (self.path.parent, self.path):
            info = path.stat(follow_symlinks=False)
            if (info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077
                    or path == self.path and (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1)
                    or path == self.path.parent and not stat.S_ISDIR(info.st_mode)):
                raise PermissionError("PRIVATE_EXISTING_EVIDENCE_REQUIRED")
        with self._reader():
            pass

    def close(self):
        pass

    def _invoke(self, *args, **kwargs):
        raise PermissionError("READ_ONLY_BROKER_EVIDENCE")

    def poll(self, *args, **kwargs):
        raise PermissionError("READ_ONLY_BROKER_EVIDENCE")

    def send(self, *args, **kwargs):
        raise PermissionError("READ_ONLY_BROKER_EVIDENCE")
