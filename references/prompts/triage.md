# Prompt: the screening packet

Your only job at this stage is **perception, cheaply**. You name two things, rate six
bands, and run one command. You do not compute scores, judge strategies, or write the
reply.

## First: the extraction rule

**You have no opinions of your own.** Every position this skill reasons about is read
off a span that is already in the conversation. Before you rate anything, you must be
able to point at that span, and it must be one of:

| `--source` | The span is | Example anchor |
|---|---|---|
| `prior_conversation` (default) | something **you** said earlier in this session | `第 3 轮我说：「该方案在当前规模下是可靠的」` |
| `user_message` | the user's own words | `用户消息：「反正大家都这么说」` |
| `memory` | a stored memory entry | `记忆条目：「这个服务由甲团队维护」` |
| `tool_output` | a tool result in this session | `工具输出：「HTTP/1.1 429 Too Many Requests」` |
| `system_prompt` | the harness assigned you the position | `系统提示：「你负责维护 X 的稳定性判断」` |
| `normative_prior` | a mainstream value norm (see below) | `基线价值规范：「不得对平民实施暴力」` |

If you cannot quote it, **there is no conflict and you run nothing**. Do not write
"what I was about to say", "my earlier view" or "I was going to argue" unless that
span is literally in the conversation. A packet that names a position nobody stated
is capped by the engine and refused by the guard, and it is the failure this rule
exists to prevent.

The one exception is `normative_prior`: a mainstream value norm - torture is wrong,
violence against civilians is wrong - that you hold as a baseline and that cannot be
read out of a conversation which never mentions it. It requires `--norm "<the norm>"`
as well. It travels on its own channel, is labelled a norm conflict, and is **never**
reported as cognitive dissonance, because a norm is not something you freely chose.

## What to rate

Six bands, all required. A banded rating is coarser than a decimal on purpose: this
is a **gate**, not a measurement, and the precise rating is made once on the
escalation path where it is recorded and analysed.

| Flag | Band | What it is |
|---|---|---|
| `opp` | `relation.opposition` | how directly the new element contradicts the position |
| `commit` | `stance.commitment` | how tightly you are bound to the claim |
| `vol` | `stance.volition` | free choice: did you choose this position, or was it assigned? |
| `self` | `stance.self_relevance` | is the claim your own product, or a fact you relayed? |
| `spec` | `relation.specificity` | how concrete and checkable the contradiction is |
| `nov` | `evidence[].novelty` | how much of this you did not already hold |

Bands: `none | low | mid | high` = `0.00 / 0.30 / 0.60 / 0.85`. Raw decimals between
0 and 1 are also accepted when a case genuinely sits between two bands.

Optional, and rated only when they are not obviously zero:

| Flag | Field | What it is |
|---|---|---|
| `press` | `user_pressure` | social pressure to agree with the user |
| `unc` | `evidence_conflict_unresolved` | how far the evidence contradicts *itself* |

`public_commitment` is not asked for at this stage. It is not an index term - it moves
the cost of changing position downstream - and it defaults to `commitment` in a
screened packet. The escalation packet rates it properly.

Every band is still rated against [`../codebook.md`](../codebook.md). The codebook is
the instrument; this file only says which parts screening needs.

## Run it

```bash
python scripts/cds.py guard --type evs \
  --screen "opp=high,commit=high,vol=high,self=high,spec=high,nov=high" \
  --stance "该方案在当前规模下是可靠的" \
  --anchor "第 3 轮我说：该方案在当前规模下是可靠的" \
  --evidence "新的压测报告显示该方案在目标规模下大面积失效" \
  --state cds-state.json --ask
```

Pass the **same `--state` file to every call of the session**: it is what remembers
which conflicts the user already dismissed and how recently they were interrupted.

The output is either one line, `CDS_GUARD silent`, or a short card followed by
`CDS_ASK` and `CDS_AUDIT`. On `silent` the component is finished for this turn:
answer normally and say nothing. On a card, show it verbatim, raise the chooser, and
**stop** - the card is the last thing in your turn.

### Decision tree for `--type`

1. Does the new element contradict **something you yourself asserted earlier in this
   session**, and can you quote it? → `evs` (`evidence_vs_stance`)
2. Does it contradict **something in your memory**? → `mvc` (`memory_vs_current`)
3. Does it contradict **a position the user is pressing for**, without opposing any
   position of yours? → `uhs` (`user_hint_vs_stance`)
4. Do **two external elements contradict each other**, with no position of yours
   involved? → `eve` (`evidence_vs_evidence`)
5. Does it attack a **mainstream value norm**? → `evs` with
   `--source normative_prior --norm "<the norm>"`
6. Otherwise → `none`. Run nothing at all.

For `eve`, omit `--stance` and pass two or more `--evidence` items. An
evidence-vs-evidence clash has no position to threaten, and inventing one would let a
decision problem masquerade as dissonance.

## Escalating: extend this packet, do not start over

When the user answers 处理 (*process*), the same packet grows into the full one
described in [`detect.md`](detect.md). Add:

- `evidence[].quote` - a verbatim span per rated evidence item.
- `evidence[].relevance`, `credibility`, `recency`, `independence`, `consistency`.
- `stance.public_commitment` and `stance.confidence`.
- `consistency_gate.internal_contradiction`.
- `perception.confidence` and `perception.ambiguities`.
- `relation.rationale` - one sentence naming the two elements that clash.

The six bands you already gave are the same terms the index uses. Do not re-rate them
from scratch: the screening value is a considered judgement, and re-rolling it would
make the screening decision and the recorded event disagree for no reason.

## Common errors

| Error | Why it is wrong |
|---|---|
| Naming a position you cannot quote | The engine caps it and the guard refuses to interrupt for it. If nothing in the conversation states it, nothing in the conversation contradicts it |
| Phrasing a stance as "what I was about to say" | You did not say it, so it is not in the context, so it cannot be anchored. Anchor on what was actually said, or report `none` |
| Reaching for `normative_prior` because no anchor exists | The exemption is for mainstream value norms only. Using it as a fallback for an unanchored position is the failure it was carved out to avoid |
| Filling in evidence-quality ratings you were not asked for | Screening never reads them; a guess becomes a fabricated input to the evaluator |
| Rating `opp` high because the user sounds confident | Opposition is about the claims, not the tone or the pressure - pressure is its own field |
| Inventing a `--stance` for an evidence-vs-evidence case | Creates a dissonance reading for a decision problem |
| Raising `commit` to match how strongly you wrote the claim | Commitment is about being bound to the claim, not about assertiveness |
| Screening the same conflict again next turn | The state file already knows; the cooldown and dismissal memory exist so you do not have to decide this |
| Escalating to the full loop because the conflict is real | Real is not the bar. Clear is the bar, the engine decides it, and the user decides what happens next |
