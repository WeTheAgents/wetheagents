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
    enrichment: bool = True
    step_budget_in_results: bool = True  # prepend step counter to tool results
    trust_chain_hints: bool = True  # hint when file is in AGENTS.MD trust chain

    # --- Injection defense mode ---
    defense_mode: str = "hard"  # "hard" | "soft_block" | "soft_hint"

    # --- Step validator (loop detection) ---
    step_validator: bool = False

    # --- Prompt cache optimization ---
    cache_aware_prompt: bool = False

    # --- Red team version ---
    redteam_version: str = "v1"  # "v1" (single-phase) | "v2" (three-phase)

    # --- Task Router ---
    router: bool = False
    router_model: str = os.getenv("ROUTER_MODEL", os.getenv("OPENAI_MODEL", "gpt-4o-mini"))
    complex_extra_steps: int = 5  # extra MAX_STEPS for complex tasks
    complex_model: str = os.getenv("COMPLEX_MODEL", "")  # upgrade model for complex tasks (empty = no upgrade)

    # --- Genome system ---
    use_genome: bool = False  # use gene-based prompt assembly instead of monolithic prompts
    genomes_dir: str = "genomes"  # directory containing genome YAML files
    taxonomy_model: str = os.getenv("TAXONOMY_MODEL", os.getenv("PLANNER_MODEL", "gpt-5.4-mini"))
    planner_model: str = os.getenv("PLANNER_MODEL", "gpt-5.4")
    action_model: str = os.getenv("ACTION_MODEL", "gpt-4.1")  # fast model for straightforward execution
    deliberation_model: str = os.getenv("DELIBERATION_MODEL", "gpt-5.4-mini")  # reasoning model for hidden constraints
    deliberation_complex_model: str = os.getenv("DELIBERATION_COMPLEX_MODEL", "gpt-5.4")  # strongest model for deliberation+complex
    executor_fixed_model: str = os.getenv("EXECUTOR_FIXED_MODEL", "gpt-4.1")
    disable_executor_tier_routing: bool = False
    max_escalations: int = 2  # max planner replans per task
    dual_executor: bool = False  # planner routes to lean (hybrid) or complete (genome) executor
    planner_loop: bool = False
    planner_replan_every: int = 7
    planner_replan_min_step: int = 4
    planner_checkpoint_limit: int = 2

    # --- Hybrid controller-executor ---
    hybrid: bool = False
    hybrid_controller_model: str = os.getenv("HYBRID_CONTROLLER_MODEL", "gpt-5.4-mini")
    hybrid_executor_model: str = os.getenv("HYBRID_EXECUTOR_MODEL", "gpt-4.1")
    hybrid_phase_length: int = int(os.getenv("HYBRID_PHASE_LENGTH", "2"))
    hybrid_max_steps: int = 35

    # --- Watchdog (real-time corrector + pre-final gate) ---
    watchdog: bool = False
    watchdog_model: str = _WATCHDOG_MODEL_DEFAULT       # mid-stream check model
    watchdog_gate_model: str = _WATCHDOG_GATE_MODEL_DEFAULT  # pre-final gate model
    watchdog_deterministic_first: bool = False
    watchdog_check_every: int = 5   # fire every N executed steps
    watchdog_min_step: int = 4      # first check after this many steps
    watchdog_gate_retries: int = 2  # first reject retries locally, second escalates to planner


# Singleton default — used when no config is explicitly passed
DEFAULT_CONFIG = AgentConfig()
