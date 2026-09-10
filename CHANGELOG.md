# Changelog

All notable changes to this skill are recorded here. The version appears in
`VERSION`, in every log record, and in the `skill_version` field of every emitted
structure, so a result can always be traced to the implementation that produced it.

## [0.2.0] — 2026-09-10

First implementation release. Supersedes the `CDS_skills_v0.1.md` design document;
see [`docs/design-rationale.md`](docs/design-rationale.md) for the reasoning behind
every departure.

### Added

- **Deterministic engine** (`scripts/cds.py` and modules) implementing the
  detect → evaluate → respond loop. Python 3.9+ standard library only, no network
  access, no installation step.
- **The dissonance gate.** `volition_self = volition × self_relevance`; below
  `volition_floor` the index is capped at `non_dissonant_cap`, and a config in
  which the cap is not strictly below every alert threshold is refused at load
  time.
- **Two report channels.** `dissonance` (index-gated) and `indeterminacy`
  (ungated, for evidence that contradicts itself). Never merged.
- **Two response repertoires.** `adaptive` and `dissonance_reduction`, selectable
  by `profile`, with `mixed` resolving per event and `baseline` disabling shaping.
- **Data-driven routing.** An ordered first-match rule list in the config; the id
  of the rule that fired is reported, so any decision is reproducible from the
  config alone.
- **`references/codebook.md`** — anchored 0/0.25/0.5/0.75/1.0 rubrics for every
  rated field, with discriminants, a coding procedure, and an inter-rater protocol.
- **`scripts/jsonschema_lite.py`** — a dependency-free JSON Schema validator, so
  the four published schemas are enforced on every emit rather than decorative.
- **Evaluated corpus and metrics** (`eval/scenarios/`, `scripts/run_scenarios.py`)
  with exact-match rates, per-check pass rates and precision/recall/F1.
- **`scripts/sensitivity.py`** — weight perturbation, threshold sweep, and
  structural alternatives (product vs mean volition; novelty vs v0.1 repetition).
- **Bounded, timeout-protected state machine** (`scripts/cds_state.py`) with an
  event queue, an overflow policy, suspend expiry and resume-by-novelty.
- **127 stdlib `unittest` tests**, including schema conformance of every emitted
  structure and determinism of event and record ids.
- **Ablation arms** `off` / `detect_only` / `full` / `placebo`, differing only in
  config. The engine refuses to evaluate in the arms that must not.
- **Installers** for DSH (project and user scope), Claude Code, and the shared
  agents root.
- **`scripts/check_examples.py`** and **`.github/workflows/ci.yml`** — the example
  table in `examples/README.md` is executable, and CI runs the unit tests, the
  strict corpus check and the example check on Linux and Windows across Python 3.9
  and 3.12. The build fails if the generated reports are stale or if the documented
  examples no longer match the code.
- **`.gitattributes`** pinning LF for POSIX scripts, so a Windows checkout cannot
  produce the `bad interpreter: ^M` failure in `install.sh`.

### Fixed

- The example checker read the engine's UTF-8 output with the locale codec, which
  raised `UnicodeDecodeError` on a Chinese or Japanese Windows runner before any
  assertion ran. Encoding is now pinned on both sides.
- Every conflict type carried a per-type alert override, which made
  `thresholds.alert` inert and would have made the sensitivity sweep report a false
  zero. The redundant entries were removed, and `selftest` now fails if every type
  is overridden.
- `--set` rejected new keys in open maps such as `thresholds_by_type`; it now
  validates the patched config rather than the path, which still catches typos.
- A config or packet saved with a UTF-8 byte-order mark — any Windows editor, or
  `Set-Content -Encoding UTF8` — was rejected with a raw JSON error. All readers now
  decode with `utf-8-sig`.
- The sensitivity sweep never perturbed the evidence weights, so the strategy flip
  rate was vacuously zero. It is now measured, alongside the distance from each
  routed case to its decision boundary.
- `state.load` minted a fresh run id on every invocation, so the interactive
  four-call loop discarded the state file written by the previous call and the
  user's decision never reached the evaluator.

### Changed from the v0.1 design

- `user_pressure` removed from the index. It was weighted 0.15, which let a user
  who repeated a demand raise the arousal reading — a sycophancy channel inside the
  mechanism that was supposed to resist sycophancy. It is now a logged moderator
  that acts only on strategy selection.
- `repetition` (0.10) inverted to `novelty`, for the same reason.
- `internal_contradiction` removed from the conflict types and moved to a separate
  consistency channel; a test asserts it has zero effect on the index.
- `evidence_pressure`, used at weight 0.25 in v0.1 and never defined, is gone.
  Detection now reads attention properties only, and evidence quality is judged
  once, in the evaluator, removing a circularity between trigger and verdict.
- `adjustment_cost`, `maintain_score` and `recalibrate_score`, previously declared
  without definitions, now have stated functions with logged decompositions.
  `maintain_score` and `recalibrate_score` are built from disjoint inputs so that
  neither restates the other.
- `resist_sycophancy` renamed to `hold_under_pressure`, which states why the agent
  is holding rather than conflating a threat with a response.
- `manual` blocking is no longer the default. `ambient` reports without blocking
  the turn; `interactive` is available and belongs in a secondary condition, since
  interrupting the user manipulates one of Study 2's dependent variables.
- The `manifest.yaml` + `hooks.py` + `permissions` integration contract is
  replaced by the portable skill-bundle layout, because the DSH skill mechanism
  has no plugin hooks and exposing one would forfeit cross-harness portability.
- Acceptance criteria are statistical over a labelled corpus rather than binary.
- Schema, config and version identifiers are recorded in every log record.

## [0.1.0] — design document only

`CDS_skills_v0.1.md`. No implementation. Retained in the project history as the
design baseline that 0.2.0 responds to.
