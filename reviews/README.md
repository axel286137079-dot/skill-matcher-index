# reviews/ · 审核日志

`log.jsonl` 是 append-only。一行一条裁决，只追加，不改历史。

## 裁决以最新一条为准

同一个 id 可以先 `approved` 再 `revoked`。校验看的是**最后一条**，不是“出现过 approved 就必须还在目录里”。

| 最新裁决 | `index.json` |
|---|---|
| `approved` | 必须在 |
| `rejected` / `revoked` / `pending` | 必须不在 |
| （没有任何记录） | 必须不在。目录里的每条技能都要有记录 |

修订号 3 已收录的条目用 `by=maintainer`、`catalog_version=3` 回填。那表示“引入日志前已经收录”，不是这次重新审核过。

## 追加一条

时间戳必须 UTC、以 `Z` 结尾，并且不早于文件里的上一条。

```json
{"ts":"2026-09-25T12:00:00Z","id":"my-skill","decision":"approved","by":"maintainer","reason":"3 名贡献者独立提交，描述与安装来源已核对","catalog_version":4}
```

`decision` 只能是 `approved`、`rejected`、`revoked`、`pending`。`reason` 至少 8 个字符。

CI 会把当前文件和 PR base 上的 `reviews/log.jsonl` 做前缀比较。改掉、删掉或重排已有行都会失败。本地可预跑：

```bash
python3 scripts/validate.py --all --review-base origin/main
```
