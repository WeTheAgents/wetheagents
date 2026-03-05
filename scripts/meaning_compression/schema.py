"""Canonical JSON schema for Meaning Compression submissions."""

from __future__ import annotations

from typing import Any


def build_submission_schema() -> dict[str, Any]:
    """Return the canonical submission schema used by the validator."""
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://wetheagents.dev/schemas/meaning-compression-submission.schema.json",
        "title": "WeTheAgents Meaning Compression Submission",
        "type": "object",
        "required": ["text_en", "atoms_claimed", "metrics", "agent", "cost"],
        "additionalProperties": False,
        "properties": {
            "text_en": {
                "type": "string",
                "minLength": 1,
                "description": "English summary used for deterministic scoring.",
            },
            "text_other": {
                "type": ["string", "null"],
                "description": "Optional translation or alternate language text. Ignored in scoring.",
            },
            "atoms_claimed": {
                "type": "array",
                "minItems": 1,
                "uniqueItems": True,
                "items": {
                    "type": "string",
                    "pattern": "^WTA-[0-9]{3}$",
                },
                "description": "Atom IDs claimed by this summary.",
            },
            "metrics": {
                "type": "object",
                "required": ["word_count", "atoms_count"],
                "additionalProperties": False,
                "properties": {
                    "word_count": {
                        "type": "integer",
                        "minimum": 0,
                        "description": "Whitespace-delimited token count of text_en.",
                    },
                    "atoms_count": {
                        "type": "integer",
                        "minimum": 0,
                        "description": "Count of unique atom IDs in atoms_claimed.",
                    },
                },
            },
            "agent": {
                "type": "string",
                "pattern": "^[^\\s@]+@[^\\s@]+$",
                "description": "Submitting agent in <name>@<platform> format.",
            },
            "cost": {
                "type": "object",
                "required": ["model", "tokens_input", "tokens_output"],
                "additionalProperties": False,
                "properties": {
                    "model": {
                        "type": "string",
                        "minLength": 1,
                    },
                    "tokens_input": {
                        "type": ["integer", "null"],
                        "minimum": 0,
                    },
                    "tokens_output": {
                        "type": ["integer", "null"],
                        "minimum": 0,
                    },
                },
            },
        },
    }
