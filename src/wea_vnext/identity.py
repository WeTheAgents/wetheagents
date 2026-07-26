"""Verified identity facade for the default immutable executor."""

from __future__ import annotations

from typing import Any

from .engine import installed_executor, load_executor

_MODULE = load_executor(installed_executor().reference).import_module("identity")
Binding = _MODULE.Binding
IdentityError = _MODULE.IdentityError


def resolve_binding(*args: Any, **kwargs: Any) -> Any:
    return _MODULE.resolve_binding(*args, **kwargs)


__all__ = ["Binding", "IdentityError", "resolve_binding"]
