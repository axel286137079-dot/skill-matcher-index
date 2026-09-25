# schema/ · 数据契约

本目录是 `index.json` 的**机器可执行契约**（JSON Schema draft-07）：

| 文件 | 作用 |
|---|---|
| [`index.schema.json`](index.schema.json) | `index.json` 顶层结构；含 v4 条件契约（`version >= 4` ⇒ 每条目必须有 `tags`/`aliases`/`added_at`） |
| [`skill.schema.json`](skill.schema.json) | 单条技能条目；含 `tags` 受控词表 |

契约有两份「等价实现」，二者必须一致：

1. **JSON Schema**（本目录）—— 给外部工具、编辑器、其他语言消费者用。
2. **[`scripts/validate.py`](../scripts/validate.py)** —— 仓库 CI 与本地预跑用，**零依赖**（无第三方库）。

`scripts/check_schema.py` 会在 CI 中另跑一次 JSON Schema 校验，并断言两份实现没有漂移（词表一致、v4 必填规则一致）。

## 向前兼容契约（重要）

`index.json` 会被**所有已安装的客户端**联网同步，因此它同时是一份兼容性承诺：

- 字段只增不减、不改语义；**新增字段必须可选**；
- 消费者**必须忽略未知字段**（`additionalProperties: true`），不得因出现新字段而拒绝整个目录；
- 破坏性变更 = 提升 `version` 主号并在 `CHANGELOG.md` 里写明迁移方式。

已核实的主仓库消费方式（2026-09 版本）：

- `plugin/lib/engine.js`：远程条目映射时**已读取 `tags`**（`tags: it.tags || []`），并把它并入词法检索与打分（命中权重 `w.tag = 4`）——所以 v4 的 `tags` 在 JS 侧**立即可用**；`String(t).toLowerCase()` 说明**必须是字符串数组**（对象会被 stringify 成 `[object object]`）。
- `bin/sync_index.py`：远程条目只透传 `id/name/description/install/source/origin`，**会静默丢弃** `tags`/`aliases`。要让它也吃到 v4 字段，主仓库需做一次透传改动（已在迁移清单里，属主仓库改动，不影响本目录安全）。
- `aliases` 目前**没有消费方**：引擎的 alias 召回是查询侧 `canonize()` 概念表，不读条目字段。它是**前瞻字段**（为后续「条目级别名召回」准备），现在入库不产生副作用，也不会被误用。
- 两个客户端都用 SHA256 钉扎远程内容：同一版本内容变化会被判为「可能被篡改」而拒绝。因此目录改用 `version` 单调递增 + tag 发布（`v<version>`）才安全，详见 [`../CHANGELOG.md`](../CHANGELOG.md)。

## 字段一览

| 字段 | 必填 | 类型 | 说明 |
|---|---|---|---|
| `id` | ✅ | string | `^[a-z0-9][a-z0-9-]{0,63}$`，全局唯一（跨条目唯一性由 `validate.py` 强制） |
| `name` | ✅ | string | 展示名 |
| `description` | ✅ | string | ≥ 8 字符；词法检索主力字段，越具体越准 |
| `install` | ✅ | string | 安装方式，如 `git clone https://...` |
| `source` | ❌ | enum | `opensource` / `community` / `local` / `marketplace` / `manual` |
| `origin` | ❌ | string | `作者/仓库名`，用于溯源与死链检查 |
| `homepage` | ❌ | string | 必须是 `https://` 开头的 URL |
| `tags` | ❌ | string[] | 受控词表（见下），1–6 个，互不重复 |
| `aliases` | ❌ | string[] | 别名/近义词，中英皆可，1–8 个；大小写不敏感去重 |
| `added_at` | ❌ | string | 首次入库日期 `YYYY-MM-DD` |

## `tags` 受控词表（v4）

标签一律为**小写 ASCII 单词**。原因：匹配器分词器对 ASCII 取整词、对中文取 bigram（`engine.js` 的 `rawTokenize`），ASCII 标签能与用户查询词**精确对上**，命中权重最高。

| tag | 中文 | 典型场景 |
|---|---|---|
| `agents` | 智能体 | 多智能体、子代理编排 |
| `animation` | 动图/动画 | GIF、逐帧动画 |
| `architecture` | 架构设计 | 系统结构、方案规划 |
| `branding` | 品牌 | 品牌规范、视觉识别 |
| `data` | 数据处理 | 表格/数据抽取与分析 |
| `debugging` | 调试 | 排障、根因定位 |
| `design` | 设计 | 视觉、画布、版式 |
| `document` | 文档 | 文档生成与编辑 |
| `e2e` | 端到端 | 端到端测试 |
| `editing` | 编辑加工 | 文件/素材的修改 |
| `ffmpeg` | 音视频工具链 | 转码、剪辑 |
| `frontend` | 前端 | HTML/CSS/JS |
| `gif` | GIF | GIF 生成 |
| `image` | 图像 | 图片处理 |
| `integration` | 集成对接 | 服务端/协议对接 |
| `layout` | 排版布局 | 版式、画布 |
| `marketplace` | 市场集合 | 插件/技能集合 |
| `mcp` | MCP 协议 | MCP 服务器与架构 |
| `media` | 媒体素材 | 图片/视频素材处理 |
| `methodology` | 方法论 | 工程流程、最佳实践 |
| `pdf` | PDF | PDF 读写 |
| `planning` | 规划 | 方案/计划编写 |
| `playwright` | Playwright | 浏览器自动化 |
| `presentation` | 演示文稿 | 幻灯片 |
| `prototype` | 原型 | 快速 demo |
| `slack` | Slack | Slack 集成 |
| `spreadsheet` | 电子表格 | Excel 类文件 |
| `styleguide` | 规范手册 | 品牌/设计规范 |
| `subagents` | 子代理 | 专家代理 |
| `tdd` | 测试驱动 | TDD 流程 |
| `testing` | 测试 | 各类测试 |
| `video` | 视频 | 视频处理 |
| `webapp` | Web 应用 | Web 应用构建 |
| `workflow` | 工作流 | 流程编排 |

**改词表**：只能由维护者在**提升 `version`** 时增删，且必须同步改三处——`skill.schema.json` 的 `items.enum`、`validate.py` 的 `TAGS`、本文件的表格；CI 会校验前两者一致（`scripts/check_schema.py`）。

## 本地校验

```bash
# 零依赖、CI 同款
python3 scripts/validate.py index.json

# JSON Schema 严格校验（需要 jsonschema，CI 会按固定版本安装）
python3 -m venv .venv && .venv/bin/pip install 'jsonschema==4.23.0'
.venv/bin/python scripts/check_schema.py --require

# 契约自测（正/负样本，退出码即结论）
python3 scripts/selftest.py
```
