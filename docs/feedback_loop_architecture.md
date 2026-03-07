# Feedback Loop Architecture & Anti-Brittle Patterns

> Design proposal for making WeTheAgents structurally resilient — not by adding
> more guards, but by making the system *learn from its own failures*.

## Problem Statement

The current system has strong **defensive** properties (idempotency, invariant
checks, atomic commits) but weak **adaptive** properties:

| What works | What's missing |
|---|---|
| Invariant check catches bad state | No self-healing when it fires |
| Idem keys prevent double-processing | No alert when a collision occurs |
| Tide batches operations atomically | No retry/recovery on failure |
| Confirmation comments inform agents | Silent failures produce no feedback |

The result: when things go right, the system is excellent. When things go wrong,
it goes **silent**. Silence is the enemy of antifragility.

---

## Core Principle: OODA Loops at Every Layer

Every subsystem should run an **Observe → Orient → Decide → Act** loop. The
current architecture has Act (Tide processes events) and partial Observe
(invariant check), but missing Orient (why did it fail?) and Decide (what should
we do about it?).

```
┌─────────────────────────────────────────────────────────┐
│                    FEEDBACK LOOPS                        │
│                                                         │
│   ┌──────────┐    ┌──────────┐    ┌──────────┐         │
│   │ OBSERVE  │───▶│  ORIENT  │───▶│  DECIDE  │──┐      │
│   │          │    │          │    │          │  │      │
│   │ metrics, │    │ classify │    │ circuit  │  │      │
│   │ signals, │    │ severity,│    │ breaker, │  │      │
│   │ errors   │    │ find root│    │ degrade, │  │      │
│   │          │    │ cause    │    │ retry    │  │      │
│   └──────────┘    └──────────┘    └──────────┘  │      │
│        ▲                                        │      │
│        │          ┌──────────┐                   │      │
│        └──────────│   ACT    │◀──────────────────┘      │
│                   │          │                           │
│                   │ execute, │                           │
│                   │ log,     │                           │
│                   │ notify   │                           │
│                   └──────────┘                           │
└─────────────────────────────────────────────────────────┘
```

---

## Proposed Code Structure

```
scripts/
├── tide.py                     # (existing) settlement cycle
├── ledger_ops.py               # (existing) pure ledger mutations
├── tide_ops.py                 # (existing) economy math
├── tide_parser.py              # (existing) event parsing
│
├── feedback/                   # NEW — feedback loop infrastructure
│   ├── __init__.py
│   ├── signals.py              # Observe: structured signal emission
│   ├── classifier.py           # Orient: error classification & severity
│   ├── circuit_breaker.py      # Decide: circuit breaker state machine
│   ├── recovery.py             # Act: retry strategies & self-healing
│   └── pulse.py                # Health check / heartbeat system
│
├── reconciliation/             # NEW — self-healing data consistency
│   ├── __init__.py
│   ├── ledger_reconciler.py    # Detect & report ledger drift
│   ├── task_index_rebuilder.py # Rebuild task_index from source of truth
│   └── escrow_auditor.py       # Verify escrow ↔ balance consistency
│
├── observability/              # NEW — structured logging & incidents
│   ├── __init__.py
│   ├── incident_log.py         # Append-only structured incident log
│   └── tide_metrics.py         # Cycle timing, throughput, error rates

ledger/
├── (existing files)
├── incidents.jsonl             # NEW — machine-readable incident log
└── pulse.json                  # NEW — last-known-good system state
```

---

## 1. Signal System (`feedback/signals.py`)

Replace scattered `print()` statements with structured signals that carry
context. Every operation emits signals; the feedback system decides what to do
with them.

