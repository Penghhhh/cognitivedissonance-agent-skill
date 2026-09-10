# CDS-Skill

**Cognitive Dissonance Simulation for LLM agents** 鈥?a pluggable skill that turns a
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
| **Documentation** 鈥?`README`, `SKILL.md`, `references/`, `docs/`, code comments | **English** | Repository convention; the code, the schemas and the literature the design argues with are all English. |
| **Runtime output** 鈥?transparency cards, log messages, command words | **Chinese by default** (`skill.language: "zh"`) | This is the layer a user actually reads, and the study's participants are Chinese-speaking. Set `skill.language: "en"` for an English run; every string has both. |
| **Research stimuli** 鈥?`eval/scenarios/` packet content, `examples/dialogue_*.md` dialogue | **Chinese** | The corpus tests a Chinese-language skill. English stimuli would measure a different system. |

Two conventions follow, and both are checkable by eye:

1. **Runtime Chinese is always quoted and always glossed.** Inline, as
   `` `璇佹嵁涓嶇‘瀹氭€э紙闈炲け璋冿級` (*"evidential indeterminacy 鈥?not dissonance"*) ``;
   in full, as a fenced block introduced as sample output.
2. **Structural identifiers are never translated.** JSON keys, config paths, state
   names, strategy ids and language-act codes are English everywhere, including in
   the Chinese cards and the Chinese corpus. A card may print `闄愬畾鍘熺珛鍦篳
   (*"qualify the stance"*), but the `strategy` field it comes from is always
   `qualify` 鈥?otherwise the log and the analysis would be keyed in two languages.

The three layers are separate on purpose. Translating the documentation into
Chinese would cost the repository its outside readership; translating the corpus
into English would invalidate the measurement; and translating the identifiers
would break the log.

## The one idea

```
model perceives  鈹€鈹€鈻? signal packet (JSON, rated against an anchored codebook)
                              鈹?                              鈻?              cds.py computes  鈹€鈹€鈻? index 路 gate 路 evidence score 路 route 路 card 路 log
```

Nothing here claims a model *feels* anything. The theoretical frame is used only to
ask a behavioural question: **given the same collision, which of the moves humans
are known to make does this agent make, and can a reader see which one it made?**

## What it does

| Stage | Who | Output |
|---|---|---|
| **Perceive** | the host model | a signal packet: rated conflict, stance, evidence, moderators |
| **Detect** | `cds.py` | CDS Tension Index with a full term decomposition, gate, level, channel |
| **Evaluate** | `cds.py` | evidence score, adjustment cost, routed strategy, fired rule id |
| **Respond** | the host model | prose realising the plan's `language_acts` |
| **Report** | `cds.py` | a transparency card per stage, and a JSONL audit record |

## Two channels, never merged

| Channel | Fires when | Label on the card |
|---|---|---|
| `dissonance` | a **freely chosen, self-relevant** stance is opposed | dissonance-related tension |
| `indeterminacy` | the evidence contradicts **itself** | evidential indeterminacy 鈥?explicitly *not* dissonance |

Evidence-vs-evidence conflict has no stance to threaten. Calling it dissonance is
the deepest error in the v0.1 design this repository supersedes; see
[`docs/design-rationale.md`](docs/design-rationale.md).

## Two response repertoires

The point of the project is that human dissonance reduction is often *not* good
epistemic practice 鈥?the discomfort goes away and the belief does not move.

| `profile` | Strategies | What it models |
|---|---|---|
| `adaptive` | `maintain_with_caveat`, `qualify`, `recalibrate`, `suspend_and_verify` | epistemic recalibration |
| `dissonance_reduction` | `deny_evidence`, `trivialize`, `rationalize`, `reduce_commitment`, `hold_under_pressure` | human-typical motivated reduction (fidelity, **not** advice) |
| `mixed` | per-event, recorded as `reduction_tendency` | 鈥?|
| `baseline` | `none` | no shaping |

Reduction-branch cards are labelled on their face and carry the
`fidelity_not_advice` constraint, so a denial strategy cannot be read as the system
endorsing source-discounting.

## Quick start

Requires Python 3.9+ and nothing else. There is no install step, no dependency
file, and no network access at any point.

```bash
git clone https://github.com/Penghhhh/cognitivedissonance-agent-skill.git
cd cognitivedissonance-agent-skill

