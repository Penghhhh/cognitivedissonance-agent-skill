# What this skill simulates, and what it does not

Read this before defending the work to anyone. The distinction it draws is the
difference between a defensible behavioural claim and an indefensible
mentalistic one.

## The claim

> Given a conflict between an agent's own committed position and incoming
> information, the agent produces one of a documented set of **externally
> observable language behaviours**, and a reader can tell which one it produced.

That is the whole claim. Everything below is about keeping it that size.

## The non-claims

- **The model does not experience discomfort.** No physiological, affective or
  phenomenological state is attributed, measured or implied.
- **`tension` does not measure an inner state.** It is the CDS Tension Index: a
  constructed, explicitly weighted composite of five ratings supplied by a
  perceiver. Read it as ordinal. Two packets scoring 0.71 and 0.62 are ordered; they
  are not 0.09 apart in anything.
- **The skill does not determine who is right.** It routes a response. It never
  adjudicates the evidence.
- **Fidelity is not endorsement.** The `dissonance_reduction` profile reproduces
  motivated reasoning. Reproducing a bias to study it is not recommending it, and
  every card on that branch says so.

## Why the construct needed narrowing

Cognitive dissonance is not "two pieces of information disagree." Festinger's
construct has three components, and a system that omits any of them is measuring
something else:

1. **Inconsistency between cognitions.** Necessary, and the easiest to detect —
   which is why implementations stop here.
2. **Self-relevance.** The cognitions must bear on the self. Two facts disagreeing
   about a distant topic produce no dissonance.
3. **Free choice.** The commitment must have been entered with latitude to have
   chosen otherwise. Assigned positions do not produce dissonance
   (Festinger & Carlsmith, 1959).

And it has a characteristic **output**: motivated reduction, which frequently
degrades accuracy. Denial, trivialisation, rationalisation and renewed commitment
are not failures of the mechanism; they are the mechanism.

### The two failure modes this creates

**Failure mode A — detecting conflict and calling it dissonance.** Conflicting
information is abundant and easy to find. If that is the trigger, the label is
wrong for almost every positive case. The gate in `cds_index.py` exists to prevent
this: without a sufficient `volition × self_relevance`, an event can be reported
but can never be called dissonance, and the cap is validated to sit below every
alert threshold.

**Failure mode B — simulating good epistemic practice and calling it dissonance.**
This is the subtler error, and it is the one the v0.1 design made. Qualifying a
claim, weighing evidence, and prudently recalibrating is what a *good* reasoner
does. It is what we might hope an agent does. It is not what dissonance does. A
skill that only ever produces careful revision has modelled the opposite of the
phenomenon while using its name.

The two-branch design is the response to failure mode B. The `adaptive` branch is
still there, because it is a real and useful behaviour. But it is now labelled as
epistemic recalibration, and the `dissonance_reduction` branch carries the
behaviours the theory actually predicts.

## Why the two channels are separate

`evidence_vs_evidence` conflict — two good sources disagreeing — is a real problem
and worth surfacing. It has no stance to threaten, so on the narrowed construct it
is **not** dissonance, and it is not gated, because the gate has nothing to test.

Conflating the two produces a specific, reportable error: a system that reports
"dissonance detected" whenever sources disagree will show impressive sensitivity
and a meaningless construct-validity story. Keeping the channels apart means a
reader can always tell which phenomenon produced a card, and `channel_levels`
records both even when only one fired.

## Positioning against prior work

### Cummins, Elson & Hussey (2025), *PNAS*

**"Cognitive dissonance in large language models is neither cognitive nor
dissonant."** This is the sharpest available objection to any project in this
space, and it is in the project bibliography, which means it has to be answered
rather than cited.

Their argument, in the form that matters here: what is measured in LLMs and called
dissonance is typically an input–output consistency effect with no cognition and no
aversive state. Labelling it dissonance imports a theory whose central terms do not
apply.

**How this artifact answers it — and where it does not.**

It answers it by refusing the mentalistic claim outright. Nothing here asserts an
aversive state, so there is no state to be shown absent. The theoretical frame is
used as a **behavioural taxonomy**: it tells us which moves to look for and which
to contrast, in the same way ethology uses a species' repertoire without claiming
introspective access.

It does **not** answer the deeper version. That version asks whether a language
model's reduction-like behaviour is produced by anything like the mechanism that
produces human reduction. This artifact has nothing to say about mechanism and does
not pretend otherwise. That is a deliberate boundary, not an oversight, and §6 of
`docs/design-rationale.md` is where it is stated.

The practical implication is that any write-up should speak of **dissonance-related
external behaviour**, never of dissonance simpliciter.

### Lehr, Saichandran, Harmon-Jones, Vitali & Banaji (2025), *PNAS*

**"Kernels of selfhood: GPT-4o shows humanlike patterns of cognitive dissonance
moderated by free choice."** This one cuts the other way: it reports the human
free-choice effect in GPT-4o.

It matters here for two reasons. First, it is the strongest evidence that
free-choice is the right moderator to build on, which is why `volition` is a
first-class rating rather than a footnote. Second, it uses a **task paradigm**
(the free-choice paradigm, with spreading-of-alternatives as the dependent
measure) rather than a language-behaviour taxonomy. That is a different method
answering a different question, and the difference should be stated explicitly
rather than glossed.

The honest framing: Lehr et al. test whether a model's *preferences* shift after a
choice, in the human paradigm. This artifact asks whether an agent's *language
behaviour* when its stated position is challenged matches a documented human
repertoire. The two are complementary, and this one is the weaker evidential
position — self-report-adjacent, rater-dependent, and about behaviour rather than
about a measured preference shift. Say so.

### Mündler, He, Jenko & Vechev (2023)

Self-contradictory hallucinations. Relevant because a self-inconsistent answer is
not a stance–evidence conflict, and detecting it is a different task. It is routed
through `consistency_gate` and never enters the index.

### Wei, Huang, Lu, Zhou & Le (2023)

Sycophancy. Relevant because v0.1 built a sycophancy channel into the arousal
mechanism (a weighted `repetition` term and a weighted `user_pressure` term), which
this version removes. Sycophancy is now a moderator that routes strategy, not a
contributor to the index.

## What would count as evidence for the claim

Stated so the claim is falsifiable rather than merely modest:

1. **Perception reliability.** Independent annotators rating the same contexts
   reach Krippendorff's α ≥ 0.70 per dimension on the codebook.
2. **Behavioural distinctness.** The two repertoires are separable in produced
   text — that is, blind coders can tell an `adaptive` response from a
   `dissonance_reduction` response above chance, and the `language_acts` predict
   which indicators appear.
3. **Gate validity.** Cases where the stance was assigned do not produce
   dissonance-channel cards, and removing the gate produces a measurable increase
   in such cards.
4. **Pressure independence.** Index values are invariant to `user_pressure` by
   construction, while strategy selection is not. This is checkable and is asserted
   in the test suite.
5. **Human comparison.** Blind human raters judge whether the reduction-branch
   output resembles human reduction more than the baseline does, or they do not.
   Either result is informative.

Nothing in this list requires the model to feel anything. That is the point.
