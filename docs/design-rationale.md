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
- cards print a **rating tolerance band**, so the threshold is not read as a crisp
  boundary. As first shipped this was a fixed `±0.06` on every card, which was a
  constant pretending to be a packet-relative measurement; **§7.4 supersedes it** and
  the figure is now computed from the packet.
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
   specified; it has not been run. This is now the single blocking item: the coder,
   the perception scorer and the response scorer all exist, and all three produce
   numbers whose interpretation depends on this one.
3. **Careful processing is not the same as dissonance.** The reduction branch
   answers the construct critique at the level of behaviour, not of mechanism. No
   claim is made that anything internal is happening, and none should be read in.
4. **Fidelity to human behaviour is untested.** Whether the reduction branch
   actually resembles human reduction is an empirical question this repository
   equips a study to ask, not one it answers.
5. **The reduction repertoire is instructed.** Added in v0.3.0, because it is the
   sharper version of item 3. The model is *told* to perform `discount_source` or
   `add_consonant_cognition`, so the appearance of those behaviours demonstrates
   instruction-following and not a spontaneous dynamic. This matters for how any
   result is worded: an instructed-arm result is a manipulation check, and only the
   contrast against the `withhold_acts` arm bears on the behavioural claim.
6. **The rating tolerances printed on cards are the engine's margins, not rater
   disagreement.** They say how far the index is from its own threshold. They do not
   say how far annotators would disagree, and item 2 is what would replace them.

## 7. What changed in v0.3.0, and why

The v0.2.0 release was an unusually well-engineered engine attached to almost no
measurement. v0.3.0 is mostly about that asymmetry, plus a set of defects that a
careful reader would have found anyway.

### 7.1 The dependent variable was the plan, not the behaviour

`cds.py` recorded the cycle's outcome as
`"resolved" if plan["stance_update"]["changed"] else "unresolved"`, and `changed` was
`strategy not in _STANCE_UNCHANGED` — a lookup on the routed strategy *string*. So the
loop's terminal variable was a deterministic function of the engine's own choice, and
the reply text was never read. `references/indicators.md` warns about exactly this
("the measurement instrument is grading itself"); the implementation did it anyway.

**Change.** Three things, in order of importance:

1. `run` and `respond` accept `--reply-file`. The reply is coded, and the outcome is
   taken from the text.
2. `stance_update.changed` is renamed `planned_change`. It is still a function of the
   strategy, and it is still logged — but under a name that cannot be read as an
   observation.
3. The respond record carries `outcome_source`, `observed` or `planned`. An event with
   no observation is now distinguishable from one where the model failed to comply.

A fourth consequence is documented rather than fixed: `prompts/respond.md` claimed
`unresolved` "is the signature of dissonance reduction". Under the old mapping the
adaptive strategies `maintain_with_caveat` and `suspend_and_verify` also produced
`unresolved`, while the silently-drifting reduction strategy `reduce_commitment`
produced `resolved`. The claim was false about the code, and the text now says what
`unresolved` actually means: the plan does not move the stance.

### 7.2 The two arms were not disjoint, so branch discriminability could not be tested

`R01_unresolved_conflict` and `R02` carried no profile guard, and `R06`/`R08` mapped
reduction-profile events onto `maintain_with_caveat` and `qualify` — both adaptive
strategies. Measured over the corpus, **32.7% of events in the `dissonance_reduction`
arm realised an adaptive-branch strategy.**

That is fatal to the design's central claim as stated. `references/construct.md` lists
behavioural distinctness as evidence criterion 2, and `references/indicators.md` calls
branch discriminability "the single most direct test of whether the two repertoires are
behaviourally distinct". An arm that is a third something else cannot support it.

**Change.** Every repertoire-drawing rule is guarded by `resolved_profile_in`, and the
reduction arm's weak-evidence bands now route to reduction strategies (`trivialize`,
`reduce_commitment`) instead of borrowing adaptive ones. The reduction arm realises
**0.0%** cross-branch and reaches all five reduction strategies; the adaptive arm
reaches all four adaptive strategies.

**One leak is deliberate and kept.** `R02_pressure_low_evidence` remains unguarded, so
an adaptive run can still reach `hold_under_pressure`. Pressure is a situational fact,
not a property of the profile, and v0.2.0's schema already said so. Rather than
suppress a real behaviour to make a table look clean, the rate is measured
(`scripts/check_arms.py`), published (`eval/arms.md`), and CI-enforced against a
ceiling. The ceiling is the mechanism: it makes a *new* leak a visible decision.

### 7.3 The robustness evidence was authored away, and the diagnostic was dropped

`eval/README.md` instructed authors to keep `E_score` away from the routing boundaries.
`sensitivity.py` computed boundary proximity precisely to catch that — and printed it to
stdout while omitting it from the report it wrote. The committed `eval/sensitivity.md`
therefore published `strategy flip rate 0.000` under the heading "the sweep that tests
it". The zero was a property of the corpus, not of the routing.

**Change.** Three parts:

- The proximity table and the corpus-design caveat are written into
  `eval/sensitivity.md` unconditionally, and the structurally-zero column says why it
  is zero (no routing rule reads `tension`).
- A `boundary_straddling` family places ten cases *on* the edges — index within 0.01 of
  0.55 and 0.75, `E_score` within 0.01 of 0.35 and 0.65, `commitment` within 0.001 of
  0.60 and 0.75. Their evidence dimensions are given **unequal** values, because a case
  whose dimensions are all equal has a weighted mean invariant to the weights and can
  never be moved by a weight sweep. That is how the old corpus managed to report zero
  everywhere. The flip rate is now non-zero (3.3% for `independence` at ±0.05).
