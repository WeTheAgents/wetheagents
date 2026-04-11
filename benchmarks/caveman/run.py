#!/usr/bin/env python3
"""
Benchmark: caveman vs normal output tokens on WEA-typical prompts.

Usage:
    python benchmarks/caveman/run.py                    # full run (requires ANTHROPIC_API_KEY)
    python benchmarks/caveman/run.py --dry-run          # preview config
    python benchmarks/caveman/run.py --trials 5         # more trials for stability
    python benchmarks/caveman/run.py --model claude-sonnet-4-20250514
"""

import argparse
import json
import statistics
import time
from pathlib import Path

try:
    import anthropic
except ImportError:
    print("pip install anthropic")
    raise SystemExit(1)

BENCH_DIR = Path(__file__).parent
CAVEMAN_SKILL = """Respond terse like smart caveman. All technical substance stay. Only fluff die.

Mode: **full**.

Rules: Drop articles (a/an/the), filler (just/really/basically/actually/simply), pleasantries (sure/certainly/of course/happy to), hedging. Fragments OK. Short synonyms (big not extensive, fix not "implement a solution for"). Technical terms exact. Code blocks unchanged. Errors quoted exact.

Pattern: [thing] [action] [reason]. [next step].

Not: "Sure! I'd be happy to help you with that. The issue you're experiencing is likely caused by..."
Yes: "Bug in auth middleware. Token expiry check use `<` not `<=`. Fix:"
"""

NORMAL_SYSTEM = "You are a helpful assistant for the WeTheAgents project — a GitHub-native platform where AI agents collaborate using an internal currency (WEA). Be clear, accurate, and professional."


def load_prompts() -> list[dict]:
    with open(BENCH_DIR / "prompts.json") as f:
        return json.load(f)["prompts"]


def call_api(client: anthropic.Anthropic, model: str, system: str, prompt: str, max_tokens: int = 1024) -> dict:
    for attempt in range(3):
        try:
            resp = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": prompt}],
            )
            return {
                "input_tokens": resp.usage.input_tokens,
                "output_tokens": resp.usage.output_tokens,
                "text": resp.content[0].text,
            }
        except anthropic.RateLimitError:
            time.sleep(2 ** attempt)
    raise RuntimeError("Rate limited after 3 retries")


def run_benchmarks(client: anthropic.Anthropic, model: str, prompts: list[dict], trials: int) -> list[dict]:
    results = []
    total = len(prompts) * trials * 2
    done = 0

    for p in prompts:
        pid = p["id"]
        normal_tokens = []
        caveman_tokens = []

        for t in range(trials):
            # Normal
            r = call_api(client, model, NORMAL_SYSTEM, p["prompt"])
            normal_tokens.append(r["output_tokens"])
            done += 1
            print(f"  [{done}/{total}] {pid} normal trial {t+1}: {r['output_tokens']} tokens")

            # Caveman
            r = call_api(client, model, CAVEMAN_SKILL, p["prompt"])
            caveman_tokens.append(r["output_tokens"])
            done += 1
            print(f"  [{done}/{total}] {pid} caveman trial {t+1}: {r['output_tokens']} tokens")

        normal_med = statistics.median(normal_tokens)
        caveman_med = statistics.median(caveman_tokens)
        saving = (1 - caveman_med / normal_med) * 100 if normal_med > 0 else 0

        results.append({
            "id": pid,
            "category": p["category"],
            "normal_median": normal_med,
            "caveman_median": caveman_med,
            "saving_pct": round(saving, 1),
            "normal_all": normal_tokens,
            "caveman_all": caveman_tokens,
        })
        print(f"  → {pid}: {normal_med} → {caveman_med} ({saving:.1f}% saving)")

    return results


def print_summary(results: list[dict], model: str):
    print(f"\n{'='*70}")
    print(f"CAVEMAN BENCHMARK — model: {model}")
    print(f"{'='*70}")
    print(f"{'Prompt':<25} {'Category':<15} {'Normal':>8} {'Caveman':>8} {'Saving':>8}")
    print("-" * 70)

    savings = []
    for r in results:
        print(f"{r['id']:<25} {r['category']:<15} {r['normal_median']:>8.0f} {r['caveman_median']:>8.0f} {r['saving_pct']:>7.1f}%")
        savings.append(r["saving_pct"])

    print("-" * 70)
    avg = statistics.mean(savings)
    med = statistics.median(savings)
    print(f"{'AVERAGE':<25} {'':<15} {'':<8} {'':<8} {avg:>7.1f}%")
    print(f"{'MEDIAN':<25} {'':<15} {'':<8} {'':<8} {med:>7.1f}%")
    print(f"{'MIN':<25} {'':<15} {'':<8} {'':<8} {min(savings):>7.1f}%")
    print(f"{'MAX':<25} {'':<15} {'':<8} {'':<8} {max(savings):>7.1f}%")


def main():
    parser = argparse.ArgumentParser(description="Caveman token reduction benchmark")
    parser.add_argument("--model", default="claude-sonnet-4-20250514", help="Model to benchmark")
    parser.add_argument("--trials", type=int, default=3, help="Trials per prompt per mode")
    parser.add_argument("--dry-run", action="store_true", help="Preview config only")
    args = parser.parse_args()

    prompts = load_prompts()
    print(f"Model: {args.model}")
    print(f"Trials: {args.trials}")
    print(f"Prompts: {len(prompts)}")
    print(f"Total API calls: {len(prompts) * args.trials * 2}")

    if args.dry_run:
        print("\n[DRY RUN] Would benchmark these prompts:")
        for p in prompts:
            print(f"  - {p['id']} ({p['category']})")
        return

    client = anthropic.Anthropic()
    results = run_benchmarks(client, args.model, prompts, args.trials)
    print_summary(results, args.model)

    # Save results
    out = BENCH_DIR / "results.json"
    with open(out, "w") as f:
        json.dump({"model": args.model, "trials": args.trials, "results": results}, f, indent=2)
    print(f"\nResults saved: {out}")


if __name__ == "__main__":
    main()
