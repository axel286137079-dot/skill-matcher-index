#!/usr/bin/env python3
"""契约自测：用正/负样本验证 validate.py 的每条规则（零依赖，CI 与本地共用）。

用法:
    python3 scripts/selftest.py           # 退出码 0 = 全绿
    python3 scripts/selftest.py -v        # 逐条用例

设计原则：每条规则都必须有一个「应被拒绝」的负样本 —— 只有负样本存在，
「CI 通过」才真的等价于「数据合格」（否则红灯只是一种可能性，不是保证）。
"""
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
VALIDATE = ROOT / "scripts" / "validate.py"
SKILL_SCHEMA = ROOT / "schema" / "skill.schema.json"
WORKFLOW = ROOT / ".github" / "workflows" / "validate.yml"


def run(target, *flags):
    return subprocess.run(
        [sys.executable, str(VALIDATE), str(target), *flags],
        capture_output=True, text=True,
    )


def entry(**over):
    base = {
        "id": "demo-skill",
        "name": "demo-skill",
        "description": "演示技能：做一个可验证的示例。",
        "install": "git clone https://github.com/example/demo",
        "source": "opensource",
        "origin": "example/demo",
        "homepage": "https://github.com/example/demo",
        "tags": ["testing"],
        "aliases": ["示例技能"],
        "added_at": "2026-09-26",
    }
    base.update(over)
    return base


def make_index(version=4, skills=None, **over):
    data = {
        "name": "测试目录",
        "description": "自测用",
        "version": version,
        "updated_at": "2026-09-26",
        "skills": skills if skills is not None else [entry()],
    }
    data.update(over)
    return data


def decision(sid="demo-skill", **over):
    base = {
        "id": sid,
        "date": "2026-09-26",
        "decision": "approved",
        "decided_by": "maintainer + ai-reviewer",
        "basis": ["PR #1 merged", "CI 机器预审通过"],
        "evidence": ["https://github.com/axel286137079-dot/skill-matcher-index/pull/1"],
    }
    base.update(over)
    return base


def network_available() -> bool:
    try:
        req = urllib.request.Request("https://github.com", method="HEAD",
                                     headers={"User-Agent": "selftest"})
        with urllib.request.urlopen(req, timeout=6):
            return True
    except Exception:
        return False


NETWORK = network_available()


