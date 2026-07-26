"""Verified projection-schema facade for the default immutable executor."""

from __future__ import annotations

from .engine import installed_executor, load_executor

_MODULE = load_executor(installed_executor().reference).import_module("projection")
ProjectionIntent = _MODULE.ProjectionIntent


__all__ = ["ProjectionIntent"]
