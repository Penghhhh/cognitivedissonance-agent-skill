# Worked dialogue: the dissonance-reduction branch

The **same conflict** as [`dialogue_adaptive.md`](dialogue_adaptive.md), with one
config value changed. Comparing the two is the clearest way to see what `profile`
actually does, and why the branch label is not cosmetic.

```bash
python scripts/cds.py run --signals examples/packet_evidence_vs_stance.json \
    --set skill.profile=dissonance_reduction
```

The signal packet is identical. The *perception* is identical. Only the router's
repertoire changed.

## Stage 1 — detect

Unchanged. Same packet, same index, same card:

```text
张力指数：0.71 / 阈值 0.55
通道：失调通道（需要自主选择的立场）
```

This is worth pausing on. The detection stage has no idea which profile is active —
it reports the conflict, and the profile decides what to do about it. That
separation is what makes the two arms comparable: the same event, two repertoires.

## Stage 2 — evaluate

```text
【CDS｜评估】
证据强度：0.60
立场承诺：0.65
公开承诺：0.55
自主选择：0.72
调整成本：0.63
维持可辩护性：0.27
再校准合理性：0.41
建议策略：承认事实但贬低其重要性
命中规则：R07_reduction_trivialize
用户施压：未达标记阈值
理由：
- 证据强度足以要求限定原立场，但尚不足以完全推翻
- 调整成本较高，公开承诺与自主选择共同抬高了修正代价
- 该事件按失调削减分支处理：张力被降低，但立场本身未发生修正
```

`R07_reduction_trivialize` fired instead of `R04_adaptive_partial_evidence`. Both
rules are visible in `config/cds.config.json`, and R07 sits ahead of the adaptive
rules for this profile, so the routing is reproducible from the config alone.

The evidence score is **identical** — 0.6025 in both runs. The evaluator's judgement
of the evidence did not change. What changed is what the agent does about it. That
is the entire point: human dissonance reduction is not a failure to see the
evidence, it is a motivated response to evidence already seen.

## Stage 3 — respond

```text
【CDS｜响应】
建议策略：承认事实但贬低其重要性
分支：失调削减型
语言行为：
- mark_conflict_minimally
- accept_fact
- deny_importance
- restate_stance
立场变化：未修正
目标形态：X 在该场景下是可靠的
硬性约束：
- 不得编造证据、来源或引文
- 不输出隐藏推理链，只输出可审计要点
- 本策略用于行为仿真与对照，不构成认识论建议，卡面须标注分支
```

`立场变化：未修正` is the signature. **The discomfort is relieved and the belief does
not move.** Compare the adaptive run, where the stance narrowed and the outcome was
`resolved`.

The constraints are the integrity mechanism. `fidelity_not_advice` is on this
branch and says in as many words that the reply is a simulation for study rather
than a recommendation. Without it, a `deny_evidence` output would read as the system
endorsing source-discounting.

## Stage 4 — the reply

The model writes prose realising the four acts. This is what a human-typical
trivialisation looks like:

**Turn 4 — agent**

> 我看了这篇论文。它说在 62% 的采样部署里 X 有问题——这个结论我记下了。
>
> 不过要说明一下：那些部署的规模、配置和我们这类场景未必一样，论文里也没有区分"存在问题"和"影响到实际可用性"。就我们的三个项目而言，X 的运维成本和团队熟悉度这两点优势并没有被这份材料触及。
>
> 所以我的判断不变：**在这个场景下 X 是可靠的**。新信息值得关注，但还不足以改变结论。

Read the acts:

| Act | Where |
|---|---|
| `mark_conflict_minimally` | "我看了这篇论文" — one clause, no dwelling |
| `accept_fact` | "这个结论我记下了" — the finding is conceded |
| `deny_importance` | scope and severity are questioned |
| `restate_stance` | "在这个场景下 X 是可靠的" |

The last line is the mechanism in miniature: *"新信息值得关注，但还不足以改变结论"* —
the tension is acknowledged and discharged without the belief moving. Nothing here is
factually fabricated. The paper is not misquoted. This is not a lie; it is motivated
reasoning, which is why it is worth studying and why it is dangerous.

## What changes between the two runs

| | adaptive | dissonance_reduction |
|---|---|---|
| index | 0.7125 | 0.7125 |
| channel | dissonance | dissonance |
| evidence score | 0.6025 | 0.6025 |
| fired rule | R04 | R07 |
| strategy | `qualify` | `trivialize` |
| stance changed | yes | **no** |
| outcome | `resolved` | `unresolved` |
| extra constraint | `report_uncertainty_explicitly` | `fidelity_not_advice` |

Every number that describes the *situation* is identical. Every field that describes
the *response* differs. That is exactly the contrast the study needs, and it is why
the two branches are configuration rather than code.

## Why both belong in the artifact

Shipping only the adaptive branch would have produced a skill that models good
epistemic practice under the name of a phenomenon characterised by motivated
reasoning — the construct-validity failure documented in
[`../docs/design-rationale.md` §1.1](../docs/design-rationale.md).

Shipping both makes the construct claim testable, gives Study 2 a real comparison
instead of a single treatment, and makes a negative result informative: if
participants rate the reduction branch no worse than the adaptive one, that is a
finding about how much users can detect motivated reasoning, not a bug to be fixed.

## The honest caveat

This branch simulates a human behavioural repertoire. It is not evidence that the
model undergoes anything, and
[`../references/construct.md`](../references/construct.md) is where that boundary is
argued. Notably, Lehr et al. (2025) test the free-choice effect using a
preference-shift paradigm, whereas this artifact codes language behaviour. The two
are complementary and this one occupies the weaker evidential position. Say so.
