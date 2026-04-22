# Ten Python repositories at near-absolute-zero discipline

A survey of public Python repositories for a "temperature" benchmark — where 1 = Kelvin-level regulation — yields a ten-repository calibration corpus in which every pillar (process, documentation, testing) is enforced in code, not merely claimed. **The single coldest specimen is HypothesisWorks/hypothesis**, which achieves 100% branch coverage, runs a scheduled fuzzing workflow every six hours, and requires every PR to ship a typed `RELEASE.rst` fragment. The set spans testing, typing, security, web, packaging, and style-guide domains; four are large popular projects (≥15k stars) and six are boutique or tooling-grade codebases whose maintainers are known individually for exacting standards (Hynek Schlawack, Bernát Gábor, Tom Christie, Sobolev, Ofek Lev, DRMacIver). Each entry below is backed by direct evidence from `pyproject.toml`, `.pre-commit-config.yaml`, `.github/workflows/`, and contributor documentation verified on the repositories' current default branches in April 2026. Weaknesses are noted honestly, because a calibration corpus that hides flaws will mis-calibrate.

The corpus is ranked by temperature, from coldest to warmest. All ten sit at or below 4/10 on a subjective scale where 10 is an undocumented, untested solo hobby repo and 1 is the theoretical floor.

## The ten reference repositories

### 1. HypothesisWorks/hypothesis — temperature 1/10

**URL:** https://github.com/HypothesisWorks/hypothesis · **Stars:** ~8.6k · **Domain:** property-based testing library.

Hypothesis is the coldest repository in the corpus because it polices itself with the very technique it invented. The CI graph contains a **scheduled fuzzing workflow that has executed over 3,400 runs at roughly six-hour cadence**, a cron posture uncommon outside security-critical code. The test suite is partitioned into `tests/cover/` (enforced to **100% branch coverage** via `make check-coverage`), `tests/nocover/` for integration, `tests/conjecture/` for shrinker-internals, plus per-optional-dependency directories for numpy, pandas, django, ghostwriter and array_api — the matrix thus multiplies across Python versions, pytest versions (pytest6, pytest7), and optional backends. Python itself is invoked with `-bb -X dev`, promoting bytes warnings and dev-mode to errors. **Bandit is run in CI** (rare at library scale), skipping only B101, B102, B110, B303, B311.

Process rigor extends into the human loop: a 242-line `CONTRIBUTING.rst` plus a `guides/` directory containing written-down invariants such as `strategies-that-shrink.rst`. **Every PR must add a `hypothesis-python/RELEASE.rst` file** with a `RELEASE_TYPE: patch|minor|major` header, which drives automatic release on merge; authors must amend `AUTHORS.rst`; non-trivial contributions require a CLA. The shrinker's correctness is treated as a first-class test concern, making this a repository whose internal invariants are themselves tested as properties.

Honest weakness: the master branch is tox/Makefile-centric and opaque to newcomers; `black` runs alongside `ruff` with some overlap; mypy/pyright are not applied to its own source.

### 2. tox-dev/tox — temperature 2/10

**URL:** https://github.com/tox-dev/tox · **Stars:** ~3.9k · **Domain:** test automation / environment orchestration.

Bernát Gábor's flagship project demonstrates the most comprehensive **pre-commit stack** of the corpus. The 277-line `pyproject.toml` declares PEP 735 `[dependency-groups]` for `test`, `type`, `docs`, `fix`, `pkg-meta`, and `release`, pins **mypy exactly to 1.18.2**, and configures Sphinx 8.2+ with `sphinxcontrib-towncrier` for changelog fragments. `.pre-commit-config.yaml` runs end-of-file-fixer, trailing-whitespace, `check-github-workflows` (JSON Schema validation of Actions YAML), `codespell`, `pyproject-fmt`, `validate-pyproject`, ruff-check with **`--fix --unsafe-fixes --exit-non-zero-on-fix`** (preview mode), and ruff-format with `format.preview = true`.

