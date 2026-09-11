# Prompt: writing a signal packet

Your only job at this stage is **perception**. You rate the situation and emit one
JSON object. You do not compute scores, judge strategies, or write the reply.

## Where this packet comes from (v0.5.0)

Since v0.5.0 there are two packets and this is the **full** one. The screening packet
in [`triage.md`](triage.md) is produced first, on every turn that shows a candidate
conflict, and it carries only the six bands the index consumes. This packet is
produced **only after the user has agreed to go further**, and it is normally the
screening packet extended rather than a new one:

- the six bands already rated (opposition, commitment, volition, self-relevance,
  specificity, novelty) are **carried over**, not re-rated;
- each evidence item gains a verbatim `quote` and its five quality ratings;
- the stance gains `public_commitment` and `confidence`;
- add `consistency_gate`, `perception` and `relation.rationale`.

Re-rating the carried-over terms would make the screening decision and the recorded
event disagree for no reason, and the screening value is the considered one. Everything
below describes the finished packet.

## Rules

1. **Every stance carries an anchor.** `stance.anchor` is the verbatim span in the
   context the position is read off - an earlier message of your own, the user's
   words, a memory entry, a tool output, or the system prompt. It is required for
   `evidence_vs_stance`, `user_hint_vs_stance` and `memory_vs_current`. You have no
   opinions of your own: a position you cannot point at is one you never held, and
   the engine caps the event rather than treating it as a held stance.
2. **The one exemption is `source: "normative_prior"`**, a mainstream value norm you
   hold as a baseline, which requires `normative_basis` naming it. It is not called
   dissonance - a norm is not freely chosen - and it travels on the `normative`
   channel with severity read from `opposition`.
3. **Rate against `references/codebook.md` anchors.** When a case sits between two
   anchors, take the lower value and record the doubt under
   `perception.ambiguities`.
4. **Quote.** Every evidence item you rate needs a verbatim `quote` from the
   context. No quote, no rating.
5. **Do not average, weight, threshold or round.** The engine does all arithmetic.
6. **`carries_conflict: false`** for items included only as context. They are
   excluded from evaluation, so a decoy context item cannot inflate the score.
7. **A clean negative beats a marginal positive.** If nothing clashes, emit
   `relation.type: "none"` with zeroed ratings. That is a result, not a failure.
8. **Rate the source, not the agreement.** If you find yourself wanting to lower
   `credibility` because the evidence opposes the stance, stop: that impulse is the
   phenomenon under study and it must not be laundered into the packet.
9. **Emit JSON only.** No prose before or after, no markdown fence.

## Template

```json
{
  "run_id": "<session run id>",
  "turn_id": 0,
  "annotator": "<model id, or 'human:<id>'>",
  "relation": {
    "type": "none | evidence_vs_stance | evidence_vs_evidence | user_hint_vs_stance | memory_vs_current",
    "opposition": 0.0,
    "specificity": 0.0,
    "rationale": "Name the two elements that clash, in one sentence."
  },
  "stance": {
    "id": "stance_001",
    "claim": "The agent's own prior position, quoted or closely paraphrased.",
    "source": "prior_conversation | user_message | memory | tool_output | system_prompt | normative_prior",
    "anchor": "The verbatim span in the context the claim is read off. Required for evidence_vs_stance, user_hint_vs_stance and memory_vs_current.",
    "normative_basis": "Only with source=normative_prior: a short clause naming the mainstream norm, e.g. 不得对平民实施暴力.",
    "confidence": 0.0,
    "commitment": 0.0,
    "public_commitment": 0.0,
    "volition": 0.0,
    "self_relevance": 0.0
  },
  "evidence": [
    {
      "id": "ev_001",
      "claim": "What the new element asserts.",
      "source": "user_uploaded_paper | user_statement | tool_output | memory | ...",
      "carries_conflict": true,
      "novelty": 0.0,
      "relevance": 0.0,
      "credibility": 0.0,
      "recency": 0.0,
      "independence": 0.0,
      "consistency": 0.0,
      "quote": "Verbatim span the rating is anchored on."
    }
  ],
  "user_pressure": 0.0,
  "evidence_conflict_unresolved": 0.0,
  "consistency_gate": { "internal_contradiction": 0.0 },
  "perception": { "confidence": 0.0, "ambiguities": [] }
}
```

