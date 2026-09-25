# Changelog

## 修订号 4 — 2026-09-25

目录修订号从 3 增到 4。收录仍是 15 条，没有新增或删除技能。

### 新增

- 可选字段 `tags`、`aliases`、`homepage`。契约在 [`schema/catalog.schema.json`](schema/catalog.schema.json)，说明在 [`SCHEMA.md`](SCHEMA.md)。
- `tags` 写成小写 ASCII 词，对齐 JS 引擎已有的标签打分（字符串数组，默认权重 4）。用引擎的 `analyzeQuery` 核对过：`测试` → `webapp-testing`，`设计` → `brand-guidelines` / `canvas-design`，`演示` → `pptx`。
- `reviews/log.jsonl`：append-only 审核日志。一致性以每个 id 的**最新**裁决为准。修订号 3 已收录的 15 条做了回填，`catalog_version` 记 3，表示这次只补审计记录。
- 现有 CI 命令会顺带做 schema 字段对账；在 GitHub Actions 里还会探测链接。负样本 schema 证明和自测脚本已入库，但本次改不了 workflow 文件（推送 token 没有 `workflows` 权限），那两步还没挂进 CI。

### 修复

- 危险指令扫描不再使用 `rm\s+-rf?\s+(~|\$HOME|/)\b`。这条正则的 `\b` 贴在 `~` 或 `/` 后面不成立，所以 `rm -rf ~`、`rm -rf /`、`rm -fr ~/` 全部漏检，而 `rm -rf /tmp/ok` 会误报。现在按命令解析，只标记家目录或文件系统根的递归删除。自测：召回 24/24，精度 15/15，并锁住旧正则的漏检和误报。

### 安全

- 链接探测不再用 `"github.com" in url` 决定是否附加 `GITHUB_TOKEN`。`https://evil.com/?x=github.com` 不会拿到 token。重定向每跳重新判断，不转发 `Authorization`。拒绝探测私网、环回和带 userinfo 的 URL。
- 自测覆盖 13 条 token 附加决策、9 条拒绝探测的 URL。

### 明确没做、也不要对外说成已做

- `aliases` 当前没有消费方。引擎的 alias 召回是查询侧概念表，不读条目的 `aliases`。字段留给下一版客户端，本次只校验、不声称它能提高匹配。
- Python 同步（`bin/sync_index.py`）不复制 `tags`，并且会覆盖 `origin`。标签今天只对 JS 引擎生效。
- 已钉扎旧哈希的安装**不会**自动收到修订号 4。两个客户端都把整文件 SHA256 钉在可变的 `raw.../main/index.json` 上，内容一变就永久拒绝更新。解开方法和上游该怎么修，写在 [`SCHEMA.md`](SCHEMA.md)。这不是本仓库能在数据文件里绕过去的。

### 数据缺口（修订号 3 已存在，本次未改 id）

`anthropics/skills` 仓库里没有与下列 id 同名的目录：`artifacts-builder`（现有目录是 `web-artifacts-builder`）、`image-editing`、`mcp-architect`、`video-editing`。没有为它们编造 `homepage`。`install` 仍指向仓库根，该 URL 返回 200，但仓库内找不到同名技能。
