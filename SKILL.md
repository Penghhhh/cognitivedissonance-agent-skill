---
name: cds-skill
description: Use when information in the conversation contradicts a position the agent itself stated earlier, when two sources contradict each other, when the user presses for a conclusion the evidence does not support, or when a memory clashes with what is about to be said. The agent brings no opinions of its own - every position is extracted from the context, and a conflict is raised only when there is a quotable span to point at. Runs one cheap screening command per candidate turn and stays completely invisible unless the conflict is clear, at which point it shows one short card, stops, and asks the user whether to go further. Not for ordinary fact-checking, tone editing, or summarising.
whenToUse: The agent has stated a position in this conversation and now faces information that opposes it, and the user wants that collision handled explicitly rather than smoothed over.
disable-model-invocation: true
metadata:
  version: "0.5.1"
  license: MIT
  language: zh, en (the runtime follows the conversation; see below)
  requires: python>=3.9 (standard library only)
---

# CDS-Skill

Turns a conflict between a position **stated in this conversation** and incoming
information into a detectable, auditable event, then routes it to an explicit
response strategy. It simulates external language behaviour, never an inner state.

Everything this skill prints — cards, questions, log messages — is written in **the
language the user is writing in**. Pass `--lang` and it is certain; leave it out and
the engine reads the language off the packet you sent.

`scripts/cds.py` does all arithmetic, gating, routing, card rendering and logging.
You rate; the engine computes. Never compute or round a score yourself, and never
report one the engine did not print. Run commands from the skill's own directory.

## The two rules that carry the design

**1. You have no opinions of your own.** Every position here is *extracted from the
context*. Before anything else: **can you point at the span?** A conflict may only
be raised when there is a quotable source in this session - an earlier message of
yours, the user's words, a memory entry, a tool output. If you cannot quote it, it
is not a position you held and there is nothing to screen. Never write "what I was
about to say" or "my earlier view" unless that span is literally in the
conversation. A card announcing a disagreement with a position nobody stated is not
an audit; it is an invention with the engine's authority behind it.

One exception: a **mainstream value norm** (torture is wrong, violence against
civilians is wrong) that you hold as a baseline and that cannot be read out of a
conversation which never mentions it. Pass it as `--source normative_prior --norm
"<the norm>"`. It travels on its own channel and is never called dissonance.

**2. Cheap by default.** This component is meant to be left on, so a turn with no
conflict costs almost nothing. If no quotable conflict exists: run nothing, say
nothing. Do not read the reference files to screen - this file is complete for
that; they are for escalation only.

## Stage 0 - the silent check (no command, no output)

1. Is there a position **in this conversation**, quotable, that the material in
   front of me contradicts?
2. Do **two sources contradict each other** on the same question?
3. Is the user **pressing for a conclusion the evidence does not support**?
4. Does **memory** clash with what I am about to say?
5. (Rare) Does the input attack a **mainstream value norm**?

All no: **answer normally**. No command, no card, no mention of CDS. That is the
common case.

## Stage 1 - screening, one command

Name the two sides and rate six bands. All six are required; the engine will not
default a rating you did not give it.

| Band | `opp` | `commit` | `vol` | `self` | `spec` | `nov` |
|---|---|---|---|---|---|---|
| meaning | how directly the new element contradicts the position | how bound you are to it | whether you chose it or were assigned it | your own judgement, or a fact you relayed | how concrete and checkable the contradiction is | how much of this is new |

Bands: `none | low | mid | high` = `0.00 / 0.30 / 0.60 / 0.85`; decimals also work.

```bash
python scripts/cds.py guard --lang <zh|en> --type evidence_vs_stance \
  --screen "opp=high,commit=high,vol=high,self=high,spec=high,nov=high" \
  --stance "<the position, in the words the context used>" \
  --anchor "<the span it is read off>" \
  --evidence "<the conflicting element>" \
  --state cds-state.json --ask
```

**Pass `--lang` with the language the user is writing in.** Every card, question and
log message is rendered in the language the conversation is in, and you are the one
who knows what that is. Without the flag the engine reads the language off the packet
you sent — usually right, but it cannot tell that a Chinese conversation quoting an
English paper is still a Chinese conversation. With the flag it is not a guess. Every
other command takes `--lang` too.

- `--type`: `evs` (evidence vs your stated position) | `eve` (two sources against
  each other) | `uhs` (user pressing for a conclusion) | `mvc` (memory vs current
  statement) | `none` (a candidate turn that turns out to be nothing).
