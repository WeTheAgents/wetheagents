"""Exact scenario scopes for accepted and implemented Spec 1.0 behavior."""

COMPATIBLE_SCENARIO_IDS = (
    "S-56",
    "S-57",
    "S-58",
    "S-59",
    "S-60",
    "S-61",
    "S-62",
    "S-63",
    "S-64",
    "S-65",
    "S-66",
    "S-67",
    "S-68",
    "S-01",
    "S-01B",
    "S-02D",
    "S-02E",
    "S-02F",
    "S-02G",
    "S-03A",
    "S-03C",
    "S-03D",
    "S-03E",
    "S-03F",
    "S-05B",
    "S-06",
    "S-06B",
    "S-06D",
    "S-07C",
    "S-08A",
    "S-08B",
    "S-08C",
    "S-08D",
    "S-08",
    "S-08E",
    "S-08F",
    "S-08G",
    "S-09",
    "S-09B",
    "S-09C",
    "S-13B",
)

CHANGED_SCENARIO_IDS = (
    "S-01C",
    "S-02A",
    "S-02B",
    "S-02C",
    "S-02H",
    "S-02I",
    "S-02J",
    "S-03B",
    "S-04A",
    "S-04B",
    "S-04C",
    "S-04D",
    "S-05A",
    "S-05C",
    "S-05D",
    "S-05E",
    "S-05F",
    "S-05G",
    "S-05H",
    "S-06C",
    "S-07A",
    "S-07B",
    "S-10",
    "S-13",
    "S-69",
    "S-70",
)

CONTROL_PLANE_SCENARIO_IDS = (
    "S-11A",
    "S-11B",
)

CORRECTION_SCENARIO_IDS = ("S-13C",)

CURRENT_SCENARIO_IDS = (
    *COMPATIBLE_SCENARIO_IDS,
    *CHANGED_SCENARIO_IDS,
    *CONTROL_PLANE_SCENARIO_IDS,
    *CORRECTION_SCENARIO_IDS,
)
SCENARIO_IDS = CURRENT_SCENARIO_IDS
ACCEPTED_FUTURE_SCENARIO_IDS: tuple[str, ...] = ()

# These references may duplicate current IDs because the version prefix is part
# of their identity. They are not implementation claims for the current ruleset.
HISTORICAL_SCENARIO_REFS = tuple(f"0.8:{item}" for item in CHANGED_SCENARIO_IDS)


def validate_registry() -> None:
    """Fail if scenario scopes overlap, omit an accepted case, or add a future claim."""
    if len(COMPATIBLE_SCENARIO_IDS) != 41:
        raise ValueError(
            f"expected 41 compatible scenario IDs, found {len(COMPATIBLE_SCENARIO_IDS)}"
        )
    if len(CHANGED_SCENARIO_IDS) != 26:
        raise ValueError(
            f"expected 26 changed scenario IDs, found {len(CHANGED_SCENARIO_IDS)}"
        )
    if len(CONTROL_PLANE_SCENARIO_IDS) != 2:
        raise ValueError(
            "expected 2 control-plane scenario IDs, "
            f"found {len(CONTROL_PLANE_SCENARIO_IDS)}"
        )
    if len(CORRECTION_SCENARIO_IDS) != 1:
        raise ValueError(
            "expected 1 correction scenario ID, "
            f"found {len(CORRECTION_SCENARIO_IDS)}"
        )
    if len(CURRENT_SCENARIO_IDS) != 70:
        raise ValueError(
            f"expected 70 current scenario IDs, found {len(CURRENT_SCENARIO_IDS)}"
        )
    duplicates = sorted(
        {item for item in CURRENT_SCENARIO_IDS if CURRENT_SCENARIO_IDS.count(item) > 1}
    )
    if duplicates:
        raise ValueError(f"duplicate current scenario IDs: {', '.join(duplicates)}")
    if CONTROL_PLANE_SCENARIO_IDS != ("S-11A", "S-11B"):
        raise ValueError("control-plane scenarios do not match the approved scope")
    if CORRECTION_SCENARIO_IDS != ("S-13C",):
        raise ValueError("correction scenarios do not match the approved scope")
    if ACCEPTED_FUTURE_SCENARIO_IDS != ():
        raise ValueError("accepted-future scenarios do not match the approved scope")
    if set(CURRENT_SCENARIO_IDS) & set(ACCEPTED_FUTURE_SCENARIO_IDS):
        raise ValueError("current and accepted-future scenario scopes overlap")


validate_registry()
