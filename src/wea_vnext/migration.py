"""Verified pure migration facade for WEA vNext."""

from __future__ import annotations

from typing import Any

from .identity import _MODULES

_MODULE = _MODULES["identity_migration"]

IdentityMigrationPlan = _MODULE.IdentityMigrationPlan
V1IdentityEvidence = _MODULE.V1IdentityEvidence


def restore_v1_identity(*args: Any, **kwargs: Any) -> Any:
    return _MODULE.restore_v1_identity(*args, **kwargs)


__all__ = ["IdentityMigrationPlan", "V1IdentityEvidence", "restore_v1_identity"]
