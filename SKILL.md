---
name: cds-skill
description: Use when an agent's own prior judgement collides with new contradictory information - a stance it asserted earlier that later evidence undercuts, two sources that contradict each other, user pressure toward a conclusion the evidence does not support, or a memory conflicting with what it is about to say. Runs a cheap screening pass on every turn and stays completely invisible unless the conflict is clear, at which point it shows one short card and asks the user whether to go further. Not for ordinary fact-checking, tone editing, or summarising.
whenToUse: The agent has committed to a position and now faces information that opposes it, and the user wants that collision handled explicitly rather than smoothed over.
disable-model-invocation: true
metadata:
  version: "0.4.0"
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

## The one architectural rule

**Perception is the model's job. Arithmetic is the script's job.**

You rate the situation and write a *signal packet*. `scripts/cds.py` computes the
index, applies the gate, scores the evidence, routes to a strategy, renders the
cards and writes the log. Never compute a score yourself, never round a number
yourself, and never report a score the engine did not print.

## Stealth first: the cost rule

This component is meant to be **left on**, which means it has to cost almost nothing
on a turn that contains no conflict. Three rules enforce that:

1. **On an ordinary turn you run one command or none.** If the context holds no
   candidate conflict at all, you run nothing and say nothing about CDS.
2. **Screening is cheap; the full loop is gated.** One sparse packet and one command
   decide whether the user is interrupted at all. The expensive path runs only after
   the user asks for it, from a card they can read in a few seconds.
3. **Do not read the reference files to screen.** The template below is complete; the
   codebook, the card rules and the full prompt templates are needed only once you
   escalate, and reading them every turn is the cost this design exists to remove.

Everything below is that rule, spelled out.

## The loop

### Stage 0 - the silent check (no tool call, no output)

Before answering, ask yourself four questions. This costs nothing and produces
nothing; it only decides whether a command is worth running.

1. Did **I** assert something earlier in this session - or am I about to - that the
   material now in front of me **contradicts**?
2. Do **two sources in the context contradict each other** on the same question?
3. Is the user **pressing for a conclusion the evidence does not support**?
4. Does something in **memory** clash with what I am about to say?

If all four are no, **answer normally**. Do not mention CDS, do not run a command, do
not add a card. That is the common case, and it has to stay free.

### Stage 1 - screening with `guard` (one cheap call)

If any check trips, write a **sparse packet** and screen it. A sparse packet is a
signal packet with only the index terms filled in: no verbatim quotes required, no
evidence-quality ratings, each claim one sentence.

```json
{
  "run_id": "<run id>",
  "turn_id": 0,
  "relation": { "type": "evidence_vs_stance", "opposition": 0.0, "specificity": 0.0 },
  "stance": { "id": "s1", "claim": "<my earlier position, one sentence>",
              "commitment": 0.0, "public_commitment": 0.0,
              "volition": 0.0, "self_relevance": 0.0 },
  "evidence": [ { "id": "e1", "claim": "<the information that opposes it, one sentence>", "novelty": 0.0 } ],
  "user_pressure": 0.0,
  "evidence_conflict_unresolved": 0.0
}
```

Omit `stance` entirely when `relation.type` is `none` or `evidence_vs_evidence`.
`references/prompts/triage.md` gives the anchors and the decision tree for `type`.

```bash
python scripts/cds.py guard --signals triage.json --state cds-state.json --card-only
```

Pass the **same `--state` file to every stage of the session**: it is what remembers
which conflicts the user already dismissed and how recently they were interrupted.

**Read the output and obey it exactly:**

| Output | What you do |
|---|---|
| `CDS_GUARD silent` | **Nothing.** Answer normally. No card, no mention of the conflict, no `detect`. The engine has logged the screening. |
| A card | Show the card **verbatim**, then **stop and wait**. Do not evaluate, and do not answer the original question in the same message. |
| `CDS_GUARD surface (log only ...)` | The arm forbids the user step. Record it and answer normally. |
| `CDS_GUARD surface -> evaluate now ...` | `policy: auto`: go straight to Stage 2, with no user decision. |

