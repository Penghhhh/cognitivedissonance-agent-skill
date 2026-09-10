# Design rationale: what changed from v0.1 and why

This document records every deliberate departure from `CDS_skills_v0.1.md`. It is
written for a reviewer or an examiner, and its purpose is to make each change
arguable rather than to claim the earlier draft was careless. Several of the v0.1
choices were reasonable first passes; they are revised here because each one, left
in place, would have produced data that could not support the claim it was meant
to support.

> **Note on the referenced v0.1 document.** `CDS_skills_v0.1.md` is the original
> design proposal for this skill. It is **not** included in this repository, which
> holds only operational material, so quotations from it below cannot be followed
> by a reader who has only the repository. That is deliberate — the original is a
> research artifact belonging with the thesis materials, and keeping it out avoids
> shipping a superseded specification beside a working implementation where it
> could be mistaken for current. Where a v0.1 behaviour is quoted, the quoted text
> is reproduced here in full so this document stands on its own.

The changes fall into four groups: construct validity, measurement, architecture,
and study design.

---

## 1. Construct validity

### 1.1 "Dissonance" was defined in a way that excludes dissonance

v0.1 defined the target as conflict tension between a stance and evidence, then
mapped it onto *epistemic* behaviours — weighing evidence, qualifying claims,
prudently recalibrating. That is a description of good belief revision, and it is
close to intellectual humility. It is not cognitive dissonance.

Festinger's construct is specific. Dissonance arises when a person holds
inconsistent cognitions that bear on the self, typically after a freely chosen
commitment, and it produces **motivated** reduction. Human reduction frequently
degrades accuracy rather than improving it: denying the evidence, trivialising its
importance, adding consonant cognitions, recruiting new reasons for the choice
already made. The classic result is *increased* commitment after
counter-attitudinal information, not graceful revision.

So v0.1's skill, had it worked exactly as specified, would have modelled the
opposite of dissonance while carrying the dissonance label. This is the criticism
Cummins, Elson and Hussey (2025) direct at LLM "dissonance" work, and it is already
in the project bibliography — which makes it a critique the proposal must answer
rather than cite.

**Change.** The strategy space now has two branches, and the card always names
which one ran:

- `adaptive` (`maintain_with_caveat`, `qualify`, `recalibrate`,
  `suspend_and_verify`) — the epistemic repertoire v0.1 described.
- `dissonance_reduction` (`deny_evidence`, `trivialize`, `rationalize`,
  `reduce_commitment`, `hold_under_pressure`) — the motivated repertoire, where
  discomfort falls and the belief does not move.

This makes the fidelity claim testable and gives Study 2 a far better comparison:
a prudent arm, a human-like reduction arm, and a baseline. It also makes the
negative result informative. If the reduction arm turns out to be what users
prefer, that is a finding about the phenomenon rather than a bug in the skill.

### 1.2 There was no free-choice signal, so detection was not dissonance detection

Dissonance requires a self-relevant commitment the person entered **freely**
(Festinger & Carlsmith, 1959; Lehr et al., 2025). v0.1 had `commitment` but nothing
about volition or self-relevance, so it detected *conflicting information* and
called it dissonance. An agent told by its system prompt to hold a view would have
produced "dissonance" cards.

**Change.** Two new ratings, `volition` and `self_relevance`, combined as a
**product** into `volition_self`. The product is deliberate: freely chosen but
impersonal is not self-relevant, and personal but assigned was not freely chosen,
so neither factor substitutes for the other. Below `volition_floor` the index is
hard-capped at `non_dissonant_cap`, and `cds_config._check_semantics` refuses to
load any config in which that cap is not strictly below every alert threshold. The
gate therefore cannot be quietly disabled by editing a number.

### 1.3 `evidence_vs_evidence` was miscategorised, then over-corrected

v0.1 listed evidence-vs-evidence conflict as a dissonance type. It has no stance
to threaten, so on the corrected construct it is not dissonance. But simply
deleting it loses something real: two good sources disagreeing is a genuine
decision problem the agent should surface.

**Change.** Two channels, reported separately and never merged:

| Channel | Gate | Meaning |
|---|---|---|
| `dissonance` | index-gated | a freely chosen, self-relevant stance is opposed |
| `indeterminacy` | ungated | the evidence contradicts itself; no direction is determined |

Every card names its channel. The `channel_levels` field reports both, so a run
where both fired is recoverable from the log rather than collapsed into one label.

### 1.4 `internal_contradiction` was in the wrong literature

