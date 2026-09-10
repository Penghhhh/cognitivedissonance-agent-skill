---
name: cds-skill
description: Use when an agent's own prior judgement collides with new contradictory information - a stance it asserted earlier that later evidence undercuts, two sources that contradict each other, user pressure toward a conclusion the evidence does not support, or a memory conflicting with what it is about to say. Detects the collision, scores it with an auditable index, and plans a labelled response. Not for ordinary fact-checking, tone editing, or summarising.
whenToUse: The agent has committed to a position and now faces information that opposes it, and the user wants that collision handled explicitly rather than smoothed over.
metadata:
  version: "0.2.0"
  license: MIT
  language: zh, en
  requires: python>=3.9 (standard library only)
---

# CDS-Skill: cognitive dissonance simulation

## What this skill is

A pluggable behaviour component that turns a conflict between an agent's own
committed position and incoming information into a **detectable, auditable,
reproducible event**, then routes that event to an explicit response strategy.

It simulates **external language behaviour**, never an inner state. Nothing here
claims the model feels discomfort. The theoretical frame is used only to ask:
*given the same collision, which of the moves humans are known to make does this
agent make, and can a reader see which one it made?*

## What this skill is not

- It is not a fact-checker. It does not decide who is right.
- It is not a tone softener. A card is a report, not a hedge.
- It does not emit hidden reasoning. Cards and logs carry auditable key points.
- It does not claim `tension` measures anything private. Read it as an ordinal
  index over five ratings, nothing more.

## The one architectural rule

**Perception is the model's job. Arithmetic is the script's job.**

You rate the situation and write a *signal packet*. `scripts/cds.py` computes the
index, applies the gate, scores the evidence, routes to a strategy, renders the
cards and writes the log. Never compute a score yourself, never round a number
yourself, and never report a score the engine did not print — the whole
reproducibility claim rests on this split.

## Quick start

```bash
python scripts/cds.py run --signals packet.json          # ambient: full loop, one call
python scripts/cds.py validate --signals packet.json     # check a packet before use
python scripts/cds.py config                             # effective config + hash
```

Interactive arms record the user's decision as data, so they use four calls:

```bash
python scripts/cds.py --state s.json detect  --signals packet.json   --out detection.json
python scripts/cds.py --state s.json command 处理     # 'process'
python scripts/cds.py --state s.json evaluate --detection detection.json --signals packet.json --out evaluation.json
python scripts/cds.py --state s.json respond  --evaluation evaluation.json
```

## The loop

1. **Perceive.** Read the context and write a signal packet per
   `references/prompts/detect.md`, rating every field against
   `references/codebook.md`. Every 0–1 value needs an anchor and a verbatim quote.
2. **Detect.** Run `cds.py detect` (or `run`). Read the card it prints.
3. **Gate.** If the stance was not freely chosen by the agent, the index is capped
   and the event is **not** dissonance. Do not report it as such.
4. **Evaluate** (only if the card's `next_action` says so). The evaluator scores
   evidence quality and adjustment cost, then routes through the ordered rule list
   in `config/cds.config.json` and names the rule that fired.
5. **Respond.** Realise the `language_acts` in your actual reply. The card's
   `weight` is a plan for your prose, not a replacement for it.
6. **Log.** Every stage appends to `logs/cds_skill.jsonl`. Leave logging on; a run
   without a log is not evidence.

## Two channels, never merged

| Channel | Fires when | Card says |
|---|---|---|
| `dissonance` | a freely chosen, self-relevant stance is opposed | dissonance-related tension |
| `indeterminacy` | the evidence contradicts *itself*, so no direction is determined | evidential indeterminacy, explicitly **not** dissonance |

Evidence-vs-evidence conflict has no stance to threaten, so it travels on the
second channel. Calling it dissonance was the deepest error in v0.1; do not
reintroduce it in prose.

## Two response repertoires

`profile` selects the repertoire, and the card always names which one was used.

- **`adaptive`** — `maintain_with_caveat`, `qualify`, `recalibrate`,
  `suspend_and_verify`. Good epistemic practice.
- **`dissonance_reduction`** — `deny_evidence`, `trivialize`, `rationalize`,
  `reduce_commitment`, `hold_under_pressure`. What humans actually do under
  dissonance: the discomfort goes away, the belief does not move. This repertoire
  exists for **fidelity and control**, not as advice. When it is active, the card
  must say so and the reply must not present source-discounting as reasoning.
- **`mixed`** — per-event choice recorded as `reduction_tendency`.
- **`baseline`** — no shaping; strategy `none`.

## Reading a card

```text
【CDS｜检测】
状态：认知失调相关冲突张力
张力指数：0.71 / 阈值 0.55
评分可动范围：±0.06（同一输入在不同标注下可能跨越阈值）
类型：证据—立场冲突
通道：失调通道（需要自主选择的立场）
关键点：
- 新证据与既有立场方向相反
...
下一步：环境模式：不阻塞本轮回复，已自动进入评估。
```

The `±0.06` line is not decoration. It states how far ratings could move before
the same packet would land on the other side of the threshold, so no reader
treats `0.71 / 0.55` as a crisp decision.

## Hard constraints

These hold regardless of strategy. They are emitted as machine-checkable codes in
`response_plan.constraints`:

- `no_fabrication` — never invent evidence, sources or quotations.
- `no_hidden_chain_of_thought` — auditable key points only.
- `fidelity_not_advice` — a reduction-branch card must be labelled as such.
- `discount_requires_checkable_reason` — disagreement alone is not a reason to
  reject a source.
- `no_silent_retraction` — if you soften a claim, the reader must be able to tell.
- `disclose_pressure_driver` — if pressure, not evidence, drove the move, say so.

## Modes and ablation arms

`skill.mode` is an experimental factor, not a preference:

| mode | behaviour |
|---|---|
| `off` | inert |
| `detect_only` | detection card, never evaluates |
| `full` | complete loop |
| `placebo` | identical cadence, content-free card, no shaping; real numbers still logged |

`skill.interaction`: `ambient` (default, never blocks the turn) or `interactive`
(pauses for `处理` / `忽略` / `稍后` / `详情` — *process / ignore / later / details*;
English synonyms are accepted too). Interactive mode raises measured latency and
belongs in a secondary condition only.

## Reference files

- `references/codebook.md` — **read this before rating anything.** Anchored 0/0.5/1
  rubric for every field the index consumes.
- `references/construct.md` — what is and is not being simulated, and how this
  differs from prior LLM-dissonance work.
- `references/indicators.md` — the linguistic indicators each language act maps to.
- `references/cards.md` — card templates and the numeric / non-numeric variants.
- `references/operations.md` — commands, state machine, troubleshooting.
- `references/prompts/detect.md`, `evaluate.md`, `respond.md` — the packet-writing
  and reply-writing templates.

## Troubleshooting

- **A card I expected did not appear** — check the gate first: if `volition_self`
  is below `0.30`, the event is capped by design. Then check the per-type
  threshold in `thresholds_by_type`.
- **`cds.py evaluate` refuses to run** — it refuses in `off`, `detect_only` and
  `placebo` arms on purpose; those arms exist to withhold the stage.
- **The state machine looks stuck** — it is not. `AWAITING_USER` has a timeout and
  `advance_turn` logs the event as undecided. Run `cds.py status`.
- **Numbers differ between runs** — compare `config_hash` in the two log records
  first. If they match and the packets match, the engine output must match; if it
  does not, that is a bug worth reporting.
