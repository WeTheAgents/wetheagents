"""Feature flags for BitGN agent — all improvements are independently toggleable."""

from __future__ import annotations

import os
from dataclasses import dataclass

_WATCHDOG_MODEL_DEFAULT = os.getenv("WATCHDOG_MODEL", os.getenv("OPENAI_MODEL", "gpt-4o-mini"))
_WATCHDOG_GATE_MODEL_DEFAULT = os.getenv("WATCHDOG_GATE_MODEL", _WATCHDOG_MODEL_DEFAULT)


@dataclass
class AgentConfig:
    """Configuration controlling all optional agent features.

    Each feature defaults to OFF so the baseline behavior is unchanged.
    Toggle features via env vars, CLI flags, or evolution loop configs.
    """

    # --- Vault warm-up ---
    warmup: bool = False
    warmup_read_agents_md: bool = True  # also pre-read AGENTS.MD if found

    # --- History compression ---
    compress_history: bool = False
    compress_threshold: int = 12  # messages before compression kicks in
    compress_keep_last: int = 4  # keep last N messages intact

    # --- Output enrichment ---
    enrichment: bool = False
    step_budget_in_results: bool = True  # prepend step counter to tool results
    trust_chain_hints: bool = True  # hint when file is in AGENTS.MD trust chain

    # --- Injection defense mode ---
    defense_mode: str = "soft_hint"  # "hard" | "soft_block" | "soft_hint"

    # --- Step validator (loop detection) ---
    step_validator: bool = False

    # --- Prompt cache optimization ---
    cache_aware_prompt: bool = False

    # --- Red team version ---
    redteam_version: str = "v1"  # "v1" (single-phase) | "v2" (three-phase)

    # --- Watchdog (real-time corrector + pre-final gate) ---
    watchdog: bool = False
    watchdog_model: str = _WATCHDOG_MODEL_DEFAULT       # mid-stream check model
    watchdog_gate_model: str = _WATCHDOG_GATE_MODEL_DEFAULT  # pre-final gate model
    watchdog_check_every: int = 5   # fire every N executed steps
    watchdog_min_step: int = 4      # first check after this many steps
    watchdog_gate_retries: int = 3  # max times pre-final gate can reject


# Singleton default — used when no config is explicitly passed
DEFAULT_CONFIG = AgentConfig()