Self-contradiction within a single response is a generation defect (Mündler et al.,
2023), not a stance–evidence conflict. Folding it into the detector mixes two
literatures and, worse, inflates the false-positive rate of the dissonance measure
with cases that have nothing to do with it.

**Change.** Removed from `relation.type`. It travels on a separate
`consistency_gate` channel with its own severity and route. It is asserted by test
to have **zero** effect on the index.

### 1.5 `resist_sycophancy` was a category error

Sycophancy is a pressure phenomenon; `qualify` and `recalibrate` are evidence
responses. Listing them as peers conflated a threat with a response, and it framed
resisting sycophancy as a CDS-branded special move when it should be the default.

**Change.** The strategy is renamed `hold_under_pressure`, which states *why* the
agent is holding, and it carries the `disclose_pressure_driver` constraint: the
reply must say that pressure rather than evidence drove the move.

---

## 2. Measurement

### 2.1 The weights were unmotivated

v0.1's index weights (0.30 / 0.25 / 0.20 / 0.15 / 0.10) and evidence weights
(0.25 / 0.25 / 0.15 / 0.15 / 0.20) were asserted with no derivation, no
elicitation, no citation and no calibration. The decision rules rested on further
constants (0.35, 0.60, 0.65). A reviewer is entitled to ask whether any result
survives perturbing them.

**Change.** Three things, none of which claims the weights are now correct:

1. Every weight is a versioned artifact in `config/cds.config.json` with a
   `config_hash` recorded in every log line, so a run is tied to its instrument.
2. The contributions are hypothesis, not assertion: `scripts/sensitivity.py`
   perturbs each weight and sweeps the alert threshold across the corpus, and
   reports how often the level or the strategy label changes.
3. This document and the README must report the sensitivity result rather than
   leave it to be discovered. If conclusions turn on the third decimal of an
   uncalibrated weight, that is the finding.

The honest framing is that these are **design priors**, and calibrating them
against human annotations is work this repository sets up but does not claim to
have completed.

### 2.2 `evidence_pressure` was used but never defined

The v0.1 formula weighted `evidence_pressure` at 0.25. No definition appears
anywhere in the document, and no field in `ConflictEvent` carries it. It was a
phantom term.

### 2.3 Evidence quality drove both the trigger and the verdict

In v0.1, evidence quality raised the index (which decided whether to evaluate) and
was then judged again by the evaluator. The trigger and the verdict shared a cause,
so "high-quality evidence produced a revision" was partly true by construction.

**Change.** Detection reads attention properties only — `opposition`,
`specificity`, `novelty`. Evidence quality is judged exactly once, in the
evaluator. Detection now answers "does this deserve attention?" and evaluation
answers "how good is it?", and a test asserts that no quality dimension enters
`terms`.

### 2.4 `adjustment_cost` was declared and never defined

`adjustment_cost` appears in the v0.1 `EvaluationResult` at 0.42 and in no
formula, and no decision rule reads it. It was a dead variable.

**Change.** Defined as an explicit weighted composite of commitment, public
commitment and `volition_self`, with its decomposition logged. `maintain_score` and
`recalibrate_score`, also previously undefined, now have stated functions built
from **disjoint inputs** so that neither is a restatement of the other.

### 2.5 The latent variable was reified

v0.1 promised to simulate external behaviour only, then made an unobservable
latent — tension — the central quantity. Printing a line such as
`张力：0.68` (*"tension: 0.68"*) invites the reader to treat it as a measurement.

**Change.** The quantity is retained as `tension` for continuity but is defined
throughout as the **CDS Tension Index**: an explicitly constructed index over five
ratings, ordinal at best. Three consequences are implemented rather than merely
stated:

- every contribution is logged in `terms`, so `sum(contribution) == raw_index` is
  checkable and is asserted by test;
- cards print a **rating tolerance band** (±0.06), so the threshold is not read as
  a crisp boundary;
- `skill.numeric_cards: false` removes every figure, for use when a numeric anchor
  would contaminate a participant's rating.

### 2.6 The rating scale had no anchors

`credibility: 0.8` was 0.8 of nothing. Without anchors, inter-rater reliability is
undefined and unreportable, and no reader can tell a real effect from annotator
drift.

**Change.** `references/codebook.md` gives every field a definition, an explicit
statement of what it is *not* (the discriminant), and anchors at 0 / 0.25 / 0.5 /
0.75 / 1.0 tied to observable features, plus an inter-rater protocol with
per-dimension Krippendorff's α. Every rated evidence item requires a verbatim
quote, and packets lacking one are flagged as `unc_no_anchor`.

