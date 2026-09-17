# skill-matcher-index

> skill-matcher 的开源技能目录 · Community Skill Index —— 由社区共建，AI 审核员每晚自动审核合并。

**当前收录：13 个技能**（`index.json`，所有安装者联网同步）

## 这是什么

[skill-matcher](https://github.com/axel286137079-dot/skill-matcher) 是一个中立的「需求 ↔ 技能」匹配器：四层递进读懂你的需求（L0 字面 → L1 语义 → L2 意图 → L3 潜在需求），从本地已装技能、市场技能、专家目录中给出 Top3 匹配与理由。

本仓库是它的**公开技能目录**：`index.json`。每个安装了 skill-matcher 的用户都可以为目录添砖加瓦——装的人越多 → 目录越全 → 匹配越准 → 更多人受益。

- 技能主页：https://github.com/axel286137079-dot/skill-matcher
- SkillHub：https://skillhub.cn/skill/skill-matcher

## 如何贡献（3 步）

1. **拿到候选清单**：本地运行 `python3 bin/sync_index.py --collect-contributions`，生成 `index/contributions/candidates.json`。
2. **提交贡献文件**：把你想公开的技能整理成 JSON 数组，在本仓库新建 `contributions/<你的GitHub用户名>.json`（格式见 [CONTRIBUTING.md](CONTRIBUTING.md)），提交 Pull Request；也可以直接开 Issue，按模板贴「技能名 / 描述 / 安装方式」。
3. **等审核**：AI 审核员每晚 23:00 自动审核（机器预审 → AI 安全+质量裁决 → 合并 → 发布 `index.json`）。

三条红线：**不含密钥 · 不含危险指令 · 不伪造刷量**。详见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 审核与共识机制

- 每条贡献经过：机器预审（敏感词/质量分/查重）→ AI 审核（安全+质量）→ 人工兜底抽查。
- 同一技能被 **≥3 个不同用户**独立提交 → 共识达成，自动采纳进 `index.json`。
- 未达共识的条目进入 `pending`，会在 PR/Issue 中说明原因。

## 目录结构

```
index.json                  # 全局开源技能目录（所有安装者联网同步的目标文件）
contributions/<user>.json   # 各贡献者的提交（待审核）
```

## 维护者

@axel286137079-dot 及其 AI 审核助手。
