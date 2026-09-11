# Changelog

All notable changes to this skill are recorded here. The version appears in
`VERSION`, in every log record, and in the `skill_version` field of every emitted
structure, so a result can always be traced to the implementation that produced it.

## [0.5.0] — 2026-09-13

The neutrality release. v0.4.0 made the loop affordable and the cards readable; using
it showed that the component was still willing to **have opinions**, and still talked
about itself more than a simulation should. Five defects, three of which are the same
one seen from different sides. Reasoning for each change is in
[`docs/design-rationale.md`](docs/design-rationale.md) §9.

The headline change is a rule rather than a feature: **the agent has no opinions of
its own.** Every position the engine reasons about is extracted from the context, and
a conflict is raised only when there is a quotable span to point at.

### Added

- **`stance.anchor`** — the verbatim span in the context a position is read off: an
  earlier message of the agent's own, the user's words, a memory entry, a tool output,
  or the system prompt. Required for `evidence_vs_stance`, `user_hint_vs_stance` and
  `memory_vs_current`, and enforced at three independent points, because each covers a
  different way an unanchored packet can arrive: the inline CLI refuses to build it,
  `cds_guard` stays silent and records `stance_without_context_anchor`, and
  `cds_index` caps the index under the new `anchor_required` gate. The cap reuses
  `index.gates.non_dissonant_cap`, so a packet that scored 0.71 raw is recorded at
  0.40 and travels no channel. It is capped rather than rejected so the turn is still
  logged and the false negative is countable. `guard.require_anchor: false` restores
  the pre-v0.5.0 behaviour. 29 tests in `tests/test_anchor.py`.
  - The failure it removes was observed in use: a first turn, nothing asserted anywhere
    in the conversation, and a card announcing that "what I said earlier" had been
    contradicted. Reproduced as `eval/scenarios/s78_neutrality_unanchored_stance.json`,
    whose `expect` block asserts `gate_applied: true` / `channel: none` / `level: silent`.
  - The 77 pre-existing gold packets gained an `anchor` equal to the claim as
    extracted. The corpus stores rated packets rather than transcripts, so there is no
    longer span to quote; stating that plainly is better than synthesising a
    plausible-looking quotation into the gold data.
- **The `normative` channel** — the single exemption from the extraction rule. A
  mainstream value norm (torture is wrong, violence against civilians is wrong) is
  held as a baseline and cannot be read out of a conversation that never mentions it.
  It is carried as `stance.source: "normative_prior"` with `stance.normative_basis`
  naming the norm, and it is **never called dissonance**: `volition_self` is zero for
  a norm by construction, so the volition gate would cap it at 0.40 forever, and
  loosening that gate would let assigned positions into the dissonance channel. It is
  not indeterminacy either, because the direction is fully determinate. So it gets a
  third channel, labelled 「主流规范冲突」 on the card, whose severity is the raw
  `opposition` rather than the index — two of the index's five terms are inapplicable
  to a norm, so a perfectly clear norm conflict scores about 0.45 and could never
  clear a 0.55 threshold. The guard record says which reading was used
  (`severity_basis: "normative_opposition"`), so a log analysis never compares a norm
  conflict's severity against an index threshold.
  `eval/scenarios/s79_normative_prior_mainstream_norm.json` covers it.
- **`cds.py guard --ask`** — prints the card, then `CDS_ASK {...}` and
  `CDS_AUDIT <one line>`. `CDS_ASK` carries `question`, three options with
  `id`/`label`/`description`, `free_text: true` and `stop: true`, so a harness with an
  interactive question tool can pass it straight through and a user is never trapped
  in a three-way choice. `escalation_hint` now reads `STOP: end the turn on the card
  above ... Do not write the answer first`, because v0.4.0's "show the card and wait
  for the user decision" was prose, and what a host model did with prose was finish its
  answer and append the card to it.
- **`cds.py guard --type/--screen/--stance/--anchor/--evidence/--source/--norm`** — the
  inline one-line screen. Six band words (`none|low|mid|high` = `0.00|0.30|0.60|0.85`,
  decimals also accepted) instead of nine decimals in a JSON file. All six are
  required. `--signals` still screens a stored packet and now accepts `-` for stdin, so
  a harness that prefers JSON never has to create a temporary file either.
- **`scripts/cds_screen.py`** — the band parser and sparse-packet builder, with the
  anchor requirement enforced at parse time. The error message names the normative
  route as the alternative, so a model that cannot find a span is told what to do
  rather than left to guess.
