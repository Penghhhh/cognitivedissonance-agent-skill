# Operations

Everything needed to run, install, debug and reproduce the skill.

## Commands

```bash
python scripts/cds.py guard    --signals triage.json --card-only # screen one sparse packet
python scripts/cds.py run      --signals packet.json            # ambient: full loop, one call
python scripts/cds.py detect   --signals packet.json            # stage 1 only
python scripts/cds.py evaluate --detection d.json --signals packet.json
python scripts/cds.py respond  --evaluation e.json
python scripts/cds.py command  处理                              # user decision: process
python scripts/cds.py status
python scripts/cds.py validate --signals packet.json
python scripts/cds.py config
python scripts/cds.py selftest
```

`guard` is the cheap front half of detection, and it is the one stage whose default
output is **not** the card-plus-JSON the others print:

| `guard` flag | Effect |
|---|---|
| `--signals PATH` | the **sparse** packet; only `relation` is required by `schemas/signals.schema.json` |
| `--card-only` | print the card and nothing else — an empty string when there is nothing to show, i.e. when the decision is `silent` or the user step is withheld (`next_action: log_only`) |
| `--json` | print the whole guard record instead of the one-line hint |
| `--out PATH` | write the guard record to a file |
| `--no-turn-advance` | do not advance the turn counter |

On the silent path — the common path, and the one the stage exists for — the entire
output is one line, `CDS_GUARD silent`, and no card is rendered at all. The record is
never lost: it goes to the JSONL log on every screening, `--json` prints it and `--out`
writes it. It validates against `schemas/guard.schema.json` and embeds the full
`DetectionResult`, so a single screening line is self-contained.

`detect` also takes `--brief`, which prints one line instead of the detection card. It
belongs to the escalation path: the guard card has already named the two claims and the
conflict reading, so a second full card is duplication. The full detection record is
still written, logged and available with `--json` or `--out`.

`run` and `respond` also take `--reply-file PATH` (or `-` for stdin). Supplying the
reply is what turns the loop's terminal variable from a restatement of the plan into
an observation:

```bash
python scripts/cds.py run     --signals packet.json --reply-file reply.txt
python scripts/cds.py respond --evaluation e.json --reply-file reply.txt --signals packet.json
```

Without it, the respond record still contains `outcome`, but `outcome_source` reads
`"planned"` and `reply.supplied` is `false`. Any log analysis must filter on that
field; treating a planned outcome as an observation is the circularity the split
exists to prevent. `--signals` is optional on `respond` and only sharpens the coding
(one indicator, `consonant_addition`, compares the reply against the evidence, so
without the packet it is reported as not checked rather than as zero).

Global flags work **before or after** the subcommand:

| Flag | Effect |
|---|---|
| `--config PATH` | use a different config |
| `--state PATH` | persist state across invocations |
| `--run-id ID` | pin the run id (overrides a stored one) |
| `--json` | print the raw structure instead of the card |
| `--card-only` | print only the card; on `guard` this is an empty string when there is nothing to show — a `silent` decision, or a withheld user step |
| `--out PATH` | write the stage output to a file |
| `--reply-file PATH` | the reply the host model wrote; codes it and sources the outcome from it |
| `--signals PATH` | on `respond`: the packet, so indicator coding can use the evidence |
| `--no-log` | skip the JSONL record |
| `--log PATH` | override the log path |
| `--model`, `--provider`, `--model-version`, `--temperature`, `--seed` | recorded in the log envelope |

The skill cannot observe the host model, so it does not pretend to: pass these and
they are recorded verbatim.

## The interactive loop spans processes

`guard` / `detect` / `command` / `evaluate` / `respond` are separate invocations, so the
state file is what carries the run. `--state` is therefore **required** for the
interactive loop; without it the engine prints a note that the precondition could
not be checked and exits cleanly.

The state file also carries the run id, so every stage of one loop lands in the
same log partition. Passing `--run-id` that differs from the stored one is an
intentional override and starts a fresh run.

