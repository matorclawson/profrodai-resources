"""Host-local ITAM admin capability: one object, never a token or customer claim.

Only the independently admitted operator launcher constructs the issuer. These
source types do not themselves admit a launcher, credential, company or run.
The capability never crosses a process boundary; same-UID hostile code is not a
security boundary promised by this operator-only class fixture.
"""
from __future__ import annotations

from datetime import datetime, timezone
import threading
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


CLASS_DAY_END_EPOCH = datetime(2026, 11, 16, 23, 59, 59, tzinfo=timezone.utc).timestamp()


class OperatorAdminCapability:
    """Opaque object whose authority is its issuer's retained identity only."""
    __slots__ = ()

    def __repr__(self):
        return "<OperatorAdminCapability opaque>"

    def __reduce_ex__(self, protocol):
        raise TypeError("HOST_LOCAL_CAPABILITY_CANNOT_BE_SERIALIZED")


class AdminCapabilityGrant(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    launcher_identity: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    company_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    action: Literal["fulfill_order"]
    run_id: str = Field(pattern=r"^[\x20-\x7e]{1,128}$")
    expires_at_epoch: float = Field(gt=0, le=CLASS_DAY_END_EPOCH, allow_inf_nan=False)


class AdminCapabilityIssuer:
    """One admitted run, one mint, repeatable checks, explicit revocation."""
    def __init__(self, *, launcher_identity, company_id, run_id, expires_at_epoch, clock):
        self._grant = AdminCapabilityGrant(launcher_identity=launcher_identity,
            company_id=company_id, action="fulfill_order", run_id=run_id,
            expires_at_epoch=expires_at_epoch)
        if not callable(clock):
            raise TypeError("EXPLICIT_CLOCK_REQUIRED")
        self._clock, self._capability, self._closed = clock, None, False
        self._lock = threading.Lock()

    def issue(self):
        with self._lock:
            if self._closed or self._capability is not None or not self._clock().timestamp() < self._grant.expires_at_epoch:
                raise PermissionError("ONE_LIVE_ADMIN_CAPABILITY_PER_RUN")
            self._capability = OperatorAdminCapability()
            return self._capability

    def verify_admin_capability(self, capability, *, launcher_identity, company_id,
                                action, run_id, now_epoch):
        with self._lock:
            if (self._closed or type(capability) is not OperatorAdminCapability
                    or capability is not self._capability or self._capability is None
                    or (launcher_identity, company_id, action, run_id) !=
                       (self._grant.launcher_identity, self._grant.company_id,
                        self._grant.action, self._grant.run_id)
                    or type(now_epoch) not in (int, float)
                    or not 0 < now_epoch < self._grant.expires_at_epoch
                    or not 0 < self._clock().timestamp() < self._grant.expires_at_epoch):
                raise PermissionError("ORIGINAL_LIVE_ADMIN_CAPABILITY_REQUIRED")
            return self._grant

    def close(self):
        with self._lock:
            self._closed = True
            self._capability = None
