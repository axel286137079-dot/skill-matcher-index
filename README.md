# skill-matcher-index

> skill-matcher 的开源技能目录 · Community Skill Index —— 由社区共建，AI 审核员每晚自动审核合并。

**当前收录：15 个技能**（`index.json`，数据版本 **v4**，所有安装者联网同步）

## 这是什么

[skill-matcher](https://github.com/axel286137079-dot/skill-matcher) 是一个中立的「需求 ↔ 技能」匹配器：四层递进读懂你的需求（L0 字面 → L1 语义 → L2 意图 → L3 潜在需求），从本地已装技能、市场技能、专家目录中给出 Top3 匹配与理由。

本仓库是它的**公开技能目录**：`index.json`。每个安装了 skill-matcher 的用户都可以为目录添砖加瓦——装的人越多 → 目录越全 → 匹配越准 → 更多人受益。

- 技能主页：https://github.com/axel286137079-dot/skill-matcher
- SkillHub：https://skillhub.cn/skill/skill-matcher

## 目录数据长什么样（v4）

```json
{
  "id": "pdf",
  "name": "pdf",
  "description": "PDF 文档处理：读取、提取文本/表格、合并拆分、生成 PDF。Official Anthropic document skill.",
  "install": "git clone https://github.com/anthropics/skills",
  "source": "opensource",
  "origin": "anthropics/skills",
  "homepage": "https://github.com/anthropics/skills",
  "tags": ["pdf", "document", "data"],
  "aliases": ["pdf 处理", "pdf 提取", "pdf 表格", "pdf extraction", "pdf forms"],
  "added_at": "2026-09-26"
}
```

- `tags` 是**受控词表**（34 个小写 ASCII 词）：匹配器分词器对 ASCII 取整词、对中文取 bigram，所以 ASCII 标签能直接命中用户查询词，权重最高。词表与中文对照见 [`schema/README.md`](schema/README.md)。
- `aliases` 是中英别名/近义词（前瞻字段：为条目级别名召回预留，当前版本的引擎还不读取它——详见 [CHANGELOG](CHANGELOG.md) 的兼容性表）。
- 必填字段始终只有 4 个：`id` / `name` / `description` / `install`。**新增字段一律可选**，消费者必须忽略未知字段。

## 数据契约（机器可校验）

| 文件 | 作用 |
|---|---|
| [`index.json`](index.json) | 唯一数据文件，所有安装者联网同步它 |
| [`schema/index.schema.json`](schema/index.schema.json) | 顶层契约；含 v4 条件规则（`version >= 4` ⇒ 每条目必须有 `tags`/`aliases`/`added_at`） |
| [`schema/skill.schema.json`](schema/skill.schema.json) | 单条目契约；含 `tags` 受控词表 |
| [`scripts/validate.py`](scripts/validate.py) | 零依赖机器预审（CI 与本地同款） |
| [`scripts/check_schema.py`](scripts/check_schema.py) | JSON Schema 严格校验 + **schema 自证**（负样本必须被拒）+ 防两份实现漂移 |

```bash
python3 scripts/validate.py index.json                  # 零依赖、本地可跑
python3 scripts/check_schema.py                         # 需 jsonschema，否则自动跳过
python3 scripts/selftest.py                             # 规则自测（正/负样本）
```

## 如何贡献（3 步）

1. **拿到候选清单**：先 clone 主仓库 [skill-matcher](https://github.com/axel286137079-dot/skill-matcher)，在其根目录运行 `python3 bin/sync_index.py --collect-contributions`（脚本在主仓库，不在本仓库），生成 `index/contributions/candidates.json`。
2. **提交贡献文件**：把你想公开的技能整理成 JSON 数组，在本仓库新建 `contributions/<你的GitHub用户名>.json`（格式见 [CONTRIBUTING.md](CONTRIBUTING.md) 和示例 [contributions/_example.json](contributions/_example.json)），提交 Pull Request——CI 会自动跑机器预审；也可以直接开 Issue，按模板贴「技能名 / 描述 / 安装方式」。
3. **等审核**：AI 审核员每晚 23:00 自动审核（机器预审 → AI 安全+质量裁决 → 合并 → 发布 `index.json`）。

三条红线：**不含密钥 · 不含危险指令 · 不伪造刷量**。详见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 审核与共识机制

- 每条贡献经过：机器预审（格式/敏感词/质量分/查重）→ AI 审核（安全+质量）→ 人工兜底抽查。
- **机器预审已实现为本仓库脚本**（零依赖、本地可跑；CI 逐步启用）：

  | 校验 | 命令 | CI 状态 |
  |---|---|---|
  | 格式/字段/查重/敏感词/v4 元数据契约 | `python3 scripts/validate.py index.json` | ✅ 已启用 |
  | 贡献文件与共识统计 | `python3 scripts/validate.py contributions` | ✅ 已启用 |
  | 留痕 ⇄ `index.json` 双向一致 | `python3 scripts/validate.py index.json --check-review-log --strict` | ⏳ 见 [ci/README.md](ci/README.md) |
  | 死链探测（网络异常降级为告警） | `python3 scripts/validate.py index.json --check-deadlinks` | ⏳ 见 [ci/README.md](ci/README.md) |
  | JSON Schema + schema 自证 + 防漂移 | `python3 scripts/check_schema.py --require` | ⏳ 见 [ci/README.md](ci/README.md) |
  | 规则自测（每条规则配负样本） | `python3 scripts/selftest.py` | ⏳ 见 [ci/README.md](ci/README.md) |

  ⏳ 的原因：本仓库当前的 GitHub 连接**没有 `workflows` 权限**，任何改动 `.github/workflows/*` 的提交都会被 push 拒绝。因此 CI 加固以补丁交付：[`ci/validate-workflow.patch`](ci/README.md)（actions 固定 commit SHA + 上述四步 + 最小权限），`git apply` 一行命令即可启用。
- **AI 审核（每晚 23:00）**：由维护者侧的 AI 审核助手执行并合并发布，实现位于维护者环境，未包含在本仓库；本仓库 CI 绿灯 = 机器预审通过。
- **留痕**：每次入库裁决写进 [`review-log/`](review-log/README.md)（append-only），记录裁决依据与可验证证据 —— 「谁在什么时候、凭什么」把条目放进了公共目录。
- 同一技能被 **≥3 个不同用户**独立提交 → 共识达成，自动采纳进 `index.json`。
- 未达共识的条目进入 `pending`，会在 PR/Issue 中说明原因。

## 已知问题（重要，公开透明）

两个客户端（`plugin/lib/engine.js`、`bin/sync_index.py`）都会对远程目录做 **SHA256 钉扎**防篡改，但远程 URL 指向**可变**的 `raw.githubusercontent.com/.../main/index.json`。这会让**任何目录更新**（包括 v4）被误判为「源可能被篡改」而拒绝。

修复方向（主仓库改动）：**版本单调递增即接受 + tag 固定拉取（`@v<version>`，jsDelivr 主源 / raw 备用源）**。完整分析与迁移清单见 [CHANGELOG.md](CHANGELOG.md) 的「已知阻断问题」。

## 目录结构

```
index.json                  # 全局开源技能目录（所有安装者联网同步的目标文件）
schema/                     # 数据契约：index / skill 的 JSON Schema + 词表说明
scripts/validate.py         # 机器预审脚本（CI 与本地共用，零依赖）
scripts/check_schema.py     # JSON Schema 校验 + schema 自证 + 防漂移
scripts/selftest.py         # 规则自测（正/负样本）
contributions/<user>.json   # 各贡献者的提交（待审核，_ 开头为示例）
review-log/<YYYY-MM>.json   # 审核裁决留痕（append-only）
CHANGELOG.md                # 数据契约变更与兼容性说明
ci/validate-workflow.patch  # CI 加固补丁（actions 固定 SHA + schema/留痕/死链/自测四步）
.github/workflows/          # CI：PR 自动跑机器预审（应用上方补丁后启用全部校验）
.github/ISSUE_TEMPLATE/     # Issue 模板：[技能提交]
LICENSE                     # MIT
```

## 许可证

[MIT](LICENSE) —— 目录数据可自由使用、复用与再分发。

## 维护者

@axel286137079-dot 及其 AI 审核助手。