### The stealth loop, the recommended operating mode

Screening runs on every turn; the full loop runs only after the user asks for it. This
is the arrangement the component is designed around, because a component that costs a
full packet and three cards on every ordinary turn is one a user switches off.

1. **Write the sparse packet.** A valid signal packet with only the index terms filled
   in: `relation.type`, `relation.opposition`, `relation.specificity`,
   `stance.{commitment, public_commitment, volition, self_relevance}`,
   `evidence[].novelty`, `user_pressure`, `evidence_conflict_unresolved`. Leave out
   `quote`, the five evidence-quality ratings (`relevance`, `credibility`, `recency`,
   `independence`, `consistency`), `consistency_gate` and `perception`.
   `references/prompts/triage.md` gives the anchors and the `type` decision tree.
2. **Screen it.**

   ```bash
   python scripts/cds.py guard --signals triage.json --state cds-state.json --card-only
   ```

3. **If it is silent, answer normally and show nothing.** `CDS_GUARD silent` — an empty
   string under `--card-only` — means the user sees no card and hears no mention of the
   conflict; the screening is logged either way. This is the majority of turns, and it
   costs one command.
4. **If it is a card, show it verbatim and wait.** Do not evaluate, and do not answer
   the original question in the same message.
5. **On 处理 (*process*), record the decision.**

   ```bash
   python scripts/cds.py command 处理 --state cds-state.json
   ```

   Consent is single-use and expires after one further turn
   (`GUARD_CONSENT_TURNS = 1`): a consent given several turns ago is not consent for the
   conflict in front of us now. 忽略 (*ignore*) and 稍后 (*later*) are recorded as
   dismissals instead.
6. **Extend the same packet into the full one.** Add the verbatim `quote` for each
   evidence item, the five evidence-quality ratings and `consistency_gate`, following
   `references/prompts/detect.md`. The terms already rated are the same terms the index
   uses, so nothing is rated twice.
7. **Run the full loop, with `--brief`.**

   ```bash
   python scripts/cds.py detect   --signals packet.json --state cds-state.json --brief --out detection.json
   python scripts/cds.py evaluate --detection detection.json --signals packet.json --state cds-state.json --out evaluation.json
   ```

8. **Write the reply after the response card**, then close the loop on the text:

   ```bash
   python scripts/cds.py respond --evaluation evaluation.json --reply-file reply.txt --signals packet.json --state cds-state.json
   ```

The reasons the sparse packet is not a degraded one: the omitted dimensions are absent
rather than zeroed, and the evaluator treats a missing dimension as *unrated* and
renormalises. A screening packet that escalates is therefore a valid evaluation input,
and nothing has to be rated twice.

`detect` does not advance the turn counter when the guard has already screened that
turn (`StateMachine.guard_ran_on_turn`), which keeps a screening and an immediate
escalation — the `guard.policy: auto` path — on one turn id. A `command 处理` in between
is a turn of its own, and the consent stays live for one turn after it.

## State machine

```text
IDLE ──on──► MONITORING ◄──────────────────────────────────────────┐
                 │ tension >= alert                                 │
                 ▼                                                  │
             DETECTED                                               │
                 │                                                  │
     ┌───────────┼────────────────┬──────────────────┐              │
     │ ambient   │ interactive    │ detect_only      │ placebo      │
     ▼           ▼                ▼                  ▼              │
 EVALUATING   AWAITING_USER   logged, back to    logged (real       │
     │           │             MONITORING        numbers kept)      │
     │           ├─ 处理 process ──► EVALUATING                    │
     │           ├─ 忽略 ignore ──► MONITORING ────────────────────┤
     │           ├─ 稍后 later ──► SUSPENDED ── expiry / novel / ──┤
     │           │                              resume              │
     │           ├─ 详情 details ──► AWAITING_USER (unchanged)      │
     │           └─ timeout ► MONITORING (outcome: no_decision) ────┤
     ▼                                                             │
 RESPONDING ──► outcome resolved | unresolved ──► MONITORING ──────┘
```

