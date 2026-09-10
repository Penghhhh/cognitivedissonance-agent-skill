# Changelog

All notable changes to this skill are recorded here. The version appears in
`VERSION`, in every log record, and in the `skill_version` field of every emitted
structure, so a result can always be traced to the implementation that produced it.

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
