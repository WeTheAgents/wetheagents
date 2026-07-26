"""Canonical registry of the BDD scenarios accepted in Spec 0.6."""

SCENARIO_IDS = (
    "S-01",
    "S-01B",
    "S-01C",
    "S-02A",
    "S-02B",
    "S-02C",
    "S-02D",
    "S-02E",
    "S-02F",
    "S-02G",
    "S-02H",
    "S-02I",
    "S-02J",
    "S-03A",
    "S-03B",
    "S-03C",
    "S-03D",
    "S-03E",
    "S-03F",
    "S-04A",
    "S-04B",
    "S-04C",
    "S-04D",
    "S-05A",
    "S-05B",
    "S-05C",
    "S-05D",
    "S-05E",
    "S-05F",
    "S-05G",
    "S-05H",
    "S-06",
    "S-06B",
    "S-06C",
    "S-06D",
    "S-07A",
    "S-07B",
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
    "S-10",
    "S-11A",
    "S-11B",
    "S-13",
    "S-13B",
    "S-13C",
)


def validate_registry() -> None:
    """Fail fast if an ID was omitted or registered more than once."""
    if len(SCENARIO_IDS) != 55:
        raise ValueError(f"expected 55 scenario IDs, found {len(SCENARIO_IDS)}")
    duplicates = sorted({item for item in SCENARIO_IDS if SCENARIO_IDS.count(item) > 1})
    if duplicates:
        raise ValueError(f"duplicate scenario IDs: {', '.join(duplicates)}")


validate_registry()
