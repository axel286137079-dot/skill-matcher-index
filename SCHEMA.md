# 目录契约

`index.json` 的 `version` 是**目录修订号**（发布时 +1，当前为 4），不是 schema 版本。文档结构以 [`schema/catalog.schema.json`](schema/catalog.schema.json) 为准。`tags` / `aliases` / `homepage` 都是可选字段，所以修订号 3 的旧文件仍能通过校验。

机器预审分两层，不要把它们说成同一件事：

| 层 | 管什么 | 不管什么 |
|---|---|---|
| JSON Schema（`scripts/check_schema.py`） | 类型、枚举、长度、正则、未知字段 | 密钥、危险指令、id 查重、审核日志、链接 |
| `scripts/validate.py` | 上面全部，再加密钥 / 危险指令 / 查重 / 最新裁决 / 链接 | — |

两边用同一组正负样本对账。Schema 单独“能通过当前文件”不够，负样本必须被拒绝。

## 技能对象

必填：`id`、`name`、`description`（至少 8 字）、`install`。

| 字段 | 约束 | 谁在读 |
|---|---|---|
| `source` | `opensource` 或 `community` | 客户端自己填 `opensource`，不信任远程文件里的值 |
| `origin` | 作者/仓库，如 `anthropics/skills` | JS 客户端会保留；Python 同步目前会用远程源的名字覆盖它 |
| `tags` | 最多 8 个、不重复的小写 ASCII token：`^[a-z0-9][a-z0-9-]{0,31}$` | **JS 引擎在读**。Python 同步目前会丢掉 |
| `aliases` | 最多 8 个展示名，可含中文，大小写不敏感去重 | **当前没有消费方**。不要写成“填了就能提高匹配” |
| `homepage` | `https://` URL，主机名必须带字母 TLD，不允许 userinfo / IP | 给人看，也给 CI 做死链检查 |

`tags` 必须是字符串数组，不能是 `{ "zh": "测试" }` 这种对象。JS 引擎对远程条目做的是 `String(tag)`（`plugin/lib/engine.js` 约 629 行）。对象会被变成 `"[object Object]"`，既匹配不到，也污染打分。本地市场目录里的 `{zh}` 标签是另一条解析路径，不要套到这个文件上。

词表用小写 ASCII，是因为引擎分词（约 529 行）对 ASCII 取 `[a-z0-9_]+`，对中文只取 2-gram；打分时标签权重大于描述（默认 `tag: 4`，`desc: 1.5`，约 383 行）。查询「测试」会先规范化成 `test`（`CONCEPT_ALIAS`），所以标签应写 `test` 而不是「测试」。连字符会把一个标签拆成两个 token，精确相等匹配用单个词。

本次用引擎自己的 `analyzeQuery` 核对过：`测试` 命中 `webapp-testing` 的 `test`，`设计` 命中 `design`，`演示` 命中 `pptx` 的 `slides`。`幻灯片` 不会命中——分词只产出「幻灯 / 灯片」，到不了概念表里的三字词。这是引擎的限制，不是本目录漏标。

## 审核日志

[`reviews/log.jsonl`](reviews/log.jsonl) 是 append-only。一致性看的是**每个 id 的最后一条裁决**，不是“文件里出现过 `approved`”。

- 在 `index.json` 里 ⟺ 最新裁决是 `approved`
- 最新裁决是 `rejected` / `revoked` / `pending` ⟺ 不在 `index.json` 里

因此先 `approved` 再 `revoked`、并且目录里已经删除该 id，是合法的。把历史 `approved` 行改掉或删掉，CI 会失败。规则和示例见 [`reviews/README.md`](reviews/README.md)。

## 链接探测

`python3 scripts/validate.py --all --check-links` 会请求 `homepage` 和 `install` 里的 GitHub 仓库地址。

- `GITHUB_TOKEN` 只在主机名恰好是 `github.com` 或 `api.github.com` 时附加。`https://evil.com/?x=github.com` 拿不到 token。
- 每次重定向都重新决定要不要带 token，不把 `Authorization` 原样转发。
- 拒绝探测 userinfo、非 https、环回 / 链路本地 / 私网地址，以及解析到这些地址的主机名。解析和连接之间仍有 DNS rebinding 的空窗，这是 CI 缓解，不是沙箱。
- 404/410 是错误。`github.com` 整体不可达降级为警告，以免一次断网挡住合并；其他主机的 DNS 失败是错误，避免用 `.invalid` 绕过死链检查。

2026-09-25 对当前目录的 12 个去重 URL 实测均为 HTTP 200。四个条目没有同名目录，所以没有填写 `homepage`，而不是猜一个会 404 的路径：`artifacts-builder`（仓库里是 `web-artifacts-builder`）、`image-editing`、`mcp-architect`、`video-editing`。它们的 `install` 仍指向 `anthropics/skills` 仓库根，这个 URL 是通的，但仓库里找不到同名技能。这是修订号 3 就存在的数据缺口，本次没有改 id、也没有删条目。

## 客户端兼容性：整文件哈希钉在可变的 main 上

这是这次发布到不了已同步安装的原因，本仓库改数据修不掉。

两个现行客户端都把远程文件的 SHA256 记下来，URL 又是可变的 `main`：

- `plugin/lib/engine.js` `fetchRemoteSkills`（约 316–322 行）：哈希不一致就打印 `remote index SHA256 mismatch` 并返回空列表，不更新已记录的哈希。
- `bin/sync_index.py` `fetch_remote_skills`（约 288–293 行）：同样拒绝更新，提示删 `index/_remote_hashes.json`。

已经成功同步过一次的安装，会一直用旧目录。任何内容变化（包括只加 `tags`）都会变哈希。

安装者要手动解开一次：

- Python：删除技能目录下的 `index/_remote_hashes.json`，再跑 `python3 bin/sync_index.py`
- JS 插件：删掉 `~/.dsh/dsh-skill-matcher/cache.json` 里该 URL 的 `remoteHashes`，或删掉整个缓存文件

上游应修，而不是让目录停止更新：

1. 哈希钉扎绑定不可变 URL（tag 或 commit）。`main` 只用来发现“有新修订号”。
2. 或者：`version` 变大时接受更新并写入新哈希；`version` 不变但内容变了才拒绝。
3. Python 同步应保留远程 `tags`。现在只拷贝 `id` / `name` / `description` / `install` / `source`，并把 `origin` 换成远程源的名字（约 302–308 行）。所以即便解开哈希，Python 路径今天也用不上这些标签。
4. 若要让 `aliases` 参与召回，引擎得在 `entryTerms` / `scoreEntry` 读取它。今天的 alias 召回只来自查询侧的 `CONCEPT_ALIAS` 表。

## 本地与 CI

```bash
python3 scripts/validate.py index.json
python3 scripts/validate.py contributions
python3 scripts/validate.py --all --check-links
python3 scripts/selftest.py
python3 -m pip install -r requirements-dev.txt && python3 scripts/check_schema.py
```

`validate.py` 和 `selftest.py` 只依赖标准库。`check_schema.py` 需要 `jsonschema==4.26.0`，用负样本证明 schema 真的会拒绝坏数据。

现有 CI 只调用 `python3 scripts/validate.py index.json` 和 `contributions`。这两条现在也会做 schema 字段/正则对账；在 GitHub Actions 里还会探测链接（本地要加 `--check-links`）。`selftest.py` 和 `check_schema.py` 的负样本证明需要在 workflow 里各加一步。本次推送改不了 `.github/workflows/validate.yml`：GitHub App 没有 `workflows` 权限。期望的 workflow 写在 PR 说明里。
