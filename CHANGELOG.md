# Changelog

本文件记录 **`index.json` 数据契约**与仓库机制的变更。

> 记录起点说明：本仓库的首个提交就是 **v3**（仓库由主仓库目录快照一次性建立，此前 v1/v2 的演进发生在主仓库内部、未在本仓库留档）。
> 因此这里**不编造 v1/v2 的条目**——没有留痕的历史就不写进 changelog。

---

## v4 — 2026-09-26

主题：**让「匹配得准」有据可依** —— 把条目从「名字 + 一句描述」升级为带受控标签与别名的可检索数据，并把契约写成机器可校验的 schema。

### 数据（`index.json`）

- `version`: 3 → **4**；15 条目录条目全部补齐以下**可选字段**：
  - `tags`：**受控词表**（34 个小写 ASCII 词，见 [`schema/README.md`](schema/README.md)），每条 1–6 个；
  - `aliases`：中英文别名/近义词（每条 1–8 个），用于提升召回；
  - `homepage`：`https://` 主页（由 `origin` 推导，便于溯源与死链检查）；
  - `added_at`：首次入库日期。
- 15 个条目的 `description`/`install`/`origin` **一个字节都没改**；改动是纯增量。

### 契约（新增 `schema/`）

- [`schema/index.schema.json`](schema/index.schema.json)：`index.json` 顶层结构，含 **v4 条件契约**（`version >= 4` ⇒ 每条目必须有 `tags`/`aliases`/`added_at`）。
- [`schema/skill.schema.json`](schema/skill.schema.json)：单条目契约，含 `tags` 词表枚举。
- `scripts/validate.py`：新增可选字段校验（词表 / 大小写不敏感去重 / https / 日期 / 数量上限），**与 schema 等价且保持零第三方依赖**；新增字段同样受三条红线（密钥 / 危险指令）扫描。
- **修复**：危险指令扫描的正则 `rm\\s+-rf?\\s+(~|\\$HOME|/)\\b` 既有漏检也有误报 —— `~` 与 `/` 都不是单词字符，`\\b` 收尾导致 `rm -rf ~`、`rm -rf /`、`rm -rf $HOME` **全部漏检**；同时 `rm -rf /tmp/build` 这类正常命令被误报。已改为「目标参数必须独立成词」的写法，两类问题一并解决（负样本见 `scripts/selftest.py`）。
- `scripts/check_schema.py`（新增）：用 `jsonschema` 严格校验 `index.json` + 全部贡献文件，并做两件「反自欺」的事：
  1. **schema 自证**：14 个正/负样本必须按预期判定（证明 schema 真的会拒绝坏数据，而不是只写了好看）；
  2. **防漂移**：断言 `validate.py` 的镜像常量与 schema 的枚举/必填/条件规则严格一致。

### 机制与加固

- 新增 [`review-log/`](review-log/README.md)：审核裁决 **append-only 留痕**（谁、何时、**凭什么**把条目放进公共目录），含 `basis`（依据）与 `evidence`（可验证证据，必须是 https URL）两个强制字段。
  - `validate.py --check-review-log [--strict]`：格式校验 + 与 `index.json` 的**双向一致**校验；
  - 一致性以「每个 id 的**最新裁决**」为准 —— 这样条目被合法移除时，历史 `approved` 记录不会让 CI 永久报错（append-only 的应有语义）；移除条目同样必须留痕；
  - 2026-09 批次是 v3 条目的**追溯登记**：只登记可核对的入库事实与依据，并如实标注「当时未保留逐条裁决记录」。
- 新增 [`scripts/selftest.py`](scripts/selftest.py)：**49 条规则自测**，每条规则配一个负样本。CI 绿灯因此等价于「数据合格」，而不是「恰好没被检查到」。
- 新增 `validate.py --check-deadlinks`：`origin`/`homepage` 可达性探测（同一 URL 只探一次；403/429 判为「无法判定」；网络不可达**降级为告警，不阻塞 CI**）。
- CI 加固：actions 固定到 **commit SHA**（防上游 tag 被移动）、最小权限 `permissions: contents: read`、新增 schema / 留痕 / 死链 / 自测四步。
  - 交付形式是 [`ci/validate-workflow.patch`](ci/README.md)：当前 GitHub 连接（Arena App）**没有 `workflows` 权限**，改动 `.github/workflows/*` 的提交会被 push 拒绝，因此 CI 编排与机制分两路落地 —— **机制已全部入库、本地随时可跑**，补丁只负责让 CI 自动跑它们（`git apply` 一行命令，见 ci/README.md）。