Command words are Chinese by default because `skill.language` is `zh`; the English
glosses above name the same commands, and `cds_state.COMMAND_SYNONYMS` accepts
either. Set `skill.language: "en"` for an English run.

Every exit is guaranteed. There is no state a run can be parked in:

| State | Exit conditions |
|---|---|
| `AWAITING_USER` | any command, or `await_timeout_turns` elapsing |
| `SUSPENDED` | command, `suspend_max_turns`, or novel evidence (`novelty ≥ resume_novelty`) |
| `EVALUATING` / `RESPONDING` / `DETECTED` | the stage completing, or a stale-cycle reset at the next turn |

### The guard and the state machine

A screening decision is **not** an event, and the guard deliberately does not create
one. A fabricated event id would have entered every log analysis that counted events,
and in ambient mode `ingest_detection` would have dispatched a suppressed event straight
into evaluation — the guard's silence would have produced the interruption it exists to
prevent. A screening therefore leaves the machine exactly where it was, and the guard
record states that rather than omitting it: its `state` block carries the same state in
`from` and `to`, because an absent block cannot be told apart from a bug.

A guard confirmation is answered with the **same words** as an event (处理 / 忽略 /
稍后), so `handle_command` checks a pending confirmation before the event path.
Otherwise the engine would report "no pending event" while a card asking exactly that
question is on the user's screen. 处理 records a single-use consent
(`GUARD_CONSENT_TURNS = 1`); 忽略 and 稍后 append to the dismissal memory, each with its
own decision recorded, because they are different user intents even though both
suppress re-asking.

The consent is honoured in `_dispatch` **before** the ambient branch, so a user who
consented is recorded as having consented whatever the arm says: the event carries
`user_consent: true` plus `consent_conflict_key`, and the state goes to `EVALUATING`
with the reason `guard_consent_recorded`. Reading the consent only in the interactive
branch would have dropped that record silently in the ambient arm.

### The `guard` block in the state file

The state file carries the session facts the packet cannot know:

```json
"guard": {
  "surfaces": [], "silent": [], "dismissed": [],
  "pending": null, "consent": null, "last_surface_turn": null
}
```

History is capped at 200 entries (`GUARD_HISTORY_CAP`); the full record of every
decision is in the JSONL log, so the cap costs an analysis nothing. `pending` is the
confirmation waiting to be answered and `consent` is a decision already given.

A state file written by v0.3.0 has no `guard` block. It is **repaired in place on load**
rather than rejected, because a long session must survive the upgrade; the repair is
keyed on the block being absent or not a dict, not on a version comparison.
`cds.py status` reports a `guard` summary beside the machine state — `surfaces`,
`silent_turns`, `dismissed`, `awaiting_confirmation` and `last_surface_turn` — and
重置 (*reset*) clears it. Note that `surfaces` counts every screening that cleared each
bar, and clearing every bar is not the same as asking the user: in the `detect_only` arm
and under `guard.policy: log_only` the decision is `surface` with
`next_action: log_only`, so the user step is withheld **and `guard_card` renders an
empty string** for it. Nothing is shown at all, and the `detect_only` arm still produces
its own detection card at the `detect` stage. It is a screening count, not a count of
questions asked.

### Event queue

`state.max_open_events` bounds the open set. When a threshold crossing arrives while
another event is in flight, the new event is **queued**, not lost, and the in-flight
cycle is not interrupted. On overflow the lowest-tension event that is not the
active one is marked `dropped` with outcome `overflow`; it stays in the JSONL log,
so only the in-session summary loses it, never the analysis.

## Install

```powershell
./install.ps1 -Target dsh-project      # <cwd>/.dsh/skills/cds-skill
./install.ps1 -Target dsh-user         # $DSH_HOME|~/.dsh/skills/cds-skill
./install.ps1 -Target claude-user      # ~/.claude/skills/cds-skill
./install.ps1 -Target agents-user      # $DSH_AGENTS_HOME|~/.agents/skills/cds-skill
```

