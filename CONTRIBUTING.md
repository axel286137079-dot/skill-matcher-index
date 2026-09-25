# 贡献指南 · Contributing

感谢你参与 skill-matcher 开源技能目录的共建！装的人越多 → 目录越全 → 匹配越准 → 更多人装。

## 三条红线

1. **隐私**：只提交你确定可以公开共享的技能。公司私有、含密钥/配置、未公开内容一律不要提交。
2. **质量**：描述写清楚（中英皆可，越具体匹配越准），SKILL.md frontmatter 完整（name + description）。
3. **诚实**：不伪造、不刷量。同一技能被 ≥3 个不同用户独立提交才自动采纳。

## 如何提交

### 方式 A：贡献文件（推荐）

1. 本地运行 `python3 bin/sync_index.py --collect-contributions` 生成候选清单。
2. 审核 `index/contributions/candidates.json`，把你确定要贡献的条目整理成 JSON 数组，放到本仓库 `contributions/<你的GitHub用户名>.json`，格式：

```json
[
  {
    "id": "my-skill",
    "name": "my-skill",
    "description": "这个技能做什么（中英皆可，越具体匹配越准）",
    "install": "git clone https://github.com/...",
    "origin": "作者/仓库名",
    "tags": ["pdf", "document"],
    "homepage": "https://github.com/作者/仓库名"
  }
]
```

`tags`、`aliases`、`homepage` 都可选。`tags` 必须是小写 ASCII 词（不要写中文，不要写 `{ "zh": "..." }` 对象）——JS 引擎会把它们当字符串数组打分。`aliases` 可以写中文展示名，但**当前客户端不读取**，填了不会提高匹配。完整约束见 [SCHEMA.md](SCHEMA.md)。

3. 开 Pull Request，或直接把文件内容发 Issue。PR 提交后 **CI 会自动运行机器预审**（脚本 [`scripts/validate.py`](scripts/validate.py)，本地可预跑 `python3 scripts/validate.py --all`）：JSON 合法性 / 必填字段 / id 格式与查重 / 密钥与危险指令扫描 / 共识统计 / 审核日志 / 死链。CI 还会跑 schema 对账和离线自测。CI 绿灯 = 这些检查通过，不等于已经人工采纳。

### 方式 B：Issue 提交

在 Issues 里用「[技能提交]」模板贴：技能名 / 描述 / 安装方式 / 来源 / 确认声明。标签和主页可选。

## 审核流程

- 每个贡献会经过：机器预审（敏感词/质量分/查重，**已实现为本仓库 CI，PR 自动运行**）→ AI 审核（安全+质量，维护者侧每晚 23:00 执行，实现在维护者环境）→ 人工兜底抽查。
- 状态：`candidate`（候选）→ `approved`（通过）→ `pending`（待查，会在 PR/Issue 里说明原因）。
- 同一技能被 ≥3 个不同贡献者提交 → 共识达成，自动采纳（CI 会在每次校验时输出各 id 的提交人数统计）。
- **发版规则（维护者）**：采纳或撤销条目时更新 `index.json` 的 `version`（+1）与 `updated_at`（YYYY-MM-DD），往 [`reviews/log.jsonl`](reviews/log.jsonl) **追加**一条裁决（不要改历史行；以该 id 的最新裁决为准），并在 GitHub 打 tag `v<version>` 以便回溯。已安装的客户端把整文件哈希钉在 `main` 上，发版后不会自动更新，见 [SCHEMA.md](SCHEMA.md)。

## 目录结构

```
index.json                  # 全局开源技能目录（联网同步的目标文件）
contributions/<user>.json   # 各贡献者的提交（待审核）
```

## 维护者

@axel286137079-dot 及其 AI 审核助手。
