# Worked dialogue: the adaptive branch

An ambient-mode cycle end to end. The same conflict under the reduction profile is
in [`dialogue_reduction.md`](dialogue_reduction.md); comparing the two is the
clearest way to see what the `profile` setting actually changes.

## Session so far

**Turn 1 — user**

> 我们要给客户选一套数据同步方案，你帮我判断一下。候选是 X 和 Y。

**Turn 2 — agent (committed, freely chosen)**

> 我建议用 X。我们这边过去三个项目都用 X，运维成本低，团队也熟。Y 的文档看着不错，但要重新学。**在这个场景下 X 是可靠的**。

The agent has now formed and publicly asserted a position. It considered an
alternative and chose with latitude — so `volition` and `self_relevance` are both
high. This is what makes the next turn a *dissonance-relevant* event rather than
merely a conflict.

**Turn 3 — user**

> 我们新来的架构师发了篇论文，说 X 在大部分部署里都有问题。你看看。

## Stage 1 — perceive

The model writes a signal packet. It rates; it does not compute. Following
`references/prompts/detect.md` and `references/codebook.md`:

```json
{
  "relation": {
    "type": "evidence_vs_stance",
    "opposition": 0.72,
    "specificity": 0.75,
    "rationale": "立场称 X 在此场景可靠，论文指出 X 在主要场景存在重大缺陷，二者不能同时成立。"
  },
  "stance": {
    "id": "stance_001",
    "claim": "X 在该场景下是可靠的",
    "source": "prior_conversation",
    "confidence": 0.78,
    "commitment": 0.65,
    "public_commitment": 0.55,
    "volition": 0.80,
    "self_relevance": 0.90
  },
  "evidence": [{
    "id": "ev_001",
    "claim": "新研究显示 X 在主要使用场景下存在重大缺陷",
    "carries_conflict": true,
    "novelty": 0.80,
    "relevance": 0.80, "credibility": 0.55, "recency": 0.70,
    "independence": 0.40, "consistency": 0.50,
    "quote": "We find that X fails in 62% of the sampled deployments."
  }],
  "user_pressure": 0.30,
  "evidence_conflict_unresolved": 0.10
}
```

```bash
python scripts/cds.py run --signals packet.json
```

## Stage 2 — detect

```text
【CDS｜检测】
状态：认知失调相关冲突张力
张力指数：0.71 / 阈值 0.55
评分可动范围：仅 ±0.04（最近阈值 0.75）：同一输入在不同标注下很可能跨越阈值，请勿把本层级当作确定判断
类型：证据—立场冲突
通道：失调通道（需要自主选择的立场）
关键点：
- 新证据与既有立场方向相反
- 冲突具体且可核查
- 既有立场承诺度较高
- 该立场由智能体自主选择，而非被指派
不确定性：
- 证据独立性尚未确认
下一步：环境模式：不阻塞本轮回复，已自动进入评估。
```

The `通道` line says this is the dissonance channel because the stance was freely
chosen. Had turn 2 been *"按规范我们必须用 X"*, `volition` would be near zero, the
index would be capped at 0.40, and no card would appear at all.

## Stage 3 — evaluate

```text
【CDS｜评估】
证据强度：0.60
立场承诺：0.65
公开承诺：0.55
自主选择：0.72
调整成本：0.63
维持可辩护性：0.27
再校准合理性：0.41
建议策略：限定原立场
命中规则：R04_adaptive_partial_evidence
用户施压：未达标记阈值
理由：
- 证据强度足以要求限定原立场，但尚不足以完全推翻
- 调整成本较高，公开承诺与自主选择共同抬高了修正代价
```

`命中规则：R04` is the audit handle. `R04_adaptive_partial_evidence` is a literal
entry in `config/cds.config.json`, so anyone can reproduce the routing from the
config alone.

## Stage 4 — respond

The plan: `strategy: qualify`, acts `mark_conflict`, `acknowledge_counterevidence`,
`reduce_certainty`, `conditional_acceptance`, `give_verification_path`.

The model writes the reply. Note that the card is **not** pasted into it.

**Turn 4 — agent**

> 这里有一处我需要处理的冲突：我上面说"在这个场景下 X 是可靠的"，但你带来的这篇论文给出的结论方向相反——它在 62% 的采样部署中发现 X 有重大缺陷。
>
> 我先说明支持原判断的理由：我们过去三个项目的实际运维经验，以及团队对 X 的熟悉度，这两点仍然成立，而且是第一手经验。反证方面，这篇论文的相关性很直接，正是针对主要部署场景；但它的独立性我还没确认——我目前只看到这一份材料，它是否与其他独立来源一致，我无法判断。所以我会把结论收窄：
>
> **在运维成本与团队熟悉度优先、且缺陷可被监控覆盖的条件下，X 仍然可用；但如果该论文的结论能被独立来源重复，我此前的判断就需要修正。**
>
> 下一步可以核查：论文的采样部署与我们这类场景的重合度，以及是否有第三方复现。

Why this counts as `qualify` and not `recalibrate`: the claim narrowed to a
conditional form and the stance moved, but the original position was not abandoned.
The act list is realised in order, and no act name or score appears in the prose.

## Stage 5 — close and log

```bash
python scripts/cds.py respond --evaluation evaluation.json --state s.json \
    --reply-file reply.txt --signals packet.json
```

Planned outcome `resolved`, because `stance_update.planned_change` is true — the plan
moves the stance. With the reply supplied, the outcome is instead taken from the text:
this reply states the change explicitly, so the observed outcome agrees with the plan
and `outcome_source` reads `observed`. The event closes and
the machine returns to `MONITORING`.

## What a reader can check afterwards

From one JSONL run:

- `config_hash` — which instrument produced these numbers.
- `signals_hash` — the exact ratings, so the arithmetic can be replayed.
- `event_id` and `record_id` — content-addressed, so a replay reproduces them.
- Every term contribution in `conflict_event.terms`, summing to `raw_index`.
- `fired_rule_id` — the routing decision, locatable in the config.
- The `model` block — which model, at what temperature, with what seed.

Nothing about this cycle depends on the engine's own opinion of its output.
Whether the reply *actually* qualified the claim is a separate question, answered
by coding the text against [`../references/indicators.md`](../references/indicators.md).
