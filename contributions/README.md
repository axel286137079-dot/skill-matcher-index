# contributions/ · 贡献提交区

各贡献者待审核的技能提交放在这里。

## 规则

- **命名**：`<你的GitHub用户名>.json`，例如 `contributions/alice.json`
- **格式**：JSON 数组，每个元素一个技能（完整示例见 [`_example.json`](_example.json)）：

  ```json
  [
    {
      "id": "my-skill",
      "name": "my-skill",
      "description": "这个技能做什么（中英皆可，越具体匹配越准）",
      "install": "git clone https://github.com/...",
      "origin": "作者/仓库名"
    }
  ]
  ```

- **`_` 开头的文件**（如 `_example.json`）是示例/说明，CI 不校验、不入库。
- 提交 PR 后，CI 会自动跑机器预审：JSON 合法性 / 字段完整性 / id 查重 / 密钥与危险指令扫描（脚本见 [`scripts/validate.py`](../scripts/validate.py)，本地可用 `python3 scripts/validate.py contributions` 预跑）。
- **共识机制**：同一 `id` 被 **≥3 个不同贡献者** 独立提交 → 自动采纳进 `index.json`；1–2 人 → `pending`，会在 PR/Issue 中说明原因。
- 三条红线：**不含密钥 · 不含危险指令 · 不伪造刷量**。