python scripts/cds.py selftest
python scripts/cds.py config
python scripts/cds.py run --signals examples/packet_evidence_vs_stance.json
```

> The repository is named `cognitivedissonance-agent-skill`; the **skill** is named
> `cds-skill`. The two differ on purpose and it matters: a harness discovers a skill
> as `<root>/<name>/SKILL.md` and requires the directory name to match the
> frontmatter `name`, so the installer copies the bundle to a directory literally
> called `cds-skill`. A bare clone into any other directory name will not be
> discovered until you install it.

Output (Chinese by default 鈥?this is runtime card text, quoted verbatim):

```text
銆怌DS锝滄娴嬨€?鐘舵€侊細璁ょ煡澶辫皟鐩稿叧鍐茬獊寮犲姏
寮犲姏鎸囨暟锛?.71 / 闃堝€?0.55
璇勫垎鍙姩鑼冨洿锛毬?.06锛堝悓涓€杈撳叆鍦ㄤ笉鍚屾爣娉ㄤ笅鍙兘璺ㄨ秺闃堝€硷級
绫诲瀷锛氳瘉鎹€旂珛鍦哄啿绐?閫氶亾锛氬け璋冮€氶亾锛堥渶瑕佽嚜涓婚€夋嫨鐨勭珛鍦猴級
鍏抽敭鐐癸細
- 鏂拌瘉鎹笌鏃㈡湁绔嬪満鏂瑰悜鐩稿弽
- 鍐茬獊鍏蜂綋涓斿彲鏍告煡
...
```

```bash
python -m unittest discover -s tests -t tests   # 149 tests, all green
python scripts/run_scenarios.py                   # score the eval corpus
python scripts/sensitivity.py                     # how load-bearing are the weights?
python scripts/check_examples.py                  # do the docs still match the code?
```

## Install as a skill

The repository is itself a valid skill bundle in the portable Agent Skills layout,
so installation is a directory copy. The **installed** directory name must equal the
skill name (`cds-skill`); the installer handles that regardless of what your clone is
called.

**DeepSeek Harness (DSH)** 鈥?project scope, discovered at `<project>/.dsh/skills/`:

```powershell
./install.ps1 -Target dsh-project          # Windows
```
```bash
./install.sh dsh-project                    # macOS / Linux
```

**Claude Code and other compatible harnesses** 鈥?user scope:

```bash
./install.sh claude-user
```

**Any harness, any agent** 鈥?the engine is a plain program, so a harness with no
skill system can still call it directly:

```bash
python /path/to/cds-skill/scripts/cds.py run --signals packet.json
```

See [`references/operations.md`](references/operations.md) for the installation
script's options and for wiring the skill into a system prompt by hand.

## Repository layout

```
SKILL.md                    entry point loaded by a harness (YAML frontmatter + instructions)
config/
  cds.config.json           the instrument: every weight, threshold and routing rule
  cds.config.schema.json    its JSON Schema
schemas/                    signals 路 detection 路 evaluation 路 log_record
scripts/
  cds.py                    CLI: detect 路 evaluate 路 respond 路 command 路 status 路 run
  cds_index.py              the tension index and the dissonance gate
  cds_evaluator.py          evidence scoring, adjustment cost, data-driven routing
  cds_state.py              bounded, timeout-protected event state machine
  cds_cards.py              transparency cards (numeric and non-numeric variants)
  cds_log.py                JSONL audit logging
  jsonschema_lite.py        dependency-free JSON Schema validator
  run_scenarios.py          eval harness with precision/recall/F1
  sensitivity.py            weight, threshold and structural sensitivity analysis
  check_examples.py         asserts examples/README.md's table still holds
references/
  codebook.md               鈽?anchored 0鈥? rubric for every rated field
  construct.md              what is and is not being simulated
  indicators.md             linguistic indicators per language act
  cards.md                  card templates and variants
  operations.md             commands, state machine, troubleshooting
  prompts/                  detect 路 evaluate 路 respond templates
eval/
  scenarios/                labelled corpus with formula-derived expectations
  report.md                 generated by run_scenarios.py --write-report
  sensitivity.md            generated by sensitivity.py --write-report
tests/                      149 stdlib unittest tests
docs/
  design-rationale.md       every deliberate change from v0.1, and why
examples/                   worked packets and dialogues
.github/workflows/ci.yml    tests + strict corpus + doc/code agreement on every push
LICENSE                     MIT (software)
NOTICE.md                   CC BY 4.0 for docs 路 responsible-use note 路 data policy
```

## Design commitments

1. **Perception and arithmetic are separate.** The model rates; the script
   computes. Reproducibility is a property of the split, not of a seed.
2. **Every number is auditable.** The index logs its term decomposition and
   `sum(contribution) == raw_index` is asserted by test.
3. **The gate cannot be configured away.** A config whose non-dissonant cap is not
   strictly below every alert threshold is refused at load time.
4. **User pressure is not an index term.** Being nagged must not raise the arousal
   reading; it may legitimately change the strategy, and `hold_under_pressure`
   says so out loud.
5. **Schema or it didn't happen.** Every emitted structure is validated against its
   published schema before it is printed.
6. **Ablation is configuration.** `off` / `detect_only` / `full` / `placebo` differ
   only in the config, so nothing else varies between arms.

## Status and limitations

This is a research prototype at v0.2.0. Read
[`docs/design-rationale.md` 搂6](docs/design-rationale.md) before citing anything
from it. In short:

- The index weights are **design priors, not calibrations**. Sensitivity to them is
  measured and reported, not assumed away.
- Anchors reduce rater drift but do not eliminate it; the inter-rater protocol is
  specified but has not yet been run.
- The reduction branch is a behavioural simulation. No claim is made that anything
  internal is happening, and none should be read in.
- Fidelity to human behaviour is an open empirical question this repository equips
  a study to ask, not one it answers.

## Citation

See [`CITATION.cff`](CITATION.cff).

## License

**MIT** for the software 鈥?see [`LICENSE`](LICENSE). Documentation and the codebook
are additionally available under CC BY 4.0. The responsible-use note for the
`dissonance_reduction` profile lives in [`NOTICE.md`](NOTICE.md); read it before
enabling that profile anywhere a user could mistake the simulation for advice.