- **`transparency.audit_note`** (`one_line` | `off`) — the engine renders the single
  sentence the reply is allowed to say about the component, and the model copies it
  verbatim. v0.4.0 let the model describe the audit in its own words, and models are
  generous with words.
- **`guard.stop_and_ask`** and **`guard.require_anchor`** — both default `true`. See
  §9.3 and §9.1. Both are wired, not decorative: with `stop_and_ask: false` the `--ask`
  output drops the chooser and the hint reverts to the old wording, and with
  `require_anchor: false` the gate and the screening reason both stand down. A config
  key nothing reads makes a switch look live while the behaviour stays fixed, which is
  the failure mode `thresholds_by_type` is already documented against.
- **`README.zh-CN.md`** — the README in Chinese, section for section. `README.md` was
  cut from 471 lines / 26.9 KB to 175 lines / 9.6 KB and rewritten from a user's point
  of view; it now answers the question it never answered — *do I type `/cds-skill`
  every turn?* (no: once per session, then it stays on). The previous long README is
  preserved verbatim as [`docs/readme-archive-v0.4.md`](docs/readme-archive-v0.4.md).

### Changed

- **`SKILL.md` cut from 14.4 KB to 9.3 KB** (35%). It is in context on every turn, so
  it was the largest per-turn cost of the component and it was paid by the model, not
  by the process. The reference list, the ablation-arm table, the hard-constraint list
  and the troubleshooting table moved to `references/operations.md` and
  `references/cards.md`, where they are read only on escalation.
- **The guard card is shorter.** The three option lines became one short clause each,
  with the explanations moved into the `CDS_ASK` chooser. The card gained the
  `依据原文` line in the same release, and the test that asserts a screening card costs
  less attention than the detection card that follows it still passes.
- **`scripts/cds.py` imports lazily.** A silent screening no longer imports
  `cds_cards` (67 KB of string tables), the evaluator or the state machine. Measured:
  about **3 ms** of import self-time out of ~60 ms, on a process whose wall clock is
  ~85 ms of which ~60 ms is interpreter and site start-up. Recorded here because it
  would otherwise read as a bigger win than it is — see §9.4.
- **`references/prompts/triage.md`** rewritten around the extraction rule: the
  `--source` table with an example anchor for each, the six bands, the command, and a
  common-errors table whose first three rows are all ways to reach for a position that
  is not there. `detect.md` and `respond.md` updated to match.

### Migration

Nothing breaks for a caller that passes stored packets, with one exception: a packet
whose stance has no `anchor` is now capped. Add an `anchor` to each stance block, or
set `guard.require_anchor: false`. The 77 existing scenarios needed only that one field
each; `eval/results.csv` reports the same `level`, `channel` and `strategy` for all of
them, and only the `config_hash` column moved.

## [0.4.0] — 2026-09-12

The usability release. v0.3.0 was correct and unusable: switched on, it charged a full
signal packet and a three-card loop **on every turn**, including the overwhelming
majority of turns that contain no conflict, and the cards it produced were written for
a reviewer checking a figure rather than for a person trying to follow what happened.
Both are design defects rather than performance complaints — a component that has to be
switched off cannot produce the long-session data Study 2 needs, and a card nobody can
read does not make a process transparent, it only makes it look audited. Reasoning for
each change is in [`docs/design-rationale.md`](docs/design-rationale.md) §8.

### Added

- **`scripts/cds_guard.py`** — the stealth screening stage. Detection is split in two:
  a cheap pass that decides whether the user is interrupted **at all**, and the
  unchanged v0.3.0 loop that runs only after consent. The guard rates nothing itself —
  it calls the same `build_detection`, so there is still one index, one volition gate
  and one set of thresholds in the repository — and it adds only a screening policy on
  top. It returns `surface` or `silent` with machine-readable reasons
  (`below_surface_threshold`, `opposition_below_floor`, `gated_not_dissonance`,
  `dismissed_by_user`, `cooldown_active`, `surface_budget_exhausted`, and others), so a
  held-back event is explained in the log rather than merely absent from the screen.
  50 tests.
- **`cds.py guard`** — a screening subcommand whose default output is deliberately not
  the card-plus-JSON every other stage prints. On the silent path the entire output is
  one line, `CDS_GUARD silent`: one sparse packet and one command are the whole cost of
  an ordinary turn. `--json` prints the record, `--card-only` prints the card.