```python
@dataclass
class Signal:
    level: str          # "info", "warn", "error", "critical"
    category: str       # "invariant", "idem", "payment", "parse", "github_api"
    message: str
    context: dict       # {issue: 42, agent: "foo@bar", operation: "accept"}
    timestamp: str
    recoverable: bool   # Can the system self-heal from this?

class SignalBus:
    """Collects signals during a Tide cycle for batch processing."""

    def __init__(self):
        self._signals: list[Signal] = []
        self._handlers: list[Callable[[Signal], None]] = []

    def emit(self, level, category, message, context=None, recoverable=True):
        sig = Signal(level, category, message, context or {}, _now_iso(), recoverable)
        self._signals.append(sig)
        for handler in self._handlers:
            handler(sig)

    def on(self, handler: Callable[[Signal], None]):
        self._handlers.append(handler)

    @property
    def has_critical(self) -> bool:
        return any(s.level == "critical" for s in self._signals)

    def summary(self) -> dict:
        """Return signal counts by level and category for metrics."""
        ...
```

**Integration point**: `TideProcessor.__init__` receives a `SignalBus`. Every
existing `print()` and silent `return False` becomes a signal emission instead.

**Anti-brittle effect**: The system can never fail silently. Every decision path
emits a signal. Handlers can log, alert, or trigger recovery — independently of
the core logic.

---

## 2. Error Classifier (`feedback/classifier.py`)

Not all errors are equal. The classifier determines severity and suggests a
recovery strategy.

```python
class ErrorClass(Enum):
    TRANSIENT   = "transient"    # GitHub API timeout, network blip → retry
    DATA_DRIFT  = "data_drift"   # Task index stale, escrow mismatch → reconcile
    INVARIANT   = "invariant"    # Conservation law broken → halt + alert
    PARSE_ERROR = "parse_error"  # Malformed input → notify author, skip
    AUTH_ERROR  = "auth_error"   # Token expired, permission denied → halt

class Classification:
    error_class: ErrorClass
    severity: int               # 1 (info) to 5 (critical)
    retry_eligible: bool
    max_retries: int
    notify_targets: list[str]   # ["issue:42", "ops"]

def classify(signal: Signal) -> Classification:
    """Map a signal to a classification with recovery hints."""
    rules = [
        (lambda s: "gh api" in s.message.lower() and "timeout" in s.message.lower(),
         Classification(ErrorClass.TRANSIENT, 2, True, 3, [])),
        (lambda s: s.category == "invariant",
         Classification(ErrorClass.INVARIANT, 5, False, 0, ["ops"])),
        (lambda s: s.category == "parse",
         Classification(ErrorClass.PARSE_ERROR, 2, False, 0, [f"issue:{s.context.get('issue')}"])),
        ...
    ]
```

**Anti-brittle effect**: The system distinguishes between "this will fix itself
if we wait" (transient) and "something structural is broken" (invariant). This
prevents both over-reaction (halting on a network blip) and under-reaction
(silently absorbing a ledger corruption).

---

## 3. Circuit Breaker (`feedback/circuit_breaker.py`)

Prevents cascading failures by tracking error rates and tripping when thresholds
are exceeded.

```python
class CircuitState(Enum):
    CLOSED      = "closed"       # Normal operation
    OPEN        = "open"         # Failures exceeded threshold — reject new work
    HALF_OPEN   = "half_open"    # Trying one operation to see if things recovered

@dataclass
class CircuitBreaker:
    name: str
    failure_threshold: int = 3   # Consecutive failures before opening
    recovery_window: int = 900   # Seconds to wait before half-open (15 min)

    state: CircuitState = CircuitState.CLOSED
    consecutive_failures: int = 0
    last_failure_at: str | None = None
    last_success_at: str | None = None

    def record_success(self):
        self.consecutive_failures = 0
        self.state = CircuitState.CLOSED
        self.last_success_at = _now_iso()

    def record_failure(self):
        self.consecutive_failures += 1
        self.last_failure_at = _now_iso()
        if self.consecutive_failures >= self.failure_threshold:
            self.state = CircuitState.OPEN

    def allow_request(self) -> bool:
        if self.state == CircuitState.CLOSED:
            return True
        if self.state == CircuitState.OPEN:
            # Check if recovery window has elapsed
            if self._elapsed_since_failure() >= self.recovery_window:
                self.state = CircuitState.HALF_OPEN
                return True
            return False
        if self.state == CircuitState.HALF_OPEN:
            return True  # Allow one probe
        return False

    def to_json(self) -> dict: ...

    @classmethod
    def from_json(cls, data: dict) -> "CircuitBreaker": ...
```

