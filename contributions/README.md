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
      "origin": "作者/仓库名",
      "tags": ["testing", "workflow"],
      "aliases": ["我的技能", "my skill"]
    }
  ]
  ```

- **必填**：`id` / `name` / `description`（≥ 8 字符）/ `install`
- **建议填**（v4 起，可选但直接影响匹配准确度）：
  - `tags`：**受控词表**（小写 ASCII，1–6 个），词表见 [`schema/README.md`](../schema/README.md)——**词表外的标签会被 CI 拒绝**；
  - `aliases`：别名/近义词（中英皆可，1–8 个，大小写不敏感去重）；
  - `homepage`：`https://` 开头的主页；`added_at`：首次入库日期 `YYYY-MM-DD`（由维护者入库时确认，贡献者可留空）。
- **`_` 开头的文件**（如 `_example.json`）是示例/说明，CI 不校验、不入库。
- 提交 PR 后，CI 会自动跑机器预审：JSON 合法性 / 字段完整性 / id 查重 / v4 元数据契约（词表、去重、https）/ 密钥与危险指令扫描（脚本见 [`scripts/validate.py`](../scripts/validate.py)，本地可用 `python3 scripts/validate.py contributions` 预跑）。
- **数据契约**：条目格式的机器可执行定义在 [`schema/skill.schema.json`](../schema/skill.schema.json)；未知字段一律忽略（向前兼容），但**受控词表内的字段要填对**。
- **共识机制**：同一 `id` 被 **≥3 个不同贡献者** 独立提交 → 自动采纳进 `index.json`；1–2 人 → `pending`，会在 PR/Issue 中说明原因。
- 三条红线：**不含密钥 · 不含危险指令 · 不伪造刷量**。
