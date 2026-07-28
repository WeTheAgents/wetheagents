"""Verified projection facade from the shared candidate executor closure."""

from __future__ import annotations

from .identity import _MODULES

_MODULE = _MODULES["projection"]
ProjectionIntent = _MODULE.ProjectionIntent


__all__ = ["ProjectionIntent"]
