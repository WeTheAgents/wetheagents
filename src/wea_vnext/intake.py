"""Verified Draft, Triage, and ordinary Contract facade."""

from __future__ import annotations

from typing import Any

from .identity import _MODULES

_MODULE = _MODULES["intake"]

AccountBalance = _MODULE.AccountBalance
AuthorConsent = _MODULE.AuthorConsent
ContractActivation = _MODULE.ContractActivation
ContractCandidate = _MODULE.ContractCandidate
ContractReadiness = _MODULE.ContractReadiness
DraftIssue = _MODULE.DraftIssue
DraftValidation = _MODULE.DraftValidation
Escrow = _MODULE.Escrow
IntakeError = _MODULE.IntakeError
IntakeState = _MODULE.IntakeState
LedgerTransition = _MODULE.LedgerTransition
MechanicTerms = _MODULE.MechanicTerms
OrdinaryContract = _MODULE.OrdinaryContract
RouteOverride = _MODULE.RouteOverride
Task = _MODULE.Task
TriageRecord = _MODULE.TriageRecord
TriageRole = _MODULE.TriageRole
TriageAssignment = _MODULE.TriageAssignment
TriageCompletion = _MODULE.TriageCompletion


def validate_draft(*args: Any, **kwargs: Any) -> Any:
    return _MODULE.validate_draft(*args, **kwargs)


def assign_triage(*args: Any, **kwargs: Any) -> Any:
    return _MODULE.assign_triage(*args, **kwargs)


def record_triage(*args: Any, **kwargs: Any) -> Any:
    return _MODULE.record_triage(*args, **kwargs)


def complete_triage(*args: Any, **kwargs: Any) -> Any:
    return _MODULE.complete_triage(*args, **kwargs)


def record_route_override(*args: Any, **kwargs: Any) -> Any:
    return _MODULE.record_route_override(*args, **kwargs)


def record_author_consent(*args: Any, **kwargs: Any) -> Any:
    return _MODULE.record_author_consent(*args, **kwargs)


def record_contract_readiness(*args: Any, **kwargs: Any) -> Any:
    return _MODULE.record_contract_readiness(*args, **kwargs)


def activate_contract(*args: Any, **kwargs: Any) -> Any:
    return _MODULE.activate_contract(*args, **kwargs)


def ordinary_contract_id(*args: Any, **kwargs: Any) -> Any:
    return _MODULE.ordinary_contract_id(*args, **kwargs)


def triage_role_id(*args: Any, **kwargs: Any) -> Any:
    return _MODULE.triage_role_id(*args, **kwargs)


def triage_escrow_id(*args: Any, **kwargs: Any) -> Any:
    return _MODULE.triage_escrow_id(*args, **kwargs)


__all__ = [
    "AccountBalance",
    "AuthorConsent",
    "ContractActivation",
    "ContractCandidate",
    "ContractReadiness",
    "DraftIssue",
    "DraftValidation",
    "Escrow",
    "IntakeError",
    "IntakeState",
    "LedgerTransition",
    "MechanicTerms",
    "OrdinaryContract",
    "RouteOverride",
    "Task",
    "TriageAssignment",
    "TriageCompletion",
    "TriageRecord",
    "TriageRole",
    "activate_contract",
    "assign_triage",
    "complete_triage",
    "ordinary_contract_id",
    "record_author_consent",
    "record_contract_readiness",
    "record_route_override",
    "record_triage",
    "triage_escrow_id",
    "triage_role_id",
    "validate_draft",
]