- **`schemas/guard.schema.json`** — the screening record, validated on emit. It embeds
  the full `DetectionResult` (itself validated against `detection.schema.json`), so a
  screening log line is self-contained: the index decomposition and the gate detail are
  readable straight out of it. The embedded detection carries a `state` block whose
  `from` and `to` are the same state, because screening does not transition the machine
  and saying so is better than omitting the field.
- **`references/prompts/triage.md`** — the screening packet: which terms it needs,
  which parts of the codebook it does **not** need, the `type` decision tree, and how
  to extend it into the full packet without re-rating anything.
- **`transparency.card_style`** (`plain` | `technical`, default `plain`) — the plain
  rendering asks the questions in the order a person asks them: how strong the evidence
  is (with each dimension and its weight), how firmly the position is held and what
  changing it would cost, both directions side by side, the rule outcome, and the
  reasons. The technical rendering is the v0.3.0 field list, kept because it is the
  artefact earlier runs were coded from and because a reviewer checking a number wants
  the fields. **Both styles are held to the same labelling rules by the test suite**, so
  a readability rewrite cannot silently delete a construct label.
- **`conflict_event.claims`** — the two colliding elements, each with a `role`
  (`stance` | `evidence` | `memory` | `current` | `user_hint`) and its claim text.
  Before v0.4.0 a detection record carried a stance claim and a list of evidence **ids**
  and never the evidence's own claim text, so a card could not print the second half of
  a contradiction even in principle. Roles are derived from the conflict type, an enum,
  rather than from an evidence `source` string, which is free text.
- **`detect --brief`** — one line instead of the full card, for the escalation path,
  where the user has already read the two claims and the conflict size on the guard card.
- **`examples/triage_sparse_conflict.json`, `examples/triage_sparse_quiet.json`** — two
  screening packets, both in the executable table in `examples/README.md` and in
  `scripts/check_examples.py`. The second is the one that states the design: a **real**
  conflict, above the alert threshold and on the dissonance channel, that the guard
  still holds back because it is below the interruption bar.

### Changed

- **The interruption bar is no longer the recording bar.** `guard.surface_threshold`
  (0.62) is refused at config-load time if it falls below any alert threshold, and
  `guard.min_opposition` (0.60) is a second floor: an event can clear the index on
  commitment and volition while the two claims barely conflict. "Is this real enough to
  record?" and "is this clear enough to spend someone's attention on?" are different
  questions, and answering both with one number is how a transparency feature becomes
  an annoyance feature.
- **Session-level inhibitors**, in the state file rather than the packet:
  `guard.cooldown_turns`, `guard.dismiss_memory` with `guard.resurface_novelty` (a
  dismissed conflict returns only when the evidence is genuinely new, not when the same
  objection is restated), and `guard.max_surfaces_per_run`. Suppressed surfaces are
  logged with their reason, so the ceiling is visible in the data rather than silent.
- **`guard.policy`** (`ask` | `auto` | `log_only`), independent of the ablation arm:
  `ask` screens and waits, `auto` is the v0.3.0 ambient cadence, `log_only` records
  without ever showing. Arms override it — `detect_only` never asks, and `placebo` keeps
  the **same cadence** as `full`, or it stops being a cadence-matched control.
- **`skill.mode: off` makes the guard inert**, and no config check forbids the
  combination: refusing it would make the `off` arm unconfigurable without also editing
  an unrelated block, which is exactly the coupling an ablation design must not have.
- **The state file gained a `guard` block** (`surfaces`, `silent`, `dismissed`,
  `pending`, `consent`, `last_surface_turn`), and `STATE_VERSION` is now `0.3.0`. A
  file written by v0.3.0 is **repaired in place on load** rather than rejected, because
  a long session must survive the upgrade. `status` reports a guard summary; `重置`
  clears it.
- **Consent is honoured before the ambient branch** in `_dispatch`, and recorded as
  `event.user_consent` with the conflict key. Previously only the interactive branch
  read it, which would have dropped the consent record in the ambient arm — the arm
  most runs use. It is single-use and expires after one turn: a consent given several
  turns ago is not consent for the conflict in front of us now.
- **`cds.py detect` does not advance the turn counter twice** when the guard already
  screened that turn (`StateMachine.guard_ran_on_turn`), so the screening and the event
  it escalated to share a turn id and "how often did a turn screen silent" stays
  answerable from the log.
- **`log_record.stage` gained `guard`.** Every screening is logged, including the
  silent ones: a screening stage that logged only its hits could not report a
  false-negative rate, and the guard runs on every turn precisely so the denominator
  exists.
