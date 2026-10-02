"""Explicit, inactive Hello World closure; no task executor selection."""

from . import sources


def _bind_verified_runtime(runtime, verifier_capability):
    if verifier_capability is None or verifier_capability is not globals().get(
        "_WEA_VERIFIER_CAPABILITY"
    ):
        raise ValueError("Hello World requires verified provenance")
    sources._bind_verified_runtime(runtime, verifier_capability)