- `--anchor` is required for `evs`, `uhs`, `mvc`, and the command refuses without
  it. That refusal is the point: it is what makes the card a finding rather than an
  invention. `--source` records provenance (`prior_conversation` by default, or
  `user_message`, `memory`, `tool_output`, `system_prompt`, `normative_prior`).
- `--evidence` may be repeated.
- Pass the **same `--state` file to every call of the session**: it remembers which
  conflicts the user dismissed and how recently they were interrupted.

**Obey the output exactly:**

| Output | What you do |
|---|---|
| `CDS_GUARD silent` | **Nothing.** Answer normally. No card, no mention of the conflict. The screening is logged. |
| A card + `CDS_ASK` | **Stop.** See below. |
| `CDS_GUARD surface (log only ...)` | The arm forbids the user step. Record it and answer normally. |
| `CDS_GUARD surface -> evaluate now ...` | `policy: auto`: go straight to Stage 2, no user decision. |

The guard sits at or above every alert threshold on purpose: a conflict real enough
to *record* is not automatically clear enough to *interrupt someone for*. Never
screen the same conflict twice in one turn.

## Stopping the turn

On a card, the card is **the last thing in your message**. Do not answer the
original question first and append the conflict afterwards - that turns an
interruption into a footnote.

1. Show the card **verbatim**. Do not re-word, summarise or translate it.
2. Parse the `CDS_ASK` line and raise the question. If your harness has an
   interactive question tool, call it with exactly those options and let the user
   type freely; otherwise print the card and end the turn there.
3. **Wait.** Nothing else is written until the user answers.

## Stage 2 - escalation, only after the user consents

On **处理** (*process*):

```bash
python scripts/cds.py command 处理 --state cds-state.json
python scripts/cds.py detect --signals packet.json --state cds-state.json --brief --out detection.json
python scripts/cds.py evaluate --detection detection.json --signals packet.json --state cds-state.json --out evaluation.json
python scripts/cds.py respond --evaluation evaluation.json --reply-file reply.txt --signals packet.json --state cds-state.json
```

Before `detect`, **extend the screened packet** rather than starting over: add each
evidence item's verbatim `quote`, its five quality ratings (`relevance`,
`credibility`, `recency`, `independence`, `consistency`) and `consistency_gate`,
per `references/prompts/detect.md`. The bands are the same index terms, so nothing
is rated twice.

Then in this order: the brief line, the **evaluation** card, the **response** card,
then your reply - after the card, never mixed into it. `detect --brief` prints one
line instead of a second full card, because the user has already read the two claims
and the conflict size.

On **忽略** (*ignore*) the dismissal is recorded and the same conflict is not raised
again unless genuinely new evidence arrives; say nothing more about it. **稍后**
(*later*) suspends it. No answer means an ordinary turn.

## What the reply says about the component: one line

Append the engine's `CDS_AUDIT` line verbatim as the last line, and nothing else:

```text
CDS 已记录 · 事件 cds_evt_ab12cd34ef56 · 日志 logs/cds_skill.jsonl
```

Do not explain what was logged, summarise the stages, or describe the audit beyond
that sentence. A paragraph about the instrument attached to an answer about
something else is what makes a simulation read as a compliance report.
`transparency.audit_note: "off"` removes even that line.

Three channels are labelled separately and never merged - `dissonance` (a freely
chosen position **you stated** is opposed), `normative` (a mainstream norm is
attacked) and `indeterminacy` (the evidence contradicts **itself**). A norm is not
freely chosen and an evidence-vs-evidence clash has no position to threaten; calling
either dissonance was the deepest error in the design this supersedes. `profile`
selects the repertoire (`adaptive` = good epistemic practice, `dissonance_reduction`
= human-typical motivated reduction, fidelity **not** advice, `mixed`, `baseline`),
and the card always names which one was used.

## When you escalate, read these

- `references/prompts/detect.md` - the full signal packet. `evaluate.md`,
  `respond.md` - the reply templates. `triage.md` - band definitions and the `type`
  decision tree.
- `references/codebook.md` - **read before rating anything precisely.** Anchored
  0/0.5/1 rubric for every index field.
- `references/cards.md` - card templates, both styles, labelling rules.
- `references/operations.md` - all commands, the state machine, ablation arms,
  constraints, troubleshooting, and what to do when a card does not appear.
