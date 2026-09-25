# ci/ · CI 加固补丁

## 为什么是一个补丁，而不是直接改 workflow？

**本仓库当前的 GitHub 连接（Arena GitHub App）没有 `workflows` 权限**：任何提交只要修改 `.github/workflows/*`，push 都会被拒绝：

```
! [remote rejected] ... (refusing to allow a GitHub App to create or update workflow
  `.github/workflows/validate.yml` without `workflows` permission)
```

为了让「机制」和「CI 编排」能分开落地，CI 加固以**补丁**形式交付：

- [`validate-workflow.patch`](validate-workflow.patch)：把 `main` 版 workflow 升级为加固版（40 行）

## 补丁做了什么

| | 应用前（main 现状） | 应用后 |
|---|---|---|
| actions 版本 | `actions/checkout@v4`、`actions/setup-python@v5`（**tag 可被上游移动**） | `@11bd71901bbe5b1630ceea73d27597364c9af683`（checkout v4.2.2）、`@42375524e23c412d93fb67b49958b491fce71c38`（setup-python v5.4.0）—— **commit SHA 不可移动** |
| 校验步骤 | `validate.py index.json` + `validate.py contributions` | 再加 **review-log --strict**、**deadlinks**、**check_schema --require**、**selftest** 四步 |
| 权限 | 默认（较宽） | `permissions: contents: read`（最小权限） |

## 如何应用（二选一）

### A. 命令行

```bash
git checkout main && git pull
git apply ci/validate-workflow.patch
git commit -am "ci: 固定 actions SHA + schema/留痕/死链/自测四步" && git push
```

补丁用的是标准 unified diff（`a/.github/workflows/validate.yml` ↔ `b/...`），在仓库根目录 `git apply` 即可；已在 `main`（29dfdd3）上验证 `git apply --check` 通过、且应用结果与加固版**逐字节一致**。

### B. 网页端

打开 `.github/workflows/validate.yml`，按补丁内容替换（补丁只有 40 行，diff 很直观）。

## 应用前 / 应用后的差别

- **机制已入库**：`validate.py --check-review-log`、`--check-deadlinks`、`check_schema.py`、`selftest.py` 都在本仓库，本地随时可跑（见 README 的「本地校验」）。
- **补丁只负责让 CI 自动跑它们**。应用前 CI 仍只跑原有两步。
- 应用后，`scripts/selftest.py` 中的 `test_live_workflow_matches_patch_when_hardened` 会从「跳过」自动转为**强制校验**（workflow 一旦加固，就不允许再退回浮动 tag）。
