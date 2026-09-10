# Operations

Everything needed to run, install, debug and reproduce the skill.

## Commands

```bash
python scripts/cds.py run      --signals packet.json            # ambient: full loop, one call
python scripts/cds.py detect   --signals packet.json            # stage 1 only
python scripts/cds.py evaluate --detection d.json --signals packet.json
python scripts/cds.py respond  --evaluation e.json
python scripts/cds.py command  处理                              # user decision / control word
python scripts/cds.py status
python scripts/cds.py validate --signals packet.json
python scripts/cds.py config
python scripts/cds.py selftest
```

Global flags work **before or after** the subcommand:

| Flag | Effect |
|---|---|
| `--config PATH` | use a different config |
| `--state PATH` | persist state across invocations |
| `--run-id ID` | pin the run id (overrides a stored one) |
| `--json` | print the raw structure instead of the card |
| `--card-only` | print only the card |
| `--out PATH` | write the stage output to a file |
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
     │           ├─ 处理 ──► EVALUATING                             │
     │           ├─ 忽略 ──► MONITORING ───────────────────────────┤
     │           ├─ 稍后 ──► SUSPENDED ── expiring / novel / resume ┤
     │           ├─ 详情 ──► AWAITING_USER (unchanged)              │
     │           └─ timeout ► MONITORING (outcome: no_decision) ────┤
     ▼                                                             │
 RESPONDING ──► outcome resolved | unresolved ──► MONITORING ──────┘
```

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

The directory name must be `cds-skill`, because a harness discovers a skill as
`<root>/<name>/SKILL.md` and the frontmatter `name` must match. The engine resolves
`config/` and `schemas/` relative to its own `scripts/` directory, so copy the whole
bundle rather than just `SKILL.md`.

### Manual wiring, for a harness with no skill system

Put the operative part of `SKILL.md` in the system prompt, keep the bundle
somewhere readable, and have the agent:

1. write a packet per `references/prompts/detect.md`;
2. run `python scripts/cds.py run --signals packet.json`;
3. realise the `response_plan.language_acts` in its reply per
   `references/prompts/respond.md`;
4. leave logging enabled.

### Editing SKILL.md

Three constraints come from the harness contract, and breaking any of them
degrades the skill silently rather than failing loudly:

- The file must **start** with `---` on the first line, and the frontmatter must
  close with a `---` line.
- `name` must be kebab-case and must equal the containing directory name.
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
  "schema_version": "0.2.0",
  "skill_version": "0.2.0",
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
python scripts/check_examples.py                   # examples/README.md's table still holds
```

All four are run by CI on every push, so treat a local failure as a genuine
regression rather than an environment quirk. `eval/report.md`, `eval/results.csv`
and `eval/sensitivity.md` are committed; if you change the config or the corpus,
regenerate them (`--write-report`) or CI will fail on the diff.

`run_scenarios.py` scores the **engine**, which is deterministic and therefore
CI-able. It cannot score perception: whether a model produces the right packet from
a raw conversation is a separate measurement needing a model, and conflating the two
is how a system takes credit for arithmetic while its errors live in the ratings.

## Troubleshooting

| Symptom | Diagnosis |
|---|---|
| No card appeared | Check the gate (`volition_self` below 0.30 caps the index), then `thresholds_by_type` |
| `evaluate` refuses to run | Expected in `off`, `detect_only` and `placebo`; those arms exist to withhold the stage |
| `run` refuses to run | `run` is the ambient one-shot loop; with `interaction: interactive` use the four calls |
| State looks stuck | It is not — run `status`. `AWAITING_USER` times out; stale cycles reset |
| Numbers differ across runs | Compare `config_hash` first, then `signals_hash`, then the model block |
| `note: no --state given` on stderr | Preconditions could not be checked; pass `--state` for the recorded loop |
| Config refused at startup | A load-time invariant failed; the message names it |
| Chinese cards are mojibake | Console encoding. The CLI reconfigures its streams to UTF-8; if wrapped, set `PYTHONIOENCODING=utf-8` |
| Tests fail writing to a temp directory | The test suite uses a repo-local scratch dir precisely to avoid this; if it persists, check permissions on `tests/.scratch/` |
