# 贡献指南 · Contributing

感谢你参与 skill-matcher 开源技能目录的共建！装的人越多 → 目录越全 → 匹配越准 → 更多人装。

## 三条红线

1. **隐私**：只提交你确定可以公开共享的技能。公司私有、含密钥/配置、未公开内容一律不要提交。
2. **质量**：描述写清楚（中英皆可，越具体匹配越准），SKILL.md frontmatter 完整（name + description）。
3. **诚实**：不伪造、不刷量。同一技能被 ≥3 个不同用户独立提交才自动采纳。

> 这三条不是口号：CI 会对**每个字段**（含 v4 新增的 `tags`/`aliases`/`homepage`）做密钥与危险指令扫描，把 token 藏进别名同样会被拦下。

## 如何提交

### 方式 A：贡献文件（推荐）

1. 本地运行 `python3 bin/sync_index.py --collect-contributions` 生成候选清单（脚本在主仓库 [skill-matcher](https://github.com/axel286137079-dot/skill-matcher)）。
2. 审核 `index/contributions/candidates.json`，把你确定要贡献的条目整理成 JSON 数组，放到本仓库 `contributions/<你的GitHub用户名>.json`：

```json
[
  {
    "id": "my-skill",
    "name": "my-skill",
    "description": "这个技能做什么（中英皆可，越具体匹配越准）",
    "install": "git clone https://...",
    "origin": "作者/仓库名",
    "homepage": "https://github.com/作者/仓库名",
    "tags": ["testing", "workflow"],
    "aliases": ["我的技能", "my skill"]
  }
]
```

3. 开 Pull Request，或直接把文件内容发 Issue。PR 提交后 **CI 会自动运行机器预审**，本地可预跑同一套命令：

```bash
python3 scripts/validate.py contributions            # 零依赖：格式/字段/id 查重/v4 契约/密钥扫描/共识统计
python3 scripts/check_schema.py                      # JSON Schema 严格校验（需 jsonschema，否则跳过）
python3 scripts/selftest.py                          # 规则自测（可选，验证工具本身）
```

### 方式 B：Issue 提交

在 Issues 里用「[技能提交]」模板贴：技能名 / 描述 / 安装方式 / 来源 / 确认声明。

## 字段说明

| 字段 | 必填 | 说明 |
|---|---|---|
| `id` | ✅ | 小写字母/数字/连字符，全局唯一，如 `my-skill` |
| `name` | ✅ | 展示名 |
| `description` | ✅ | ≥ 8 字符；**匹配的主力字段**，写清「做什么 + 什么时候用」 |
| `install` | ✅ | 安装方式（`git clone https://...` 或 `skillhub install ...`） |
| `origin` | ❌ | `作者/仓库名`，用于溯源与死链检查（强烈建议填） |
| `homepage` | ❌ | `https://` 开头的主页 |
| `tags` | ❌ | **受控词表**（小写 ASCII，1–6 个，**词表外的标签会被 CI 拒绝**）：词表与中文对照见 [`schema/README.md`](schema/README.md) |
| `aliases` | ❌ | 别名/近义词（中英皆可，1–8 个；大小写不敏感去重）——用户可能搜的词都值得加 |
| `added_at` | ❌ | 首次入库日期 `YYYY-MM-DD`（由维护者在入库时确认） |

契约的机器可执行定义在 [`schema/skill.schema.json`](schema/skill.schema.json)：**新增字段永远是可选的**，消费者必须忽略未知字段。

**写 `tags`/`aliases` 的实用建议**：

- `tags` 只能从词表里挑（想加新词：开 Issue 说明理由，维护者在提升 `version` 时统一增补）；
- `aliases` 想「用户会怎么搜」：中文口语说法（如「修图」）、英文同义词（如 `photo editing`）、常被误写的简称（如 `ppt`）；
- 别把 `id`/`name` 原样抄进 `aliases`（那是重复劳动，索引本来就会分词它们）。

## 审核流程

- 每个贡献会经过：机器预审（格式/敏感词/质量分/查重，**已实现为本仓库 CI，PR 自动运行**）→ AI 审核（安全+质量，维护者侧每晚 23:00 执行，实现在维护者环境）→ 人工兜底抽查。
- 状态：`candidate`（候选）→ `approved`（通过）→ `pending`（待查，会在 PR/Issue 里说明原因）。
- 同一技能被 ≥3 个不同贡献者提交 → 共识达成，自动采纳（CI 会在每次校验时输出各 id 的提交人数统计）。
- **留痕**：每次入库裁决必须写进 [`review-log/<YYYY-MM>.json`](review-log/README.md)，包含裁决依据（`basis`）与可验证证据（`evidence`，如 PR 链接）。`python3 scripts/validate.py index.json --check-review-log --strict` 会校验「留痕 ⇄ index.json 双向一致」，缺一条都会报错（本地随时可跑；让 CI 自动跑需先应用 [`ci/validate-workflow.patch`](ci/README.md)）。

## 发版规则（维护者）

采纳条目时：

1. 更新 `index.json`：`version` +1（单调递增）、`updated_at` 改为当天（`YYYY-MM-DD`）；
2. 更新 [CHANGELOG.md](CHANGELOG.md)，写入变更与**兼容性影响**；
3. 在 `review-log/<当月>.json` 为每个新入库 id 追加一条 `approved` 裁决（含依据与证据）；
4. 跑全套校验（`validate.py --check-review-log --strict --check-deadlinks` + `check_schema.py --require` + `selftest.py`）；
5. 合并后打 tag `v<version>` 并发 Release：

```bash
git tag -a v4 -m "index v4: 受控标签 + 中英别名 + schema 契约" && git push origin v4
gh release create v4 --title "index v4" --notes-file releases/v4.md
```

## 目录结构

```
index.json                  # 全局开源技能目录（联网同步的目标文件）
schema/                     # 数据契约（JSON Schema + 词表说明）
scripts/                    # validate.py / check_schema.py / selftest.py
contributions/<user>.json   # 各贡献者的提交（待审核）
review-log/<YYYY-MM>.json   # 审核裁决留痕（append-only）
ci/validate-workflow.patch  # CI 加固补丁（应用后 CI 会自动跑全套校验）
```

## 维护者

@axel286137079-dot 及其 AI 审核助手。