```bash
./install.sh dsh-project               # same targets, POSIX
PROJECT_ROOT=/path/to/project ./install.sh dsh-project
FORCE=1 ./install.sh dsh-user          # replace an existing install
```

The directory name must be `cds-skill` **on harnesses that enforce the Agent Skills
convention** (a skill is discovered as `<root>/<name>/SKILL.md` with the frontmatter
`name` matching), which is why the installer always uses that name. DeepSeek Harness
is not one of them: its filesystem provider reads `name` from the frontmatter and
never compares it to the directory, so a bare clone placed at
`<project>/.dsh/skills/<anything>/` is discovered as `cds-skill` regardless. Use the
installer anyway if you want one layout that works everywhere.

The engine resolves `config/` and `schemas/` relative to its own `scripts/`
directory, so copy the whole bundle rather than just `SKILL.md`.

### Manual wiring, for a harness with no skill system

Put the operative part of `SKILL.md` in the system prompt, keep the bundle
somewhere readable, and have the agent:

1. write a packet per `references/prompts/detect.md`;
2. run `python scripts/cds.py run --signals packet.json`;
3. realise the `response_plan.language_acts` in its reply per
   `references/prompts/respond.md`;
4. hand the reply back with `--reply-file reply.txt` so the loop closes on the text;
5. leave logging enabled.

Skipping step 4 is allowed and is recorded as such, but it leaves the event's
outcome equal to the plan and the log will say `outcome_source: "planned"`.

With the guard — the default since v0.4.0 — the five steps keep their order with two
changes: step 1 writes the sparse packet and step 2 is the screening call,
`python scripts/cds.py guard --signals triage.json --state cds-state.json --card-only`,
after which the agent answers normally while the output is `CDS_GUARD silent`. The full
loop runs only after the user answers 处理, from that same packet extended with the
evidence ratings as in step 6 of the stealth loop above.

### Editing SKILL.md

Three constraints come from the harness contract, and breaking any of them
degrades the skill silently rather than failing loudly:

- The file must **start** with `---` on the first line, and the frontmatter must
  close with a `---` line.
- `name` must be kebab-case, and must equal the containing directory name on
  harnesses that enforce the convention (Claude Code and the Agent Skills layout
  generally). DeepSeek Harness does not check it.
- The harness renders `description` into its skill catalog and **caps it at 500
  characters**, truncating with `...`. Keep the whole description — especially any
  "not for ..." clause — inside that budget. The clause that prevents
  mis-invocation is exactly the part that truncation removes first.

`metadata` and `whenToUse` are optional and are read as plain YAML. A wrong-typed
optional value is dropped rather than fatal, but a rejected camel-case spelling or a
non-boolean invocation value drops the **entire skill** from discovery.

## Configuration

`config/cds.config.json` is the instrument. Everything that can change a reported
number or a chosen strategy lives there, and `config_hash` is recorded in every log
record.

| Key | Meaning |
|---|---|
| `skill.mode` | `off` / `detect_only` / `full` / `placebo` / `withhold_acts` |
| `skill.interaction` | `ambient` (default) / `interactive` |
| `skill.profile` | `adaptive` / `dissonance_reduction` / `mixed` / `baseline` |
| `skill.numeric_cards` | print figures or not — a Study 2 factor |
| `index.weights` | the five index weights; **must sum to 1** |
| `index.gates` | `volition_floor`, `non_dissonant_cap` |
| `thresholds` | `low` / `alert` / `high` |
| `thresholds_by_type` | per-conflict-type alert overrides |
| `channels.indeterminacy` | the ungated second channel |
| `evaluator.*` | evidence weights, cost weights, the ordered rule list |
| `consistency_gate` | self-contradiction reporting, independent of dissonance |
| `guard.*` | the screening stage: `enabled`, `policy`, `surface_threshold`, `min_opposition`, `cooldown_turns`, `dismiss_memory`, `resurface_novelty`, `max_surfaces_per_run` |
| `state.*` | queue bound and timeouts |
| `transparency.*` | which cards are shown, and in which `card_style` |
| `logging.*` | JSONL path and whether signals are embedded |