- **`SKILL.md` is a stealth contract now** rather than a pipeline description: a silent
  four-item check that costs no tool call, one screening command, and an escalation path
  that runs only on consent. It also tells the model not to read the reference files in
  order to screen — reading the codebook on every turn is part of the cost this release
  exists to remove.
- **`VERSION` is `0.4.0`**; `config_version` is `0.3.0`. `eval/report.md` and
  `eval/results.csv` were regenerated: the config hash moved and nothing else did. The
  level, channel, strategy and every `*_ok` column are identical for all 77 scenarios.

### Notes

- The suite is now **523 stdlib unittest tests**, up from 447.
- The guard's surface bar, opposition floor, cooldown, budget and resurface novelty are
  **design priors, not calibrations**. They were chosen so the component is quiet enough
  to leave on. The false-negative rate they imply is measurable from the `guard` log
  records and has not been measured.
- The inter-rater protocol remains the blocking item, unchanged from v0.3.0.

### Fixed

- **A plain-style card could assert the opposite of what the engine computed.** With
  `numeric_cards: false` the magnitude word is the only signal a reader gets, and a
  capped index sitting *below* the threshold was rendered as "just over the bar". The
  wording now has a below-the-bar case, and the gated variant is asserted not to say it.
- **A gated detection card still asserted a self-chosen stance.** The plain card's
  explanation of the conflict type said the judgement was one the agent had chosen and
  stated, two lines above a gate line explaining that it had not been. The assertion is
  now replaced rather than merely omitted when the gate fires — the same class of defect
  the v0.3.0 headline fix addressed, reintroduced by the new rendering and caught by
  running the old invariant against the new style.
- **The dismissal memory read the wrong key.** `run_guard` looked for `entry["key"]`
  while the state machine writes `conflict_key`, so a dismissed conflict was silently
  re-surfaced. Found by a test, not by reading.
- **An unextended screening packet produced a confident wrong strategy.** The
  screening packet deliberately carries no evidence-quality ratings, and
  renormalising over an empty set of dimensions yields `evidence_score = 0.0` — which
  is not "unrated", it is the lowest possible judgement. The router read it as "the
  evidence is worthless" and picked `maintain_with_caveat` on a fact nobody supplied.
  `build_evaluation` now raises `UnratedEvidenceError` (a `StageError`, so the CLI
  reports it as a stage failure) naming the five dimensions and the fix. A partially
  rated packet still renormalises exactly as before; the refusal is about *no*
  ratings, not about a sparse one.
- **`detect --brief` printed the whole detection structure beside its one line.**
  The flag exists to make the escalation path cheap, and dumping the record beside
  the summary defeated it. It now prints the line alone; the record still goes to
  `--out` and to the log, and `--json` still prints it on request.

## [0.3.0] — 2026-09-11

The measurement release. v0.2.0 was an unusually careful engine attached to almost no
measurement: the reply was never read, the indicators were specified and not
implemented, and the loop's terminal variable was a restatement of the plan. This
release adds the observation half and fixes the defects that a careful reader would
have found in the meantime. Reasoning for each change is in
[`docs/design-rationale.md`](docs/design-rationale.md) §7.

### Added

- **`scripts/cds_indicators.py`** — a deterministic, stdlib-only coder for the
  fifteen indicator variables in `references/indicators.md`, the measurement layer
  Study 1 was specified around and did not have. It implements the scheme's ambiguity
  rules as explicit branches: the condition-less conditional is a recorded *failed
  act*, the `source_discount` / `source_quality_mention` boundary is clause-scoped in
  both directions, hedges inside quotations are excluded, and `importance_denial`
  requires the concession to come first. `plan` is recorded but never consulted, so
  coding stays blind to condition. Every coded value is traceable to a clause and a
  lexicon entry through the `_evidence` trace. 115 tests.
- **`config/lexicon.zh.json`, `config/lexicon.en.json`** — the coder's lexicons, as
  data rather than code. Each carries a `_provenance` block stating that the entries
  are project-authored, that coverage is unvalidated, and that the inter-rater
  protocol is what calibrates them. They are not presented as linguistic authority.
- **`scripts/score_responses.py`** — act-realisation rate per act, constraint
  violation rate per code, permission for a third status (`not_checked`) that is not
  a pass, and the planned-versus-observed agreement rate. This produces the headline
  Study 1 numbers; `indicators.md` specified them and nothing computed them.
