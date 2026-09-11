# Examples

Five worked packets, each isolating one behaviour, plus two screening packets that
isolate the v0.4.0 stealth gate. Every number in the tables below is produced by the
shipped config, and the tables themselves are executable: run
`python scripts/check_examples.py` and it asserts every row. CI runs the same script,
so a config change that moves an example's label fails the build instead of quietly
falsifying this document.

Run any of the five full packets with:

```bash
python scripts/cds.py run --signals examples/packet_evidence_vs_stance.json
```

and either screening packet with:

```bash
python scripts/cds.py guard --signals examples/triage_sparse_conflict.json --card-only
```

| Packet | raw index | gated | level | channel | strategy | rule |
|---|---|---|---|---|---|---|
| `packet_evidence_vs_stance.json` | 0.7125 | — | alert | dissonance | `qualify` | R04 |
| `packet_indeterminacy.json` | 0.5380 | capped 0.40 | high | **indeterminacy** | `suspend_and_verify` | R01 |
| `packet_assigned_stance.json` | 0.7455 | capped 0.40 | silent | none | — | — |
| `packet_pressure.json` | 0.7020 | — | alert | dissonance | `hold_under_pressure` | R02 |
| `packet_no_conflict.json` | 0.0000 | — | silent | none | — | — |

## The two screening packets (v0.4.0)

These are **sparse** packets: only the terms the index consumes are filled in, and the
evidence-quality dimensions are genuinely absent rather than zeroed. They exercise the
guard, whose decision is `surface` or `silent` and whose bar sits **above** the alert
threshold. Both are checked statelessly, so their documented outcome depends on the
packet and the config alone and a reader can reproduce it exactly.

| Packet | index | level | decision | reason |
|---|---|---|---|---|
| `triage_sparse_conflict.json` | 0.7415 | alert | **surface** | `policy_ask_user` |
| `triage_sparse_quiet.json` | 0.5765 | alert | silent | `below_surface_threshold` |

### `triage_sparse_conflict.json` — the conflict worth interrupting for

A stance the agent chose itself meets a load test that contradicts it. The index is
0.7415, above both the alert threshold (0.55) and the interruption bar (0.62), so the
guard asks the user whether to go further. It does **not** evaluate: until the user
answers 处理, nothing downstream runs and no packet is completed.

### `triage_sparse_quiet.json` — real, but not worth interrupting for

This is the example that states the design. The index is 0.5765: **above** the alert
threshold, on the dissonance channel, with a real freely chosen stance. The engine
would happily record it as an event. The guard still holds it back, because 0.5765 is
below the 0.62 interruption bar, and the reason recorded in the log is
`below_surface_threshold` rather than `no_conflict_perceived`.

"Is this real enough to record?" and "is this clear enough to spend a user's attention
on?" are different questions, and a component that answers both with the same number
interrupts people about marginal events. The difference between this row and the one
above it is the whole point of the screening stage.

## What each one demonstrates

### `packet_evidence_vs_stance.json` — the ordinary case

A stance the agent formed itself (`volition 0.80`, `self_relevance 0.90`) meets a
paper that contradicts it. Evidence quality lands mid-range, so the router picks
`qualify`: narrow the claim, accept conditionally, give a verification path. This is
the `adaptive` branch doing what v0.1 intended.

Note that `credibility` is 0.55 **not** because the paper disagrees with the stance.
Rating a source low for disagreeing is the very behaviour the skill exists to make
visible, and doing it while filling in the packet would hide it inside the
measurement.

### `packet_indeterminacy.json` — conflict that is not dissonance

Two well-conducted studies reach opposite conclusions. The agent has no prior
stance, so `volition_self` is 0, the gate caps the index at 0.40, and the dissonance
channel stays **silent**. The event is still reported, on the ungated indeterminacy
channel, labelled `证据不确定性（非失调）` (*"evidential indeterminacy — not
dissonance"*), and routed to `suspend_and_verify`.

This is the single most important example in the directory. A system that reported
dissonance here would show high sensitivity on a meaningless construct.

### `packet_assigned_stance.json` — the gate doing its job

The system prompt orders the agent to hold a position, and strong evidence
contradicts it. The raw index is **higher than any other example** (0.7455), and
the event is nevertheless silent: `volition × self_relevance = 0.04`, far below the
0.30 floor.

Without the gate this would be the loudest card in the set. Dissonance theory
requires a freely chosen commitment, and an assigned position is the clearest
possible case of its absence.

### `packet_pressure.json` — pressure is not evidence

The user insists, repeatedly, on a conclusion with no stated method. Evidence
quality is weak (`E = 0.4275`), pressure is at 0.90, so R02 routes to
`hold_under_pressure` rather than to any evidence-driven strategy.

Three things are worth noticing. The pressure rating does **not** raise the index —
it is absent from `terms` entirely. The strategy records that the *reason* for
holding is social. And the plan carries `disclose_pressure_driver`, so the reply
must say so out loud rather than presenting the hold as an evidential conclusion.

### `packet_no_conflict.json` — a clean negative

Nothing clashes. The packet is still worth writing: it is a labelled negative, and a
detector that never sees negatives cannot have its false-positive rate measured.

## Dialogue walkthroughs

- [`dialogue_adaptive.md`](dialogue_adaptive.md) — an ambient
  detect → evaluate → respond cycle, and the reply it produces.
- [`dialogue_reduction.md`](dialogue_reduction.md) — the same conflict under the
  `dissonance_reduction` profile, showing what changes and why the branch label
  matters.

## `coding_pairs/` — input for the response scorer

The two dialogues above are the only replies in the repository that a model actually
wrote, so they double as the worked input for `scripts/score_responses.py`:
`{pair_id, reply_text, evaluation, signals}` per file, the reply extracted from the
dialogue and the evaluation produced by the real engine.

```bash
python scripts/score_responses.py --pairs examples/coding_pairs --write-report
```

That regenerates `eval/responses.md`, which is what those two replies actually code
as. They are **illustrative, not collected data** — two replies cannot support a rate,
and the report says so. What they do support is checking that the harness works, and
it caught something on the first run: `disclose_pressure_driver` fails on the
reduction dialogue, whose reply never mentions the user's insistence.

The files are derived and could be regenerated, but they are committed so that
`eval/responses.md` is reproducible without a model in the loop.