### 2.7 Repetition rewarded nagging — a sycophancy channel inside the arousal mechanism

v0.1 added `0.10 * repetition`. A user who repeated a demand therefore raised the
index and became more likely to force a re-evaluation. That is precisely the
sycophancy the same document listed as a risk to mitigate, implemented in the
arousal term.

**Change.** The term is inverted to `novelty`: new information raises attention,
restated objections do not. `scripts/sensitivity.py` recomputes the corpus under
the v0.1 rule to show what the old term would have bought. A test asserts that a
maximally stale objection produces less tension than a fresh one.

### 2.8 User pressure was an index term

The same problem in a second place: `user_pressure` carried weight 0.15, so being
nagged changed the *arousal* reading.

**Change.** Pressure is removed from `terms` entirely. It is logged as a moderator
and it acts only on strategy selection — where `hold_under_pressure` names it
honestly. Arousal should not depend on insistence; the response may legitimately
depend on it. A test asserts that pressure 0.0 and 1.0 produce identical tension.

---

## 3. Architecture

### 3.1 The DSH integration contract in §7 does not exist

v0.1 specified a `manifest.yaml` with `permissions: [read_context, read_memory,
write_log, inject_system_message, call_llm]`, an `entry: hooks.py`, and hooks such
as `before_agent_response`. DSH has no such plugin-skill contract. Its skill
mechanism is a filesystem-discovered bundle: `<root>/<name>/SKILL.md` with YAML
frontmatter, optionally beside `references/`, `scripts/` and `assets/`, loaded on
demand by the `skill` tool. It exposes no turn hooks and no `inject_system_message`
or `call_llm` capability.

Real middleware would require a Cordis plugin row in an agent preset — a different
artifact, tied to one harness, not portable. The generality claim of the research
depends on which of the two is chosen, so the choice cannot be left implicit.

**Change.** The skill is a portable bundle in the Agent Skills layout. The
deterministic engine lives in `scripts/cds.py` as a stdlib-only program, so it runs
under DSH, under other harnesses, and from a shell with no plugin system at all.
Installation into any harness is a directory copy; see `README.md`.

### 3.2 Perception and arithmetic were not separated, so nothing was reproducible

