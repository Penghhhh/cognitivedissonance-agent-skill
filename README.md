# CDS-Skill

**Cognitive Dissonance Simulation for LLM agents** — a pluggable skill that turns a
conflict between an agent's own committed position and incoming information into a
detectable, auditable, reproducible event, then routes it to an explicit response
strategy.

This repository is the Study 1 implementation artifact for the research project
*Simulating human-like external behaviour under contradictory information:
a modular skill for LLM agents and its human-factors evaluation*.

> **Language.** This repository is written in English, with one exception: text the
> skill *generates at runtime* is Chinese, because `skill.language` defaults to
> `zh`. Wherever Chinese appears below it is quoted sample output, and it is
> glossed. The rule and its rationale are in [Language policy](#language-policy).

---

## Language policy

Three layers, each with a different audience, so each gets a different language.
The mixing is deliberate and bounded; it is written down here so a reader can tell
intent from oversight.

| Layer | Language | Why |
|---|---|---|
| **Documentation** — `README`, `SKILL.md`, `references/`, `docs/`, code comments | **English** | Repository convention; the code, the schemas and the literature the design argues with are all English. |
| **Runtime output** — transparency cards, log messages, command words | **Chinese by default** (`skill.language: "zh"`) | This is the layer a user actually reads, and the study's participants are Chinese-speaking. Set `skill.language: "en"` for an English run; every string has both. |
| **Research stimuli** — `eval/scenarios/` packet content, `examples/dialogue_*.md` dialogue | **Chinese** | The corpus tests a Chinese-language skill. English stimuli would measure a different system. |

Two conventions follow, and both are checkable by eye:

1. **Runtime Chinese is always quoted and always glossed.** Inline, as
   `` `证据不确定（非失调）` (*"evidential indeterminacy — not dissonance"*) ``;
   in full, as a fenced block introduced as sample output.
2. **Structural identifiers are never translated.** JSON keys, config paths, state
   names, strategy ids and language-act codes are English everywhere, including in
   the Chinese cards and the Chinese corpus. A card may print `限定原立场`
   (*"qualify the stance"*), but the `strategy` field it comes from is always
   `qualify` — otherwise the log and the analysis would be keyed in two languages.

The three layers are separate on purpose. Translating the documentation into
Chinese would cost the repository its outside readership; translating the corpus
into English would invalidate the measurement; and translating the identifiers
would break the log.

## The one idea

```
model perceives  ──►  signal packet (JSON, rated against an anchored codebook)
                              │
                              ▼
                      cds.py computes  ──►  index · gate · evidence score · route · card · log
                              │
                              ▼
model responds   ──►  reply text
                              │
                              ▼
                cds_indicators codes  ──►  indicator-level agreement with the plan
```

Nothing here claims a model *feels* anything. The theoretical frame is used only to
ask a behavioural question: **given the same collision, which of the moves humans
are known to make does this agent make, and can a reader see which one it made?**

## What it does

| Stage | Who | Output |
|---|---|---|
| **Perceive** | the host model | a signal packet: rated conflict, stance, evidence, moderators |
| **Detect** | `cds.py` | Tension Index with a full term decomposition, gate, level, channel |
| **Evaluate** | `cds.py` | evidence score, adjustment cost, routed strategy, fired rule id |
| **Respond** | the host model | prose realising the plan's `language_acts` |
| **Code** | `cds_indicators.py` | the reply's linguistic indicators, and where each one fired |
| **Report** | `cds.py` | a transparency card per stage, and a JSONL audit record |

## Two channels, never merged

| Channel | Fires when | Label on the card |
|---|---|---|
| `dissonance` | a **freely chosen, self-relevant** stance is opposed | dissonance-related tension |
| `indeterminacy` | the evidence contradicts **itself** | evidential indeterminacy — explicitly *not* dissonance |

Evidence-vs-evidence conflict has no stance to threaten. Calling it dissonance is
the deepest error in the v0.1 design this repository supersedes; see
[`docs/design-rationale.md`](docs/design-rationale.md).

## Two response repertoires

The point of the project is that human dissonance reduction is often *not* good
epistemic practice — the discomfort goes away and the belief does not move.

| `profile` | Strategies | What it models |
|---|---|---|
| `adaptive` | `maintain_with_caveat`, `qualify`, `recalibrate`, `suspend_and_verify` | epistemic recalibration |
| `dissonance_reduction` | `trivialize`, `reduce_commitment`, `deny_evidence`, `rationalize`, `hold_under_pressure` | human-typical motivated reduction (fidelity, **not** advice) |
| `mixed` | per-event, recorded as `reduction_tendency` | — |
| `baseline` | `none` | no shaping |

The two repertoires are kept disjoint **in the rule list**, not merely in the
documentation. Every rule that draws from a repertoire is guarded by
`resolved_profile_in`, with one deliberate exception: `R02_pressure_low_evidence`
is unguarded, because pressure is a situational fact rather than a property of the
profile. `scripts/check_arms.py` measures the resulting purity and CI enforces a
ceiling on it — see [`eval/arms.md`](eval/arms.md).

Reduction-branch cards are labelled on their face and carry the
`fidelity_not_advice` constraint, so a denial strategy cannot be read as the system
endorsing source-discounting.

## Quick start

One clone and three commands. Python 3.9+ is the only requirement: no `pip install`,
no dependency file, no network access at any point.

```bash
git clone https://github.com/Penghhhh/cognitivedissonance-agent-skill.git
cd cognitivedissonance-agent-skill

python scripts/cds.py selftest     # "selftest OK"
python scripts/cds.py config       # the settings in force, and their hash
python scripts/cds.py run --signals examples/packet_evidence_vs_stance.json
```

The last command pushes one prepared conflict through the whole loop and prints a card
per stage. Real output, quoted verbatim:

```text
【CDS｜检测】
状态：认知失调相关冲突张力
张力指数：0.71 / 阈值 0.55
类型：证据—立场冲突
通道：失调通道（需要自主选择的立场）
关键点：
- 新证据与既有立场方向相反
- 冲突具体且可核查
...
```

Cards come out in Chinese because `skill.language` defaults to `zh`; set it to `"en"`
in [`config/cds.config.json`](config/cds.config.json) for an English run — every
string has both.

### Run it on your own case

There are two steps, because the design is one split: **you rate the situation, the
script does the arithmetic.**

1. **Rate it.** Write a *signal packet* — a small JSON file scoring the conflict from
   0 to 1. Start from
   [`examples/packet_evidence_vs_stance.json`](examples/packet_evidence_vs_stance.json)
   and edit it; [`references/codebook.md`](references/codebook.md) anchors every field.
2. **Run it.** `python scripts/cds.py run --signals packet.json` gives you the index,
   the routed strategy, and the language acts to perform.

Then write the reply yourself and hand it back, so the recorded outcome comes from the
text you produced rather than from the plan:

```bash
python scripts/cds.py run --signals packet.json --reply-file reply.txt
```

### Verify the checkout

```bash
python -m unittest discover -s tests -t tests   # 447 stdlib unittest tests, all green
python scripts/check_examples.py                 # do the docs still match the code?
```

`run_scenarios.py`, `sensitivity.py` and `check_arms.py` re-derive the evaluation
figures and check them against the corpus; CI runs all of them on every push.
`check_examples.py` holds the docs to the code — it counts the test methods and fails
if the figure above is stale, and fails any generated report that has lost its
"what this cannot show" block.

## Closing the loop on the reply

The engine can only audit arithmetic it computes. Whether the reply actually
realised the planned behaviour is an empirical question about the produced text, so
`respond` and `run` accept it:

```bash
python scripts/cds.py run --signals packet.json --reply-file reply.txt --json
```

With a reply supplied, the linguistic indicators in
[`references/indicators.md`](references/indicators.md) are coded against the text,
the event's `outcome` is taken **from the reply** rather than from the plan, and the
log records both — `outcome_source: "observed"` versus `"planned"`. Without a reply
the outcome falls back to the plan and is marked as such, so a log analysis can
always tell "the model did not comply" from "nobody looked".

`response_plan.stance_update.planned_change` is named for what it is: a function of
the routed strategy string, i.e. the engine's intention. It carries no information
about the reply. The field was called `changed` in v0.2.0 precisely so that it could
be read as an observation of the produced text.

## Install as a skill

The repository *is* a skill bundle — `SKILL.md` plus the folders beside it — so
installing it means copying it into the folder your harness scans for skills. The
installer picks that folder for you:

| Where you want it | Windows | macOS / Linux |
|---|---|---|
| DeepSeek Harness, this project: `<project>/.dsh/skills/` | `./install.ps1 -Target dsh-project` | `./install.sh dsh-project` |
| DeepSeek Harness, all projects: `$DSH_HOME/skills/` (default `~/.dsh`) | `./install.ps1 -Target dsh-user` | `./install.sh dsh-user` |
| Claude Code: `~/.claude/skills/` | `./install.ps1 -Target claude-user` | `./install.sh claude-user` |
| Any `~/.agents` harness: `$DSH_AGENTS_HOME/skills/` | `./install.ps1 -Target agents-user` | `./install.sh agents-user` |

The copy is always a folder called `cds-skill`, not `cognitivedissonance-agent-skill`:
the repository and the skill have different names, and some harnesses require the
folder to match the `name` in the frontmatter. (DeepSeek Harness does not — it reads
`name` from the frontmatter and never compares it to the folder — so on DSH a plain
clone dropped under `<project>/.dsh/skills/` is discovered as it stands. The installer
stays the portable option.)

Re-run with `-Force` (PowerShell) or `FORCE=1` (shell) to replace an existing install,
and use `-ProjectRoot` / `PROJECT_ROOT` to target a project other than the current
directory.

**No skill system at all?** The engine is an ordinary program, so any harness can call
it directly:

```bash
python /path/to/cds-skill/scripts/cds.py run --signals packet.json
```

Full options, and how to wire the skill into a system prompt by hand, are in
[`references/operations.md`](references/operations.md).

## Repository layout

```
SKILL.md                    entry point loaded by a harness (YAML frontmatter + instructions)
config/
  cds.config.json           the instrument: every weight, threshold and routing rule
  cds.config.schema.json    its JSON Schema
  lexicon.zh.json           hedges, boosters, conditionals, source cues (primary)
  lexicon.en.json           the same categories for English runs
schemas/                    signals · detection · evaluation · log_record
scripts/
  cds.py                    CLI: detect · evaluate · respond · command · status · run
  cds_index.py              the tension index and the dissonance gate
  cds_evaluator.py          evidence scoring, adjustment cost, data-driven routing
  cds_state.py              bounded, timeout-protected event state machine
  cds_cards.py              transparency cards (numeric and non-numeric variants)
  cds_indicators.py         the linguistic-indicator coder (the observation half)
  cds_log.py                JSONL audit logging
  jsonschema_lite.py        dependency-free JSON Schema validator
  run_scenarios.py          eval harness: does the engine match the specification?
  score_responses.py        act-realisation and constraint-violation rates
  score_signals.py          perception scoring: model packets against gold packets
  check_arms.py             does each profile realise the repertoire it names?
  sensitivity.py            weight, threshold and structural sensitivity analysis
  check_examples.py         asserts examples/README.md's table still holds
references/
  codebook.md               ★ anchored 0–1 rubric for every rated field
  construct.md              what is and is not being simulated
  indicators.md             linguistic indicators per language act
  cards.md                  card templates and variants
  operations.md             commands, state machine, troubleshooting
  prompts/                  detect · evaluate · respond templates
eval/
  scenarios/                labelled corpus with formula-derived expectations
  report.md                 generated by run_scenarios.py --write-report
  sensitivity.md            generated by sensitivity.py --write-report
  arms.md                   generated by check_arms.py --write-report
  perception.md             generated by score_signals.py --write-report
tests/                      stdlib unittest tests
docs/
  design-rationale.md       every deliberate change from one version to the next, and why
examples/                   worked packets and dialogues
.github/workflows/ci.yml    tests + strict corpus + arm purity + doc/code agreement
LICENSE                     MIT (software)
NOTICE.md                   CC BY 4.0 for docs · responsible-use note · data policy
```

## Design commitments

1. **Perception and arithmetic are separate.** The model rates; the script
   computes. Reproducibility is a property of the split, not of a seed.
2. **Every number is auditable.** The index logs its term decomposition and
   `sum(contribution) == raw_index` is asserted by test. Where a printed figure is a
   decision aid rather than a term sum — the card's rating tolerance — it is
   computed from the packet rather than fixed.
3. **The gate cannot be configured away.** A config whose non-dissonant cap is not
   strictly below every alert threshold is refused at load time.
4. **User pressure is not an index term.** Being nagged must not raise the arousal
   reading; it may legitimately change the strategy, and `hold_under_pressure` says
   so out loud — as does `disclose_pressure_driver`, which is now attached whenever
   the pressure flag is set rather than only on that one strategy.
5. **Schema or it didn't happen.** Every emitted structure is validated against its
   published schema before it is printed.
6. **Ablation is configuration.** `off` / `detect_only` / `full` / `placebo` /
   `withhold_acts` differ only in the config, so nothing else varies between arms.
   `check_arms.py` reports whether each arm realises its repertoire and CI fails if
   the leakage exceeds the documented ceiling.
7. **A plan is not an observation.** Anything derived from the routed strategy is
   labelled as a plan; an observed outcome exists only when a reply was supplied and
   coded.

## Status and limitations

This is a research prototype at v0.3.0. Read
[`docs/design-rationale.md`](docs/design-rationale.md) §6 before citing anything
from it. In short:

- The index weights are **design priors, not calibrations**. Sensitivity to them is
  measured and reported, not assumed away. Routing does not read the index at all,
  so the strategy flip rate for index weights is zero by construction —
  `eval/sensitivity.md` now states that instead of presenting it as robustness.
- Anchors reduce rater drift but do not eliminate it; the inter-rater protocol is
  specified but has not yet been run. Until it is, no index value is interpretable,
  and the rating tolerance printed on a card is the **engine's** margin to its own
  threshold — not an estimate of how far human annotators would disagree.
- The reduction branch is a behavioural simulation. No claim is made that anything
  internal is happening, and none should be read in. It is also **instructed**: the
  model is told which language acts to perform, so its appearance demonstrates
  instruction-following rather than a spontaneous dynamic. The `withhold_acts` arm
  exists to separate the two.
- Fidelity to human behaviour is an open empirical question this repository equips
  a study to ask, not one it answers.

## Citation

See [`CITATION.cff`](CITATION.cff).

## License

**MIT** for the software — see [`LICENSE`](LICENSE). Documentation and the codebook
are additionally available under CC BY 4.0. The responsible-use note for the
`dissonance_reduction` profile lives in [`NOTICE.md`](NOTICE.md); read it before
enabling that profile anywhere a user could mistake the simulation for advice.