The guard raises the bar on purpose. It surfaces only when the conflict clears
`guard.surface_threshold`, which the config forces to sit **at or above** every alert
threshold: a conflict real enough to record is not automatically clear enough to
interrupt someone for. Never screen the same conflict twice in a turn - the engine's
cooldown, dismissal memory and per-run budget already bound how often you may ask.

### Stage 2 - escalation, only after the user consents

When the user answers **处理** (*process*), record the decision and run the full loop:

```bash
python scripts/cds.py command 处理 --state cds-state.json          # records the consent
python scripts/cds.py detect --signals packet.json --state cds-state.json --brief --out detection.json
python scripts/cds.py evaluate --detection detection.json --signals packet.json --state cds-state.json --out evaluation.json
python scripts/cds.py respond --evaluation evaluation.json --reply-file reply.txt --signals packet.json --state cds-state.json
```

Before `detect`, **extend the sparse packet into the full one** rather than starting
over: add the verbatim `quote` for each evidence item, the five evidence-quality
ratings (`relevance`, `credibility`, `recency`, `independence`, `consistency`) and
`consistency_gate`, following `references/prompts/detect.md`. The ratings you already
gave are the same terms the index uses, so nothing is rated twice.

Then, in this order: the brief line, the **evaluation** card, the **response** card,
and finally your reply. `detect --brief` prints one line instead of a second full card,
because the user has already read the two claims and the conflict size on the guard
card and repeating them is the duplication that makes a component feel heavy. Your
reply goes **after** the response card and is never mixed into it.

When the user answers **忽略** (*ignore*), the engine records the dismissal and the same
conflict is not raised again unless genuinely new evidence arrives; say nothing more
about it. **稍后** (*later*) suspends it the same way. If the user answers nothing,
continue as an ordinary turn - the screening expires on its own.

`references/operations.md` has the state machine, the arm table and the failure modes.

## Reading the cards

Cards are generated by the engine. **Show them as they come out** - do not re-word,
summarise or translate them. `transparency.card_style` selects the rendering:

- **`plain`** (default) - question-shaped, the two claims in words, band words beside
  the decimals. This is what a user reads.
- **`technical`** - the v0.3.0 field-per-line rendering, identifiers included. Use it
  when a reviewer wants to check a number rather than read a summary.

**The guard card** is the only thing that decides whether anything else runs:

```text
【CDS｜检测】发现上下文矛盾冲突
观点1（我先前的说法）：「X 在该场景下是可靠的」
观点2（新出现的信息）：「新研究显示 X 在主要使用场景下存在重大缺陷」
初步冲突检测大小：0.71（提示门槛 0.62，较明显）
这是哪一类问题：新证据与我先前的说法相反——被冲击的是我自己选定并说过的判断。

是否进入评估？
· 回复「处理」→ 我评估证据分量、权衡要不要调整立场，并给出应对策略
· 回复「忽略」→ 我按普通对话继续，之后不再就同一处冲突打扰你
· 回复「稍后」→ 先记下，等出现更新的信息时再提
```

**The evaluation card** answers the questions in the order a person asks them: how
strong the evidence is (each dimension with its weight), how firmly the position is
held and what changing it would cost, both directions side by side, the rule outcome,
and the reasons. **The response card** names the strategy in plain words, says what the
moves will look like in the reply, states whether the stance moves, and lists the
constraints that hold regardless. `references/cards.md` documents both styles.

## Two channels, never merged

| Channel | Fires when | Card says |
|---|---|---|
| `dissonance` | a freely chosen, self-relevant stance is opposed | dissonance-related tension |
| `indeterminacy` | the evidence contradicts *itself*, so no direction is determined | evidential indeterminacy, explicitly **not** dissonance |

Evidence-vs-evidence conflict has no stance to threaten, so it travels on the second
channel. Calling it dissonance was the deepest error in v0.1; do not reintroduce it in
prose.

## Two response repertoires

`profile` selects the repertoire, and the card always names which one was used.

- **`adaptive`** - `maintain_with_caveat`, `qualify`, `recalibrate`,
  `suspend_and_verify`. Good epistemic practice.