CI (`check.yaml`) runs a matrix of Windows × Ubuntu × (dev, pkg_meta) tox environments plus a dedicated pre-commit job, and **includes a daily cron** to catch dependency drift. Publishing is gated on signed tags. The development guide (tox.wiki/development) **mandates type annotations on all new code**, a towncrier changelog entry per PR, explicit `line-length = 120`, and forbids feature branches. Sibling repos in the tox-dev org (`pyproject-api`, `tox-ini-fmt`) enforce `report.fail_under=100` and `strict = true` mypy, establishing a house style.

Honest weakness: tox's own coverage threshold is not directly enforced at 100% (its siblings are); SECURITY.md and CODEOWNERS are not directly evident; RST-only docs raise the barrier for casual contributors.

### 3. python-attrs/attrs — temperature 2/10

**URL:** https://github.com/python-attrs/attrs · **Stars:** ~5.5k · **Domain:** class-building / declarative data.

Hynek Schlawack's project is the corpus's reference for **supply-chain and release hygiene**. Every third-party Action is **pinned by full SHA with a version comment** (e.g. `actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd # v6.0.2`); `persist-credentials: false` is set on all checkouts; `permissions: {}` is explicit. A dedicated `zizmor.yml` workflow lints the other workflows for unsafe patterns, and `codeql-analysis.yml` runs SAST. Ruff is configured with **`lint.select = ["ALL"]`** minus a curated ignore list; `interrogate` enforces **100% docstring coverage**; `fail-under = 100` is enforced on coverage via a dedicated combine-and-report job that writes a markdown summary to `$GITHUB_STEP_SUMMARY`.

A uniquely disciplined pattern: the first CI job is `build-package`, which uses `hynek/build-and-inspect-python-package` to **derive the supported-Python matrix from trove classifiers in package metadata** — a single source of truth. Subsequent jobs delete `src/` and run tests against the installed wheel via `tox run --installpkg dist/*.whl`, so tests exercise the shipped artifact. Four type-checkers (mypy, pyright, ty, pyrefly) each get their own dependency group. A `required-checks-pass` job using `re-actors/alls-green` consolidates branch-protection. Changelog fragments via towncrier.

Honest weakness: mypy is deliberately *not* in full `strict` mode — only `disallow_untyped_defs` and `check_untyped_defs` — because attrs must accept very broad user code.

### 4. pyca/cryptography — temperature 2/10

**URL:** https://github.com/pyca/cryptography · **Stars:** ~7.5k · **Domain:** security-critical cryptography bindings.

The security-critical reference. CI runs against **multiple cryptographic backends pinned to upstream SHAs** — OpenSSL master, BoringSSL master, LibreSSL, AWS-LC — with a separate `boring-open-version-bump.yml` that daily advances those SHAs and re-runs the suite. The Python matrix covers 3.8–3.13 plus PyPy 3.10/3.11 across Ubuntu, macOS, Windows. `wheel-builder.yml` uses cibuildwheel across manylinux2014/2_28/2_34, musllinux_1_2, and the architectures x86_64, aarch64, armv7l, ppc64le, with **hash-pinned build requirements** (`--require-hashes`) and **container images pinned by digest**. Wycheproof and x509-limbo test vectors are pulled in for standards compliance; OSS-Fuzz harnesses live under `src/rust/`. Nox sessions separate `tests`, `rust` (clippy + rustfmt), `flake`, `docs`.

`docs/security.rst` defines a formal disclosure process: 48-hour acknowledgment SLA, broad scope including cryptography.io infrastructure, support for main plus latest release, private GitHub advisory reporting, and a new release mandated for every security issue. The project has handled CVE-2023-50782 (Bleichenbacher) and CVE-2026-26007 under this process.

Honest weaknesses: the README explicitly states cryptography has not had an external audit; because wheels statically link OpenSSL, multiple versions (37.0.0–43.0.0, 42.0.0–44.0.0) have shipped vulnerable OpenSSL and needed chained re-releases; the root `SECURITY.md` is absent (policy lives in `docs/`).