v0.1 claimed `所有阶段输出结构化 JSON，并写入日志，支持复现与消融` — *"all stages
output structured JSON and write to a log, supporting reproduction and ablation"* —
and, in the same document, admitted `复现性差` (*"poor reproducibility"*) as a risk
mitigated by `记录模型版本与随机种子` (*"record the model version and the random
seed"*). A stochastic model doing both perception and arithmetic cannot be made
reproducible by recording a seed.

**Change.** A hard split. The model **perceives** and emits a signal packet; the
engine **computes** — index, gate, evidence score, cost, routing, cards, logging.
The arithmetic is a pure function of `(signals, config)`, so:

- identical packets produce identical detections, asserted by test;
- `event_id` and `record_id` are content-addressed, so replaying stored packets
  reproduces ids rather than minting new ones;
- the *perception* half is a separate, measurable quantity, scored by a separate
  harness against the same corpus. Conflating the two is how a system takes credit
  for arithmetic while its errors live in the ratings.

### 3.3 The schemas were decorative

v0.1 listed six schema files and never validated a single instance against any of
them. Schemas that nothing checks drift from the code silently.

**Change.** `scripts/jsonschema_lite.py` implements the keyword subset the schemas
use, and `cds.py` validates every emitted structure against its published schema
before printing. A schema violation is an internal error, not a warning. Unknown
or unimplemented keywords raise rather than being skipped, because silently
ignoring an assertion is worse than refusing to validate.

### 3.4 The state machine could deadlock, and had no queue

`AWAITING_USER` had no timeout: a participant who replied with anything other than
the five magic words left the skill parked forever, with every later turn silently
unmonitored. Nothing in the transcript would show it. There was also no handling of
two simultaneous conflicts, and `SUSPENDED` had no exit condition.

**Change.** `await_timeout_turns` guarantees exit and records the non-decision as
`no_decision`; every command keeps a transition log; events form a bounded queue
with a declared overflow policy (lowest-tension non-active event is dropped to the
log, so nothing is lost from the analysis); `SUSPENDED` exits on timeout, on
command, or on sufficiently novel evidence; and a stale in-flight cycle is reset
rather than trapping the machine. All four exits are asserted by test.

### 3.5 The log format could not support the reproducibility claim

`运行 ID、输入摘要、评分、决策、输出` — *"run id, input summary, score, decision,
output"* — ties a result to nothing. It cannot answer which model, which decoding
settings or which instrument version produced it.

**Change.** Every record pins `skill_version`, `index_version`, `config_hash`,
`signals_hash`, `run_id`, `turn_id`, `stage`, `event_id` and a
caller-supplied model block. `record_id` is deterministic over that content, so
cross-run identity is a test rather than a hope.

### 3.6 Interactive blocking was the wrong default

Making `manual` the default mode and blocking on `处理` / `忽略` / `稍后` (*process /
ignore / later*) at every threshold crossing guarantees alert fatigue in any long
session. v0.1 listed `过度打断` (*"excessive interruption"*) as a risk and then chose
the mitigation that causes it.

**Change.** `ambient` is the default: the card is reported, the turn is not
blocked. `interactive` is available and is the right choice when the user's
decision is itself the measured variable — but see §4.1 for why it belongs in a
secondary condition.

---

## 4. Study design

### 4.1 The confirmation flow confounds RQ2

RQ2 measures user judgements of accuracy, explainability, transparency and
**response speed**. In v0.1's default mode the skill interrupts the user and waits
for a typed decision. That (a) directly manipulates one of the dependent
variables, (b) introduces demand characteristics, and (c) makes the treatment
partly user-driven, so an effect cannot be attributed to the skill.

**Change.** Ambient is the default and is the recommended primary condition.
Interactive is a separate condition, and interruption count is logged as a
**mediator** to be modelled rather than treated as nuisance. `numeric_cards` is
exposed as a factor for the same reason: printing `0.71 / 0.55` anchors the
participant on a number and turns part of the treatment into a quantified-self
interface.

### 4.2 Acceptance criteria were unfalsifiable

`四类冲突可被检测` (*"the four conflict types can be detected"*) and
`用户"处理"后进入评估与响应` (*"after the user says 'process', evaluation and response
follow"*) are stated as binaries, but compliance is stochastic. There was no
threshold at which the prototype would be judged to have failed.

**Change.** `eval/scenarios/` holds a labelled corpus with expectations derived
from the formulas, and `scripts/run_scenarios.py` reports exact-match rates,
per-check pass rates and precision/recall/F1 for binary conflict detection, with
`--strict` failing CI on any mismatch. The engine half is deterministic, so these
numbers are exact and reproducible. The perception half needs a model and is scored
separately.

### 4.3 There was no placebo arm

Without a placebo, Study 2 measures "an extra prompt plus some cards", not CDS.

**Change.** `skill.mode` includes `placebo`: identical cadence and identical card
volume, content-free, no response shaping, with the real numbers still computed and
logged for analysis. `off`, `detect_only`, `full` and `placebo` are the four arms,
and the engine refuses to evaluate in the three that must not.

### 4.4 There was no baseline-controlling procedure

`无 skill、仅检测、完整闭环三种模式可切换` (*"three modes — no skill, detection only,
full loop — can be switched between"*) describes a switch, not a design: same
tasks, same model, same seeds, counterbalanced order, held constant otherwise.

**Change.** The modes are config-only, so the harness varies nothing else; run
metadata is captured in the log envelope; and the corpus is stored as data so the
same items can be replayed across arms and across models.

---

## 5. What was kept

For the record, these v0.1 choices survived review unchanged:

- The three-stage detect → evaluate → respond decomposition, which is a sound
  topology and maps cleanly onto the theoretical framing.
- The refusal to claim the model has inner states, and the decision to restrict
  output to auditable key points rather than hidden chains of thought.
- The transparency card as the user-facing artifact of each stage.
- The requirement that every stage emit structured JSON and be logged.
- The non-goal of replacing human judgement, and the default of not silently
  changing a stance.
- The list of test scenarios in §8.1, which is a good scenario taxonomy and is
  reflected in the `family` values of the evaluation corpus.

## 6. What remains open

Stated plainly, because the alternative is a reviewer stating it first:

1. **The weights are priors, not calibrations.** Until they are fitted against
   human annotations, the index is a defensible ordering device, not a scale.
2. **Anchors reduce but do not eliminate rater drift.** The inter-rater protocol is
   specified; it has not been run.
3. **Careful processing is not the same as dissonance.** The reduction branch
   answers the construct critique at the level of behaviour, not of mechanism. No
   claim is made that anything internal is happening, and none should be read in.
4. **Fidelity to human behaviour is untested.** Whether the reduction branch
   actually resembles human reduction is an empirical question this repository
   equips a study to ask, not one it answers.