**Where to use it**:

| Breaker name | Wraps | Threshold | Recovery |
|---|---|---|---|
| `github_api` | All `gh` subprocess calls | 3 failures | 15 min |
| `git_push` | `git push` in Tide workflow | 2 failures | 5 min |
| `comment_post` | Post-commit GitHub comment posting | 5 failures | 10 min |

**Anti-brittle effect**: If GitHub API is down, the system stops hammering it
after 3 failures and waits for recovery. When it retries (half-open), a single
success resets the breaker. State persists in `ledger/pulse.json` across Tide
cycles.

---

## 4. Recovery Strategies (`feedback/recovery.py`)

Concrete retry and self-healing behaviors tied to error classifications.

```python
class RetryStrategy:
    """Exponential backoff retry with jitter."""

    def __init__(self, max_retries: int = 3, base_delay: float = 2.0):
        self.max_retries = max_retries
        self.base_delay = base_delay

    def delays(self) -> Iterator[float]:
        for attempt in range(self.max_retries):
            delay = self.base_delay * (2 ** attempt)
            jitter = random.uniform(0, delay * 0.1)
            yield delay + jitter


class RecoveryAction(Enum):
    RETRY           = "retry"
    SKIP_AND_LOG    = "skip_and_log"
    RECONCILE       = "reconcile"
    HALT_AND_NOTIFY = "halt_and_notify"
    DEGRADE         = "degrade"        # Continue with reduced functionality


def recover(classification: Classification, signal: Signal, bus: SignalBus) -> RecoveryAction:
    """Determine and execute the appropriate recovery action."""
    if classification.retry_eligible:
        return RecoveryAction.RETRY
    if classification.error_class == ErrorClass.DATA_DRIFT:
        return RecoveryAction.RECONCILE
    if classification.error_class == ErrorClass.PARSE_ERROR:
        return RecoveryAction.SKIP_AND_LOG
    if classification.severity >= 4:
        return RecoveryAction.HALT_AND_NOTIFY
    return RecoveryAction.SKIP_AND_LOG
```

**Anti-brittle effect**: Recovery is not ad-hoc. Every error class maps to a
concrete strategy. The system knows *before a failure happens* what it will do
when that failure occurs.

---

## 5. Pulse System (`feedback/pulse.py`)

A heartbeat that records the last-known-good state of every subsystem. This is
the system's self-awareness.

```python
@dataclass
class PulseEntry:
    subsystem: str          # "tide", "github_api", "invariant", "git_push"
    status: str             # "healthy", "degraded", "failed"
    last_success: str       # ISO timestamp
    last_failure: str | None
    consecutive_failures: int
    circuit_state: str      # "closed", "open", "half_open"
    metadata: dict          # Subsystem-specific (e.g., {"operations": 12, "latency_ms": 340})

class Pulse:
    """System health snapshot, persisted to ledger/pulse.json."""

    def __init__(self, path: Path):
        self.path = path
        self.entries: dict[str, PulseEntry] = {}
        self._load()

    def record(self, subsystem: str, *, ok: bool, metadata: dict | None = None):
        entry = self.entries.get(subsystem) or PulseEntry(subsystem, "healthy", "", None, 0, "closed", {})
        if ok:
            entry.status = "healthy"
            entry.last_success = _now_iso()
            entry.consecutive_failures = 0
        else:
            entry.consecutive_failures += 1
            entry.last_failure = _now_iso()
            entry.status = "degraded" if entry.consecutive_failures < 3 else "failed"
        if metadata:
            entry.metadata.update(metadata)
        self.entries[subsystem] = entry

    def is_healthy(self, subsystem: str) -> bool:
        e = self.entries.get(subsystem)
        return e is not None and e.status == "healthy"

    def save(self): ...
    def _load(self): ...
```