### 5. wemake-services/wemake-python-styleguide — temperature 2/10

**URL:** https://github.com/wemake-services/wemake-python-styleguide · **Stars:** ~2.6k · **Domain:** the strictest flake8-based style guide, distributed as the `WPS` plugin.

This repository is both its own dogfood and the corpus's reference for **test strictness configuration**. `pyproject.toml` enables `mypy strict = true` plus an unusually long list of extra error codes: `truthy-bool`, `truthy-iterable`, `redundant-expr`, `unused-awaitable`, `possibly-undefined`, `redundant-self`, `unimported-reveal`, `deprecated`, and `exhaustive-match`. Ruff selects ~40 rule families (A, B, C4, C90, COM, D, DTZ, E, ERA, EXE, F, FA, FBT, FLY, FURB, G, I, ICN, ISC, LOG, N, PERF, PIE, PL, PT, PTH, Q, RET, RSE, RUF, S, SIM, SLF, SLOT, T100, TRY, UP, W, YTT) with `preview = true`, `mccabe.max-complexity = 6` (stricter than Ruff's default 10), and Google-style docstrings enforced.

Pytest is configured with **`--strict-config`, `--strict-markers`, `--doctest-modules`, `--cov-fail-under=100`, `xfail_strict = true`, and `filterwarnings = ["error"]`** — every warning fails the build. Dev dependencies include hypothesis, hypothesmith, syrupy snapshot testing, nbqa, import-linter, codespell, and typos (crate-ci). The project ships as a first-class pre-commit hook since v1.0.0 and uses `pre-commit.ci` autoupdate.

Honest weakness: opinionated to the point of being unusable in many settings (the 100% coverage gate and warnings-as-errors mean contributors must clean up before every commit); Poetry-based tooling is heavier than modern uv/hatch alternatives.

### 6. dry-python/returns — temperature 2/10

**URL:** https://github.com/dry-python/returns · **Stars:** ~3.5k · **Domain:** functional-style typing primitives (Result, IO, Future, Maybe).

The corpus's reference for **custom type-system rigor**. The package ships its own `returns.contrib.mypy.returns_plugin` *and* its own pytest plugin; CI runs `mypy --enable-error-code=unused-awaitable returns` and `mypy tests` as separate steps. The `setup.cfg` mypy section declares `strict = true`, `ignore_missing_imports = true`, and loads the custom plugin. Typesafety tests live separately and are run with `pytest typesafety --num-shards=4 --shard-id=${{ matrix.shard }} --mypy-ini-file=setup.cfg` — **four-way sharding of type-level tests** under `pytest-mypy-plugins`.

Ruff selects the same ~40-family rule set as WPS with `mccabe.max-complexity = 6`, single-quote formatting, `line-length = 80`, and `lint.external = ["WPS"]` so codes from wemake pass through cleanly. Additional tools: `slotscheck` with `strict-imports=true`, `require-subclass=true`, `require-superclass=true`; `codespell` on source, docs, README and CHANGELOG; `pip check`; `covdefaults`. The matrix covers Python 3.11–3.14 with least-privilege permissions and concurrency-group cancellation.

Honest weakness: canonical mypy config lives in `setup.cfg` rather than `pyproject.toml`, which is marginally harder for newcomers; the project is opinionated FP-style that many Python teams won't adopt.

### 7. pydantic/pydantic — temperature 3/10

**URL:** https://github.com/pydantic/pydantic · **Stars:** ~27.5k · **Domain:** data validation (one of the most-downloaded Python packages).

Included as a **famous, large-project** reference to demonstrate the concept scales. CI rotates the Python version, **the mypy version, and the typing-extensions version** (including git-HEAD) across the matrix, so pydantic is simultaneously tested against multiple type-checkers and multiple typing backports. Third-party downstream regression tests run against FastAPI and other libraries to catch breaking changes; benchmarks run via `pytest-benchmark` and `pytest-codspeed`; docstring/markdown examples are executed via `pytest-examples` with print-output equality enforced — **the docs are literally tests**. Pyright is the primary static type-checker, run through `make lint` and through local pre-commit system hooks.

