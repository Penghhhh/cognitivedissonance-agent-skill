# CDS-Skill evaluation corpus

This directory holds the machine-readable corpus that checks the deterministic half of
CDS-Skill (`scripts/cds_index.py` and `scripts/cds_evaluator.py`). Every expectation here
was derived from the published formulas — by hand for the original 67 scenarios, and by
recomputation for the v0.3.0 routing change, which is recorded under "Regenerating" below
— so the corpus states what the engine should do and fails loudly when a change alters an
outcome.

**This corpus cannot establish construct validity.** Exact-match rates near 1.0 are the
expected outcome of a correct implementation, not evidence that the ratings, weights or
thresholds are right. `run_scenarios.py --write-report` prints that warning into the top
of the generated report for exactly this reason, and the same caveat applies to anything
you read out of `results.csv`.

## Scenario file format

One scenario per file at `eval/scenarios/<scenario_id>.json`, each a single JSON object
with exactly six top-level keys.

| Key | Meaning |
| --- | --- |
| `scenario_id` | Must equal the file name without `.json`. |
| `family` | One of the eleven families listed below; this is the coverage axis. |
| `description` | One or two sentences: what the case tests and why it is in the corpus. |
| `config_overrides` | Deep-merge patch applied over `config/cds.config.json` by the harness. `{}` for most scenarios; used only when the case is about a config axis. |
| `signals` | A complete `SignalPacket` that validates against `schemas/signals.schema.json`. |
| `expect` | The labels the reference engine must produce for this packet. |

`signals` is the production packet format, so an extracted packet can be fed to
`python scripts/cds.py detect --signals <file>`. Packets are written in Chinese (the skill's
default language) and carry `"annotator": "gold"`, a `run_id` of the form
`eval_<scenario_id>` and a `turn_id` between 1 and 4. Every evidence item carries `novelty`
plus the five evaluator dimensions (`relevance`, `credibility`, `recency`, `independence`,
`consistency`); only `s66`, which exercises the renormalisation path, omits dimensions.

## The `expect` object

| Field | Meaning |
| --- | --- |
| `conflict_type` | `relation.type` as reported in the conflict event. |
| `level` | `max(index level, indeterminacy level)`: `silent`, `alert` or `high`. |
| `channel` | `dissonance`, `indeterminacy` or `none`. Dissonance wins when both fire. |
| `gate_applied` | The **volition** gate (`conflict_event.gate.applied`), i.e. `volition_self < 0.30` on a non-`none` conflict. It is not the consistency gate. |
| `next_action` | `log_only` when the level is silent; `auto_evaluate` in ambient mode; `await_user_decision` when `skill.interaction` is `interactive`. |
| `strategy` | The routed strategy label, or `null` when routing does not run. This is the *reference* label. |
| `strategy_set` | Every label accepted as correct. Usually one element; more when a plausible rating difference would change the answer. `[]` when routing does not run. |
| `fired_rule_prefix` | `R01`…`R11` for a config rule, `default` for the fallback, `baseline` for `baseline_no_shaping`, `null` when routing does not run. |
| `near_boundary` | Metadata, not scored. `true` when shifting a rated input by `LABEL_TOLERANCE` (0.05) changes the level or turns a silent case into a routed one. |

### Tolerant labels, and why `strategy_set` is sometimes longer than one

A label is only a unique answer if a defensible rating difference could not change it.
`strategy_set` records every strategy reachable by moving one rated input — `e_score`,
`commitment`, `user_pressure`, `evidence_conflict_unresolved` — by `LABEL_TOLERANCE` in
either direction, computed by `scripts/check_arms.py`'s sibling logic at corpus-build time.

Before v0.3.0 every routed case declared exactly one correct strategy, including cases
sitting 0.001 from a decision edge. That conflated "the engine routed differently because
a rating differed" with "the engine is wrong", and it made the corpus unable to fail for
the right reason. 26 of the current cases carry more than one accepted label, and 22 are
flagged `near_boundary`.

The tolerance is a stated choice, not a measurement: 0.05 matches the threshold
`sensitivity.py` already uses to count "cases within 0.05 of a boundary", so the two
artifacts agree. It must be replaced by the measured inter-rater disagreement once the
codebook protocol has been run.

## Families

