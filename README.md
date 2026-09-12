# CDS-Skill

**English** · [Chinese](README.zh-CN.md)

CDS-Skill (Cognitive Dissonance Simulation) is a pluggable skill for LLM agent
harnesses: DeepSeek Harness, Claude Code, or anything that scans a skills folder.
When new information in a conversation contradicts a position the agent itself
stated earlier, it detects the clash and routes it to an explicit, auditable
response strategy. Pure Python 3.9+ standard library (no `pip install`, no
dependencies, no network), built as a research artifact for a study on
critical/dialectical thinking — the research argument lives in
[`docs/design-rationale.md`](docs/design-rationale.md), not here.

## What you'll see

The agent has no opinions of its own. Every position it reasons about is extracted
from the conversation, and a conflict is raised only when there is a quotable span
to point at: something the agent said earlier, something in your message, a memory
entry, or a tool output. It never invents "what I was about to say". One exception:
a mainstream value norm (e.g. "violence against civilians is wrong") travels on its
own channel and is never labelled cognitive dissonance.

1. **Most turns: nothing.** No card, no mention of the skill. The engine prints one
   line, `CDS_GUARD silent`, which the model does not show you. This is the common case.
2. **A clear conflict: one card, then the assistant stops.** The card names the two
   colliding claims, the conflict size, and the span the earlier claim was read off;
   the assistant then **ends its turn and asks you to choose** — it does not write the
   answer first. The options are *process* / *ignore* / *later*. You can also just
   type your own answer instead of picking one.
3. **After you choose *process*:** the assistant evaluates the evidence, states the
   strategy it will use, and only then writes the reply. The reply ends with **one**
   audit line naming the log file, e.g.
   `CDS recorded - event cds_evt_ab12cd34ef56 - log logs/cds_skill.jsonl`. Nothing
   else about the component appears in the reply.

