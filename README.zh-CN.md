# CDS-Skill

CDS-Skill（Cognitive Dissonance Simulation，认知失调模拟）是一个可插拔的 LLM agent
技能组件，适用于 DeepSeek Harness、Claude Code，或任何会扫描 skills 目录的工具。当对话中
新出现的信息与 agent 自己先前说过的立场相矛盾时，它会检测出这一冲突，并交给一套明确、
可审计的应对策略来处理。纯 Python 3.9+ 标准库实现（无需 `pip install`、无依赖、不联网）；
它是关于批判性/辩证思维研究的研究工件，研究层面的论述见
[`docs/design-rationale.md`](docs/design-rationale.md)，不放在本 README 中。

## 你会看到什么

Agent 没有自己的观点。它推理所依据的每一个立场都必须从对话上下文中提取；只有当存在一个
可引用的原文片段时才会提出冲突：agent 之前说过的话、你消息里的内容、一条记忆条目，或一次
工具输出。它绝不会虚构「我本来要说的话」。唯一的例外是主流价值规范（例如「针对平民的暴力
是错误的」），这类内容走单独的通道，永远不会被标记为认知失调。

1. **绝大多数回合：什么都不会发生。** 没有卡片，也不会提到这个技能。引擎只打印一行
   `CDS_GUARD silent`，模型不会展示给你。这是最常见的情况。
2. **明确的冲突：一张卡片，然后助手停下来。** 卡片指出两个相互冲突的说法、冲突大小，以及
   先前那个说法是从哪段原文提取出来的；接着助手**结束当前回合并请你做选择**——不会先把答案
   写出来。选项：处理 / 忽略 / 稍后。你也可以不选，直接输入自己的回答。
3. **你选择「处理」之后：** 助手会评估证据、说明将采用的策略，然后才写回复。回复结尾是
   **一行**审计信息，指明日志文件，例如
   `CDS 已记录 · 事件 cds_evt_ab12cd34ef56 · 日志 logs/cds_skill.jsonl`。
   除此之外，回复中不会再出现关于这个组件的任何内容。

卡片示例（运行时原样输出）：

```text
【CDS｜检测】发现上下文矛盾冲突
观点1（我先前的说法）：「X 在该场景下是可靠的」
观点2（新出现的信息）：「新研究显示 X 在主要使用场景下存在重大缺陷」
冲突大小：0.71（门槛 0.62，较明显）
类别：新证据与我先前的说法相反——被冲击的是我自己选定并说过的判断。
依据原文：第 2 轮我说：X 在该场景下是可靠的

是否进入评估？
· 回复「处理」→ 我评估证据分量，并给出应对策略
· 回复「忽略」→ 按普通对话继续，不再就同一处冲突打扰你
· 回复「稍后」→ 先记下，出现更新信息时再提
```

真实运行时输出；运行时语言默认为中文（`skill.language: "zh"`）。

幕后的筛查刻意做得很轻：在需要筛查的回合，模型只运行一条命令、传六个粗粒度档位词，
不需要 JSON 文件。

```bash
python scripts/cds.py guard --type evidence_vs_stance \
  --screen "opp=high,commit=high,vol=high,self=high,spec=high,nov=high" \
  --stance "X 在该场景下是可靠的" \
  --anchor "第 2 轮我说：X 在该场景下是可靠的" \
  --evidence "新研究显示 X 在主要使用场景下存在重大缺陷" \
  --state cds-state.json --ask
```

档位取值为 `none | low | mid | high`（= 0.00 / 0.30 / 0.60 / 0.85）；也可以直接传小数。
`--ask` 会打印卡片，以及宿主模型交给其提问工具的选择结构。档位定义见
[`references/prompts/triage.md`](references/prompts/triage.md)。完整流程
（`detect` → `evaluate` → `respond`）**只**在你回复「处理」之后才运行。

## 如何开启

**每个会话输入一次 `/cds-skill` 即可。** 不是每条消息都要输入：这一次激活之后，技能在该会话
的剩余时间内保持开启，在后台静默筛查**每一个**回合。新会话需要重新输入 `/cds-skill`——
跨会话不保留任何状态，只有一个 JSONL 日志文件和可选的状态文件。

想让它每个回合都自动可用、无需手动输入？删除 `SKILL.md` 中的
`disable-model-invocation: true` 这一行，harness 就会把它列入技能目录、由模型自行决定是否
调用。代价：每个回合多占一点固定的目录开销，并且「模型是否调用它」会从受控变量变成被测量的
变量。

## 安装

```bash
git clone https://github.com/Penghhhh/cognitivedissonance-agent-skill.git
cd cognitivedissonance-agent-skill
```

然后运行下面其中**一条**（Windows 用 `./install.ps1 -Target X`，macOS/Linux 用 `./install.sh X`）：

| 目标 | 安装到 | Windows | macOS / Linux |
|---|---|---|---|
| 所有项目（推荐） | `~/.dsh/skills/cds-skill` | `./install.ps1 -Target dsh-user` | `./install.sh dsh-user` |
| 仅某个项目 | `<project>/.dsh/skills/cds-skill` | `./install.ps1 -Target dsh-project -ProjectRoot "<project>"` | `PROJECT_ROOT="<project>" ./install.sh dsh-project` |
| Claude Code | `~/.claude/skills/cds-skill` | `./install.ps1 -Target claude-user` | `./install.sh claude-user` |
| 任何 `~/.agents` harness | `~/.agents/skills/cds-skill` | `./install.ps1 -Target agents-user` | `./install.sh agents-user` |