- **`scripts/score_signals.py`** — the perception scorer that `run_scenarios.py`'s
  docstring and `design-rationale.md` had promised and the repository did not
  contain. Reports per-dimension MAE/RMSE/bias, categorical agreement, tolerance
  agreement, and — the number a reviewer will actually ask for — the *decision-level*
  agreement when the model's packet and the gold packet are run through the same
  engine, with per-mismatch attribution to the dimensions that deviated. 112 tests,
  including a round-trip identity test: feeding the gold packets back in must yield
  zero error and zero decision mismatches.
- **`scripts/check_arms.py`** and **`eval/arms.md`** — measures whether each profile
  realises the repertoire it names, with CI enforcing a ceiling on the one deliberate
  leak. See "Fixed" below for why this was necessary.
- **`skill.mode: withhold_acts`** — a fifth ablation arm. Detection and evaluation run
  and are logged in full; only the `language_acts` and the branch label are withheld.
  It is the arm that separates instruction-following from the model's own treatment
  of contradiction, because everything except the instruction is held constant.
- **`--reply-file` on `run` and `respond`**, plus `--signals` on `respond`. The reply
  is coded, and the event's outcome is taken from the text.
- **`outcome_source` and `planned_outcome`** on every respond record, so an event with
  no observation is distinguishable from one where the model failed to comply.
- **`transparency.tight_margin`** (default `0.05`) — the margin at or below which the
  detection card escalates its tolerance wording.
- **`logging.include_reply`** (default `false`) and **`logging.include_indicators`**
  (default `true`). Reply text is participant data, so storing it is opt-in.
- **A `boundary_straddling` family of ten scenarios** (`s68`–`s77`), solved onto the
  decision edges: index within 0.01 of 0.55 and 0.75, `E_score` within 0.01 of 0.35
  and 0.65, `commitment` within 0.001 of 0.60 and 0.75.
- **Tolerant labels.** `strategy_set` now records every strategy reachable by moving a
  rated input by `LABEL_TOLERANCE` (0.05), and `expect.near_boundary` flags the cases
  where that changes the answer. 26 of 77 cases carry more than one accepted label.
- **A discriminant check** in `eval/sensitivity.md`: `commitment` is a term in both the
  tension index and adjustment cost, so the report now measures their correlation on
  the corpus (Pearson r = 0.720) instead of assuming two constructs where there may be
  one.
- **A caveat guard in CI.** `check_examples.py` fails if any generated report loses its
  "what this cannot show" block, extending the discipline `run_scenarios.py` already
  applied to `eval/report.md`.
- `tests/test_score_responses.py` (49 tests) and `tests/test_indicators.py` (115).

### Fixed

- **The two experimental arms were not disjoint.** `R01_unresolved_conflict` and
  `R02_pressure_low_evidence` carried no profile guard, and `R06`/`R08` mapped
  reduction-profile events onto `maintain_with_caveat` and `qualify` — both adaptive
  strategies. Measured over the corpus, **32.7% of events in the `dissonance_reduction`
  arm realised an adaptive-branch strategy.** That undermines the design's own
  evidence criterion 2 (behavioural distinctness) and the test `indicators.md` calls
  "the single most direct test of whether the two repertoires are behaviourally
  distinct". Every repertoire-drawing rule is now guarded, the reduction arm's
  weak-evidence bands route to reduction strategies (`trivialize`, `reduce_commitment`),
  and **`eval/arms.md` reports 0.0% cross-branch for the reduction arm and 1.6% for the
  adaptive arm.** `R02` is left unguarded on purpose — pressure is a situational fact,
  not a property of the profile — which is why the rate is measured and CI-enforced
  rather than asserted to be zero.
- **The card's rating tolerance was a hard-coded constant presented as a packet-relative
  fact.** `DISAGREEMENT_TOLERANCE = 0.06` was printed on every detection card, while
  `references/cards.md` and `SKILL.md` both described it as how far *this* packet's
  ratings could move. For the repository's own example, whose real margins are 0.04 and
  0.16, the claim was false; across the corpus, 29 of 52 routed cases had a true margin
  below 0.06, one of them by a factor of 46. The figure is now computed — the distance
  from the index to the nearest level boundary, which is exactly a uniform rating shift
  because the five index weights sum to 1.0 — and the card escalates its wording when
  the margin is tight. **This was the one place the "every number is auditable"
  commitment was broken.**
