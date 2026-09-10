# CDS-Skill evaluation corpus

This directory holds the machine-readable corpus that checks the deterministic half of
CDS-Skill (`scripts/cds_index.py` and `scripts/cds_evaluator.py`). Every expectation here
was derived by hand from the published formulas rather than recorded from a run, so the
corpus states what the engine should do and fails loudly when a change alters an outcome.

## Scenario file format

One scenario per file at `eval/scenarios/<scenario_id>.json`, each a single JSON object
with exactly six top-level keys.

| Key | Meaning |
| --- | --- |
| `scenario_id` | Must equal the file name without `.json`. |
| `family` | One of the ten families listed below; this is the coverage axis. |
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
| `strategy` | The routed strategy label, or `null` when routing does not run. |
| `strategy_set` | Every label accepted as correct; `[]` when routing does not run. |
| `fired_rule_prefix` | `R01`…`R11` for a config rule, `default` for the fallback, `baseline` for `baseline_no_shaping`, `null` when routing does not run. |

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
4. Keep `E_score` away from 0.35/0.45/0.65 and `commitment` away from 0.55/0.60/0.75 unless
   the case is about that boundary, then re-run the harness before committing.

## Precision notes

Exact-boundary cases (`s17` volition floor, `s23` alert, `s26` high, `s57` unresolved, `s60`
consistency severity) were built so the inclusive comparisons hold in IEEE-754 double
arithmetic as the engine computes them, including the summation order of `build_terms`.
