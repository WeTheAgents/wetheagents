"""Participant admission closure; task execution remains in its own runtime."""


def _bind_verified_runtime(runtime, verifier_capability):
    if verifier_capability is not globals().get("_WEA_VERIFIER_CAPABILITY"):
        raise ValueError("participant runtime requires verified provenance")