Linters include ruff, pyright, and pydocstyle with Google-style docstrings. The docs pipeline uses MkDocs-Material, `mike` for versioned docs, mkdocstrings for API reference, and algoliasearch upload. A separate `linting` dependency group decouples lint tooling from dev tooling.

Honest weaknesses: no public coverage-threshold gate; mypy is tested *against* pydantic rather than *on* pydantic; the minimalist pre-commit delegates to a Makefile, so the canonical rule set isn't visible from config alone; ~500 open issues reflect backlog typical of a popular project rather than a discipline gap.

### 8. encode/httpx — temperature 3/10

**URL:** https://github.com/encode/httpx · **Stars:** ~15.2k · **Domain:** modern HTTP client for Python.

The corpus's reference for **tight type-safety with a minimalist lint posture**. `pyproject.toml` declares `mypy strict = true` **globally**, with tests overriding only `disallow_untyped_defs = false`. Pytest runs with **`filterwarnings = ["error", ...]`** — warnings promoted to errors — plus strict markers (`copied_from`, `network`). The Python matrix is 3.9–3.13. `docs/contributing.md` contains a formal release checklist: keepachangelog format, compare `master` against the latest tag, rules for changelog-worthy versus non-worthy changes, plus shell scripts (`scripts/check`, `scripts/test`, `scripts/docs`) that unify local and CI behavior.

Ruff's selection is deliberately narrow — `["E", "F", "I", "B", "PIE"]` — trading lint breadth for a curated, stable rule set maintained by Tom Christie (Encode OSS Ltd).

Honest weaknesses: no `.pre-commit-config.yaml` is visible; no explicit coverage threshold; SECURITY.md and CODEOWNERS are not surfaced in the repo root. The discipline here is concentrated in typing and warning rigor, not breadth of linters.

### 9. pypa/hatch — temperature 3/10

**URL:** https://github.com/pypa/hatch · **Stars:** ~7.2k · **Domain:** modern Python project manager and build backend (PyPA project).

The corpus's reference for **self-dogfooded modern packaging**. Hatch is built with `hatchling` + `hatch-vcs`. A separate `ruff.toml` extends `ruff_defaults.toml` with `[format] preview = true` and `[lint] preview = true` — **aggressive preview-mode ruff** not found elsewhere in the corpus. Mypy uses targeted strictness: defaults relaxed, but per-module overrides for `hatchling.*` and `hatch.utils.*` enable `disallow_untyped_defs = true` and `warn_no_return = true`; global flags include `warn_unused_ignores = true` and `enable_error_code = ["ignore-without-code", "truthy-bool"]`. Coverage is configured with `branch = true`, explicit omit lists, and `exclude_lines` for `TYPE_CHECKING`.

The test workflow runs `hatch test --python ${{matrix.python-version}} --cover-quiet --randomize --parallel --retries 5 --retry-delay 3` across Linux/macOS/Windows — **test randomization, parallelism, and flake-resilient retries** are uncommon quality signals, and demonstrate that hatch's own test runner is exercised through its own CI.

Honest weaknesses: mypy is not globally strict (relies on per-module overrides); no `.pre-commit-config.yaml` is directly evident (hatch prefers `hatch fmt`); CODEOWNERS/SECURITY.md not surfaced; bus factor concentrated on Ofek Lev.

### 10. python/mypy — temperature 4/10

**URL:** https://github.com/python/mypy · **Stars:** ~20.3k · **Domain:** gradual static type-checker.

Included as the corpus's **dogfooding exemplar** and to show the methodology applies to large, decade-old codebases. The flagship CI gate is `python runtests.py self` → `mypy --config-file mypy_self_check.ini -p mypy`, so **mypy type-checks itself** with `ignore-without-code`, `redundant-expr`, `PreciseTupleTypes`, and `show_error_code_links` enabled. The `mypy_primer.yml` workflow runs **mypy against a curated set of real third-party projects on every relevant PR**, catching downstream regressions before release. Mypyc-compiled builds are tested separately for the oldest and newest supported Python, so the compiled-self-bootstrap is exercised.

