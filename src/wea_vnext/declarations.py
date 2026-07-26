"""Verified declaration facade for the default immutable executor."""

from __future__ import annotations

from typing import Any

from .engine import installed_executor, load_executor

_MODULE = load_executor(installed_executor().reference).import_module("declarations")
Declaration = _MODULE.Declaration
DeclarationError = _MODULE.DeclarationError


def parse_declaration(comment: str) -> Any:
    return _MODULE.parse_declaration(comment)


__all__ = ["Declaration", "DeclarationError", "parse_declaration"]