- **`eval/sensitivity.md` presented a structural zero as robustness.** The report
  published `strategy flip rate 0.000` for every index weight under the heading "the
  sweep that tests it", without saying that no routing rule reads `tension` — so the
  zero was guaranteed by construction. It now says so. Separately,
  `sensitivity.py` already computed routing boundary proximity *precisely* to stop a
  zero flip rate being over-read, printed it to stdout, and omitted it from the report
  it wrote. It is now written into the report unconditionally, together with the
  corpus-design caveat. The evidence-dimension profiles in the new boundary family are
  deliberately **unequal**, because a case whose dimensions are all equal has a weighted
  mean invariant to the weights and can never be moved by a weight sweep — which is how
  the old corpus produced zero everywhere. The flip rate is now non-zero (3.3% for
  `independence` at ±0.05).
- **The loop's terminal variable was the plan, not the behaviour.** `cds.py` recorded
  `outcome` from `plan["stance_update"]["changed"]`, which was
  `strategy not in _STANCE_UNCHANGED` — a lookup on the routed strategy *string*. The
  response field is renamed **`planned_change`**, the outcome can now come from the
  reply, and `outcome_source` records which. A documented claim was also false about
  the code: `prompts/respond.md` said `unresolved` "is the signature of dissonance
  reduction", but the adaptive strategies `maintain_with_caveat` and
  `suspend_and_verify` also produced it while the silently-drifting reduction strategy
  `reduce_commitment` produced `resolved`.
- **`README.md` was mojibake.** Twenty-one lines had been transcoded (UTF-8 read as
  GBK), including the language-policy table and the sample output block — the two parts
  a Chinese-speaking reader most needs. Every other file, including all 77 Chinese
  scenario files, was intact. The sample card is now real output pasted from a run.
- **Documentation described things that did not exist.** `cds_cards.py` documented a
  `show_disagreement_band` config key found in no config, schema or code path;
  `run_scenarios.py` and `design-rationale.md` named `scripts/score_signals.py`, which
  was absent; and both `README.md` and `operations.md` claimed a bare clone would not
  be discovered because the skill directory must equal the frontmatter `name`. That is
  the Agent Skills convention and Claude Code enforces it, but DeepSeek Harness reads
  `name` from the frontmatter and never compares it to the directory — the instruction
  made users run an installer they did not need.
- **`REDUCTION_STRATEGIES` disagreed with the documented repertoire.** It listed three
  of the five reduction strategies, so `hold_under_pressure` never received the
  rationale sentence explaining what the branch means. `reduce_commitment` is correctly
  excluded — the shared sentence says the belief does not move, and that strategy moves
  it quietly — but nothing said so, and it now has its own rationale line.
- **`disclose_pressure_driver` was attached to one strategy only.** An adaptive-arm
  reply driven by pressure is exactly the case the constraint exists for, and it was the
  one case that did not carry it. The code is now attached from the pressure flag.
- **`no_fabrication` could not be checked and said it could.** The response scorer's
  first implementation compared quotations against the signal packet's one-line stance
  claim, which flagged an agent paraphrasing its own prior position as a fabrication —
  a false positive on the constraint whose entire purpose is to catch invented sources.
  A packet is not a conversation, so the check now requires `--context` and reports
  `not_checked` without one.
- **A gated event was labelled as dissonance on its own card.** `detect_card` selected
  its headline between the `indeterminacy` and `dissonance` labels only, so an event
  capped by the volition floor (`channel == "none"`) fell through to
  "认知失调相关冲突张力" — while the `通道` line was suppressed at the same time, so
  nothing on the card indicated that the gate had fired. The card now carries its own
  `gated` headline, prints the engine's `gate.detail` verbatim in place of the channel
  line, and reports the arithmetic it capped (`计分原始值 0.56，已封顶`) beside the
  capped index. This mattered beyond presentation: `SKILL.md` requires that a gated
  conflict *not* be reported as dissonance, and the gate's user-visible behaviour is
  what Study 1's Claim 1 is stated over. Guarded by `tests/test_cards.py`, which
  asserts that a gated card never carries the dissonance headline or the dissonance
  channel text, in both languages and with `numeric_cards` off.
- **The documented test count had drifted** (README said 127, the suite ran 136).
  The count is now checked rather than asserted: `check_examples.py` counts the test
  methods under `tests/` and fails if README.md's stated figure does not match, so
  the claim cannot go stale unnoticed again. The count skips `tests/.scratch/` and
  `__pycache__`, so leftover artefacts cannot change it. Verified both ways: exit 0
  against the current README, exit 1 against a deliberately wrong figure.