`.pre-commit-config.yaml` runs: pre-commit-hooks (trailing-whitespace, EOF-fixer), black, astral-sh/ruff-pre-commit with `--exit-non-zero-on-fix`, check-jsonschema validating github-workflows / github-actions / readthedocs config files, codespell, rhysd/actionlint with go-shellcheck integration, **woodruffw/zizmor-pre-commit** (Actions security linter), a local `bad-pr-link` pygrep on CHANGELOG.md, plus the meta hooks `check-hooks-apply` and `check-useless-excludes`. Matrix covers Python 3.8–3.13 on Ubuntu/Windows/macOS.

Honest weaknesses: no root SECURITY.md (the GitHub Security tab shows 0 advisories), consistent with a dev tool but still a gap; no CODEOWNERS; no fuzzing or mutation testing; as a type-checker, it doesn't cross-validate with pyright. The 4/10 rating reflects a heavy process + tooling posture but a thinner runtime-safety posture than pyca/cryptography.

## What the corpus reveals about "low temperature"

Synthesizing across the ten repositories, six configuration patterns emerge as **reliable signals of deep discipline** rather than cosmetic rigor. First, **warnings promoted to errors** (`filterwarnings = ["error"]` in WPS and httpx; `-bb -X dev` in Hypothesis) indicates the project refuses to accumulate silent deprecation debt. Second, **coverage threshold at exactly 100%** (Hypothesis branch coverage, WPS, attrs, tox siblings) is binary and un-gameable. Third, **scheduled cron CI** (Hypothesis fuzz, tox daily, cryptography daily upstream-bump) proves the project tests without being provoked. Fourth, **SHA-pinned Actions plus a dedicated Actions-linter workflow** (attrs + mypy use `zizmor`; cryptography hash-pins build requirements) signals supply-chain awareness beyond what most repositories exhibit. Fifth, **dependency groups by task** (PEP 735 in attrs and tox; Poetry groups in returns and WPS) demonstrate that lint tooling, type tooling, and docs tooling have distinct named contracts. Sixth, **changelog discipline via towncrier or required release fragments** (Hypothesis, tox, attrs) forces every PR to state its release intent.

Equally instructive are the **anti-patterns that still appear even in cold repos**: pydantic hides its rule set behind a Makefile, httpx has no visible pre-commit, hatch's strict mypy is scoped only to sub-packages, and cryptography's `SECURITY.md` is missing from the root despite the project being security-critical. These imperfections are valuable for a calibration corpus — they show that a repository can score very cold on most axes while leaking heat on one or two, which is what a temperature metric must quantify.

## Conclusion

**The coldest Python repositories are not uniformly cold; they are cold in characteristic combinations.** Hypothesis concentrates its discipline in testing (scheduled fuzz, 100% branch coverage, written-down PR ritual). Attrs concentrates it in release and supply-chain hygiene (SHA-pinned actions, zizmor, metadata-driven matrix, `re-actors/alls-green` consolidation). Cryptography concentrates it in backend compatibility and formal vulnerability handling. Returns and WPS concentrate it in type-system and lint breadth. Mypy concentrates it in self-dogfooding and primer regression testing. A useful "AI-readiness temperature" metric should therefore be **multi-dimensional** rather than a single score: the ten repositories above form a natural basis set where each axis is strongly represented by at least two exemplars. **The practical implication for a measurement system is that weighting dimensions equally will undervalue repositories that are extremely cold on three axes and average on two — which is exactly what most of these boutique projects are.** A final scoring rubric should probably take the *minimum* across pillars rather than the mean, so a project cannot compensate for thin testing with heavy linting, or vice versa. This corpus makes that trade-off visible and therefore tunable.