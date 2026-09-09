"""Open declaration grammar shared by future CLI and Tide adapters."""

from __future__ import annotations

from dataclasses import dataclass

DECLARATION_HEADER = "### Декларация WEA"
_SYSTEM_FIELDS = {"revision", "stage", "work_id"}


class DeclarationError(ValueError):
    """Raised when a comment is not an open, unambiguous declaration."""


@dataclass(frozen=True)
class Declaration:
    fields: tuple[tuple[str, str], ...]

    def get(self, name: str) -> str | None:
        return dict(self.fields).get(name)


def parse_declaration(comment: str) -> Declaration | None:
    lines = comment.splitlines()
    if not lines or lines[0] != DECLARATION_HEADER:
        return None
    fields: dict[str, str] = {}
    for line in lines[1:]:
        if not line.strip():
            continue
        if not line.startswith("- ") or ":" not in line:
            raise DeclarationError("declaration fields must use '- name: value'")
        name, value = line[2:].split(":", 1)
        name = name.strip()
        value = value.strip()
        if not name or not value or name in fields:
            raise DeclarationError("declaration fields must be unique and non-empty")
        if name in _SYSTEM_FIELDS:
            raise DeclarationError(f"{name} is computed by the protocol")
        fields[name] = value
    if not fields:
        raise DeclarationError("declaration contains no fields")
    return Declaration(tuple(sorted(fields.items())))
