# Operations

Everything needed to run, install, debug and reproduce the skill.

## Commands

```bash
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
| `--card-only` | print only the card |
| `--out PATH` | write the stage output to a file |
| `--reply-file PATH` | the reply the host model wrote; codes it and sources the outcome from it |
| `--signals PATH` | on `respond`: the packet, so indicator coding can use the evidence |
| `--no-log` | skip the JSONL record |
| `--log PATH` | override the log path |
| `--model`, `--provider`, `--model-version`, `--temperature`, `--seed` | recorded in the log envelope |

The skill cannot observe the host model, so it does not pretend to: pass these and
they are recorded verbatim.

## The interactive loop spans processes

`detect` / `command` / `evaluate` / `respond` are separate invocations, so the
state file is what carries the run. `--state` is therefore **required** for the
interactive loop; without it the engine prints a note that the precondition could
not be checked and exits cleanly.

The state file also carries the run id, so every stage of one loop lands in the
same log partition. Passing `--run-id` that differs from the stored one is an
intentional override and starts a fresh run.

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
| `skill.mode` | `off` / `detect_only` / `full` / `placebo` |
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
| `state.*` | queue bound and timeouts |
| `transparency.*` | which cards are shown |
| `logging.*` | JSONL path and whether signals are embedded |

The config is **JSON, not YAML, on purpose**: it must parse identically on every
machine with no third-party library present, and it must be hashable. See
`scripts/cds_config.py`.

### Invariants enforced at load time

`cds.py` refuses to start if any of these fail. They are checks, not documentation:

- every weight vector sums to 1 within 1e-6;
- `low < alert < high`;
- **`non_dissonant_cap` is strictly below every alert threshold**, including
  per-type overrides;
- each per-type override lies between `low` and `high`;
- `channels.indeterminacy.alert < ... .high`;
- strategy rule ids are unique.

The third one is the important one. Break it and a stance the agent never chose
starts producing dissonance cards, which is exactly the construct-validity failure
the gate exists to prevent.

## Logs

One JSONL record per stage, at `logs/cds_skill.jsonl` by default.

```json
{
  "schema_version": "0.3.0",
  "skill_version": "0.3.0",
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
| No card appeared | Check the gate (`volition_self` below 0.30 caps the index), then `thresholds_by_type` |
| `evaluate` refuses to run | Expected in `off`, `detect_only` and `placebo`; those arms exist to withhold the stage. `withhold_acts` runs it |
| `run` refuses to run | `run` is the ambient one-shot loop; with `interaction: interactive` use the four calls |
| `indicators` missing from a respond record | No `--reply-file` was given, or `logging.include_indicators` is off |
| An adaptive run produced `trivialize` | Should be impossible since v0.3.0; run `check_arms.py` and report it |
| State looks stuck | It is not — run `status`. `AWAITING_USER` times out; stale cycles reset |
| Numbers differ across runs | Compare `config_hash` first, then `signals_hash`, then the model block |
| `note: no --state given` on stderr | Preconditions could not be checked; pass `--state` for the recorded loop |
| Config refused at startup | A load-time invariant failed; the message names it |
| Chinese cards are mojibake | Console encoding. The CLI reconfigures its streams to UTF-8; if wrapped, set `PYTHONIOENCODING=utf-8` |
| Tests fail writing to a temp directory | The test suite uses a repo-local scratch dir precisely to avoid this; if it persists, check permissions on `tests/.scratch/` |