The config is **JSON, not YAML, on purpose**: it must parse identically on every
machine with no third-party library present, and it must be hashable. See
`scripts/cds_config.py`.

### The `guard` block

| Key | Meaning |
|---|---|
| `guard.enabled` | `false` removes the screening stage: no card, no question, and the full loop runs whenever `detect` is called — the v0.3.0 cadence, though not its card rendering, which `transparency.card_style` selects |
| `guard.policy` | `ask` (show the card and wait for the user's decision) / `auto` (surface and evaluate without asking — the v0.3.0 ambient cadence) / `log_only` (record the conflict and take no user step). `ask` and `auto` render a card when the decision is `surface`; `log_only` renders nothing, because the user step is withheld and a card for it would make "record, never show" a documentation claim rather than a property of the code. Only `ask` waits for an answer |
| `guard.surface_threshold` | the interruption bar. **Refused at load time if it falls below any alert threshold** |
| `guard.min_opposition` | a second floor: an event can clear the index on commitment and volition while the two claims barely conflict |
| `guard.cooldown_turns` | turns before the guard may surface again; `0` disables the cooldown |
| `guard.dismiss_memory` | whether a dismissed conflict stays down |
| `guard.resurface_novelty` | the novelty at which a dismissed conflict may return, i.e. when it is no longer the same objection restated |
| `guard.max_surfaces_per_run` | a hard ceiling on interruptions; further surfaces are logged with `surface_budget_exhausted`; `0` disables the ceiling |

**The interruption bar is not the recording bar.** `guard.surface_threshold` is refused
at config-load time by `cds_config._check_semantics` if it falls below `thresholds.alert`
or any `thresholds_by_type` value. "Is this real enough to record?" and "is this clear
enough to spend a user's attention on?" are different questions, and collapsing them
into one number makes the skill nag about every marginal event — which is how a
transparency feature becomes an annoyance feature. A marginal-but-real conflict is
exactly the case that belongs in the log and not on the screen.

The session inhibitors — cooldown, dismissal memory, the per-run ceiling — live in the
**state file**, not in the packet, because they are facts about the session rather than
about this turn's conflict.

No config check pairs `guard.enabled` with `skill.mode: off`. An inert arm wins over the
guard unconditionally, because refusing the combination would make the `off` ablation
arm unconfigurable without editing an unrelated block.

Arms override the policy: `detect_only` never asks (it may never evaluate, so it would be
asking permission for something it cannot do), and `placebo` keeps the *same cadence* as
`full` — it asks, with a content-free card — or it stops being a cadence-matched control.

### Card style

`transparency.card_style` selects the rendering. It changes what a reader sees and no
number at all:

| Value | Rendering |
|---|---|
| `plain` (default) | question-shaped headings, the two colliding claims named in words, band words beside the decimals, no identifiers a reader has to look up |
| `technical` | the v0.3.0 field-per-line rendering, identifiers included; kept because it is the artefact earlier runs were coded from |

Both styles are held to the **same** labelling rules by `tests/test_cards.py`, which runs
every labelling invariant against both: the channel is always named, a gated event is
never reported as dissonance, and the branch is always named. A style is a presentation
choice and never a licence to drop a construct label.

### Invariants enforced at load time

`cds.py` refuses to start if any of these fail. They are checks, not documentation:

- every weight vector sums to 1 within 1e-6;
- `low < alert < high`;
- **`non_dissonant_cap` is strictly below every alert threshold**, including
  per-type overrides;
- each per-type override lies between `low` and `high`;
- `channels.indeterminacy.alert < ... .high`;
- strategy rule ids are unique;
- **`guard.surface_threshold` is at or above every alert threshold**, including
  per-type overrides.

The third one is the important one. Break it and a stance the agent never chose
starts producing dissonance cards, which is exactly the construct-validity failure
the gate exists to prevent.

The last one is the same discipline applied to interruption: a bar that sits below the
recording bar would have the guard asking a user about events the engine's own index
calls silent.

## Logs

One JSONL record per stage, at `logs/cds_skill.jsonl` by default.

```json
{
  "schema_version": "0.4.0",
  "skill_version": "0.4.0",
  "index_version": "cds-ti-0.2",
  "config_hash": "sha256:...",
  "record_id": "cds_rec_...",
  "run_id": "cds_20260910_120000_ab12",
  "turn_id": 4,
  "stage": "detect",
  "ts": "2026-09-10T12:00:03Z",
  "event_id": "cds_evt_...",
  "signals_hash": "sha256:...",
  "model": { "provider": null, "name": null, "version": null, "temperature": null, "seed": null },
  "payload": { }
}
```

`record_id` and `event_id` are content-addressed, so replaying stored packets
reproduces ids rather than minting new ones. That is what makes the cross-run
identity check a test instead of a hope.

The `stage` enum carries `guard` as well, and a `guard` record is written on **every**
screening, including the silent ones. That is the point of the stage: a screening that
logged only its hits would have no denominator, so no false-negative rate could ever be
computed from it. The record validates against `schemas/guard.schema.json` and embeds
the full `DetectionResult`, itself validated against `schemas/detection.schema.json`, so
the index decomposition and the gate detail are readable straight out of one screening
line. Its `event_id` is `null`, because a screening decision is not an event, and its
embedded `state` block carries the same state in `from` and `to`. `guard_version`
(`cds-guard-0.1`) versions the screening policy separately from the skill, because the
surface bar and the index move independently.

A screening and an event it escalated to immediately share a `turn_id`; see the stealth
loop above. That is what makes "how often did a turn screen silent, and how often did it
become an event" a question the log can answer.

The `respond` record's payload is worth reading before any log analysis, because two
of its fields look alike and are not:

| Field | Meaning |
|---|---|
| `stance_update.planned_change` | what the engine intended. A function of the routed strategy string; carries no information about the reply. |
| `outcome` | the cycle's outcome, taken from the reply when one was supplied. |
| `outcome_source` | `"observed"` or `"planned"`. **Filter on this.** |
| `planned_outcome` | what the plan implied, kept alongside so the two can be compared. |
| `reply` | `{supplied, chars, sha256, observed_outcome}`; `text` only when `logging.include_reply` is on. |
| `indicators` | the coded indicator values, when a reply was supplied and `logging.include_indicators` is on. |

An analysis that treats `outcome` as behavioural without checking `outcome_source` will
be reading a config lookup for every event where nobody looked at the reply.

**Turn logging off and a run stops being evidence.** `--no-log` exists for
throwaway experiments; do not use it for anything you intend to analyse.

## The four version numbers, and why they differ

`status` prints `state_version: 0.3.0` while `VERSION` reads `0.4.0`, and that is
correct rather than stale: the identifiers version four different things, and each moves
only when its own object changes. Reading them as one number is the mistake worth
avoiding, so they are listed together here.

| Identifier | Where | Versions | Current |
|---|---|---|---|
| `skill_version` | `VERSION`, and every emitted structure and log record | the skill as a whole: cards, CLI, arms, documentation | `0.4.0` |
| `config_version` | `config/cds.config.json` | the configuration schema, i.e. the instrument's shape | `0.3.0` |
| `index_version` | `config/cds.config.json` → `index.index_version` | the tension index definition: its weights and their meaning | `cds-ti-0.2` |
| `state_version` | `STATE_VERSION` in `scripts/cds_state.py`, echoed by `status` | the on-disk state file format | `0.3.0` |

A release can move one without the others, which is the point: v0.4.0 added the `guard`
block to both the config and the state file, so `config_version` and `state_version` both
moved to `0.3.0` while `index_version` did not move at all, because the index was not
touched. A result is reproducible from `config_hash` plus `index_version` — the skill
version tells you which build produced it, not what it computed.

## Reproducing a result

1. Read `config_hash` and `signals_hash` from the log records.
2. Re-run with the matching config and the stored packet.
3. The detection and evaluation payloads must match exactly. If they do not, one of
   the hashes will differ — that is the diagnostic.
4. If the *perception* differs, that is a model-side difference, not an engine one.
   Compare with `--model`, `--temperature` and `--seed` recorded in the envelope.

## Evaluation and sensitivity

```bash
python scripts/run_scenarios.py                    # summary table
python scripts/run_scenarios.py --strict           # non-zero exit on any mismatch (CI)
python scripts/run_scenarios.py --write-report     # eval/report.md + eval/results.csv
python scripts/run_scenarios.py --family gate_boundary
python scripts/sensitivity.py --write-report       # eval/sensitivity.md
python scripts/check_arms.py --strict              # eval/arms.md
python scripts/score_signals.py --write-report     # eval/perception.md
python scripts/score_responses.py --pairs pairs/ --write-report   # act-realisation rates
python scripts/check_examples.py                   # examples/README.md's table still holds
```

All of these are run by CI on every push, so treat a local failure as a genuine
regression rather than an environment quirk. `eval/report.md`, `eval/results.csv`,
`eval/sensitivity.md`, `eval/arms.md` and `eval/perception.md` are committed; if you
change the config or the corpus, regenerate them (`--write-report`) or CI will fail
on the diff.

Which harness measures what — they are deliberately not interchangeable:

| Harness | Measures | Cannot measure |
|---|---|---|
| `run_scenarios.py` | does the engine compute what the specification says? | whether the ratings, weights or thresholds are *right* |
| `sensitivity.py` | how load-bearing are the weights and thresholds? | rater variance; no sweep here moves a rating |
| `check_arms.py` | does each profile realise the repertoire it names? | whether a model follows the plan |
| `score_signals.py` | do model-produced packets agree with gold packets, and what does the disagreement cost at the decision level? | whether the gold packets are correct |
| `score_responses.py` | did the reply realise the planned acts, and did it stay inside the constraints? | whether the planned acts were the right ones |

The first three are deterministic and CI-able. The last two need a model in the loop,
so CI runs them in their "nothing to score yet" mode and they are run by hand once
data exists.

## Troubleshooting

| Symptom | Diagnosis |
|---|---|
| No card appeared | Read the guard record's `reasons` first — since v0.4.0 that is the common cause, and each value is glossed under "Screenings that stayed silent" below. If the guard surfaced, check the gate (`volition_self` below 0.30 caps the index), then `thresholds_by_type` |
| `evaluate` refuses to run | Expected in `off`, `detect_only` and `placebo`; those arms exist to withhold the stage. `withhold_acts` runs it |
| `run` refuses to run | `run` is the ambient one-shot loop; with `interaction: interactive` use the four calls |
| `indicators` missing from a respond record | No `--reply-file` was given, or `logging.include_indicators` is off |
| An adaptive run produced `trivialize` | Should be impossible since v0.3.0; run `check_arms.py` and report it |
| State looks stuck | It is not — run `status`. `AWAITING_USER` times out; stale cycles reset |
| Numbers differ across runs | Compare `config_hash` first, then `signals_hash`, then the model block |
| `note: no --state given` on stderr | Preconditions could not be checked; pass `--state` for the recorded loop |
| Config refused at startup | A load-time invariant failed; the message names it |
| `LexiconError: ... has keys that are not lexicon categories` | A lexicon file has a misspelled key. Fix the key (the message lists the valid ones); metadata keys must start with `_`. This is deliberate: the old behaviour fell back to the built-in default and measured with an instrument nobody had edited |
| Every indicator comes out zero after editing a lexicon | The file failed to parse (a stray comma returns the built-in default silently) — check it with `python -c "import json;json.load(open('config/lexicon.zh.json',encoding='utf-8'))"` |
| A conditional fires where the text has no conditional | A short lexeme is matching inside a longer host word. Add the host to the `blockers` category in the lexicon; see `references/indicators.md`, "Editing a lexicon" |
| Chinese cards are mojibake | Console encoding. The CLI reconfigures its streams to UTF-8; if wrapped, set `PYTHONIOENCODING=utf-8` |
| Tests fail writing to a temp directory | The test suite uses a repo-local scratch dir precisely to avoid this; if it persists, check permissions on `tests/.scratch/` |
| `CDS_GUARD silent` on a turn you expected to be interrupted | Working as designed — the guard holds back far more than `detect` does. The `reasons` field says which bar held it; see below |
| A card appeared when the user did not want one | `guard.policy: auto` surfaces and evaluates without asking (that is the v0.3.0 ambient cadence). Use `ask` to require a decision, or `log_only` to record without asking. The `placebo` arm asks for the same reason `full` does: the cadence is the control, so it cannot be made quieter without ceasing to be a control |
| A confirmation appears to have been ignored — the user answered 处理 and nothing happened | The consent is single-use and expires after one further turn (`GUARD_CONSENT_TURNS = 1`). If the user answered a card that was shown several turns earlier, the consent has lapsed by design and the card has to be answered again. `status` shows `guard.awaiting_confirmation` and `guard.last_surface_turn` |
| A study meant to measure the screening stage but every screening is `arm_inert` | `skill.mode` is `off`, and an inert arm wins over the guard unconditionally — deliberately, so the `off` arm stays configurable without editing the `guard` block. `selftest` warns about exactly this combination before the run starts |
| `guard.enabled: false` in a config nobody remembers editing | `selftest` warns that the guard is disabled, which means no screening happens at all and the full loop runs whenever `detect` is called. That is v0.3.0 behaviour, restored on purpose as a control |
| A config is refused for its `guard.surface_threshold` | The bar sits below `thresholds.alert` or below a `thresholds_by_type` value. The message names both numbers. This is the interruption-bar invariant, not a range check |

### Screenings that stayed silent

Nine `reasons` values hold a screening back, and they are checked in the order below.
The first failure is the recorded reason, so a single value says what failed first, not
what was the only thing wrong. The three session inhibitors are checked last and only
after the packet has cleared every content bar, so a screening they hold back is always
a clear conflict and never a marginal one. On the `surface` path the recorded reason
instead names the policy that released the card: `policy_ask_user`,
`policy_auto_escalate` or `arm_withholds_the_user_step`.

| `reasons` value | What it means |
|---|---|
| `arm_inert` | `skill.mode: off`, or `guard.enabled: false`. The record is still written and still embeds the computed detection, but no policy is applied and nothing downstream runs |
| `no_conflict_perceived` | `relation.type` is `none`: the packet itself says nothing clashed |
| `gated_not_dissonance` | the volition floor capped the index and the channel is not `indeterminacy`. A conflict against a stance the agent did not freely choose is not dissonance, and the guard does not ask a user about a construct it has just declined to count |
| `below_alert_threshold` | the index is below `thresholds.alert` (or the applicable per-type override). Real enough to log, not real enough to record as an event |
| `below_surface_threshold` | above every alert threshold but below `guard.surface_threshold`. This is the marginal-but-real case: recorded, deliberately not shown |
| `opposition_below_floor` | the index cleared, but `opposition` is below `guard.min_opposition`: the two claims barely conflict |
| `cooldown_active` | the guard surfaced within `guard.cooldown_turns` turns. The user has just been interrupted |
| `dismissed_by_user` | the same conflict (`conflict_key`, which is keyed on the claim pair rather than the event id) was already answered 忽略 or 稍后, and `novelty` is below `guard.resurface_novelty`. It returns when the objection stops being the same objection restated |
| `surface_budget_exhausted` | `guard.max_surfaces_per_run` interruptions have already been made in this run. The per-run ceiling is a hard cap and it is logged rather than silently applied |

Read them with `--json` or straight out of the `guard` log records. `tests/test_guard.py`
exercises each of these conditions, the two config refusals, the state-file upgrade and
the consent path.