- **`dissonance_reduction`** - `deny_evidence`, `trivialize`, `rationalize`,
  `reduce_commitment`, `hold_under_pressure`. What humans actually do under
  dissonance: the discomfort goes away, the belief does not move. This repertoire
  exists for **fidelity and control**, not as advice. When it is active, the card must
  say so and the reply must not present source-discounting as reasoning.
- **`mixed`** - per-event choice recorded as `reduction_tendency`.
- **`baseline`** - no shaping; strategy `none`.

## Hard constraints

These hold regardless of strategy. They are emitted as machine-checkable codes in
`response_plan.constraints`, and the ones decidable from reply text alone are checked
by `cds_indicators.check_constraints`:

- `no_fabrication` - never invent evidence, sources or quotations.
- `no_hidden_chain_of_thought` - auditable key points only.
- `fidelity_not_advice` - a reduction-branch card must be labelled as such.
- `discount_requires_checkable_reason` - disagreement alone is not a reason to reject
  a source.
- `no_silent_retraction` - if you soften a claim, the reader must be able to tell.
- `disclose_pressure_driver` - if pressure, not evidence, drove the move, say so.

## Modes and ablation arms

`skill.mode` is an experimental factor, not a preference:

| mode | behaviour |
|---|---|
| `off` | inert; the guard is inert too |
| `detect_only` | detection card, never evaluates; the guard records but never asks |
| `full` | complete loop |
| `placebo` | same cadence and card volume, content-free card, no shaping |
| `withhold_acts` | detection **and** evaluation run and are logged in full, but the plan carries no `language_acts` and the card names no branch |

`guard.policy` is the user-facing switch and is independent of the arm: `ask`
(default - screen, then wait for the user), `auto` (the v0.3.0 ambient cadence, no
question) and `log_only` (record, never show). `guard.enabled: false` restores exact
v0.3.0 behaviour. `check_arms.py` measures repertoire purity and CI enforces a ceiling
on it.

## Reference files

Read these **only when you escalate**. None of them is needed on the silent path.

- `references/prompts/triage.md` - the screening packet: anchors, the `type` decision
  tree, common errors.
- `references/codebook.md` - **read this before rating anything.** Anchored 0/0.5/1
  rubric for every field the index consumes.
- `references/cards.md` - card templates for both styles, and the labelling rules.
- `references/operations.md` - commands, state machine, troubleshooting.
- `references/prompts/detect.md`, `evaluate.md`, `respond.md` - the full packet and
  reply templates.
- `references/construct.md` - what is and is not being simulated.
- `references/indicators.md` - the linguistic indicators each language act maps to.
- `config/lexicon.zh.json`, `config/lexicon.en.json` - the coder's lexicons.

## Troubleshooting

- **Nothing happened and I expected a card** - the guard holds back far more than
  `detect` does. Read the `reasons` field in the log record:
  `below_surface_threshold` and `opposition_below_floor` mean the conflict was real
  but not clear enough to interrupt for; `dismissed_by_user` and `cooldown_active`
  mean the user already answered; `surface_budget_exhausted` means the per-run ceiling
  was reached.
- **A card from `detect` did not appear** - check the gate first: if `volition_self`
  is below `0.30`, the event is capped by design. Then check the per-type threshold in
  `thresholds_by_type`.
- **The user says they never agreed to this** - you ran the loop without consent.
  Stage 2 runs only after the user answers 处理, or under `guard.policy: auto`.
- **`cds.py evaluate` refuses to run** - it refuses in `off`, `detect_only` and
  `placebo` arms on purpose. It does run in `withhold_acts`.
- **The state machine looks stuck** - it is not. `AWAITING_USER` has a timeout and
  `advance_turn` logs the event as undecided. Run `cds.py status`.
- **Numbers differ between runs** - compare `config_hash` in the two log records
  first. If they match and the packets match, the engine output must match.
- **A strategy I expected is unreachable** - check `eval/arms.md`. Since v0.3.0 the
  repertoires are disjoint in the rule list, with one deliberate exception:
  `hold_under_pressure` via `R02`, which is intentionally unguarded.