class TempRepoCase(unittest.TestCase):
    """每个用例一个临时目录：index.json + review-log/ + contributions/"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="smi-selftest-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.index = self.tmp / "index.json"

    def write_index(self, data):
        self.index.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return self.index

    def write_review_log(self, month="2026-09", decisions=None, **over):
        directory = self.tmp / "review-log"
        directory.mkdir(exist_ok=True)
        data = {"month": month, "decisions": decisions if decisions is not None else [decision()]}
        data.update(over)
        (directory / f"{month}.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return directory

    def write_contribution(self, name, skills):
        directory = self.tmp / "contributions"
        directory.mkdir(exist_ok=True)
        (directory / name).write_text(json.dumps(skills, ensure_ascii=False, indent=2), encoding="utf-8")
        return directory


class TestIndexFormat(TempRepoCase):
    def test_valid_v4_index_passes(self):
        r = run(self.write_index(make_index()))
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("v4 元数据契约", r.stdout)

    def test_legacy_v3_index_without_new_fields_passes(self):
        """向后兼容：v3 数据（无 tags/aliases/added_at）仍然合法。"""
        legacy = {k: v for k, v in entry().items()
                  if k not in ("tags", "aliases", "added_at", "homepage", "source", "origin")}
        r = run(self.write_index(make_index(version=3, skills=[legacy])))
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_v4_entry_missing_tags_fails(self):
        skill = {k: v for k, v in entry().items() if k != "tags"}
        r = run(self.write_index(make_index(skills=[skill])))
        self.assertEqual(r.returncode, 1)
        self.assertIn("version >= 4 要求字段 'tags'", r.stdout)

    def test_v4_entry_missing_aliases_and_added_at_fails(self):
        skill = {k: v for k, v in entry().items() if k not in ("aliases", "added_at")}
        r = run(self.write_index(make_index(skills=[skill])))
        self.assertEqual(r.returncode, 1)
        self.assertIn("'aliases'", r.stdout)
        self.assertIn("'added_at'", r.stdout)

    def test_unknown_tag_fails(self):
        r = run(self.write_index(make_index(skills=[entry(tags=["testing", "blockchain"])])))
        self.assertEqual(r.returncode, 1)
        self.assertIn("词表外的标签", r.stdout)

    def test_uppercase_or_cjk_tag_fails(self):
        for bad in ("Testing", "测试", "pdf-doc?"):
            with self.subTest(tag=bad):
                r = run(self.write_index(make_index(skills=[entry(tags=[bad])])))
                self.assertEqual(r.returncode, 1, f"{bad} 应被拒绝")
                self.assertIn("小写 ASCII 单词", r.stdout)

    def test_duplicate_tag_fails(self):
        r = run(self.write_index(make_index(skills=[entry(tags=["pdf", "pdf"])])))
        self.assertEqual(r.returncode, 1)
        self.assertIn("标签重复", r.stdout)

    def test_too_many_tags_fails(self):
        tags = ["agents", "animation", "architecture", "branding", "data", "debugging", "design"]
        r = run(self.write_index(make_index(skills=[entry(tags=tags)])))
        self.assertEqual(r.returncode, 1)
        self.assertIn("最多 6 个", r.stdout)

    def test_duplicate_alias_case_insensitive_fails(self):
        r = run(self.write_index(make_index(skills=[entry(aliases=["PDF 提取", "pdf 提取"])])))
        self.assertEqual(r.returncode, 1)
        self.assertIn("别名重复", r.stdout)

    def test_too_many_aliases_fails(self):
        r = run(self.write_index(make_index(skills=[entry(aliases=[f"别名{i}" for i in range(9)])])))
        self.assertEqual(r.returncode, 1)
        self.assertIn("最多 8 个", r.stdout)

    def test_http_homepage_fails(self):
        r = run(self.write_index(make_index(skills=[entry(homepage="http://example.com")])))
        self.assertEqual(r.returncode, 1)
        self.assertIn("https://", r.stdout)

    def test_bad_added_at_fails(self):
        r = run(self.write_index(make_index(skills=[entry(added_at="2026/09/26")])))
        self.assertEqual(r.returncode, 1)
        self.assertIn("added_at", r.stdout)

    def test_bad_source_fails(self):
        r = run(self.write_index(make_index(skills=[entry(source="unknown-source")])))
        self.assertEqual(r.returncode, 1)
        self.assertIn(".source", r.stdout)

    def test_duplicate_ids_fails(self):
        r = run(self.write_index(make_index(skills=[entry(), entry()])))
        self.assertEqual(r.returncode, 1)
        self.assertIn("duplicate skill ids", r.stdout)

    def test_secret_in_new_fields_fails(self):
        """三条红线对新增字段同样生效：把 token 藏进 alias 也要拦住。"""
        r = run(self.write_index(make_index(skills=[entry(aliases=["ghp_" + "A" * 40])])))
        self.assertEqual(r.returncode, 1)
        self.assertIn("possible secret detected", r.stdout)

    def test_dangerous_command_fails(self):
        """回归：旧正则用 \\b 收尾 → 'rm -rf ~' / 'rm -rf /' / 'rm -rf $HOME' 全部漏检。"""
        for payload in ("rm -rf ~ && git clone https://x/y", "rm -rf /", "rm -rf $HOME",
                        "rm -fr ~/", "rm -rf --no-preserve-root /"):
            with self.subTest(install=payload):
                r = run(self.write_index(make_index(skills=[entry(install=payload)])))
                self.assertEqual(r.returncode, 1, f"{payload!r} 应被拒绝")
                self.assertIn("dangerous command detected", r.stdout)

    def test_normal_recursive_delete_not_flagged(self):
        """精度：只删自己目录下的构建产物是正常安装脚本，不能误报。"""
        for payload in ("rm -rf /tmp/build && git clone https://x/y",
                        "rm -rf ./node_modules && make install",
                        "rm -rf dist/*.js"):
            with self.subTest(install=payload):
                r = run(self.write_index(make_index(skills=[entry(install=payload)])))
                self.assertEqual(r.returncode, 0, f"{payload!r} 不应被拒绝：{r.stdout}")

    def test_missing_required_field_fails(self):
        skill = {k: v for k, v in entry().items() if k != "description"}
        r = run(self.write_index(make_index(skills=[skill])))
        self.assertEqual(r.returncode, 1)
        self.assertIn("missing or empty required field 'description'", r.stdout)

    def test_short_description_fails(self):
        r = run(self.write_index(make_index(skills=[entry(description="太短")])))
        self.assertEqual(r.returncode, 1)
        self.assertIn("description too short", r.stdout)

    def test_invalid_json_fails(self):
        self.index.write_text("{ not json", encoding="utf-8")
        r = run(self.index)
        self.assertEqual(r.returncode, 1)
        self.assertIn("not valid JSON", r.stdout)

    def test_usage_error_returns_2(self):
        r = subprocess.run([sys.executable, str(VALIDATE)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)

    def test_unknown_flag_returns_2(self):
        r = run(self.write_index(make_index()), "--nope")
        self.assertEqual(r.returncode, 2)


class TestReviewLog(TempRepoCase):
    def test_valid_review_log_passes(self):
        self.write_index(make_index())
        self.write_review_log()
        r = run(self.index, "--check-review-log", "--strict")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("均有 approved 留痕", r.stdout)

    def test_missing_basis_fails(self):
        self.write_index(make_index())
        self.write_review_log(decisions=[decision(basis=[])])
        r = run(self.index, "--check-review-log")
        self.assertEqual(r.returncode, 1)
        self.assertIn("'basis'", r.stdout)

    def test_bad_decision_value_fails(self):
        self.write_index(make_index())
        self.write_review_log(decisions=[decision(decision="maybe")])
        r = run(self.index, "--check-review-log")
        self.assertEqual(r.returncode, 1)
        self.assertIn("decision 必须是", r.stdout)

    def test_approved_but_not_indexed_fails(self):
        self.write_index(make_index())
        self.write_review_log(decisions=[decision(sid="ghost-skill")])
        r = run(self.index, "--check-review-log")
        self.assertEqual(r.returncode, 1)
        self.assertIn("不在 index.json 中", r.stdout)

    def test_rejected_but_indexed_fails(self):
        self.write_index(make_index())
        self.write_review_log(decisions=[decision(decision="rejected")])
        r = run(self.index, "--check-review-log")
        self.assertEqual(r.returncode, 1)
        self.assertIn("仍在 index.json 中", r.stdout)

    def test_missing_record_warns_by_default_fails_when_strict(self):
        self.write_index(make_index(skills=[entry(), entry(id="other-skill", name="other-skill")]))
        self.write_review_log()  # 只有 demo-skill 的留痕
        soft = run(self.index, "--check-review-log")
        self.assertEqual(soft.returncode, 0, soft.stdout)
        self.assertIn("[WARN]", soft.stdout)
        self.assertIn("缺少 approved 留痕", soft.stdout)
        hard = run(self.index, "--check-review-log", "--strict")
        self.assertEqual(hard.returncode, 1)
        self.assertIn("缺少 approved 留痕", hard.stdout)

    def test_filename_must_be_month(self):
        self.write_index(make_index())
        self.write_review_log()
        (self.tmp / "review-log" / "2026-09.json").rename(self.tmp / "review-log" / "sept.json")
        r = run(self.index, "--check-review-log")
        self.assertEqual(r.returncode, 1)
        self.assertIn("YYYY-MM.json", r.stdout)

    def test_month_mismatch_fails(self):
        self.write_index(make_index())
        self.write_review_log(month="2026-09")
        path = self.tmp / "review-log" / "2026-09.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["month"] = "2026-08"
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        r = run(self.index, "--check-review-log")
        self.assertEqual(r.returncode, 1)
        self.assertIn("必须等于文件名", r.stdout)

    def test_date_outside_month_fails(self):
        self.write_index(make_index())
        self.write_review_log(decisions=[decision(date="2026-08-31")])
        r = run(self.index, "--check-review-log")
        self.assertEqual(r.returncode, 1)
        self.assertIn("不在 2026-09 月份内", r.stdout)

    def test_pending_record_not_in_index_is_fine(self):
        self.write_index(make_index())
        self.write_review_log(decisions=[decision(), decision(sid="later-skill", decision="pending")])
        r = run(self.index, "--check-review-log", "--strict")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("留痕当前不在 index.json 中", r.stdout)
        self.assertIn("later-skill(pending)", r.stdout)

    def test_latest_decision_wins_for_removed_entry(self):
        """append-only 的核心：条目被合法移除后，历史 approved 记录不得让它永久报错。"""
        self.write_index(make_index())  # 只有 demo-skill
        self.write_review_log(decisions=[
            decision(),
            decision(sid="legacy-skill", date="2026-09-01", decision="approved"),
            decision(sid="legacy-skill", date="2026-09-20", decision="rejected",
                     basis=["上游仓库已归档"], evidence=["https://github.com/example/legacy"]),
        ])
        r = run(self.index, "--check-review-log", "--strict")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("legacy-skill(rejected)", r.stdout)

    def test_removal_without_logging_fails(self):
        """移除条目也必须留痕：只有 approved、条目却不在库 → 红灯。"""
        self.write_index(make_index())
        self.write_review_log(decisions=[decision(), decision(sid="removed-skill", decision="approved")])
        r = run(self.index, "--check-review-log", "--strict")
        self.assertEqual(r.returncode, 1)
        self.assertIn("最新裁决是 approved", r.stdout)

    def test_no_review_log_dir_warns_or_fails(self):
        self.write_index(make_index())
        soft = run(self.index, "--check-review-log")
        self.assertEqual(soft.returncode, 0)
        self.assertIn("未找到留痕文件", soft.stdout)
        hard = run(self.index, "--check-review-log", "--strict")
        self.assertEqual(hard.returncode, 1)


class TestContributions(TempRepoCase):
    def test_consensus_threshold_and_dedupe(self):
        self.write_index(make_index(skills=[entry(id="existing-skill", name="existing-skill")]))
        contrib = [{"id": "new-skill", "name": "new-skill",
                    "description": "社区新技能：被三个不同贡献者独立提交。",
                    "install": "git clone https://github.com/example/new"}]
        for user in ("alice", "bob", "carol"):
            self.write_contribution(f"{user}.json", contrib)
        r = run(self.tmp / "contributions")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("达到自动采纳阈值", r.stdout)

    def test_duplicate_id_in_same_file_fails(self):
        self.write_index(make_index())
        dup = [{"id": "dup-skill", "name": "dup-skill",
                "description": "重复 id：同一文件内出现两次。",
                "install": "git clone https://github.com/example/dup"}] * 2
        self.write_contribution("alice.json", dup)
        r = run(self.tmp / "contributions")
        self.assertEqual(r.returncode, 1)
        self.assertIn("duplicate id", r.stdout)

    def test_example_prefixed_files_ignored(self):
        self.write_index(make_index())
        self.write_contribution("_example.json", [{"id": "x"}])
        r = run(self.tmp / "contributions")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("no contribution files yet", r.stdout)


class TestDeadlinks(TempRepoCase):
    @unittest.skipUnless(NETWORK, "网络不可达：死链探测按设计降级，跳过")
    def test_real_url_reachable(self):
        self.write_index(make_index(skills=[entry(origin="axel286137079-dot/skill-matcher-index",
                                                  homepage="https://github.com/axel286137079-dot/skill-matcher-index")]))
        r = run(self.index, "--check-deadlinks")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("deadlink ok", r.stdout)

    @unittest.skipUnless(NETWORK, "网络不可达：死链探测按设计降级，跳过")
    def test_404_origin_is_dead_link(self):
        self.write_index(make_index(skills=[entry(origin="axel286137079-dot/no-such-repo-xyz-9999")]))
        r = run(self.index, "--check-deadlinks")
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("已失效", r.stdout)

    def test_network_failure_degrades_to_warning(self):
        """不可达主机 → 告警而非错误（网络天气不该阻塞贡献者）。"""
        self.write_index(make_index(skills=[entry(homepage="https://nonexistent.invalid/x")]))
        r = run(self.index, "--check-deadlinks")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("deadlink 未判定", r.stdout)

    def test_origin_used_when_homepage_absent(self):
        """没有 homepage 时，用 origin 推导 https://github.com/<origin> 来探测。"""
        skill = {k: v for k, v in entry().items() if k != "homepage"}
        skill["origin"] = "axel286137079-dot/no-such-repo-xyz-9999"
        self.write_index(make_index(skills=[skill]))
        r = run(self.index, "--check-deadlinks")
        if "未判定" in r.stdout:
            self.skipTest("网络不可达：降级路径已由上一个用例覆盖")
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("github.com/axel286137079-dot/no-such-repo-xyz-9999", r.stdout)