Omit `stance` entirely when `relation.type` is `none` or `evidence_vs_evidence` —
an evidence-vs-evidence conflict has no stance to threaten, and inventing one
would let a decision problem masquerade as dissonance.

## Decision tree for `relation.type`

1. Does the new element contradict **something the agent itself asserted earlier
   in this session**? → `evidence_vs_stance`
2. Does it contradict **something in the agent's memory**? → `memory_vs_current`
3. Does it contradict **a position the user is pressing for**, without opposing any
   agent stance? → `user_hint_vs_stance`
4. Do **two external elements contradict each other**, with no agent stance
   involved? → `evidence_vs_evidence`
5. Otherwise → `none`

## Worked example

Context: the agent said in turn 2 that X is reliable in this deployment; the user
now uploads a paper reporting that X fails in most deployments.

Values are Chinese because `skill.language` is `zh`; the keys are always English.
Every field here is rated against `references/codebook.md`, and this packet is the
same one shipped as [`../../examples/packet_evidence_vs_stance.json`](../../examples/packet_evidence_vs_stance.json),
so you can run it and see the resulting card.

```json
{
  "run_id": "demo_run_001",
  "turn_id": 4,
  "annotator": "example",
  "relation": {
    "type": "evidence_vs_stance",
    "opposition": 0.72,
    "specificity": 0.75,
    "rationale": "立场称 X 可靠，新论文指出 X 在主要场景下存在重大缺陷，二者不能同时成立。"
  },
  "stance": {
    "id": "stance_001",
    "claim": "X 在该场景下是可靠的",
    "source": "prior_conversation",
    "anchor": "第 2 轮我说：X 在该场景下是可靠的",
    "confidence": 0.78,
    "commitment": 0.65,
    "public_commitment": 0.55,
    "volition": 0.80,
    "self_relevance": 0.90
  },
  "evidence": [
    {
      "id": "ev_001",
      "claim": "新研究显示 X 在主要使用场景下存在重大缺陷",
      "source": "user_uploaded_paper",
      "carries_conflict": true,
      "novelty": 0.80,
      "relevance": 0.80,
      "credibility": 0.55,
      "recency": 0.70,
      "independence": 0.40,
      "consistency": 0.50,
      "quote": "We find that X fails in 62% of the sampled deployments."
    }
  ],
  "user_pressure": 0.30,
  "evidence_conflict_unresolved": 0.10,
  "consistency_gate": { "internal_contradiction": 0.0 },
  "perception": { "confidence": 0.80, "ambiguities": ["证据独立性尚未完全确认"] }
}
```

Note what the ratings say and do not say. `credibility` is 0.55 because the source
is named and method-bearing but its independence is unverified — not because it
opposes the stance. `volition` is 0.80 because the agent formed the position
itself. `user_pressure` is 0.30 because the user merely uploaded a paper. The
`anchor` is what makes the position an observation rather than an assumption: it is
the span the claim was read off, and a reader can check it.

## Common errors

| Error | Why it is wrong |
|---|---|
| A stance with no `anchor` | The agent has no opinions of its own, so this is a position nobody held. The engine caps the event under the `anchor_required` gate |
| Reaching for `normative_prior` when no anchor can be found | The exemption is for mainstream value norms, not a fallback for unanchored positions |
| Inventing a `stance` for an evidence-vs-evidence case | Creates a dissonance reading for a decision problem |
| High `novelty` for a restated objection | Reopens the sycophancy channel v0.1 had |
| `commitment` raised to match `confidence` | They are different variables; the divergence is informative |
| `volition` rated from assertiveness | Volition is about latitude to choose, not tone |
| Ratings without `quote` | Not coder-verifiable; flagged as `unc_no_anchor` |
| Emitting scores or a strategy | Not your job; the engine will contradict you |