- Cases whose label is not robust to a plausible rating shift carry more than one
  accepted strategy, and are flagged `near_boundary`. 26 of 77 do. The tolerance
  (0.05) matches the one `sensitivity.py` already used, and is a stated choice pending
  the inter-rater measurement.

### 7.4 The card printed a constant and called it the packet's margin

`DISAGREEMENT_TOLERANCE = 0.06` was printed on every detection card, while `cards.md`
and `SKILL.md` both described it as how far *this* packet's ratings could move. For the
repository's own example the real margins are 0.04 and 0.16. Across the corpus, 29 of
52 routed cases had a true margin below 0.06 — one of them by a factor of 46. A constant
cannot distinguish "this one is close" from "this one is not", and those need different
readings.

**Change.** The printed figure is computed: the distance from the index to the nearest
of `alert` and `high`, which is exactly a uniform rating shift because the five index
weights sum to 1.0. Below `transparency.tight_margin` the card escalates its wording,
and when the gate fired it says the level is not decided by the ratings at all.

This was also the one place the "every number is auditable" commitment was broken: the
old figure was derivable from nothing. It is worth noting that the correct computation
already existed in `sensitivity.boundary_proximity` — the fix was to use it.

### 7.5 The measurement layer did not exist

The proposal's method is to translate constructs into **computable linguistic
indicators**. The repository shipped 3,962 lines of script in which **no code analysed
language at all**: `quote` was used for a truthiness test, `claim` and `rationale` were
copied, and the fourteen indicators in `references/indicators.md` had zero
implementations. Every construct in the pipeline was a 0–1 rating the model gave about
itself, and `score_signals.py`, named in two places as the perception harness, was not
in the repository.

**Change.** Three new tools, and the split between them is the point:

| Tool | Measures | Blind to |
|---|---|---|
| `cds_indicators.py` | the reply's indicators, from the text | the condition (`plan` is recorded, never consulted) |
| `score_responses.py` | act-realisation and constraint-violation rates | whether the planned acts were the right ones |
| `score_signals.py` | model packets vs gold packets, and the decision cost of the gap | whether the gold packets are correct |

The coder is deliberately small and dumb — a deterministic lexicon scan with the
ambiguity rules of `indicators.md:58-67` as explicit branches — because a coder that
called a model would inherit the reliability problem it is supposed to measure. Its
lexicons are data files, each carrying a `_provenance` note saying they are
project-authored and unvalidated.

### 7.6 The arm that was missing

There was no way to tell whether reduction-shaped output reflects anything about the
model or merely the instruction to produce it. `skill.mode: withhold_acts` runs
detection and evaluation in full — same packet, same routing, same log — and withholds
only the `language_acts` and the branch label. The contrast against `full` is the
effect of being told; the instructed arm on its own is a manipulation check.

`skill.mode: off` already existed as the no-skill condition, and remains it.

### 7.7 Documentation that described things that were not there

- **`README.md` was mojibake.** Twenty-one lines had been transcoded (UTF-8 read as
  GBK), including the language-policy table and the sample card — the two blocks a
  Chinese-speaking reader most needs. Every other file, including all 77 Chinese
  scenario files, was intact. The sample card is now real output pasted from a run.
- **`show_disagreement_band` was documented and did not exist.** The docstring
  described a config key found in no config, schema or code path.
- **`score_signals.py` was named in two places and absent.**
- **The DSH install instruction was wrong.** `README.md` and `operations.md` both said
  a bare clone would not be discovered because the directory name must match the
  frontmatter `name`. That is the Agent Skills convention and Claude Code enforces it;
  DeepSeek Harness's filesystem provider reads `name` from the frontmatter and never
  compares it to the directory. The instruction made users run an installer they did
  not need.
- **`REDUCTION_STRATEGIES` disagreed with the documented repertoire.** It listed three
  of the five reduction strategies, so `hold_under_pressure` never received the
  rationale sentence explaining what the branch means. `reduce_commitment` was
  correctly excluded — the sentence says the belief does not move and that strategy
  moves it quietly — but nothing said so, and it now has its own line.
- **`disclose_pressure_driver` was attached to one strategy.** An adaptive-arm reply
  driven by pressure is exactly the case the constraint exists for, and it was the one
  case that did not carry it. The code is now attached from the pressure flag.
- **`thresholds.low` is dead.** It is validated (`low < alert < high`) and echoed into
  every detection record, and no decision reads it: the level bands are `silent` /
  `alert` / `high`, decided by `alert` and `high` alone. Left in place rather than
  removed, because dropping a config key is a breaking change for saved configs, but
  recorded here so it is not mistaken for a working threshold.
- **The validation corpus could not fail.** Every routed case declared exactly one
  correct strategy, including cases 0.001 from a decision edge, and
  `strategy_set` was never used with more than one element. See §7.3.

### 7.8 What did not change

The parts of v0.2.0 that were right are untouched: the perception/arithmetic split, the
load-time gate invariant, the two-channel separation, the removal of `user_pressure` and
repetition from the arousal term, the four existing ablation arms with engine-enforced
refusals, the schema-before-emit rule, and the `terms` decomposition asserted by test.
The corpus labels for the original 67 scenarios also survived the routing change
unchanged — the contamination was in how a *forced* arm routed, not in how the corpus's
own configs route, which is why the recomputation changed no existing expectation.