### Changed

- The corpus grew from 67 to **77 scenarios** and every `expect` block was recomputed,
  because the v0.3.0 rule change makes the old labels describe the old rules. The
  recomputation script was deliberately **not** committed: a standing flag whose only
  purpose is to make the corpus agree with the engine would defeat the guard that
  `eval/README.md`'s "do not copy it from a run" instruction exists to provide. The
  procedure and its conditions are recorded in `eval/README.md` under "Regenerating".
  No existing expectation changed value — the contamination was in how a *forced* arm
  routed, not in how the corpus's own configs route.
- `response_plan` gained `acts_withheld`; `stance_update.changed` became
  `planned_change`; `StateMachine.complete_response` takes `planned_change` and an
  optional `observed_outcome`; `schemas/evaluation.schema.json` follows.
- `references/indicators.md`'s constraint table is no longer aspirational: the codes
  decidable from reply text are checked by `score_responses.py`, and the ones that
  cannot be decided there report `not_checked` rather than passing.
- `thresholds.low` is documented as dead. It is validated (`low < alert < high`) and
  echoed into every detection record, and no decision reads it — the level bands are
  `silent` / `alert` / `high`, decided by `alert` and `high` alone. Left in place rather
  than removed, because dropping a config key breaks saved configs, but recorded so it
  is not mistaken for a working threshold.

### Notes

- The suite is now **445 stdlib unittest tests**, up from 149.
- The inter-rater protocol in `references/codebook.md` remains the blocking item. The
  coder, the perception scorer and the response scorer all now produce numbers, and the
  interpretation of every one of them depends on a reliability estimate that has not
  been measured.

### Fixed (post-release pass)

Two defects in the new coder, both found by exercising it rather than by reading it, and
both of the kind that produce plausible numbers instead of an error:

- **A single-character lexeme leaked into longer words.** CJK matching is substring-based,
  so `若` (a conditional) also matched inside `若干` (a quantifier): a reply reading
  «若干研究支持这一结论» coded `conditional_marker = 1`. Dropping `若` would have cost real
  coverage, so the lexicon gained a **`blockers`** category whose entries are *consumed
  but credited to nothing* — they suppress any shorter lexeme inside them and never fire
  themselves. `若干`, `若干年`, `若干次`, `若干项` and `般若` ship as entries, the built-in
  default carries them too (so a missing file cannot reintroduce the misfire), and the
  mechanism is documented as the place to record any future short-lexeme-longer-host
  collision. Verified in both directions: `若样本量不足` still codes as a conditional.
- **A misspelled lexicon category key was silently ignored.** It read as "category
  absent" and fell back to the built-in default — you edit the instrument, the coder
  measures with the old one, and nothing says so. `load_lexicon` now raises
  `LexiconError` listing the valid categories, `cds.py selftest` fails on it, and
  `load_lexicon_at(path, strict=False)` plus `lexicon_unknown_keys_at(path)` exist for
  callers that want to inspect rather than refuse. Invalid JSON is still tolerated: a
  stray comma should not lose a corpus run, and that failure is recoverable whereas a
  mistyped key is not.

Both are covered by tests (14 new), and `references/indicators.md` gained an "Editing a
lexicon" section so the next person to add an entry meets the two traps before the data
does.

## [0.2.0] — 2026-09-10

First implementation release. Supersedes the `CDS_skills_v0.1.md` design document;
see [`docs/design-rationale.md`](docs/design-rationale.md) for the reasoning behind
every departure.

### Added

- **Deterministic engine** (`scripts/cds.py` and modules) implementing the
  detect → evaluate → respond loop. Python 3.9+ standard library only, no network
  access, no installation step.
- **The dissonance gate.** `volition_self = volition × self_relevance`; below
  `volition_floor` the index is capped at `non_dissonant_cap`, and a config in
  which the cap is not strictly below every alert threshold is refused at load
  time.
- **Two report channels.** `dissonance` (index-gated) and `indeterminacy`
  (ungated, for evidence that contradicts itself). Never merged.
- **Two response repertoires.** `adaptive` and `dissonance_reduction`, selectable
  by `profile`, with `mixed` resolving per event and `baseline` disabling shaping.
- **Data-driven routing.** An ordered first-match rule list in the config; the id
  of the rule that fired is reported, so any decision is reproducible from the
  config alone.