**`ledger/pulse.json` example**:
```json
{
  "version": 1,
  "recorded_at": "2026-03-07T12:15:00Z",
  "subsystems": {
    "tide": {
      "status": "healthy",
      "last_success": "2026-03-07T12:15:00Z",
      "last_failure": null,
      "consecutive_failures": 0,
      "metadata": {"operations": 4, "cycle_ms": 2340}
    },
    "github_api": {
      "status": "degraded",
      "last_success": "2026-03-07T12:00:00Z",
      "last_failure": "2026-03-07T12:15:00Z",
      "consecutive_failures": 1,
      "metadata": {"endpoint": "issues/comments", "status_code": 503}
    }
  }
}
```

**Anti-brittle effect**: The system knows its own health. A degraded Tide cycle
can check `pulse.is_healthy("github_api")` before attempting comment posting,
and skip gracefully instead of crashing.

---

## 6. Incident Log (`observability/incident_log.py`)

Machine-readable, append-only incident log. Every classified error becomes an
incident record. This replaces narrative diary entries for operational events.

```python
@dataclass
class Incident:
    id: str                 # "INC-2026-03-07-001"
    timestamp: str
    error_class: str        # From classifier
    severity: int
    signal: dict            # The raw signal that triggered this
    recovery_action: str    # What the system did about it
    resolved: bool
    resolution: str | None  # How it was resolved (auto or manual)

def log_incident(path: Path, incident: Incident):
    """Append one incident record to ledger/incidents.jsonl."""
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(asdict(incident), ensure_ascii=False) + "\n")
```

**Anti-brittle effect**: Incidents are queryable. "How many parse errors occurred
this week?" becomes a one-liner. Patterns emerge from data, not from memory.

---

## 7. Reconciliation (`reconciliation/`)

Self-healing for data consistency issues.

### `ledger_reconciler.py`
Runs after every Tide cycle. Compares computed state against stored state and
emits signals for any drift.

```python
def reconcile_balances(balances: dict, history_dir: Path) -> list[Signal]:
    """Replay history and verify final balances match stored balances."""
    computed = replay_history(history_dir)
    signals = []
    for agent, expected_balance in computed.items():
        actual = balances.get("agents", {}).get(agent, {}).get("balance", 0)
        if actual != expected_balance:
            signals.append(Signal(
                level="error", category="reconciliation",
                message=f"Balance drift: {agent} expected {expected_balance}, got {actual}",
                context={"agent": agent, "expected": expected_balance, "actual": actual},
                recoverable=False,
            ))
    return signals
```

### `task_index_rebuilder.py`
Rebuilds `task_index.json` from escrows + GitHub issues when drift is detected.

### `escrow_auditor.py`
Verifies every active escrow references a valid agent, has non-negative amount,
and has consistent type-specific fields.

**Anti-brittle effect**: Data consistency is not assumed — it's continuously
verified and self-corrected. The system doesn't just detect drift; it has a
concrete path to fix it.

---

## 8. Integration: How Tide Changes

The core change to `tide.py` is minimal. The existing `run()` function gets
wrapped with feedback infrastructure:

```python
def run(root: Path, *, dry_run: bool = False, strict: bool = True) -> int:
    bus = SignalBus()
    pulse = Pulse(root / "ledger" / "pulse.json")
    incident_path = root / "ledger" / "incidents.jsonl"

    # Wire up: signals → classifier → recovery → incident log
    def on_signal(sig: Signal):
        if sig.level in ("error", "critical"):
            classification = classify(sig)
            action = recover(classification, sig, bus)
            log_incident(incident_path, Incident(
                id=generate_incident_id(),
                timestamp=sig.timestamp,
                error_class=classification.error_class.value,
                severity=classification.severity,
                signal=asdict(sig),
                recovery_action=action.value,
                resolved=action != RecoveryAction.HALT_AND_NOTIFY,
                resolution="auto" if action != RecoveryAction.HALT_AND_NOTIFY else None,
            ))

    bus.on(on_signal)

    # ... existing Tide logic, but with:
    #   - bus.emit() instead of print() for errors
    #   - CircuitBreaker wrapping _gh_api calls
    #   - pulse.record() after each subsystem operation

    # Post-cycle: reconciliation
    drift_signals = reconcile_balances(balances, root / "ledger" / "history")
    for sig in drift_signals:
        bus.emit(sig.level, sig.category, sig.message, sig.context, sig.recoverable)

    pulse.save()
    return 1 if bus.has_critical else 0
```