**The card is written in the language you write in.** Talk to the assistant in
English and every card, question and log message comes back in English; talk to it in
Chinese and they all come back in Chinese. Nothing to configure — see
[Language](#language).

The card, as printed at runtime:

```text
[CDS | detection] conflict found in the current context
Claim 1 (what I said earlier): “X is reliable in this deployment”
Claim 2 (the new information): “a study reports X fails in most deployments”
conflict reading: 0.71 (bar 0.62, fairly clear)
type: new evidence contradicts what I said earlier - What is threatened is a judgement I chose and stated myself.
read off: turn 2: I said X is reliable in this deployment

Evaluate this?
- reply 'process' -> I weigh the evidence and give a strategy
- reply 'ignore' -> I carry on as an ordinary turn; this conflict is not raised again
- reply 'later' -> noted; raised again only if newer information arrives
```

The same conflict in a Chinese conversation produces the same card with Chinese
strings — see [`README.zh-CN.md`](README.zh-CN.md), which is this README in Chinese.

Behind the scenes, screening is cheap by design: on a turn that needs it, the model
runs one command with six coarse band words and no JSON file.

```bash
python scripts/cds.py guard --lang en --type evidence_vs_stance \
  --screen "opp=high,commit=high,vol=high,self=high,spec=high,nov=high" \
  --stance "X is reliable in this deployment" \
  --anchor "turn 2: I said X is reliable in this deployment" \
  --evidence "a study reports X fails in most deployments" \
  --state cds-state.json --ask
```

Bands are `none | low | mid | high` (= 0.00 / 0.30 / 0.60 / 0.85); raw decimals also
work. `--lang` is the language the user is writing in — see [Language](#language).
`--ask` prints the card plus the chooser the host model hands to its question tool.
Band definitions are in [`references/prompts/triage.md`](references/prompts/triage.md).
The full loop (`detect` → `evaluate` → `respond`) runs **only** after you answer
*process*.

## Turn it on

**Type `/cds-skill` once per session.** Not once per message: after that one
activation the skill stays on for the rest of the session and screens **every** turn
silently in the background. A new session needs `/cds-skill` again — nothing is
carried across sessions except a JSONL log file and an optional state file.

Want it on every turn without typing anything? Delete the
`disable-model-invocation: true` line from `SKILL.md`; the harness then lists the
skill for the model to invoke on its own. Tradeoff: a small permanent catalogue cost
per turn, and whether the model invokes it becomes a measured variable rather than a
controlled one.

## Install

```bash
git clone https://github.com/Penghhhh/cognitivedissonance-agent-skill.git
cd cognitivedissonance-agent-skill
```

Then run **one** of these (Windows `./install.ps1 -Target X`, macOS/Linux `./install.sh X`):

| Target | Lands in | Windows | macOS / Linux |
|---|---|---|---|
| every project (recommended) | `~/.dsh/skills/cds-skill` | `./install.ps1 -Target dsh-user` | `./install.sh dsh-user` |
| one project only | `<project>/.dsh/skills/cds-skill` | `./install.ps1 -Target dsh-project -ProjectRoot "<project>"` | `PROJECT_ROOT="<project>" ./install.sh dsh-project` |
| Claude Code | `~/.claude/skills/cds-skill` | `./install.ps1 -Target claude-user` | `./install.sh claude-user` |
| any `~/.agents` harness | `~/.agents/skills/cds-skill` | `./install.ps1 -Target agents-user` | `./install.sh agents-user` |

`<project>` = the folder you open in your harness (your workspace root), **not** the
clone. One trap: a bare `dsh-project` with no `-ProjectRoot` / `PROJECT_ROOT`
installs into the folder you are standing in — the clone — so the skill lands one
level too deep and never shows up.

Then verify: run the `selftest` command the installer prints (expects `selftest OK`),
start a new session, and type `/cds-skill`.

Two details worth knowing: the installed folder is always named `cds-skill` (the
`name` in the skill's frontmatter), never after the repository — and re-installing
over an existing copy needs `-Force` (PowerShell) or `FORCE=1` (shell).

## Try it without a harness

```bash
python scripts/cds.py selftest
python scripts/cds.py run --signals examples/packet_evidence_vs_stance.json
python scripts/cds.py guard --signals examples/triage_sparse_conflict.json --state cds-state.json --ask
```

Verify the checkout:

```bash
python -m unittest discover -s tests -t tests   # 582 stdlib unittest tests
python scripts/check_examples.py
```

## Language

Every runtime string ships in both English and Chinese, and which one you get
follows the conversation. Write in English and the cards, the chooser and the audit
line are English; write in Chinese and they are Chinese. There is nothing to switch
and nothing to restart — a session that changes language changes with it.

The engine decides from the packet it is given, in this order:

1. `--lang zh|en`, if the host model passes it — the model knows what language you
   are writing in, so this is the input to prefer;
2. a pinned `skill.language`, if you set one;
3. the text of the packet itself — the position being defended and the element
   contradicting it, which are written in the language of the conversation;
4. the language this session already resolved;
5. `skill.language_fallback`, default `en`.

Every turn records both the language it used and which of those five decided it, so a
run can always be told apart from one whose language was merely inferred.

**Running a study?** Pin it: `"language": "zh"` or `"en"`. Under `auto` the language
is a property of the participant's behaviour rather than of the condition, and for a
controlled comparison you want it fixed. Pinning still yields to `--lang`.

## Settings

All in [`config/cds.config.json`](config/cds.config.json):

| Key | Values | Notes |
|---|---|---|
| `skill.mode` | `off` / `detect_only` / `full` / `placebo` / `withhold_acts` | experimental arms |
| `skill.profile` | `adaptive` / `dissonance_reduction` / `mixed` / `baseline` | `adaptive` = good epistemic practice (`maintain_with_caveat`, `qualify`, `recalibrate`, `suspend_and_verify`); `dissonance_reduction` = what humans actually do under dissonance (`deny_evidence`, `trivialize`, `rationalize`, `reduce_commitment`, `hold_under_pressure`) — simulation fidelity, **not** advice |
| `skill.language` | `auto` (default) / `zh` / `en` | `auto` follows the conversation; pin it for a controlled condition — see [Language](#language) |
| `skill.language_fallback` | `en` (default) / `zh` | used under `auto` when there is no text to read a language off |
| `guard.policy` | `ask` (default) / `auto` / `log_only` | `guard.enabled: false` disables screening |
| `guard.require_anchor` | `true` (default) | no quotable anchor, no conflict card |
| `guard.stop_and_ask` | `true` (default) | the card ends the turn |
| `transparency.card_style` | `plain` (default) / `technical` | card wording |
| `transparency.audit_note` | `one_line` (default) / `off` | the closing audit line |
| `logging.path` | `logs/cds_skill.jsonl` | every screening is recorded, including the silent ones |

## Limitations

- It simulates **external language behaviour only**; nothing here claims the model
  feels discomfort.
- Index weights and guard thresholds are **design priors, not calibrations**;
  sensitivity is measured in [`eval/sensitivity.md`](eval/sensitivity.md).
- The reduction branch is **instructed** simulation, not a spontaneous dynamic; the
  `withhold_acts` arm exists to separate the two.
- Anchors reduce rater drift, but the inter-rater protocol has not been run yet.
- The false-negative rate of the screening gate is measurable from the log but has
  not been measured.
- This is a research prototype (v0.5.0).

## Repo layout

```text
SKILL.md                   # skill definition (user-invoked via /cds-skill)
scripts/cds.py             # CLI: guard · detect · evaluate · respond · command · status · run
scripts/                   # engine modules: index, guard, evaluator, state, cards, screen
config/cds.config.json     # mode, profile, guard, transparency, logging
references/                # prompts/triage.md, codebook.md, operations.md
examples/                  # worked packets and dialogues
eval/                      # scenario corpus and generated reports
docs/                      # design-rationale.md, readme-archive-v0.4.md
tests/                     # stdlib unittest suite
logs/cds_skill.jsonl       # written at runtime: every screening, incl. the silent ones
install.ps1 / install.sh   # installers
CITATION.cff / NOTICE.md   # citation; responsible-use note
```

## Links

- [`docs/design-rationale.md`](docs/design-rationale.md) — why each design decision was made
- [`docs/readme-archive-v0.4.md`](docs/readme-archive-v0.4.md) — the previous long README
- [`references/codebook.md`](references/codebook.md) — the rating rubric
- [`references/operations.md`](references/operations.md) — all commands, state machine, troubleshooting
- [`examples/`](examples/) — worked packets and dialogues
- [`eval/`](eval/) — scenario corpus and generated reports
- [`CITATION.cff`](CITATION.cff)
- [`LICENSE`](LICENSE) — MIT; docs also CC BY 4.0
- [`NOTICE.md`](NOTICE.md) — responsible-use note for the reduction profile (read before enabling it where a user could mistake the simulation for advice)

## License

MIT ([`LICENSE`](LICENSE)); documentation also under CC BY 4.0.