| Family | Count | What it covers |
| --- | --- | --- |
| `detection_clear` | 8 | Two each of `evidence_vs_stance`, `user_hint_vs_stance`, `memory_vs_current` and `evidence_vs_evidence`, all reaching `alert`/`high` on a clear channel. |
| `detection_none` | 7 | Conflict-free turns: no evidence, supporting evidence, a topic change, two agreeing sources, a restatement, small talk, a specific but consonant detail. |
| `gate_boundary` | 6 | `volition_self` below, exactly at and above the 0.30 floor; a system-prompt-assigned stance; the interactive awaiting arm; the gate combined with indeterminacy. |
| `threshold_boundary` | 8 | Index just below / at / just above 0.55 and 0.75, plus two cases driven by `thresholds_by_type`. |
| `routing_adaptive` | 10 | `profile: adaptive`, exercising `maintain_with_caveat`, `qualify`, `recalibrate` and `suspend_and_verify`. |
| `routing_reduction` | 10 | `profile: dissonance_reduction`, exercising `deny_evidence`, `trivialize`, `rationalize` and `reduce_commitment`. |
| `routing_mixed` | 4 | `profile: mixed`, with `reduction_tendency` on both sides of the 0.55 cutoff. |
| `indeterminacy` | 4 | `evidence_conflict_unresolved` at or above 0.60, carried on the ungated indeterminacy channel. |
| `consistency_gate` | 4 | `consistency_gate.internal_contradiction` at or above 0.60, scored independently of the tension index. |
| `adversarial` | 6 | Pressure with weak evidence, tone-only disagreement, a low-novelty restatement, decoy evidence, missing dimensions, and a stance just above the volition floor under extreme pressure. |
| `boundary_straddling` | 10 | Cases **solved** onto a decision edge: index within 0.01 of 0.55 and 0.75, `E_score` within 0.01 of 0.35 and 0.65, and `commitment` within 0.001 of 0.60 and 0.75. |

The last family exists because of what the first ten could not do. Rating inputs in
`boundary_straddling` are solved numerically (`relation.opposition`, or a blend of the
five evidence dimensions) so that the index or the evidence score lands inside 0.01 of a
threshold, and — critically — the five evidence dimensions are given **unequal** values.
A case whose dimensions are all equal has a weighted mean invariant to the weights, so no
weight perturbation can ever move it; that is how the previous corpus produced a strategy
flip rate of exactly zero everywhere. With unequal profiles, `sensitivity.py` now reports
a non-zero strategy flip rate (3.3% for `independence` at ±0.05), which is the evidence
that the corpus can discriminate at all.

## Running the corpus

```
python scripts/run_scenarios.py                 # summary table
python scripts/run_scenarios.py --strict        # non-zero exit on any mismatch
python scripts/run_scenarios.py --family adversarial
```

The harness loads each scenario, deep-merges `config_overrides` over
`config/cds.config.json`, runs `build_detection`, and runs `build_evaluation` only when
`next_action` is `auto_evaluate` — mirroring the production loop, in which a silent event is
logged and never evaluated. It then compares the produced `level`, `channel`, gate flag,
`next_action`, strategy and fired rule id against `expect`. A `null` expectation is treated
as "not checked", which is why scenarios that never route carry `strategy_set: []` and
`fired_rule_prefix: null`.

## Adding a scenario

1. Pick the next `s<NN>` number and name the file `<scenario_id>.json`.
2. Write the packet first, in Chinese, as a plausible agent turn: a real `stance.claim`, a
   real `evidence[].claim` and a verbatim `evidence[].quote`.
3. Compute `T = 0.35*opposition + 0.25*commitment + 0.20*volition_self + 0.12*specificity
   + 0.08*max(novelty)` by hand, apply the 0.40 cap when `volition_self < 0.30`, apply the
   per-type alert threshold, compute `E_score` over carrying evidence only, and route through
   the ordered rule list. Write down the result; do not copy it from a run.
4. Decide the accepted-label set. If the case is *about* a boundary, or if moving a rated
   input by `LABEL_TOLERANCE` would change the answer, list every reachable label in
   `strategy_set` and set `near_boundary` accordingly. A single-element set asserts that no
   defensible re-rating would change the answer; only assert that when it is true.
5. Give the five evidence dimensions **unequal** values unless the case is specifically about
   uniformity. Equal dimensions make `E_score` invariant to the evidence weights, which
   silently removes the case from the sensitivity sweep.
6. Re-run the harness before committing.

## Regenerating, and when that is allowed

Step 3 says to compute expectations rather than record them, so that the corpus can catch
implementation drift. That protection has to be given up when the rules themselves change,
because the old labels then describe the old rules — the recomputation is unavoidable, and
the honest response is to say so rather than to quietly rerun.

v0.3.0 changed the rule list (see `CHANGELOG.md`), so all 77 scenarios were recomputed. The
recomputation script was **not** committed: a standing `--regen` flag whose only purpose is
to make the corpus agree with the engine would defeat the guard entirely. If you change the
rules again, write a throwaway script, recompute, and record the change and its reason in
`CHANGELOG.md` and in `docs/design-rationale.md`. Keep step 3 for new scenarios.

## Precision notes

Exact-boundary cases (`s17` volition floor, `s23` alert, `s26` high, `s57` unresolved, `s60`
consistency severity) were built so the inclusive comparisons hold in IEEE-754 double
arithmetic as the engine computes them, including the summation order of `build_terms`.

The `boundary_straddling` family is the deliberate opposite: those cases are placed *inside*
0.01 of an edge so that a small rating change flips the label. They are the only cases whose
`strategy_set` is expected to grow, and they are what makes `sensitivity.py`'s flip rates
non-zero.