class TestProbeSecurity(unittest.TestCase):
    """安全回归：探测时绝不能把 CI token 发给非 GitHub 主机。"""

    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("_validate_probe", VALIDATE)
        cls.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.mod)

    def _probe_with_fake_transport(self, url):
        captured = []

        class FakeResponse:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        def fake_urlopen(req, timeout=None):
            captured.append({k.lower(): v for k, v in req.header_items()})
            return FakeResponse()

        with mock.patch.object(self.mod.urllib.request, "urlopen", fake_urlopen):
            with mock.patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_" + "S" * 36}, clear=False):
                verdict = self.mod._probe(url)
        return verdict, captured

    def test_token_not_leaked_to_lookalike_host(self):
        """`https://evil.example/?x=github.com` 这类 URL 不能骗到 token（子串判断的经典坑）。"""
        verdict, captured = self._probe_with_fake_transport("https://evil.example/?x=github.com")
        self.assertEqual(verdict[0], "ok")
        self.assertTrue(captured)
        self.assertNotIn("authorization", captured[0])

    def test_token_sent_to_github_host(self):
        verdict, captured = self._probe_with_fake_transport("https://github.com/anthropics/skills")
        self.assertEqual(verdict[0], "ok")
        self.assertIn("authorization", captured[0])


class TestRepoConsistency(unittest.TestCase):
    """本仓库自身的文档/数据/CI 一致性（防「文档说的」与「代码做的」漂移）。"""

    def test_real_index_passes_all_checks(self):
        flags = ["--check-review-log", "--strict"]
        r = run(ROOT / "index.json", *flags)
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_schema_vocab_documented_in_readme(self):
        schema = json.loads(SKILL_SCHEMA.read_text(encoding="utf-8"))
        tags = schema["properties"]["tags"]["items"]["enum"]
        readme = (ROOT / "schema" / "README.md").read_text(encoding="utf-8")
        missing = [t for t in tags if f"| `{t}` |" not in readme]
        self.assertEqual(missing, [], f"schema/README.md 词表缺行：{missing}")

    def test_example_contribution_shows_optional_fields(self):
        data = json.loads((ROOT / "contributions" / "_example.json").read_text(encoding="utf-8"))
        for skill in data:
            for field in ("tags", "aliases", "homepage", "added_at"):
                self.assertIn(field, skill, f"_example.json 应示范可选字段 '{field}'")

    def test_readme_documents_local_checks(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        for needle in ("scripts/validate.py", "scripts/check_schema.py", "scripts/selftest.py"):
            self.assertIn(needle, readme, f"README 应说明本地校验入口：{needle}")


class TestCIConfiguration(unittest.TestCase):
    """CI 编排的校验对象是「本 PR 交付的 CI 配置」：

    - `ci/validate-workflow.patch`：随仓库交付的加固版（应用前的工作副本）；
    - `.github/workflows/validate.yml`：仓库实际生效的版本。

    为什么用补丁：当前 GitHub 连接（Arena App）没有 `workflows` 权限，任何改动 workflow 的
    提交都会被 push 拒绝 —— 详见 ci/README.md。机制已入库且本地可跑，补丁只负责让 CI 自动跑。
    """

    @classmethod
    def setUpClass(cls):
        cls.patch = ROOT / "ci" / "validate-workflow.patch"

    def test_patch_is_shipped(self):
        self.assertTrue(self.patch.is_file(), "应随仓库交付 ci/validate-workflow.patch（见 ci/README.md）")

    def test_patch_pins_actions_by_commit_sha(self):
        added = [l for l in self.patch.read_text(encoding="utf-8").splitlines()
                 if l.startswith("+") and "uses:" in l]
        self.assertTrue(added, "补丁应包含 actions 步骤")
        for line in added:
            self.assertRegex(line, r"uses:\s*\S+@[0-9a-f]{40}",
                             f"{line.strip()} 必须固定到 40 位 commit SHA（防上游 tag 被移动）")

    def test_patch_runs_all_checks(self):
        text = self.patch.read_text(encoding="utf-8")
        for needle in ("scripts/validate.py index.json", "scripts/validate.py contributions",
                       "scripts/check_schema.py --require", "scripts/selftest.py",
                       "--check-review-log", "--check-deadlinks", "permissions:"):
            self.assertIn(needle, text, f"CI 加固版应包含：{needle}")

    def test_live_workflow_matches_patch_when_hardened(self):
        """应用补丁后，本用例从「跳过」转为强制：生效的 workflow 不允许退回浮动 tag。"""
        text = WORKFLOW.read_text(encoding="utf-8")
        uses = re.findall(r"uses:\s*(\S+)", text)
        hardened = bool(uses) and all(re.fullmatch(r"[^@]+@[0-9a-f]{40}", u) for u in uses)
        if not hardened:
            self.skipTest("CI 加固尚未应用（补丁见 ci/README.md）；应用后本用例转为强制校验")
        for u in uses:
            self.assertRegex(u, r"^[^@]+@[0-9a-f]{40}$")
        for needle in ("--check-review-log", "--check-deadlinks", "scripts/selftest.py"):
            self.assertIn(needle, text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
