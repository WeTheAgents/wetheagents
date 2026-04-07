"""Tests for genome decomposition — verify gene split preserves all content."""

import os
import sys

# Ensure project root is on sys.path
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from src.genome import (
    GENOMES_DIR,
    Gene,
    Genome,
    _select_genes,
    assemble_prompt,
    load_genome,
    save_genome,
    validate_genome,
)
from src.prompts import (
    _ROUTE_OVERLAYS,
    _STATIC_INSTRUCTIONS,
    _WORK_METHOD_COLD,
    _WORK_METHOD_WARM,
    build_system_prompt,
)


def _normalize(text: str) -> str:
    """Normalize whitespace for comparison."""
    import re
    # Collapse multiple newlines to single, strip each line
    lines = [line.strip() for line in text.strip().splitlines()]
    return "\n".join(line for line in lines if line)


def test_executor_genome_loads():
    """Genome file loads without errors."""
    genome = load_genome("executor")
    assert genome.name == "executor"
    assert genome.version == 1
    assert len(genome.genes) > 0
    print(f"  OK: executor genome loaded, {len(genome.genes)} genes")


def test_planner_genome_loads():
    genome = load_genome("planner")
    assert genome.name == "planner"
    assert len(genome.genes) > 0
    print(f"  OK: planner genome loaded, {len(genome.genes)} genes")


def test_watchdog_genome_loads():
    genome = load_genome("watchdog")
    assert genome.name == "watchdog"
    assert len(genome.genes) > 0
    print(f"  OK: watchdog genome loaded, {len(genome.genes)} genes")


def test_executor_genome_validates():
    genome = load_genome("executor")
    warnings = validate_genome(genome)
    for w in warnings:
        print(f"  WARN: {w}")
    # Warnings are allowed but critical ones shouldn't exist
    critical = [w for w in warnings if "Missing required" in w or "empty content" in w]
    assert not critical, f"Critical validation failures: {critical}"
    print(f"  OK: executor genome validates ({len(warnings)} warnings)")


def test_content_preservation():
    """All content from _STATIC_INSTRUCTIONS appears in executor genome genes."""
    genome = load_genome("executor")

    # Normalize the monolith
    mono_norm = _normalize(_STATIC_INSTRUCTIONS)

    # Collect all gene content
    gene_texts = [gene.content for gene in genome.genes.values()]
    all_genes_norm = _normalize("\n\n".join(gene_texts))

    # Check that each paragraph from the monolith appears in genes
    mono_paragraphs = [p.strip() for p in mono_norm.split("\n\n") if p.strip()]
    missing = []
    for para in mono_paragraphs:
        # Check first 80 chars of each paragraph (enough to identify it)
        key = para[:80]
        if key not in all_genes_norm:
            missing.append(key[:60] + "...")

    if missing:
        print(f"  MISSING paragraphs ({len(missing)}):")
        for m in missing:
            print(f"    - {m}")
    assert not missing, f"{len(missing)} paragraphs from _STATIC_INSTRUCTIONS not found in genome"
    print(f"  OK: all {len(mono_paragraphs)} paragraphs preserved in genome")


def test_route_overlay_selection():
    """Correct route overlay is selected for each route."""
    genome = load_genome("executor")

    for route in ["vault_ops", "inbox_email", "inbox_chat", "query", "security_reject"]:
        genes = _select_genes(genome, route, warmup=False, is_complex=False)
        overlay_genes = [g for g in genes if g.slot == "route_overlay"]
        assert len(overlay_genes) == 1, f"Route {route}: expected 1 overlay, got {len(overlay_genes)}"
        assert overlay_genes[0].name == f"overlay_{route}", (
            f"Route {route}: expected overlay_{route}, got {overlay_genes[0].name}"
        )
        # Verify overlay has meaningful content (evolved genes may differ from original)
        assert len(overlay_genes[0].content.strip()) > 50, (
            f"Route {route}: overlay content too short"
        )
    print("  OK: all 5 route overlays correctly selected with content")


def test_work_method_selection():
    """Correct work method is selected based on warmup."""
    genome = load_genome("executor")

    # Cold (no warmup)
    genes_cold = _select_genes(genome, "vault_ops", warmup=False)
    wm_cold = [g for g in genes_cold if g.slot == "work_method"]
    assert len(wm_cold) == 1
    assert wm_cold[0].name == "work_method_cold"
    assert "WORK METHOD:" in wm_cold[0].content
    assert "tree" in wm_cold[0].content or "outline" in wm_cold[0].content

    # Warm (with warmup)
    genes_warm = _select_genes(genome, "vault_ops", warmup=True)
    wm_warm = [g for g in genes_warm if g.slot == "work_method"]
    assert len(wm_warm) == 1
    assert wm_warm[0].name == "work_method_warm"
    assert "WORK METHOD:" in wm_warm[0].content
    assert "already loaded" in wm_warm[0].content

    # Self-roast should be a separate gene, always present
    gene_names_cold = {g.name for g in genes_cold}
    assert "self_roast" in gene_names_cold, "self_roast gene missing"

    print("  OK: work method cold/warm selection correct + self_roast present")


