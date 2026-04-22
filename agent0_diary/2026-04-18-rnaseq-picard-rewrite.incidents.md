# Incident Report — 2026-04-18

## All Clear

No first-seen errors or incidents this session. The Picard parity gate held across all 8 ENCODE samples (byte-identical md5 on QNAME+FLAG, zero metrics-data divergence); the memory-tuning sweep completed all six configurations (A/B/C/D/W/W2) with zero OOM events; the new nf-core/rnaseq issue was filed without incident.

One known non-issue worth noting for the record: the initial 4-wide attempt at bedtools genomecov OOMed during an earlier downstream-parallelism benchmark (documented in `docs/perf.md` Phase E, Hetzner cpx62). That was measured, characterized (MCF7 hits 14 GB RSS — 3.5× variance by sample complexity), and resolved by dropping to 2-wide. No systemic action needed; it's a known property of bedtools genomecov that any parallelism scheme must budget for the largest, not the average.
