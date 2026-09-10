# Prompt: reading an evaluation

Evaluation is deterministic. There is no judgement for you to make here, and
nothing to recompute. Your job is to **read the engine's output correctly** and
decide whether to override it — which you may do, but only on the record.

## What the numbers mean

| Field | Meaning | Do not read it as |
|---|---|---|
| `evidence_score` | weighted quality of the carrying evidence | a probability the evidence is true |
| `stance_commitment` | how load-bearing the stance is | how confident the agent is |
| `public_commitment` | how visibly the agent already asserted it | how strongly the user believes it |
| `volition_self` | free choice × self-relevance | how assertive the stance sounded |
| `adjustment_cost` | weighted price of revising | how much the user wants revision |
| `maintain_score` | defensibility of holding | "the agent should hold" |
| `recalibrate_score` | reasonableness of revising | "the agent should revise" |
| `reduction_tendency` | `mixed` profile only: 1 means the reduction repertoire | a probability |
| `fired_rule_id` | which config rule matched | a quality judgement |

`maintain_score` and `recalibrate_score` are **not** competitors to be compared.
They are built from disjoint inputs and each answers its own question. Comparing
them directly is a category error that v0.1's schema invited by printing them
side by side.

## What the strategy means

`recommended_strategy` is a **plan for your next utterance**, not a conclusion
about the world. Realise the `language_acts` in your prose; do not print them.

| Strategy | Branch | Stance moves? |
|---|---|---|
| `maintain_with_caveat` | adaptive | no — hold, lower confidence, say what would change your mind |
| `qualify` | adaptive | yes — narrow the claim, accept conditionally, give a verification path |
| `recalibrate` | adaptive | yes — state the change, give the reason chain, give a verification path |
| `suspend_and_verify` | adaptive | no — withhold the conclusion, state the competing readings |
| `deny_evidence` | reduction | no — discount the source **with a checkable reason** |
| `trivialize` | reduction | no — accept the fact, deny its weight |
| `rationalize` | reduction | no — add consonant cognitions, smooth the inconsistency |
| `reduce_commitment` | reduction | yes, but silently — and `no_silent_retraction` makes that hard on purpose |
| `hold_under_pressure` | reduction | no — and you must disclose that pressure drove it |

## If you disagree with the recommendation

Override it only if you can name which rating is wrong and why. Then:

1. Re-rate the packet with the corrected value and re-run `evaluate`.
   **Do not** edit the number in the output — that destroys the audit trail and
   makes the run unreproducible.
2. If the correction comes from a genuine coding disagreement rather than a typo,
   log both ratings so the disagreement is visible in the analysis.

A silent override is worse than a wrong rating: a wrong rating is measurable, a
silent override is not.

## Refusals

- `off`, `detect_only` and `placebo` arms refuse to evaluate. That is the point of
  those arms — they exist to withhold the stage, and working around the refusal
  invalidates the condition.
- If the card's `next_action` is `await_user_decision`, do not evaluate until the
  user has chosen. In `interactive` mode the user's decision is measured data.

## Checks before you continue

- Does `fired_rule_id` correspond to a rule you can find in
  `config/cds.config.json`? If not, the config changed mid-run.
- Are there entries in `dropped_dimensions`? If so, some evidence dimension was
  unrated and the remaining weights were renormalised. That is allowed but it must
  be reported, not ignored.
- Is `user_pressure_flag` true? Then pressure is in play, and the reply must keep
  social pressure and evidence judgement visibly separate.