def test_route_filtering():
    """Inbox-only genes excluded from query route."""
    genome = load_genome("executor")

    genes_query = _select_genes(genome, "query", warmup=False)
    gene_names = {g.name for g in genes_query}

    # inbox_processing should NOT be in query
    assert "inbox_processing" not in gene_names, "inbox_processing should not appear for query route"
    # overlay_query should be present
    assert "overlay_query" in gene_names, "overlay_query missing for query route"
    # contact_lookup should NOT be in query (routes: inbox_email, vault_ops)
    assert "contact_lookup" not in gene_names, "contact_lookup should not appear for query route"

    print("  OK: route filtering works (inbox genes excluded from query)")


def test_gene_isolation():
    """Mutating one gene only changes that section of the prompt."""
    genome = load_genome("executor")
    prompt_before = assemble_prompt(genome, route="query", warmup=False, task_text="test task")

    # Mutate answer_rules
    mutated = genome.clone()
    mutated.set_gene_content("answer_rules", "MUTATED ANSWER RULES: new content here.")
    prompt_after = assemble_prompt(mutated, route="query", warmup=False, task_text="test task")

    # The mutation should appear
    assert "MUTATED ANSWER RULES" in prompt_after
    assert "MUTATED ANSWER RULES" not in prompt_before

    # Other genes should be unchanged
    assert "TRUST MODEL:" in prompt_after
    assert "FIRST CHECK" in prompt_after

    print("  OK: gene isolation works (mutating one gene doesn't affect others)")


def test_gene_selection_override():
    """Planner can override gene selection."""
    genome = load_genome("executor")

    # Select only a subset of genes
    selection = ["identity", "trust_model", "answer_rules", "overlay_query", "work_method_cold"]
    genes = _select_genes(genome, "query", warmup=False, gene_selection=selection)
    gene_names = {g.name for g in genes}

    # Should include selected genes + mandatory (weight >= 1.0)
    for name in selection:
        assert name in gene_names, f"Selected gene '{name}' missing"

    # Non-selected optional genes should be excluded
    assert "capability_boundaries" not in gene_names, "Non-selected optional gene should be excluded"
    assert "vault_discovery" not in gene_names, "Non-selected optional gene should be excluded"

    print(f"  OK: gene selection override works ({len(gene_names)} genes selected)")


def test_save_load_roundtrip():
    """Genome can be saved and loaded without data loss."""
    import tempfile

    genome = load_genome("executor")
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "test_executor.yaml")
        save_genome(genome, path)
        loaded = load_genome("test_executor", genomes_dir=tmpdir)

    # The loaded genome should match the original (modulo name from filename)
    assert len(loaded.genes) == len(genome.genes)
    for name in genome.genes:
        assert name in loaded.genes, f"Gene '{name}' missing after roundtrip"
        assert loaded.genes[name].content == genome.genes[name].content

    print(f"  OK: save/load roundtrip preserves all {len(genome.genes)} genes")


def test_task_injection():
    """Task text is correctly injected at the end of the prompt."""
    genome = load_genome("executor")
    task = "Find all admin users in the vault"
    prompt = assemble_prompt(genome, route="query", warmup=False, task_text=task)

    assert "YOUR TASK (the ONLY task you must complete):" in prompt
    assert task in prompt
    # Task should be at the end
    task_pos = prompt.index("YOUR TASK")
    # No gene content should appear after task block
    after_task = prompt[task_pos:]
    assert "TRUST MODEL:" not in after_task

    print("  OK: task injection at end of prompt")


def main():
    tests = [
        test_executor_genome_loads,
        test_planner_genome_loads,
        test_watchdog_genome_loads,
        test_executor_genome_validates,
        test_content_preservation,
        test_route_overlay_selection,
        test_work_method_selection,
        test_route_filtering,
        test_gene_isolation,
        test_gene_selection_override,
        test_save_load_roundtrip,
        test_task_injection,
    ]

    print(f"\n{'='*60}")
    print("Genome Decomposition Tests")
    print(f"{'='*60}\n")

    passed = 0
    failed = 0
    for test in tests:
        name = test.__name__
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"  FAIL: {e}")
            failed += 1

    print(f"\n{'='*60}")
    print(f"Results: {passed} passed, {failed} failed")
    print(f"{'='*60}\n")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
