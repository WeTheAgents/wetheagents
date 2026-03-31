"""Convert pitcher names to the LASTNAME-Hand format used in our xlsx schema.

Examples:
    "Paul Skenes" + "R" → "SKENES-R"
    "Jacob deGrom" + "R" → "DEGROM-R"

Disambiguation: when two pitchers share the same last name + hand in a season,
prefix with first initial: "JMARTINEZ-R" vs "PMARTINEZ-R".
"""

from __future__ import annotations


def name_to_code(full_name: str, hand: str) -> str:
    """Convert a full name + throwing hand to our pitcher code format.

    Args:
        full_name: e.g. "Paul Skenes", "Jacob deGrom"
        hand: "R" or "L"

    Returns:
        e.g. "SKENES-R", "DEGROM-R"
    """
    if not full_name or not full_name.strip():
        return ""
    parts = full_name.strip().split()
    last = parts[-1] if parts else full_name
    return f"{last.upper()}-{hand.upper()}"


def disambiguate(full_name: str, hand: str) -> str:
    """Produce a disambiguated code with first initial prefix.

    "Pedro Martinez" + "R" → "PMARTINEZ-R"
    """
    if not full_name or not full_name.strip():
        return ""
    parts = full_name.strip().split()
    first_initial = parts[0][0].upper() if parts else ""
    last = parts[-1] if len(parts) > 1 else parts[0]
    return f"{first_initial}{last.upper()}-{hand.upper()}"


class PitcherCodeRegistry:
    """Track pitcher codes within a season to detect and resolve collisions."""

    def __init__(self) -> None:
        # code → list of full names that map to it
        self._code_to_names: dict[str, list[str]] = {}
        # full_name → final code (may be disambiguated)
        self._name_to_code: dict[str, str] = {}

    def get_code(self, full_name: str, hand: str) -> str:
        """Get or register a pitcher code, disambiguating on collision."""
        if not full_name:
            return ""

        # Already registered?
        if full_name in self._name_to_code:
            return self._name_to_code[full_name]

        code = name_to_code(full_name, hand)

        if code in self._code_to_names:
            existing_names = self._code_to_names[code]
            if full_name not in existing_names:
                # Collision: disambiguate both the existing and the new
                for prev_name in existing_names:
                    new_code = disambiguate(prev_name, hand)
                    self._name_to_code[prev_name] = new_code
                # Now disambiguate the new one
                code = disambiguate(full_name, hand)
                existing_names.append(full_name)
        else:
            self._code_to_names[code] = [full_name]

        self._name_to_code[full_name] = code
        return code
