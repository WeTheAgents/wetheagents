"""Feature flags for BitGN agent — all improvements are independently toggleable."""

from __future__ import annotations

from dataclasses import dataclass, field


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

    # --- Prompt cache optimization ---
    cache_aware_prompt: bool = False

    # --- Red team version ---
    redteam_version: str = "v1"  # "v1" (single-phase) | "v2" (three-phase)


# Singleton default — used when no config is explicitly passed
DEFAULT_CONFIG = AgentConfig()
