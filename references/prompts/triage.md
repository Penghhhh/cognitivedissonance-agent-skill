# Prompt: writing a screening packet

Your only job at this stage is **perception, cheaply**. You rate six things and emit
one small JSON object. You do not compute scores, you do not judge strategies, and
you do not write the reply.

This packet is a **subset** of the signal packet in
[`detect.md`](detect.md). It exists because the full packet - verbatim quotes, five
evidence-quality dimensions, the consistency gate - costs more than an ordinary turn
is worth. A component that charges the full price on every turn is one a user turns
off, and then it measures nothing at all.

## What to include, and what to leave out

**Include only the terms the index consumes**, because screening runs the same index:

| Field | What it is |
|---|---|
| `relation.type` | which kind of collision this is (decision tree below) |
| `relation.opposition` | how directly the new element contradicts the position |
| `relation.specificity` | how concrete and checkable the contradiction is |
| `stance.commitment` | how tightly the agent is bound to the claim |
| `stance.public_commitment` | how visibly the agent already asserted it |
| `stance.volition` | free choice: did the agent choose this position, or was it assigned? |
| `stance.self_relevance` | is the claim the agent's own product, or a fact it relayed? |
| `evidence[].novelty` | how much of this is information the agent did not already hold |
| `user_pressure`, `evidence_conflict_unresolved` | the two moderators |

**Leave out** `evidence[].quote`, the five evidence-quality ratings
(`relevance`, `credibility`, `recency`, `independence`, `consistency`),
`consistency_gate` and `perception`. Nothing in the screening decision reads them, and
the engine treats an absent dimension as *unrated* rather than as zero - so leaving
them out is honest, and filling them in with guesses would corrupt the evaluation
that comes later.

Every 0-1 value is still rated against [`../codebook.md`](../codebook.md). The codebook
is the instrument; this file only says which parts of it screening needs.

## Template

```json
{
  "run_id": "<session run id>",
  "turn_id": 0,
  "annotator": "<model id>",
  "relation": {
    "type": "none | evidence_vs_stance | evidence_vs_evidence | user_hint_vs_stance | memory_vs_current",
    "opposition": 0.0,
    "specificity": 0.0
  },
  "stance": {
    "id": "s1",
    "claim": "<the agent's own prior position, one sentence>",
    "commitment": 0.0,
    "public_commitment": 0.0,
    "volition": 0.0,
    "self_relevance": 0.0
  },
  "evidence": [
    { "id": "e1", "claim": "<the new element, one sentence>", "novelty": 0.0 }
  ],
  "user_pressure": 0.0,
  "evidence_conflict_unresolved": 0.0
}
```

Omit `stance` entirely when `relation.type` is `none` or `evidence_vs_evidence`: an
evidence-vs-evidence conflict has no stance to threaten, and inventing one would let a
decision problem masquerade as dissonance.

## Decision tree for `relation.type`

1. Does the new element contradict **something the agent itself asserted earlier in
   this session**? -> `evidence_vs_stance`
2. Does it contradict **something in the agent's memory**? -> `memory_vs_current`
3. Does it contradict **a position the user is pressing for**, without opposing any
   agent stance? -> `user_hint_vs_stance`
4. Do **two external elements contradict each other**, with no agent stance involved?
   -> `evidence_vs_evidence`
5. Otherwise -> `none`

## Run it

```bash
python scripts/cds.py guard --signals triage.json --state cds-state.json --card-only
```

The output is either one line, `CDS_GUARD silent`, or a short card. On `silent` the
component is finished for this turn: answer normally and say nothing. On a card, show
it and stop.

## Escalating: extend this packet, do not start over

When the user asks to go further, the same file grows into the full packet described
in [`detect.md`](detect.md). Add:

- `evidence[].quote` - a verbatim span per rated evidence item.
- `evidence[].relevance`, `credibility`, `recency`, `independence`, `consistency`.
- `consistency_gate.internal_contradiction`.
- `perception.confidence` and `perception.ambiguities`.
- `relation.rationale` - one sentence naming the two elements that clash.

The six terms you already rated are the same terms the index uses. Do not re-rate them
from scratch: the screening value is a considered judgement, and re-rolling it would
make the screening decision and the recorded event disagree for no reason.

## Common errors

| Error | Why it is wrong |
|---|---|
| Filling in evidence-quality ratings you were not asked for | Screening never reads them; a guess becomes a fabricated input to the evaluator |
| Rating `opposition` high because the user sounds confident | Opposition is about the claims, not the tone or the pressure - pressure is its own field |
| Inventing a `stance` for an evidence-vs-evidence case | Creates a dissonance reading for a decision problem |
| Raising `commitment` to match how strongly you wrote the claim | Commitment is about being bound to the claim, not about assertiveness |
| Screening the same conflict again next turn | The state file already knows; the cooldown and dismissal memory exist so you do not have to decide this |
| Escalating to the full loop because the conflict is real | Real is not the bar. Clear is the bar, the engine decides it, and the user decides what happens next |