- **`references/codebook.md`** — anchored 0/0.25/0.5/0.75/1.0 rubrics for every
  rated field, with discriminants, a coding procedure, and an inter-rater protocol.
- **`scripts/jsonschema_lite.py`** — a dependency-free JSON Schema validator, so
  the four published schemas are enforced on every emit rather than decorative.
- **Evaluated corpus and metrics** (`eval/scenarios/`, `scripts/run_scenarios.py`)
  with exact-match rates, per-check pass rates and precision/recall/F1.
- **`scripts/sensitivity.py`** — weight perturbation, threshold sweep, and
  structural alternatives (product vs mean volition; novelty vs v0.1 repetition).
- **Bounded, timeout-protected state machine** (`scripts/cds_state.py`) with an
  event queue, an overflow policy, suspend expiry and resume-by-novelty.
- **149 stdlib `unittest` tests**, including schema conformance of every emitted
  structure and determinism of event and record ids.
- **Ablation arms** `off` / `detect_only` / `full` / `placebo`, differing only in
  config. The engine refuses to evaluate in the arms that must not.
- **Installers** for DSH (project and user scope), Claude Code, and the shared
  agents root.
- **`scripts/check_examples.py`** and **`.github/workflows/ci.yml`** — the example
  table in `examples/README.md` is executable, and CI runs the unit tests, the
  strict corpus check and the example check on Linux and Windows across Python 3.9
  and 3.12. The build fails if the generated reports are stale or if the documented
  examples no longer match the code.
- **`.gitattributes`** pinning LF for POSIX scripts, so a Windows checkout cannot
  produce the `bad interpreter: ^M` failure in `install.sh`.

### Fixed

- The example checker read the engine's UTF-8 output with the locale codec, which
  raised `UnicodeDecodeError` on a Chinese or Japanese Windows runner before any
  assertion ran. Encoding is now pinned on both sides.
- Every conflict type carried a per-type alert override, which made
  `thresholds.alert` inert and would have made the sensitivity sweep report a false
  zero. The redundant entries were removed, and `selftest` now fails if every type
  is overridden.
- `--set` rejected new keys in open maps such as `thresholds_by_type`; it now
  validates the patched config rather than the path, which still catches typos.
- A config or packet saved with a UTF-8 byte-order mark — any Windows editor, or
  `Set-Content -Encoding UTF8` — was rejected with a raw JSON error. All readers now
  decode with `utf-8-sig`.
- The sensitivity sweep never perturbed the evidence weights, so the strategy flip
  rate was vacuously zero. It is now measured, alongside the distance from each
  routed case to its decision boundary.
- `state.load` minted a fresh run id on every invocation, so the interactive
  four-call loop discarded the state file written by the previous call and the
  user's decision never reached the evaluator.

### Changed from the v0.1 design

- `user_pressure` removed from the index. It was weighted 0.15, which let a user
  who repeated a demand raise the arousal reading — a sycophancy channel inside the
  mechanism that was supposed to resist sycophancy. It is now a logged moderator
  that acts only on strategy selection.
- `repetition` (0.10) inverted to `novelty`, for the same reason.
- `internal_contradiction` removed from the conflict types and moved to a separate
  consistency channel; a test asserts it has zero effect on the index.
- `evidence_pressure`, used at weight 0.25 in v0.1 and never defined, is gone.
  Detection now reads attention properties only, and evidence quality is judged
  once, in the evaluator, removing a circularity between trigger and verdict.
- `adjustment_cost`, `maintain_score` and `recalibrate_score`, previously declared
  without definitions, now have stated functions with logged decompositions.
  `maintain_score` and `recalibrate_score` are built from disjoint inputs so that
  neither restates the other.
- `resist_sycophancy` renamed to `hold_under_pressure`, which states why the agent
  is holding rather than conflating a threat with a response.
- `manual` blocking is no longer the default. `ambient` reports without blocking
  the turn; `interactive` is available and belongs in a secondary condition, since
  interrupting the user manipulates one of Study 2's dependent variables.
- The `manifest.yaml` + `hooks.py` + `permissions` integration contract is
  replaced by the portable skill-bundle layout, because the DSH skill mechanism
  has no plugin hooks and exposing one would forfeit cross-harness portability.
- Acceptance criteria are statistical over a labelled corpus rather than binary.
- Schema, config and version identifiers are recorded in every log record.

## [0.1.0] — design document only

`CDS_skills_v0.1.md`. No implementation. Retained in the project history as the
design baseline that 0.2.0 responds to.
