# CDS-Skill

**Cognitive Dissonance Simulation for LLM agents** — a pluggable skill that turns a
conflict between an agent's own committed position and incoming information into a
detectable, auditable, reproducible event, then routes it to an explicit response
strategy.

This repository is the Study 1 implementation artifact for the research project
*Simulating human-like external behaviour under contradictory information:
a modular skill for LLM agents and its human-factors evaluation*.

> 中文摘要：本项目是研究一（认知失调外显行为仿真 Skill 的实现）的技术产物。它把"智能体既有立场与新信息冲突"转化为可检测、可审计、可复现的事件，并显式路由到某一种响应策略。**感知由模型完成，算术由脚本完成** —— 模型只负责给情境打分并输出结构化信号包，脚本负责计算指数、门控、评分、路由、渲染卡片与写日志。因此所有数值都可从存下的信号包完整复现。

---

## The one idea

```
model perceives  ──►  signal packet (JSON, rated against an anchored codebook)
                              │
                              ▼
              cds.py computes  ──►  index · gate · evidence score · route · card · log
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
| `dissonance_reduction` | `deny_evidence`, `trivialize`, `rationalize`, `reduce_commitment`, `hold_under_pressure` | human-typical motivated reduction (fidelity, **not** advice) |
| `mixed` | per-event, recorded as `reduction_tendency` | — |
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

Output:

```text
【CDS｜检测】
状态：认知失调相关冲突张力
张力指数：0.71 / 阈值 0.55
评分可动范围：±0.06（同一输入在不同标注下可能跨越阈值）
类型：证据—立场冲突
通道：失调通道（需要自主选择的立场）
关键点：
- 新证据与既有立场方向相反
- 冲突具体且可核查
...
```

```bash
python -m unittest discover -s tests -t tests   # 127 tests, all green
python scripts/run_scenarios.py                   # score the eval corpus
python scripts/sensitivity.py                     # how load-bearing are the weights?
python scripts/check_examples.py                  # do the docs still match the code?
```

## Install as a skill

The repository is itself a valid skill bundle in the portable Agent Skills layout,
so installation is a directory copy. The **installed** directory name must equal the
skill name (`cds-skill`); the installer handles that regardless of what your clone is
called.

**DeepSeek Harness (DSH)** — project scope, discovered at `<project>/.dsh/skills/`:

```powershell
./install.ps1 -Target dsh-project          # Windows
```
```bash
./install.sh dsh-project                    # macOS / Linux
```

**Claude Code and other compatible harnesses** — user scope:

```bash
./install.sh claude-user
```

**Any harness, any agent** — the engine is a plain program, so a harness with no
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
schemas/                    signals · detection · evaluation · log_record
scripts/
  cds.py                    CLI: detect · evaluate · respond · command · status · run
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
tests/                      127 stdlib unittest tests
docs/
  design-rationale.md       every deliberate change from v0.1, and why
examples/                   worked packets and dialogues
.github/workflows/ci.yml    tests + strict corpus + doc/code agreement on every push
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
[`docs/design-rationale.md` §6](docs/design-rationale.md) before citing anything
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

MIT for code. Documentation and the codebook are CC BY 4.0 — see
[`LICENSE`](LICENSE).
