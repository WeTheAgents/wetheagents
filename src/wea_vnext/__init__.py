"""WEA vNext protocol core.

This package is isolated from the live v1 Tide and ledger write paths.  The
public surface selects an immutable executor and replays canonical inputs.
"""

from .engine import RuntimeReference, installed_executor, load_executor
from .store import replay

__all__ = ["RuntimeReference", "installed_executor", "load_executor", "replay"]