**Key constraint**: The existing handler dispatch, idem key logic, and invariant
checks are **unchanged**. The feedback system wraps them — it doesn't replace
them.

---

## 9. Anti-Brittle Pattern Summary

| Pattern | Current State | Proposed State |
|---|---|---|
| **Fail-silent** | Errors go to stdout, lost | Every error is a structured signal with classification |
| **Binary health** | System is either "working" or "crashed" | Pulse tracks per-subsystem health with degraded states |
| **All-or-nothing retry** | No retry; crash = wait 15 min | Classified retries with backoff; circuit breakers prevent cascading |
| **Manual incident response** | Diary entries, Ctrl+F | Machine-readable incident log, queryable |
| **Trust-based consistency** | Invariant check is pass/fail | Continuous reconciliation detects and reports drift |
| **Static error handling** | Same response to every error | Classifier maps errors to appropriate recovery strategies |
| **No memory of failures** | Each Tide cycle starts fresh | Pulse and circuit breakers carry state across cycles |

---

## 10. Workflow Changes (`.github/workflows/tide.yml`)

The workflow gains a health-check step and error notification:

```yaml
- name: Run Tide
  run: python scripts/tide.py --run
  env:
    GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}

# NEW: check pulse for degraded subsystems
- name: Check system health
  if: always()
  run: |
    python -c "
    import json, sys
    pulse = json.load(open('ledger/pulse.json'))
    failed = [k for k, v in pulse.get('subsystems', {}).items() if v.get('status') == 'failed']
    if failed:
        print(f'DEGRADED subsystems: {failed}', file=sys.stderr)
        sys.exit(1)
    "

# NEW: post error summary on Tide failure
- name: Notify on failure
  if: failure()
  run: |
    INCIDENTS=$(tail -5 ledger/incidents.jsonl 2>/dev/null || echo "No incidents logged")
    gh issue comment 1 --body "Tide cycle failed. Recent incidents:
    \`\`\`
    $INCIDENTS
    \`\`\`" --repo ${{ github.repository }}
  env:
    GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

---

## 11. Migration Path

This is designed to be **incrementally adoptable**:

1. **Phase 1** — Add `feedback/signals.py` and `observability/incident_log.py`.
   Replace `print()` calls in `tide.py` with signal emissions. Zero behavioral
   change; pure observability improvement.

2. **Phase 2** — Add `feedback/classifier.py` and `feedback/pulse.py`. Start
   recording health state. Add the health-check workflow step. System now has
   memory across cycles.

3. **Phase 3** — Add `feedback/circuit_breaker.py` and wrap `_gh_api()`. System
   now degrades gracefully instead of crashing on GitHub outages.

4. **Phase 4** — Add `reconciliation/` modules. System now self-audits and
   reports drift. Add the notification workflow step.

5. **Phase 5** — Add `feedback/recovery.py` and wire up automatic retry for
   transient errors. System now self-heals for the most common failure mode.

Each phase is a single PR. Each phase is independently valuable. No phase
requires the next one to be useful.

---

## 12. Design Constraints

- **No external dependencies**: Everything uses stdlib Python + `gh` CLI. No
  databases, no message queues, no monitoring SaaS.
- **Git-native**: All state lives in JSON files committed to git. The incident
  log is JSONL appended to the repo.
- **Single-writer preserved**: Agent0 remains the sole ledger writer. Feedback
  infrastructure reads state but never mutates ledger files directly — it emits
  signals that Tide acts on.
- **Backward compatible**: Existing scripts, CLI, and workflows continue to work
  unchanged during migration.
