# skill-matcher-index

> skill-matcher 的开源技能目录 · Community Skill Index —— 由社区共建，AI 审核员每晚自动审核合并。

**当前收录：15 个技能**（`index.json` 修订号 4。已经同步过旧目录的客户端会因整文件哈希钉扎而拒绝这次更新，见 [SCHEMA.md](SCHEMA.md)）

## 这是什么

[skill-matcher](https://github.com/axel286137079-dot/skill-matcher) 是一个中立的「需求 ↔ 技能」匹配器：四层递进读懂你的需求（L0 字面 → L1 语义 → L2 意图 → L3 潜在需求），从本地已装技能、市场技能、专家目录中给出 Top3 匹配与理由。

本仓库是它的**公开技能目录**：`index.json`。每个安装了 skill-matcher 的用户都可以为目录添砖加瓦——装的人越多 → 目录越全 → 匹配越准 → 更多人受益。

- 技能主页：https://github.com/axel286137079-dot/skill-matcher
- SkillHub：https://skillhub.cn/skill/skill-matcher

## 如何贡献（3 步）

1. **拿到候选清单**：先 clone 主仓库 [skill-matcher](https://github.com/axel286137079-dot/skill-matcher)，在其根目录运行 `python3 bin/sync_index.py --collect-contributions`（脚本在主仓库，不在本仓库），生成 `index/contributions/candidates.json`。
2. **提交贡献文件**：把你想公开的技能整理成 JSON 数组，在本仓库新建 `contributions/<你的GitHub用户名>.json`（格式见 [CONTRIBUTING.md](CONTRIBUTING.md) 和示例 [contributions/_example.json](contributions/_example.json)），提交 Pull Request——CI 会自动跑机器预审；也可以直接开 Issue，按模板贴「技能名 / 描述 / 安装方式」。
3. **等审核**：AI 审核员每晚 23:00 自动审核（机器预审 → AI 安全+质量裁决 → 合并 → 发布 `index.json`）。

三条红线：**不含密钥 · 不含危险指令 · 不伪造刷量**。详见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 审核与共识机制

- 每条贡献经过：机器预审（敏感词/质量分/查重）→ AI 审核（安全+质量）→ 人工兜底抽查。
- **机器预审已实现为本仓库 CI**：任何 PR 自动运行 [`scripts/validate.py`](scripts/validate.py)（JSON 合法性 / 必填字段 / id 格式与查重 / 密钥与危险指令扫描 / 共识统计 / 审核日志 / schema 字段对账；Actions 里还会探测链接）。本地可预跑 `python3 scripts/validate.py --all`。字段契约和客户端限制见 [SCHEMA.md](SCHEMA.md)。
- **AI 审核（每晚 23:00）**：由维护者侧的 AI 审核助手执行并合并发布，实现位于维护者环境，未包含在本仓库；本仓库 CI 绿灯 = 机器预审通过。
- 同一技能被 **≥3 个不同用户**独立提交 → 共识达成，自动采纳进 `index.json`。
- 未达共识的条目进入 `pending`，会在 PR/Issue 中说明原因。

## 目录结构

```
index.json                  # 全局开源技能目录（所有安装者联网同步的目标文件）
schema/catalog.schema.json  # 目录契约（可选字段 tags / aliases / homepage）
reviews/log.jsonl           # append-only 审核日志（以每个 id 的最新裁决为准）
contributions/<user>.json   # 各贡献者的提交（待审核，_ 开头为示例）
scripts/validate.py         # 机器预审脚本（CI 与本地共用，只依赖标准库）
scripts/check_schema.py     # JSON Schema 校验，并和 validate.py 对账
scripts/selftest.py         # 离线回归（危险指令、审核日志、token 附加）
.github/workflows/          # CI：PR 自动跑机器预审、schema 对账和自测
.github/ISSUE_TEMPLATE/     # Issue 模板：[技能提交]
LICENSE                     # MIT
```

## 许可证

[MIT](LICENSE) —— 目录数据可自由使用、复用与再分发。

## 维护者

@axel286137079-dot 及其 AI 审核助手。
