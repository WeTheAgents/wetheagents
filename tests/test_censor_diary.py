"""Tests for scripts/censor_diary.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from censor_diary import BLOCK, censor_text, check_file

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def censored(text: str) -> str:
    result, _ = censor_text(text, source_hint="test")
    return result

def found_terms(text: str) -> list[str]:
    _, terms = censor_text(text, source_hint="test")
    return terms


# ---------------------------------------------------------------------------
# Words that MUST be redacted
# ---------------------------------------------------------------------------

class TestHardBlocks:
    def test_genome(self):
        assert "genome" not in censored("the genome of Claude")
        assert BLOCK in censored("the genome of Claude")

    def test_genomes(self):
        assert "genomes" not in censored("multiple genomes exist")

    def test_genomic(self):
        assert "genomic" not in censored("genomic drift")

    def test_gene(self):
        assert BLOCK in censored("a single gene")
        assert "gene" not in censored("a single gene")

    def test_genes(self):
        assert "genes" not in censored("multiple genes")

    def test_genetic(self):
        assert "genetic" not in censored("genetic mutation")

    def test_genetics(self):
        assert "genetics" not in censored("the field of genetics")

    def test_mutation(self):
        assert "mutation" not in censored("a beneficial mutation")

    def test_mutations(self):
        assert "mutations" not in censored("many mutations")

    def test_mutate(self):
        assert "mutate" not in censored("agents mutate over time")

    def test_mutated(self):
        assert "mutated" not in censored("the mutated sequence")

    def test_dna(self):
        assert "DNA" not in censored("the DNA of our process")

    def test_chromosome(self):
        assert "chromosome" not in censored("a chromosome pair")

    def test_phenotype(self):
        assert "phenotype" not in censored("observable phenotype")

    def test_genotype(self):
        assert "genotype" not in censored("underlying genotype")

    def test_hereditary(self):
        assert "hereditary" not in censored("hereditary traits")

    def test_heredity(self):
        assert "heredity" not in censored("laws of heredity")

    def test_agents_local_filename(self):
        assert "AGENTS.local" not in censored("Read AGENTS.local first.")

    def test_agents_local_md_filename(self):
        assert "AGENTS.local" not in censored("Read AGENTS.local.md first.")

    def test_genome_meta(self):
        assert "genome_meta" not in censored("check genome_meta.json")

    def test_genome_snapshot(self):
        assert "genome_snapshot" not in censored("run genome_snapshot.py")

    def test_genome_log(self):
        assert "genome_log" not in censored("see genome_log for details")


# ---------------------------------------------------------------------------
# Words that must NOT be redacted (false positive prevention)
# ---------------------------------------------------------------------------

class TestFalsePositives:
    def test_generate(self):
        text = "generate a report"
        assert text == censored(text)

    def test_general(self):
        text = "in general terms"
        assert text == censored(text)

    def test_regenerate(self):
        text = "regenerate the token"
        assert text == censored(text)

    def test_commutation(self):
        text = "commutation of sentences"
        assert text == censored(text)

    def test_evolution(self):
        text = "the evolution of our platform"
        assert text == censored(text)

    def test_evolve(self):
        text = "systems evolve over time"
        assert text == censored(text)

    def test_adaptation(self):
        text = "rapid adaptation to change"
        assert text == censored(text)

    def test_fitness_alone(self):
        # "fitness" is not in hard block list
        text = "fitness for purpose"
        assert text == censored(text)

    def test_mutually(self):
        text = "mutually beneficial"
        assert text == censored(text)

    def test_dna_lowercase_partial(self):
        # Only whole-word \bDNA\b is matched; "cDNA" should not match (no word boundary)
        # Actually "cDNA" — the c is adjacent, \b is between c and D only if c is non-word char
        # In practice "cDNA" has \b before c if preceded by space, but \bDNA\b won't match inside cDNA
        text = "complementary cDNA strand"
        # cDNA contains DNA but as part of a longer token — should NOT match \bDNA\b
        assert "cDNA" in censored(text)


# ---------------------------------------------------------------------------
# Mask length properties
# ---------------------------------------------------------------------------

class TestMaskLength:
    def test_mask_never_shorter_than_word(self):
        words = ["gene", "genes", "genome", "DNA", "mutation", "genetic"]
        for word in words:
            result = censored(word)
            blocks = result.count(BLOCK)
            assert blocks >= len(word), f"Mask for '{word}' is shorter: {blocks} < {len(word)}"

    def test_mask_at_most_plus_two(self):
        words = ["gene", "genes", "genome", "DNA", "mutation"]
        for word in words:
            result = censored(word)
            blocks = result.count(BLOCK)
            assert blocks <= len(word) + 2, f"Mask for '{word}' is too long: {blocks}"

    def test_deterministic_same_file(self):
        text = "the genome is the genome"
        r1, _ = censor_text(text, source_hint="2026-03-09.md")
        r2, _ = censor_text(text, source_hint="2026-03-09.md")
        assert r1 == r2

    def test_different_files_may_differ(self):
        # Same word, different source hints → may produce different lengths
        # (not guaranteed, but overwhelmingly likely across different seeds)
        results = set()
        for i in range(10):
            r, _ = censor_text("genome", source_hint=f"file{i}.md")
            results.add(len(r))
        # At least 2 different lengths across 10 different files
        assert len(results) >= 2


# ---------------------------------------------------------------------------
# check_file integration
# ---------------------------------------------------------------------------

class TestCheckFile:
    def test_clean_file_returns_empty(self, tmp_path):
        f = tmp_path / "diary.md"
        f.write_text("The agents are learning and growing.\n")
        assert check_file(f) == []

    def test_dirty_file_returns_hits(self, tmp_path):
        f = tmp_path / "diary.md"
        f.write_text("The genome of Claude-1 changed.\n")
        hits = check_file(f)
        assert len(hits) == 1
        lineno, term = hits[0]
        assert lineno == 1
        assert "genome" in term.lower()

    def test_multiple_hits_on_same_line(self, tmp_path):
        f = tmp_path / "diary.md"
        f.write_text("genetic mutation in genome\n")
        hits = check_file(f)
        assert len(hits) == 3


# ---------------------------------------------------------------------------
# Sentence-level smoke test
# ---------------------------------------------------------------------------

def test_full_sentence():
    raw = "The genome of Claude-1 evolved through genetic mutation of its core genes."
    result = censored(raw)
    assert "genome" not in result
    assert "genetic" not in result
    assert "mutation" not in result
    assert "genes" not in result
    assert "evolved" in result  # NOT blocked
    assert BLOCK in result
