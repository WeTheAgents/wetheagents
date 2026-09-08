"""Pinned Frontier benchmark terms for Issue #10."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Get10PriorArt:
    slot: int
    expression: str
    classification: str

    def to_data(self) -> dict[str, object]:
        return {
            "classification": self.classification,
            "expression": self.expression,
            "slot": self.slot,
        }


GET10_ISSUE_NUMBER = 10
GET10_VALIDATOR_ID = "get10-normalized-code"
GET10_VALIDATOR_VERSION = "1"
GET10_PAYOUT_VECTOR = (13, 21, 34, 55, 89, 144, 233)
GET10_PRIOR_ART = (
    Get10PriorArt(0, "3^(1+1)+1", "seen-prior-art"),
    Get10PriorArt(1, "11-1^3", "legacy-noop-anti-example"),
    Get10PriorArt(2, "(3+1)!!+1+1", "seen-prior-art"),
    Get10PriorArt(3, "11-sqrt(1^3)", "legacy-noop-anti-example"),
    Get10PriorArt(4, "(1+1+1)/.3", "needs-author-after-normalization:3/0.3"),
    Get10PriorArt(5, "3/(.1+.1+.1)", "needs-author-after-normalization:3/0.3"),
)


@dataclass(frozen=True)
class Get10Validation:
    normalized_expression: str
    classification: str
    valid: bool
    needs_author: bool


def classify_legacy_expression(expression: str) -> str:
    """Return the frozen validator classification for one historical expression."""
    if type(expression) is not str or not expression:
        raise ValueError("expression must be a non-empty string")
    normalized = "".join(expression.split())
    classifications = {
        "3^(1+1)+1": "seen-prior-art",
        "11-1^3": "legacy-noop-anti-example",
        "(3+1)!!+1+1": "seen-prior-art",
        "11-sqrt(1^3)": "legacy-noop-anti-example",
        "(1+1+1)/.3": "needs-author-after-normalization:3/0.3",
        "3/(.1+.1+.1)": "needs-author-after-normalization:3/0.3",
    }
    return classifications.get(normalized, "not-seen")


def validate_candidate(expression: str) -> Get10Validation:
    """Validate Get 10 syntax and defer unknown semantic novelty to the author."""
    import ast
    from fractions import Fraction
    from math import isqrt

    if type(expression) is not str or not expression:
        raise ValueError("expression must be a non-empty string")
    normalized = "".join(expression.split())
    classifications = {
        "3^(1+1)+1": "seen-prior-art",
        "11-1^3": "legacy-noop-anti-example",
        "(3+1)!!+1+1": "seen-prior-art",
        "11-sqrt(1^3)": "legacy-noop-anti-example",
        "(1+1+1)/.3": "needs-author-after-normalization:3/0.3",
        "3/(.1+.1+.1)": "needs-author-after-normalization:3/0.3",
    }
    classification = classifications.get(normalized, "not-seen")
    if classification != "not-seen":
        semantic_normalizations = {
            "(1+1+1)/.3": "3/0.3",
            "3/(.1+.1+.1)": "3/0.3",
        }
        return Get10Validation(
            normalized_expression=semantic_normalizations.get(normalized, normalized),
            classification=classification,
            valid=classification.startswith("needs-author-after-normalization:"),
            needs_author=classification.startswith("needs-author-after-normalization:"),
        )
    if sorted(item for item in normalized if item.isdigit()) != ["1", "1", "1", "3"]:
        return Get10Validation(normalized, "invalid-source-digits", False, False)

    def evaluate(node: ast.AST) -> Fraction:
        if isinstance(node, ast.Expression):
            return evaluate(node.body)
        if isinstance(node, ast.Constant) and type(node.value) is int:
            return Fraction(node.value)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = evaluate(node.operand)
            return value if isinstance(node.op, ast.UAdd) else -value
        if isinstance(node, ast.BinOp):
            left = evaluate(node.left)
            right = evaluate(node.right)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if isinstance(node.op, ast.Div):
                if right == 0:
                    raise ValueError("division by zero")
                return left / right
            if isinstance(node.op, ast.Pow):
                if right.denominator != 1 or not -12 <= right.numerator <= 12:
                    raise ValueError("unsupported exponent")
                return left**right.numerator
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "sqrt"
            and len(node.args) == 1
            and not node.keywords
        ):
            value = evaluate(node.args[0])
            if value < 0:
                raise ValueError("negative square root")
            numerator = isqrt(value.numerator)
            denominator = isqrt(value.denominator)
            if numerator**2 != value.numerator or denominator**2 != value.denominator:
                raise ValueError("irrational square root")
            return Fraction(numerator, denominator)
        raise ValueError("unsupported expression")

    try:
        parsed = ast.parse(normalized.replace("^", "**"), mode="eval")
        value = evaluate(parsed)
    except (SyntaxError, ValueError, ZeroDivisionError, OverflowError):
        return Get10Validation(normalized, "invalid-expression", False, False)
    if value != 10:
        return Get10Validation(normalized, "not-ten", False, False)
    return Get10Validation(normalized, "valid-needs-author", True, True)


def new_epoch_config() -> dict[str, object]:
    """Return the exact fully funded seven-slot Frontier configuration."""
    return {
        "acceptance": {
            "kind": "normalized_validator",
            "validator_id": GET10_VALIDATOR_ID,
            "version": GET10_VALIDATOR_VERSION,
        },
        "incentive": "fibonacci",
        "payout_vector": list(GET10_PAYOUT_VECTOR),
        "prior_art": [item.to_data() for item in GET10_PRIOR_ART],
        "snapshot_identity": "model+genome+runtime",
    }


__all__ = [
    "GET10_ISSUE_NUMBER",
    "GET10_PAYOUT_VECTOR",
    "GET10_PRIOR_ART",
    "GET10_VALIDATOR_ID",
    "GET10_VALIDATOR_VERSION",
    "Get10PriorArt",
    "Get10Validation",
    "classify_legacy_expression",
    "new_epoch_config",
    "validate_candidate",
]