- 发布物：[`releases/v4.md`](releases/v4.md)（Release notes 草稿 + 一键创建命令）。

### 兼容性（升级前必读）

| 消费者 | 影响 | 依据 |
|---|---|---|
| `plugin/lib/engine.js`（JS 匹配引擎） | ✅ **无需改动，且立刻受益**：远程条目映射时已读取 `tags` 并纳入词法检索与打分（命中权重 `w.tag = 4`），分词器对 ASCII 取整词 → 小写 ASCII 标签直接命中 | 主仓库 `plugin/lib/engine.js`（2026-09 版本） |
| `bin/sync_index.py`（Python 同步） | ⚠️ **安全但无收益**：只透传 `id/name/description/install/source/origin`，会静默丢弃 `tags`/`aliases`。不是严格解析，**不会因新字段报错**；要让 Python 侧吃到 v4 字段需主仓库做一次透传改动 | 主仓库 `bin/sync_index.py` |
| `aliases` 的任何消费者 | ⚠️ **目前不存在**：引擎的 alias 召回是查询侧 `canonize()` 概念表，不读条目字段。`aliases` 是**前瞻字段**，现在入库无副作用，也不应被宣传成「已经生效」 | 同上 |
| 任何第三方/未知消费者 | ✅ 只要遵守「忽略未知字段」即可；`additionalProperties: true` 是明文承诺 | `schema/*.schema.json` |

### ⚠️ 已知阻断问题（主仓库侧，必须随 v4 一起处理）

**两个客户端都用 SHA256 钉扎远程内容，且远程 URL 指向可变的 `raw.githubusercontent.com/.../main/index.json`。**
后果：**任何**目录内容变更（包括本次 v4）都会被判为「内容哈希与上次不一致 → 源可能被篡改」而被**拒绝更新**，客户端将永远停在旧版本。

- Python 侧：`bin/sync_index.py` → `fetch_remote_skills()`（`known != digest` 即 `continue`）
- JS 侧：`plugin/lib/engine.js` → `fetchRemoteSkills()`（`known !== digest` 即 `return []`）

迁移清单（主仓库改动，见本仓库 issue/PR 讨论）：

1. **改为「版本单调递增即接受」**：上游 `version` 变大 ⇒ 正常更新并刷新哈希；同版本内容变化才判为可疑；
2. **tag 固定拉取**：`@v<version>`（jsDelivr 主源 + `raw.githubusercontent.com` 备用源），让「固定的 URL 对应固定的内容」成立，哈希钉扎才不再是自锁；
3. Python 侧透传 `tags`/`aliases`；JS 侧把 `aliases` 并入词法字段。

### 发布纪律（本仓库）

- 数据变更 ⇒ `version` +1、`updated_at` 更新、**必须** `git tag v<version>` 并在 GitHub Release 里说明；客户端据此区分「新版本」与「被篡改」。
- 每次入库裁决须在 `review-log/` 留痕（v4 之后的机制，见 review-log/README.md）。

---

## v3 — 2026-09-26（维护者本地时区；PR #1 合并于 2026-09-25 21:33Z，tag `v3`）

- 建立社区基础设施：贡献指南、Issue 模板、`contributions/` 提交区与示例。
- CI 机器预审 [`scripts/validate.py`](scripts/validate.py)：JSON 合法性 / 必填字段 / id 格式与查重 / 密钥与危险指令扫描 / 贡献共识统计（≥3 个不同贡献者 → 自动采纳阈值）。
- 目录 15 条入库：13 条 Anthropic 官方 skill + 2 条社区项目（`obra/superpowers`、`wshobson/agents`）。
