# Hardening Gauntlet — Evaluation Rubric

Evaluator: **Gemini 3.1** (IDE-based, manual invocation after each round)

## Protocol

1. Evaluator receives both submissions **anonymized** as Agent-A and Agent-B
2. Evaluator does NOT know which model produced which submission
3. Evaluator scores each submission independently on 5 dimensions
4. Evaluator writes a brief reasoning section for each dimension
5. Evaluator declares a winner (or tie)

## Dimensions

| # | Dimension | Weight | Score range | What to evaluate |
|---|-----------|--------|-------------|-----------------|
| 1 | **Correctness** | 30% | 1-10 | Does it work? Does it compile/pass tests? Are there bugs? |
| 2 | **Depth** | 25% | 1-10 | Surface-level or root-cause? Does it show real understanding? |
| 3 | **Robustness** | 20% | 1-10 | Edge cases handled? Defensive coding? Failure modes considered? |
| 4 | **Clarity** | 15% | 1-10 | Code/proposal well-structured? Easy to follow? Good naming? |
| 5 | **Impact** | 10% | 1-10 | How much does this actually improve the system? |

## Scoring

**Weighted score** = (Correctness * 0.30) + (Depth * 0.25) + (Robustness * 0.20) + (Clarity * 0.15) + (Impact * 0.10)

**Winner**: Higher weighted score wins the slot.
**Tie-break**: If scores are within 0.5 of each other, the agent who went **second** wins (disadvantage compensation — going second means less novelty to explore).

## Output Format

For each round, produce:
1. **JSON scorecard** — machine-parseable, goes into `benchmarks/scores/`
2. **Markdown evaluation** — human-readable reasoning, goes into `benchmarks/evaluations/`

### JSON scorecard template

```json
{
  "trajectory": "T1",
  "slot": 1,
  "evaluator": "gemini-3.1",
  "timestamp": "2026-03-09T12:00:00Z",
  "agent_a": {
    "correctness": 0,
    "depth": 0,
    "robustness": 0,
    "clarity": 0,
    "impact": 0,
    "weighted_score": 0.0
  },
  "agent_b": {
    "correctness": 0,
    "depth": 0,
    "robustness": 0,
    "clarity": 0,
    "impact": 0,
    "weighted_score": 0.0
  },
  "winner": "agent_a | agent_b | tie",
  "reasoning": ""
}
```

### Markdown evaluation template

```markdown
## [T1-S1] Logic Leak Hunter — Slot 1

### Agent A
- **Correctness** (8/10): ...
- **Depth** (7/10): ...
- **Robustness** (6/10): ...
- **Clarity** (9/10): ...
- **Impact** (7/10): ...
- **Weighted**: 7.35

### Agent B
- **Correctness** (7/10): ...
- **Depth** (8/10): ...
- **Robustness** (7/10): ...
- **Clarity** (8/10): ...
- **Impact** (6/10): ...
- **Weighted**: 7.25

### Winner: Agent A (+0.10)
Reasoning: ...
```

## Anti-Gaming Rules

1. **No self-evaluation**: Agents never see each other's submissions before submitting
2. **Blind evaluation**: Gemini doesn't know Agent-A = Claude or Codex
3. **Immutable submissions**: Once submitted (PR or comment), no edits
4. **Turn fairness**: Strict alternation, tracked in `turn_order.json`
