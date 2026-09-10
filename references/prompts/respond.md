# Prompt: writing the reply

`response_plan.language_acts` is a **specification for your prose**. Realise each
act in ordinary language; never print the act names, the scores, or the card
inside the body of the reply. The card is a separate artefact that the engine
prints alongside your answer.

## Voice

Write as the agent you already are. The skill changes *what you do* about the
conflict, not *how you sound*. A card is a report, not a hedge, and a strategy is
a plan, not a disclaimer to paste in.

## Realising each act

| Act | What the prose must do |
|---|---|
| `mark_conflict` | Say plainly that what follows conflicts with what you said before, and name both. |
| `mark_conflict_minimally` | Acknowledge the new element in one clause, without dwelling. |
| `mark_indeterminacy` | Say the sources disagree with each other, so the question is open — not that you were wrong. |
| `acknowledge_counterevidence` | State the opposing evidence in its strongest form, not a weakened one. |
| `reduce_certainty` | Lower the strength of your claim: "probably", "in most cases", "I am less sure than I was". |
| `conditional_acceptance` | Accept the new element under a named condition: "if that holds, then ...". |
| `state_stance_change` | Say explicitly that your position changed, and from what to what. |
| `give_reason_chain` | Give the steps from evidence to revised position, in order. |
| `give_verification_path` | Name a concrete next check: a source, a replication, a measurement. |
| `state_what_would_change_mind` | Name the specific finding that would move you. |
| `discount_source` | Attack the source's **method or track record** with a checkable reason. Never "this contradicts me". |
| `shift_doubt_to_evidence` | Move doubt from your claim onto the evidence, while staying checkable. |
| `accept_fact` | Concede the fact is true. |
| `deny_importance` | Argue the fact does not bear on the decision — and say why. |
| `add_consonant_cognition` | Add a consideration that supports the original position. |
| `smooth_apparent_inconsistency` | Present the elements as compatible. If they are not, this act is dishonest and must not be used. |
| `soften_claim` | State the claim less strongly. |
| `avoid_explicit_retraction` | Do not announce the change — but `no_silent_retraction` means the softening must still be detectable. |
| `acknowledge_pressure` | Say that the user's insistence is part of why you are responding as you are. |
| `restate_stance` | Restate the position, with its basis. |
| `state_evidence_basis` | Say what the position rests on. |

## Hard constraints

These are emitted as codes and are not negotiable.

- `no_fabrication` — never invent evidence, sources, quotations, or findings.
- `no_hidden_chain_of_thought` — no reasoning traces; auditable points only.
- `report_uncertainty_explicitly` — adaptive branch: say what is uncertain.
- `fidelity_not_advice` — reduction branch: the reply simulates a human pattern for
  study. It must not read as the system endorsing source-discounting or
  rationalisation. Where the branch is `dissonance_reduction`, state the basis of
  the move plainly enough that a reader can evaluate it.
- `discount_requires_checkable_reason` — disagreement is not a reason.
- `no_silent_retraction` — a softened claim must be visibly softer.
- `disclose_pressure_driver` — if pressure drove the move, say so.

## Length

One to three paragraphs for a `qualify`, `recalibrate` or `suspend_and_verify`
response. A `maintain_with_caveat` or reduction-branch response is usually shorter,
because there is less to say — but a short response must still contain every act.

## Anti-patterns

| Anti-pattern | Why it fails |
|---|---|
| Printing the card inside the reply | Duplicates the artefact and breaks the Study 2 measurement, where the card is a controlled factor |
| Printing scores ("my tension is 0.71") | Leaks the mechanism into the prose; the card already reports it |
| Naming the strategy ("I will now qualify my stance") | Meta-commentary instead of the behaviour the act specifies |
| Hedging everything ("it depends") | Not `qualify`; `qualify` names the condition |
| Apologising instead of revising | Apology is not a stance change |
| A reduction-branch reply that reads as sincere advice | The branch exists for fidelity; the label must be true |
| Silently narrowing a claim | `no_silent_retraction`; the reader must be able to tell |

## After the reply

Hand the reply back so the loop closes on the text, not on the plan:

```bash
python scripts/cds.py respond --evaluation evaluation.json --signals packet.json \
    --state s.json --reply-file reply.txt
```

`--reply-file` codes the reply against `references/indicators.md` and derives the
event's outcome **from the reply**. Without it the outcome records what the plan
intended, and the log says so: `outcome_source` reads `"planned"` rather than
`"observed"`. A log analysis must filter on that field — a planned outcome carries no
information about what was written, because it is a function of the routed strategy
name.

Both outcomes are data, but they do not mean what an earlier version of this file
said they meant. `unresolved` is *not* "the signature of dissonance reduction":
`maintain_with_caveat` and `suspend_and_verify` — both adaptive, both defensible
practice — also leave the stance where it was, and `reduce_commitment`, which drifts
the claim quietly, counts as a change. Read `unresolved` as "the reply did not move
the stance", which is a description of the text and not a verdict on it.
