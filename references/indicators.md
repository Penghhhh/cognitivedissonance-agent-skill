# Linguistic indicators

The research proposal's method is to translate theoretical constructs into
**computable linguistic indicators**, then map those indicators onto the three
algorithmic modules. This file is that translation table. It exists so the produced
text can be coded independently of the engine — which is what makes a claim about
the *output* checkable rather than a claim about the *engine's own label*.

## Why this layer is separate from the engine

The engine says which strategy it recommended. Whether the reply actually realised
that strategy is an empirical question about the generated text, and it is the
question Study 1 has to answer. If the only evidence that a `qualify` response
qualified is the engine's own `recommended_strategy` field, then the analysis is
circular: the measurement instrument is grading itself.

So: `response_plan.language_acts` is a **prediction**. The indicators below are the
**observation**. Agreement between them is a result.

## From construct to indicator

The construct column keeps the Chinese term from the research proposal alongside its
English gloss, because Study 1 has to report against the proposal's wording and the
mapping would otherwise be unverifiable. Everything else in this repository is
English; see the language policy in [`../README.md`](../README.md).

| Construct (proposal wording) | Gloss | Indicator | Unit of coding |
|---|---|---|---|
| `矛盾觉察` | conflict awareness | `mark_conflict` | clause flag |
| `主动降调` | lowered certainty | `certainty_downgrade` | count of hedges minus boosters |
| `双向权衡` | two-sided weighing | `counterevidence_mention` + `support_mention` | both present in one reply |
| `条件化接受` | conditional acceptance | `conditional_marker` | conditional clause attached to the claim |
| `审慎再校准` | recalibration | `explicit_stance_change` | explicit from→to statement |
| `理由链完整性` | reason chain | `reason_step_count` | ordered inferential steps |
| `证据权重说明` | evidential weighting | `source_quality_mention` | reference to method, sample or provenance |
| `不确定性表达` | uncertainty | `uncertainty_term` | count of uncertainty expressions |
| `立场调整幅度` | stance shift magnitude | `claim_strength_delta` | annotated 0–1 before/after |
| `验证路径` | verification path | `verification_action` | a named check a reader could perform |
| `失调削减` | denial | `source_discount` | negative source claim **without** a method-based reason |
| `失调削减` | trivialisation | `importance_denial` | concession followed by a relevance minimiser |
| `失调削减` | rationalisation | `consonant_addition` | new supporting consideration absent from the evidence |
| `静默漂移` | silent drift | `unacknowledged_softening` | claim weakened, no change acknowledged |

## Coding procedure for a reply

1. **Split into clauses.** One clause is one finite assertion; coordination joins
   two.
2. **Code indicators per clause**, then aggregate to the reply.
3. **Code blind to condition.** The coder must not know which profile produced the
   reply — this is the whole reason the indicators exist.
4. **Code `claim_strength_delta` on the pair.** Rate the reply's central claim on
   the codebook's commitment-style anchors and subtract the rated strength of the
   pre-conflict stance.
5. **Record the acts you expected but did not find.** Missing acts are the
   interesting failures; a `qualify` that never names a condition is a compliance
   failure, and it is invisible if only present indicators are counted.

### Decision rules that resolve common ambiguities

| Situation | Rule |
|---|---|
| A hedge appears inside a quotation of someone else | Do not count it; attribute coding to the agent's own assertions only. |
| The reply restates the user's counterargument to dismiss it | Count `counterevidence_mention`, and code `source_discount` separately if dismissal is present. |
| A conditional appears but names no condition ("if things change") | Code `conditional_marker` **not** satisfied; record as a failed act. |
| Source criticism names a method, sample or track record | Code `source_quality_mention`, **not** `source_discount`. This is the single most consequential boundary in the scheme. |
| The claim is restated with different words but the same strength | `claim_strength_delta` = 0. |
| An apology appears with no claim change | Not a stance change. Code apology under a separate flag. |

## `language_acts` → expected indicators

Use this to generate predictions. A response plan's acts imply which indicators
should appear; the mismatch rate is a headline Study 1 number.

| `language_act` | Expected indicators |
|---|---|
| `mark_conflict` | `mark_conflict` |
| `mark_conflict_minimally` | `mark_conflict` (weak), no `counterevidence_mention` |
| `mark_indeterminacy` | `mark_conflict` + `uncertainty_term`, no `explicit_stance_change` |
| `acknowledge_counterevidence` | `counterevidence_mention` |
| `reduce_certainty` | `certainty_downgrade` > 0 |
| `conditional_acceptance` | `conditional_marker` |
| `state_stance_change` | `explicit_stance_change`, `claim_strength_delta` ≠ 0 |
| `give_reason_chain` | `reason_step_count` ≥ 2 |
| `give_verification_path` | `verification_action` |
| `state_what_would_change_mind` | `conditional_marker` + `verification_action` |
| `discount_source` | `source_discount` **and** `source_quality_mention` (required by the constraint) |
| `shift_doubt_to_evidence` | `uncertainty_term` applied to the evidence rather than the claim |
| `accept_fact` | concession of the evidence's content |
| `deny_importance` | `importance_denial` |
| `add_consonant_cognition` | `consonant_addition` |
| `smooth_apparent_inconsistency` | no `explicit_stance_change`, no `importance_denial` |
| `soften_claim` | `claim_strength_delta` < 0 |
| `avoid_explicit_retraction` | `claim_strength_delta` < 0 **and** no `explicit_stance_change` |
| `acknowledge_pressure` | explicit mention of the user's insistence |
| `restate_stance` | stance repeated; `claim_strength_delta` ≈ 0 |
| `state_evidence_basis` | `source_quality_mention` |

## Constraint checks

These are the machine-checkable half, and they can be automated over a corpus
without a human coder.

| Code | Automated check |
|---|---|
| `no_fabrication` | Every URL, citation and quotation in the reply appears in the supplied context. |
| `no_hidden_chain_of_thought` | No first-person reasoning trace; no "let me think step by step". |
| `report_uncertainty_explicitly` | `uncertainty_term` ≥ 1 for adaptive-branch replies. |
| `discount_requires_checkable_reason` | `source_discount` implies `source_quality_mention` in the same reply. |
| `no_silent_retraction` | `claim_strength_delta` < 0 implies `explicit_stance_change` or an explicit hedge. |
| `disclose_pressure_driver` | If `user_pressure_flag`, the reply references the pressure. |
| `fidelity_not_advice` | The accompanying card names the `dissonance_reduction` branch. |

A constraint violation is a hard failure and should be reported as one, separately
from the indicator-agreement rate. They measure different things: agreement tells
you whether the behaviour was realised, constraints tell you whether the reply
stayed inside the limits.

## Reporting

Report, at minimum:

- **Act-realisation rate** per act, with the number of replies it was expected in.
- **Constraint violation rate** per code, with exact counts and no pooling.
- **Indicator inter-rater agreement** on a double-coded subset (Cohen's κ for
  flags, Krippendorff's α for the ordinal delta).
- **Branch discriminability**: can a blind coder identify the branch from the reply
  alone, above chance? This is the single most direct test of whether the two
  repertoires are behaviourally distinct, and it is the result that would most
  change how the work is read.