`<project>` 指你在 harness 中打开的文件夹（工作区根目录），**不是** clone 出来的仓库目录。
一个坑：`dsh-project` 不带 `-ProjectRoot` / `PROJECT_ROOT` 时，会安装到你当前所在的目录
（也就是 clone 仓库本身），技能会落深一层，永远不会显示出来。

最后验证：运行安装器打印出来的 `selftest` 命令（应输出 `selftest OK`），开一个新会话，
输入 `/cds-skill`。

顺带两个细节：安装后的文件夹名固定是 `cds-skill`（取自技能 frontmatter 里的 `name`），
不会跟仓库同名；覆盖已有安装需要加 `-Force`（PowerShell）或 `FORCE=1`（shell）。

## 不用 harness 快速试用

```bash
python scripts/cds.py selftest
python scripts/cds.py run --signals examples/packet_evidence_vs_stance.json
python scripts/cds.py guard --signals examples/triage_sparse_conflict.json --state cds-state.json --ask
```

验证 checkout：

```bash
python -m unittest discover -s tests -t tests   # 554 个标准库 unittest 测试
python scripts/check_examples.py
```

## 设置

都在 [`config/cds.config.json`](config/cds.config.json)：

| 键 | 取值 | 说明 |
|---|---|---|
| `skill.mode` | `off` / `detect_only` / `full` / `placebo` / `withhold_acts` | 实验分组 |
| `skill.profile` | `adaptive` / `dissonance_reduction` / `mixed` / `baseline` | `adaptive` = 良好的认知实践（`maintain_with_caveat`、`qualify`、`recalibrate`、`suspend_and_verify`）；`dissonance_reduction` = 人在失调状态下的真实表现（`deny_evidence`、`trivialize`、`rationalize`、`reduce_commitment`、`hold_under_pressure`）——追求仿真度，**不是**建议 |
| `skill.language` | `zh`（默认）/ `en` | 运行时输出语言 |
| `guard.policy` | `ask`（默认）/ `auto` / `log_only` | `guard.enabled: false` 可关闭筛查 |
| `guard.require_anchor` | `true`（默认） | 没有可引用的锚点，就不出冲突卡片 |
| `guard.stop_and_ask` | `true`（默认） | 卡片会结束当前回合 |
| `transparency.card_style` | `plain`（默认）/ `technical` | 卡片风格 |
| `transparency.audit_note` | `one_line`（默认）/ `off` | 结尾的审计行 |
| `logging.path` | `logs/cds_skill.jsonl` | 每次筛查都会记录，包括静默通过的 |

## 局限

- 只模拟**外部语言行为**；这里没有任何内容声称模型会感到不适。
- 指标权重和 guard 阈值是**设计先验，不是校准结果**；敏感性测量见
  [`eval/sensitivity.md`](eval/sensitivity.md)。
- reduction 分支是**指令式**模拟，不是自发动态；`withhold_acts` 分组就是为了区分这两者。
- 锚点能减少评分者漂移，但评分者间一致性协议尚未实际执行。
- 筛查门的漏报率可以从日志中测出，但还没有测。
- 这是一个研究原型（v0.5.0）。

## 仓库结构

```text
SKILL.md                   # 技能定义（用户通过 /cds-skill 手动激活）
scripts/cds.py             # 命令行：guard · detect · evaluate · respond · command · status · run
scripts/                   # 引擎模块：index、guard、evaluator、state、cards、screen
config/cds.config.json     # mode、profile、guard、transparency、logging 设置
references/                # prompts/triage.md、codebook.md、operations.md
examples/                  # 现成的 packet 与对话示例
eval/                      # 场景语料库与生成的报告
docs/                      # design-rationale.md、readme-archive-v0.4.md
tests/                     # 标准库 unittest 测试
logs/cds_skill.jsonl       # 运行时写入：每次筛查都有记录，含静默通过的
install.ps1 / install.sh   # 安装脚本
CITATION.cff / NOTICE.md   # 引用信息；负责任使用说明
```

## 链接

- [`docs/design-rationale.md`](docs/design-rationale.md) — 每个设计决策的原因
- [`docs/readme-archive-v0.4.md`](docs/readme-archive-v0.4.md) — 之前的长版 README
- [`references/codebook.md`](references/codebook.md) — 评分细则
- [`references/operations.md`](references/operations.md) — 全部命令、状态机、故障排查
- [`examples/`](examples/) — 现成的 packet 与对话示例
- [`eval/`](eval/) — 场景语料库与生成的报告
- [`CITATION.cff`](CITATION.cff)
- [`LICENSE`](LICENSE) — MIT；文档同时以 CC BY 4.0 提供
- [`NOTICE.md`](NOTICE.md) — reduction profile 的负责任使用说明（在用户可能把模拟误当成建议的场合启用前，请先阅读）

## 许可

MIT（见 [`LICENSE`](LICENSE)）；文档同时以 CC BY 4.0 提供。
