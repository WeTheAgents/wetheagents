"""Verified identity facade for the explicitly pinned candidate executor."""

from __future__ import annotations

from typing import Any

from .engine import installed_executor, load_executor

_FACADE_EXECUTOR_VERSION = "0.6.3"

_MODULES = load_executor(
    installed_executor(_FACADE_EXECUTOR_VERSION).reference
).import_modules(
    (
        "declarations",
        "identity",
        "identity_hello_world",
        "identity_migration",
        "intake",
        "projection",
    )
)
_MODULE = _MODULES["identity"]
Binding = _MODULE.Binding
ControlDisclosure = _MODULE.ControlDisclosure
ControlGroupBinding = _MODULE.ControlGroupBinding
DeclarationError = _MODULE.DeclarationError
GitHubAccount = _MODULE.GitHubAccount
IdentityAuthority = _MODULE.IdentityAuthority
IdentityError = _MODULE.IdentityError
IdentityRegistry = _MODULE.IdentityRegistry


def resolve_binding(*args: Any, **kwargs: Any) -> Any:
    return _MODULE.resolve_binding(*args, **kwargs)


def resolve_control_group_binding(*args: Any, **kwargs: Any) -> Any:
    return _MODULE.resolve_control_group_binding(*args, **kwargs)


def authorize_agent(*args: Any, **kwargs: Any) -> Any:
    return _MODULE.authorize_agent(*args, **kwargs)


def authorize_issue_author(*args: Any, **kwargs: Any) -> Any:
    return _MODULE.authorize_issue_author(*args, **kwargs)


def authorize_manual_declaration(*args: Any, **kwargs: Any) -> Any:
    return _MODULE.authorize_manual_declaration(*args, **kwargs)


def select_cli_authority(*args: Any, **kwargs: Any) -> Any:
    return _MODULE.select_cli_authority(*args, **kwargs)


def control_disclosure_requirement(*args: Any, **kwargs: Any) -> Any:
    return _MODULE.control_disclosure_requirement(*args, **kwargs)


__all__ = [
    "Binding",
    "ControlDisclosure",
    "ControlGroupBinding",
    "DeclarationError",
    "GitHubAccount",
    "IdentityAuthority",
    "IdentityError",
    "IdentityRegistry",
    "authorize_agent",
    "authorize_issue_author",
    "authorize_manual_declaration",
    "control_disclosure_requirement",
    "resolve_binding",
    "resolve_control_group_binding",
    "select_cli_authority",
]
