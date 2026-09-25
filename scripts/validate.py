#!/usr/bin/env python3
"""skill-matcher-index 机器预审（CI 与本地共用，只依赖标准库）。

用法:
    python3 scripts/validate.py index.json
    python3 scripts/validate.py contributions
    python3 scripts/validate.py reviews/log.jsonl
    python3 scripts/validate.py --all [--check-links] [--review-base REF]

结构约束的单一事实源是 schema/catalog.schema.json；本脚本再额外检查
JSON Schema 表达不了的规则：密钥、危险指令、id 查重、审核日志一致性、
链接可访问性。scripts/check_schema.py 会断言两边没有漂移。

退出码: 0 通过，1 有错误（warning 不改变退出码），2 用法错误。
"""
from __future__ import annotations

import argparse
import ipaddress
import json
import os
import posixpath
import re
import shlex
import socket
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# --- 与 schema/catalog.schema.json 保持逐字一致（check_schema.py 会比对） ---

ID_PATTERN = r"^[a-z0-9][a-z0-9-]{0,63}$"
NAME_PATTERN = r"^[^\r\n]{1,128}$"
TAG_PATTERN = r"^[a-z0-9][a-z0-9-]{0,31}$"
DATE_PATTERN = r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$"
TS_PATTERN = r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$"
HOMEPAGE_PATTERN = (
    r"^https://(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,}"
    r"(?::[0-9]{1,5})?(?:/[A-Za-z0-9._~:/?#@!$&'()*+,;=%-]*)?$"
)
NONEMPTY_PATTERN = r"^(?=.*\S)[\s\S]+$"
ORIGIN_PATTERN = r"^[^\r\n]{1,200}$"
ALIAS_PATTERN = r"^(?=.*\S)[^\x00-\x1F\x7F]{1,64}$"
BY_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$"
REASON_PATTERN = r"^(?=.*\S)[^\x00-\x1F\x7F]{8,500}$"

ID_RE = re.compile(ID_PATTERN)
NAME_RE = re.compile(NAME_PATTERN)
TAG_RE = re.compile(TAG_PATTERN)
DATE_RE = re.compile(DATE_PATTERN)
TS_RE = re.compile(TS_PATTERN)
HOMEPAGE_RE = re.compile(HOMEPAGE_PATTERN)
NONEMPTY_RE = re.compile(NONEMPTY_PATTERN)
ORIGIN_RE = re.compile(ORIGIN_PATTERN)
ALIAS_RE = re.compile(ALIAS_PATTERN)
BY_RE = re.compile(BY_PATTERN)
REASON_RE = re.compile(REASON_PATTERN)

REQUIRED_SKILL_FIELDS = ("id", "name", "description", "install")
ALLOWED_SKILL_FIELDS = frozenset({
    "id", "name", "description", "install", "source", "origin",
    "tags", "aliases", "homepage",
})
ALLOWED_INDEX_FIELDS = frozenset({"name", "description", "version", "updated_at", "skills"})
ALLOWED_REVIEW_FIELDS = frozenset({"ts", "id", "decision", "by", "reason", "catalog_version"})
REQUIRED_REVIEW_FIELDS = ("ts", "id", "decision", "by", "reason")
SOURCE_VALUES = frozenset({"opensource", "community"})
DECISIONS = frozenset({"approved", "rejected", "revoked", "pending"})
DECISIONS_ABSENT = frozenset({"rejected", "revoked", "pending"})

DESCRIPTION_MIN = 8
DESCRIPTION_MAX = 2000
NAME_MAX = 128
INSTALL_MAX = 500
HOMEPAGE_MAX = 2048
TAGS_MAX = 8
ALIASES_MAX = 8

SECRET_PATTERNS = [
    (r"AKIA[0-9A-Z]{16}", "AWS Access Key"),
    (r"\b(ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36,}\b", "GitHub token"),
    (r"github_pat_[A-Za-z0-9_]{20,}", "GitHub fine-grained PAT"),
    (r"\bsk-[A-Za-z0-9]{20,}\b", "OpenAI-style API key"),
    (r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b", "Slack token"),
    (r"-----BEGIN [A-Z ]*PRIVATE KEY-----", "private key block"),
    (r"//[^\s:/@]+:[^\s@/]+@", "credentials in URL (user:pass@host)"),
]
WARN_PATTERNS = [
    (r"(curl|wget)\b[^|\n]*\|\s*(sudo\s+)?(ba|z|da)?sh\b",
     "pipe-to-shell install (manual review suggested)"),
]

# 旧正则 rm\s+-rf?\s+(~|\$HOME|/)\b 的 \b 贴在非单词字符后永不成立，
# 所以 `rm -rf ~` / `rm -rf /` 漏检，而 `rm -rf /tmp/ok` 又会误报。
# 不要把下面的解析器“简化”回那条正则。selftest 锁着这个回归。
_RM_CMD = re.compile(
    r"(?i)(?:^|[\s;|&`(])(?:(?:sudo|command|nohup|time)\s+)*(?:(?:/usr)?/bin/)?rm(?=\s|$)"
)
_GH_HTTPS = re.compile(
    r"https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)", re.IGNORECASE
)
_GH_SSH = re.compile(
    r"git@github\.com:([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)", re.IGNORECASE
)

UA = "skill-matcher-index-validate/1.0"
GITHUB_TOKEN_HOSTS = frozenset({"github.com", "api.github.com"})
BLOCKED_HOSTS = frozenset({
    "localhost", "localhost.localdomain", "metadata.google.internal",
})
# 只在这两个主机名上附 GITHUB_TOKEN。用 "github.com" in url 会被
# https://evil.com/?x=github.com 骗走 CI token。
LINK_TIMEOUT = 10.0
LINK_RETRIES = 2


class Report:
    def __init__(self, quiet: bool = False):
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.quiet = quiet

    def err(self, msg: str) -> None:
        self.errors.append(msg)
        if not self.quiet:
            print(f"[FAIL] {msg}")

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)
        if not self.quiet:
            print(f"[WARN] {msg}")

    def ok(self, msg: str) -> None:
        if not self.quiet:
            print(f"[PASS] {msg}")

    def info(self, msg: str) -> None:
        if not self.quiet:
            print(f"[INFO] {msg}")

    def finish(self) -> int:
        if not self.quiet:
            print()
            if self.errors:
                print(f"❌ {len(self.errors)} error(s), {len(self.warnings)} warning(s)")
            else:
                print(f"✅ all checks passed ({len(self.warnings)} warning(s))")
        return 1 if self.errors else 0


def _is_real_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _calendar_date(text: str) -> bool:
    try:
        datetime.strptime(text, "%Y-%m-%d")
    except ValueError:
        return False
    return True


def _calendar_ts(text: str) -> bool:
    try:
        datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return False
    return True


# ---------- 危险指令 ----------

def _is_recursive_flag(arg: str) -> bool:
    if arg == "--recursive" or arg.startswith("--recursive="):
        return True
    if arg.startswith("--") or not arg.startswith("-") or arg == "-":
        return False
    return "r" in arg[1:].lower()


def _has_recursive(args: list[str]) -> bool:
    for arg in args:
        if arg == "--":
            break
        if _is_recursive_flag(arg):
            return True
    return False


def _operands(args: list[str]) -> list[str]:
    out: list[str] = []
    ended = False
    for arg in args:
        if not ended:
            if arg == "--":
                ended = True
                continue
            if arg.startswith("-") and arg != "-":
                continue
        out.append(arg)
    return out


def _only_meta(rest: str) -> bool:
    return rest == "" or re.fullmatch(r"[/*.]+", rest) is not None


def _escapes_base(rest: str) -> bool:
    """`~/foo` 不是家目录清空；`~/..`、`~/*`、`~/foo/../..` 是。"""
    if _only_meta(rest):
        return True
    norm = posixpath.normpath(rest)
    return norm in {".", "..", "/"} or norm.startswith("../") or norm.startswith("/")


def _split_home_var(token: str) -> str | None:
    for var in ("${HOME}", "${home}", "$HOME", "$home"):
        if token == var:
            return ""
        if token.startswith(var + "/"):
            return token[len(var) + 1:]
    return None


def is_wipe_target(token: str) -> bool:
    """家目录或文件系统根的递归删除目标。`/tmp/ok`、`~/projects/foo` 不是。"""
    text = token.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "'\"":
        text = text[1:-1]
    if not text:
        return False
    home_rest = _split_home_var(text)
    if home_rest is not None:
        return _escapes_base(home_rest)
    if text == "~" or text.startswith("~/"):
        return _escapes_base(text[2:] if text.startswith("~/") else "")
    user_home = re.fullmatch(r"~([A-Za-z0-9._-]+)(/.*)?", text)
    if user_home:
        rest = (user_home.group(2) or "/")[1:]
        return _escapes_base(rest)
    if text.startswith("/"):
        if re.fullmatch(r"/+\*?", text) or re.fullmatch(r"/+\./?", text):
            return True
        collapsed = text
        if "*" in text:
            collapsed = text.replace("*", "")
            if collapsed == "":
                return True
        norm = posixpath.normpath(collapsed)
        if norm in {"/", "//"}:
            return True
    return False


def iter_rm_args(text: str):
    for match in _RM_CMD.finditer(text):
        tail = text[match.end():]
        tail = re.split(r"[;&|`\n]", tail, maxsplit=1)[0]
        try:
            args = shlex.split(tail, posix=True)
        except ValueError:
            args = tail.split()
        yield args


def dangerous_rm_targets(text: str) -> list[str]:
    found: list[str] = []
    for args in iter_rm_args(text):
        if not _has_recursive(args):
            continue
        for op in _operands(args):
            if is_wipe_target(op):
                found.append(op)
    return found


def dangerous_command_labels(text: str) -> list[str]:
    labels: list[str] = []
    if dangerous_rm_targets(text):
        labels.append("dangerous recursive delete of home or filesystem root")
    if re.search(r"\bmkfs\b", text):
        labels.append("filesystem format command")
    if re.search(r"\bdd\s+if=", text):
        labels.append("raw disk write")
    if re.search(r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:", text):
        labels.append("fork bomb")
    if re.search(r">\s*/dev/sd[a-z]", text):
        labels.append("overwrite block device")
    return labels


def scan_text(text: str, where: str, report: Report) -> None:
    for pattern, label in SECRET_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            report.err(f"{where}: possible secret detected ({label})")
    for label in dangerous_command_labels(text):
        report.err(f"{where}: dangerous command detected ({label})")
    for pattern, label in WARN_PATTERNS:
        if re.search(pattern, text):
            report.warn(f"{where}: {label}")


# ---------- 结构（与 schema 对齐的那一层） ----------

def structural_skill_errors(skill: object) -> list[str]:
    """JSON Schema 能表达的技能对象约束。不含密钥/危险指令扫描。"""
    errs: list[str] = []
    if not isinstance(skill, dict):
        return ["entry must be a JSON object"]
    unknown = sorted(set(skill) - ALLOWED_SKILL_FIELDS)
    if unknown:
        errs.append(f"unknown field(s): {', '.join(unknown)}")
    for field in REQUIRED_SKILL_FIELDS:
        value = skill.get(field)
        if not isinstance(value, str) or value == "":
            errs.append(f"missing or empty required field '{field}'")
    sid = skill.get("id")
    if isinstance(sid, str) and sid and not ID_RE.fullmatch(sid):
        errs.append("invalid id format")
    name = skill.get("name")
    if isinstance(name, str) and name and not NAME_RE.fullmatch(name):
        errs.append("invalid name")
    desc = skill.get("description")
    if isinstance(desc, str) and desc and not (DESCRIPTION_MIN <= len(desc) <= DESCRIPTION_MAX):
        errs.append("description length out of range")
    install = skill.get("install")
    if isinstance(install, str) and install and len(install) > INSTALL_MAX:
        errs.append("install too long")
    if "source" in skill and skill.get("source") not in SOURCE_VALUES:
        errs.append("invalid source")
    if "origin" in skill:
        origin = skill.get("origin")
        if not isinstance(origin, str) or not ORIGIN_RE.fullmatch(origin):
            errs.append("invalid origin")
    if "tags" in skill:
        tags = skill.get("tags")
        if not isinstance(tags, list) or len(tags) > TAGS_MAX:
            errs.append("invalid tags")
        elif any(not isinstance(t, str) or not TAG_RE.fullmatch(t) for t in tags):
            errs.append("invalid tags")
        elif len(tags) != len(set(tags)):
            errs.append("invalid tags")
    if "aliases" in skill:
        aliases = skill.get("aliases")
        if not isinstance(aliases, list) or len(aliases) > ALIASES_MAX:
            errs.append("invalid aliases")
        elif any(not isinstance(a, str) or not ALIAS_RE.fullmatch(a) for a in aliases):
            errs.append("invalid aliases")
    if "homepage" in skill:
        homepage = skill.get("homepage")
        if (not isinstance(homepage, str) or len(homepage) > HOMEPAGE_MAX
                or not HOMEPAGE_RE.fullmatch(homepage)):
            errs.append("invalid homepage")
    return errs


def structural_index_errors(data: object) -> list[str]:
    errs: list[str] = []
    if not isinstance(data, dict):
        return ["index must be a JSON object"]
    unknown = sorted(set(data) - ALLOWED_INDEX_FIELDS)
    if unknown:
        errs.append(f"unknown top-level field(s): {', '.join(unknown)}")
    for field in ("name", "description"):
        value = data.get(field)
        if not isinstance(value, str) or not NONEMPTY_RE.fullmatch(value):
            errs.append(f"top-level field '{field}' missing or empty")
    version = data.get("version")
    if not _is_real_int(version) or version < 1:
        errs.append("'version' must be a positive integer")
    updated = data.get("updated_at")
    if not isinstance(updated, str) or not DATE_RE.fullmatch(updated) or not _calendar_date(updated):
        errs.append("'updated_at' must be a real YYYY-MM-DD date")
    skills = data.get("skills")
    if not isinstance(skills, list) or not skills:
        errs.append("'skills' must be a non-empty array")
    return errs


def check_skill(skill: object, where: str, report: Report) -> str | None:
    if not isinstance(skill, dict):
        report.err(f"{where}: entry must be a JSON object")
        return None
    sid = skill.get("id") if isinstance(skill.get("id"), str) else ""
    label = f"{where} ({sid})" if sid else where
    ok = True
    for msg in structural_skill_errors(skill):
        report.err(f"{label}: {msg}")
        ok = False
    texts: list[tuple[str, str]] = []
    for field in ("id", "name", "description", "install", "origin", "homepage"):
        value = skill.get(field)
        if isinstance(value, str):
            texts.append((field, value))
    tags = skill.get("tags")
    if isinstance(tags, list):
        texts.extend((f"tags[{i}]", t) for i, t in enumerate(tags) if isinstance(t, str))
    aliases = skill.get("aliases")
    if isinstance(aliases, list):
        texts.extend((f"aliases[{i}]", a) for i, a in enumerate(aliases) if isinstance(a, str))
    for field, value in texts:
        scan_text(value, f"{label}.{field}", report)
    aliases = skill.get("aliases")
    if isinstance(aliases, list) and all(isinstance(a, str) for a in aliases):
        folded = [a.casefold() for a in aliases]
        if len(folded) != len(set(folded)):
            report.err(f"{label}: duplicate aliases ignoring case")
            ok = False
    if not ok:
        return None
    return sid or None


def load_json(path: Path, report: Report):
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        report.err(f"{path}: cannot read ({exc})")
        return None
    if text.startswith("\ufeff"):
        report.err(f"{path}: BOM is not allowed")
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        report.err(f"{path}: not valid JSON ({exc})")
        return None


def check_schema_drift(report: Report, schema_path: Path | None = None) -> None:
    """比对 schema 文件和本模块常量。不依赖 jsonschema，CI 现有命令也能跑。"""
    path = schema_path or (ROOT / "schema" / "catalog.schema.json")
    if not path.is_file():
        report.err(f"{path}: schema file missing")
        return
    try:
        schema = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        report.err(f"{path}: cannot load schema ({exc})")
        return
    skill = schema.get("$defs", {}).get("skill", {})
    review = schema.get("$defs", {}).get("reviewRecord", {})
    problems: list[str] = []

    def expect(label: str, schema_value, code_value) -> None:
        if schema_value != code_value:
            problems.append(f"{label}: schema={schema_value!r} code={code_value!r}")

    try:
        expect("index fields", set(schema["properties"]), set(ALLOWED_INDEX_FIELDS))
        expect("index required", set(schema["required"]),
               {"name", "description", "version", "updated_at", "skills"})
        expect("skill fields", set(skill["properties"]), set(ALLOWED_SKILL_FIELDS))
        expect("skill required", set(skill["required"]), set(REQUIRED_SKILL_FIELDS))
        expect("source enum", set(skill["properties"]["source"]["enum"]), set(SOURCE_VALUES))
        expect("review fields", set(review["properties"]), set(ALLOWED_REVIEW_FIELDS))
        expect("review required", set(review["required"]), set(REQUIRED_REVIEW_FIELDS))
        expect("decisions", set(review["properties"]["decision"]["enum"]), set(DECISIONS))
        expect("id pattern", skill["properties"]["id"]["pattern"], ID_PATTERN)
        expect("name pattern", skill["properties"]["name"]["pattern"], NAME_PATTERN)
        expect("origin pattern", skill["properties"]["origin"]["pattern"], ORIGIN_PATTERN)
        expect("tag pattern", skill["properties"]["tags"]["items"]["pattern"], TAG_PATTERN)
        expect("alias pattern", skill["properties"]["aliases"]["items"]["pattern"], ALIAS_PATTERN)
        expect("homepage pattern", skill["properties"]["homepage"]["pattern"], HOMEPAGE_PATTERN)
        expect("index.name pattern", schema["properties"]["name"]["pattern"], NONEMPTY_PATTERN)
        expect("updated_at pattern", schema["properties"]["updated_at"]["pattern"], DATE_PATTERN)
        expect("ts pattern", review["properties"]["ts"]["pattern"], TS_PATTERN)
        expect("by pattern", review["properties"]["by"]["pattern"], BY_PATTERN)
        expect("reason pattern", review["properties"]["reason"]["pattern"], REASON_PATTERN)
        expect("description min", skill["properties"]["description"]["minLength"], DESCRIPTION_MIN)
        expect("description max", skill["properties"]["description"]["maxLength"], DESCRIPTION_MAX)
        expect("install max", skill["properties"]["install"]["maxLength"], INSTALL_MAX)
        expect("tags max", skill["properties"]["tags"]["maxItems"], TAGS_MAX)
        expect("aliases max", skill["properties"]["aliases"]["maxItems"], ALIASES_MAX)
        expect("homepage max", skill["properties"]["homepage"]["maxLength"], HOMEPAGE_MAX)
    except (KeyError, TypeError) as exc:
        problems.append(f"schema shape: {exc}")
    for msg in problems:
        report.err(f"{path}: drift {msg}")
    if not problems:
        report.ok(f"{path}: patterns and field sets match validate.py")


def validate_index(path: Path, report: Report) -> set[str]:
    print_path = path
    if not report.quiet:
        print(f"== index: {print_path}")
    data = load_json(path, report)
    if data is None:
        return set()
    report.ok(f"{path}: valid JSON")
    for msg in structural_index_errors(data):
        report.err(f"{path}: {msg}")
    skills = data.get("skills") if isinstance(data, dict) else None
    if not isinstance(skills, list):
        return set()
    seen: dict[str, int] = {}
    for i, skill in enumerate(skills):
        check_skill(skill, f"{path}.skills[{i}]", report)
        # 查重和审核日志看的是“文件里声明的 id”，不要因为别的字段出错就把条目当成不存在。
        sid = skill.get("id") if isinstance(skill, dict) else None
        if isinstance(sid, str) and ID_RE.fullmatch(sid):
            seen[sid] = seen.get(sid, 0) + 1
    dupes = [sid for sid, n in seen.items() if n > 1]
    if dupes:
        report.err(f"{path}: duplicate skill ids: {', '.join(dupes)}")
    elif seen:
        report.ok(f"{path}: {len(seen)} skills, ids unique")
    if path.resolve() == (ROOT / "index.json").resolve():
        check_schema_drift(report)
    return set(seen)


def validate_contributions(directory: Path, indexed_ids: set[str], report: Report) -> None:
    files = sorted(p for p in directory.glob("*.json") if not p.name.startswith("_"))
    if not report.quiet:
        print(f"== contributions: {directory} ({len(files)} file(s), '_'-prefixed ignored)")
    if not files:
        report.info("no contribution files yet — 欢迎成为第一个贡献者 🎉")
        return
    submitters: dict[str, list[str]] = {}
    for path in files:
        where = path.name
        data = load_json(path, report)
        if data is None:
            continue
        if not isinstance(data, list):
            report.err(f"{where}: contribution file must be a JSON array")
            continue
        report.ok(f"{where}: valid JSON array with {len(data)} entr{'y' if len(data) == 1 else 'ies'}")
        local_ids: set[str] = set()
        for i, skill in enumerate(data):
            sid = check_skill(skill, f"{where}[{i}]", report)
            if not sid:
                continue
            if sid in local_ids:
                report.err(f"{where}: duplicate id '{sid}' within the same file")
            local_ids.add(sid)
            if path.name not in submitters.setdefault(sid, []):
                submitters[sid].append(path.name)
    for sid in sorted(submitters):
        if sid in indexed_ids:
            report.info(f"{sid}: 已在 index.json 中（{len(submitters[sid])} 份重复提交将不重复入库）")
    pending = {sid: fs for sid, fs in submitters.items() if sid not in indexed_ids}
    for sid, fs in sorted(pending.items()):
        n = len(fs)
        if n >= 3:
            report.ok(f"consensus: {sid} 被 {n} 个不同贡献者提交（{', '.join(fs)}）→ 达到自动采纳阈值")
        else:
            report.info(f"pending: {sid} 目前 {n}/3 个贡献者（{', '.join(fs)}），未达共识")


# ---------- 审核日志：以每个 id 的最新裁决为准，不是“出现过 approved” ----------

def structural_review_errors(rec: object) -> list[str]:
    errs: list[str] = []
    if not isinstance(rec, dict):
        return ["record must be a JSON object"]
    unknown = sorted(set(rec) - ALLOWED_REVIEW_FIELDS)
    if unknown:
        errs.append(f"unknown field(s): {', '.join(unknown)}")
    for field in REQUIRED_REVIEW_FIELDS:
        if field not in rec:
            errs.append(f"missing field '{field}'")
    ts = rec.get("ts")
    if not isinstance(ts, str) or not TS_RE.fullmatch(ts) or not _calendar_ts(ts):
        errs.append("invalid ts")
    sid = rec.get("id")
    if not isinstance(sid, str) or not ID_RE.fullmatch(sid):
        errs.append("invalid id")
    if rec.get("decision") not in DECISIONS:
        errs.append("invalid decision")
    by = rec.get("by")
    if not isinstance(by, str) or not BY_RE.fullmatch(by):
        errs.append("invalid by")
    reason = rec.get("reason")
    if not isinstance(reason, str) or not REASON_RE.fullmatch(reason):
        errs.append("invalid reason")
    if "catalog_version" in rec and (not _is_real_int(rec.get("catalog_version")) or rec["catalog_version"] < 1):
        errs.append("invalid catalog_version")
    return errs


def parse_review_log(text: str) -> tuple[list[dict], list[str]]:
    errs: list[str] = []
    records: list[dict] = []
    if text.startswith("\ufeff"):
        return [], ["BOM is not allowed"]
    if text and not text.endswith("\n"):
        errs.append("file must end with a newline")
    lines = text.splitlines()
    for i, line in enumerate(lines, 1):
        if line == "":
            errs.append(f"line {i}: blank line")
            continue
        if line != line.strip() or "\t" in line:
            errs.append(f"line {i}: unexpected whitespace")
        try:
            rec = json.loads(line)
        except json.JSONDecodeError as exc:
            errs.append(f"line {i}: not JSON ({exc})")
            continue
        for msg in structural_review_errors(rec):
            errs.append(f"line {i}: {msg}")
        if isinstance(rec, dict):
            records.append(rec)
    timestamps = [r.get("ts") for r in records if isinstance(r.get("ts"), str)]
    for prev, cur in zip(timestamps, timestamps[1:]):
        if cur < prev:
            errs.append(f"timestamps must be non-decreasing ({prev} -> {cur})")
            break
    return records, errs


def latest_decisions(records: list[dict]) -> dict[str, dict]:
    latest: dict[str, dict] = {}
    for rec in records:
        sid = rec.get("id")
        if isinstance(sid, str):
            latest[sid] = rec
    return latest


def review_consistency_errors(records: list[dict], indexed_ids: set[str]) -> list[str]:
    """在目录 ⟺ 该 id 的最新裁决是 approved。历史 approved 被撤销后不再要求仍在目录里。"""
    errs: list[str] = []
    latest = latest_decisions(records)
    for sid in sorted(indexed_ids):
        rec = latest.get(sid)
        if rec is None:
            errs.append(f"{sid}: in index.json but has no review record")
        elif rec.get("decision") != "approved":
            errs.append(
                f"{sid}: latest decision is {rec.get('decision')} but id is still in index.json"
            )
    for sid, rec in sorted(latest.items()):
        decision = rec.get("decision")
        if decision == "approved" and sid not in indexed_ids:
            errs.append(f"{sid}: latest decision is approved but id is not in index.json")
        if decision in DECISIONS_ABSENT and sid in indexed_ids:
            # 上面已报过“仍在目录里”。这里不重复。
            pass
    return errs


def append_only_errors(new_text: str, old_text: str | None) -> list[str]:
    if old_text is None:
        return []
    if old_text == "":
        return []
    if not new_text.startswith(old_text):
        return ["reviews/log.jsonl is not append-only relative to base "
                "(existing lines were edited, reordered, or removed)"]
    return []


def git_blob(ref: str, relpath: str) -> str | None:
    """返回 blob 文本；路径不存在返回 None。ref 无效则抛 RuntimeError。"""
    rev = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", ref],
        cwd=ROOT, capture_output=True, text=True,
    )
    if rev.returncode != 0:
        raise RuntimeError(f"git ref not found: {ref}")
    spec = f"{ref}:{relpath}"
    exists = subprocess.run(
        ["git", "cat-file", "-e", spec], cwd=ROOT, capture_output=True,
    )
    if exists.returncode != 0:
        return None
    blob = subprocess.run(
        ["git", "cat-file", "blob", spec], cwd=ROOT, capture_output=True,
    )
    if blob.returncode != 0:
        raise RuntimeError(blob.stderr.decode("utf-8", "replace").strip() or f"cannot read {spec}")
    return blob.stdout.decode("utf-8")


def validate_review_log(
    path: Path,
    indexed_ids: set[str],
    report: Report,
    *,
    review_base: str | None = None,
    base_text: str | None = None,
) -> list[dict]:
    if not report.quiet:
        print(f"== reviews: {path}")
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        report.err(f"{path}: cannot read ({exc})")
        return []
    records, errs = parse_review_log(text)
    for msg in errs:
        report.err(f"{path}: {msg}")
    for msg in review_consistency_errors(records, indexed_ids):
        report.err(f"{path}: {msg}")
    if base_text is None and review_base:
        rel = "reviews/log.jsonl"
        try:
            base_text = git_blob(review_base, rel)
        except RuntimeError as exc:
            report.err(f"{path}: append-only check failed ({exc})")
            base_text = None
        else:
            if base_text is None:
                report.info(f"append-only: {review_base} has no {rel} yet (introducing the log)")
    if review_base or base_text is not None:
        for msg in append_only_errors(text, base_text):
            report.err(f"{path}: {msg}")
        if base_text and not any("append-only" in e for e in report.errors):
            report.ok(f"{path}: append-only relative to base")
    consistent = not review_consistency_errors(records, indexed_ids)
    if not errs and consistent:
        report.ok(f"{path}: {len(records)} records, latest decision consistent with index.json")
    return records


def resolve_review_base(explicit: str | None) -> str | None:
    if explicit:
        return explicit
    env = os.environ.get("REVIEW_LOG_BASE")
    if env:
        return env
    event = os.environ.get("GITHUB_EVENT_NAME")
    if event == "pull_request":
        base = os.environ.get("GITHUB_BASE_REF")
        if not base:
            return ""
        return f"origin/{base}"
    if event == "push":
        return "HEAD^"
    return None


# ---------- 链接探测：token 只按主机名附加，且每跳重建请求头 ----------

def token_for_probe(url: str, token: str | None) -> str | None:
    if not token:
        return None
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https":
        return None
    if parts.username or parts.password:
        return None
    host = (parts.hostname or "").lower().rstrip(".")
    if host not in GITHUB_TOKEN_HOSTS:
        return None
    return token


def refusal_reason(url: str) -> str | None:
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https":
        return "only https URLs are probed"
    if parts.username or parts.password:
        return "refusing URL with userinfo"
    host = parts.hostname
    if not host:
        return "URL has no host"
    host = host.lower().rstrip(".")
    if host in BLOCKED_HOSTS or host.endswith(".local") or host.endswith(".internal"):
        return f"refusing blocked host {host}"
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        addr = None
    if addr is not None and not addr.is_global:
        return f"refusing non-public address {host}"
    if len(url) > HOMEPAGE_MAX:
        return "URL too long"
    return None


def dns_guard(host: str) -> tuple[str, str] | None:
    """返回 (kind, detail)。kind 为 refused 或 network。通过则 None。"""
    try:
        infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        return ("network", f"dns:{exc.errno or type(exc).__name__}")
    ips = {item[4][0] for item in infos}
    if not ips:
        return ("network", "dns:no-address")
    for ip in sorted(ips):
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            return ("refused", f"unparseable address {ip}")
        if not addr.is_global:
            return ("refused", f"{host} resolved to non-public {ip}")
    return None


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def probe_once(url: str, token: str | None, timeout: float = LINK_TIMEOUT):
    """探测一个 URL。每跳重新调用 token_for_probe，不把 Authorization 原样转发出去。"""
    current = url
    opener = urllib.request.build_opener(_NoRedirect)
    for _hop in range(6):
        refused = refusal_reason(current)
        if refused:
            return ("refused", refused, current)
        host = (urllib.parse.urlsplit(current).hostname or "").lower().rstrip(".")
        guarded = dns_guard(host)
        if guarded:
            return (guarded[0], guarded[1], current)
        headers = {
            "User-Agent": UA,
            "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
        }
        # 故意每跳重建。redirect 到其他主机时 token_for_probe 返回 None。
        tok = token_for_probe(current, token)
        if tok:
            headers["Authorization"] = f"Bearer {tok}"
        req = urllib.request.Request(current, headers=headers, method="GET")
        try:
            with opener.open(req, timeout=timeout) as resp:
                resp.read(512)
                code = getattr(resp, "status", 200)
                if 200 <= int(code) < 300:
                    return ("ok", str(code), current)
                return ("http_client", str(code), current)
        except urllib.error.HTTPError as exc:
            if exc.code in {301, 302, 303, 307, 308}:
                loc = exc.headers.get("Location") if exc.headers else None
                if not loc:
                    return ("http_client", f"{exc.code} without Location", current)
                current = urllib.parse.urljoin(current, loc)
                continue
            if exc.code in {404, 410}:
                return ("dead", str(exc.code), current)
            if 400 <= exc.code < 500:
                return ("http_client", str(exc.code), current)
            return ("http_server", str(exc.code), current)
        except Exception as exc:  # noqa: BLE001 - 网络失败要归类，不能把栈扔给贡献者
            return ("network", type(exc).__name__, current)
    return ("http_client", "too many redirects", current)


def probe_url(url: str, token: str | None) -> tuple[str, str, str]:
    kind, detail, final = probe_once(url, token)
    # 坏 token 不该把公开仓库判死。只在确实附过 token 时，再裸请求一次。
    # 公开页面不需要 token。token 引起的 401/403 退回裸请求，避免把公开仓库判死。
    if kind == "http_client" and detail in {"401", "403"} and token_for_probe(url, token):
        kind, detail, final = probe_once(url, None)
    attempts = 0
    while kind in {"network", "http_server"} and attempts < LINK_RETRIES:
        attempts += 1
        kind, detail, final = probe_once(url, token)
    return kind, detail, final


def link_disposition(url: str, kind: str) -> str:
    """返回 error / warn / ok。github.com 整体不可达时降级为 warn，避免一次断网挡住合并；
    其他主机的网络失败是 error，防止用 .invalid 域名绕过死链检查。"""
    if kind == "ok":
        return "ok"
    if kind in {"dead", "refused", "http_client"}:
        return "error"
    host = (urllib.parse.urlsplit(url).hostname or "").lower().rstrip(".")
    if kind in {"network", "http_server"} and host in GITHUB_TOKEN_HOSTS:
        return "warn"
    return "error"


def github_repo_urls(install: str) -> list[str]:
    found: list[str] = []
    for rx in (_GH_HTTPS, _GH_SSH):
        for match in rx.finditer(install):
            owner, repo = match.group(1), match.group(2)
            if repo.lower().endswith(".git"):
                repo = repo[:-4]
            found.append(f"https://github.com/{owner}/{repo}")
    return found


def link_targets_from_skill(skill: dict, where: str) -> list[tuple[str, str]]:
    targets: list[tuple[str, str]] = []
    homepage = skill.get("homepage")
    if isinstance(homepage, str) and homepage:
        targets.append((f"{where}.homepage", homepage))
    install = skill.get("install")
    if isinstance(install, str):
        for url in github_repo_urls(install):
            targets.append((f"{where}.install", url))
    return targets


def iter_catalog_link_targets(root: Path = ROOT) -> list[tuple[str, str]]:
    targets: list[tuple[str, str]] = []
    index_path = root / "index.json"
    try:
        data = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    for i, skill in enumerate(data.get("skills") or []):
        if isinstance(skill, dict):
            targets.extend(link_targets_from_skill(skill, f"index.json.skills[{i}]"))
    contrib = root / "contributions"
    if contrib.is_dir():
        for path in sorted(contrib.glob("*.json")):
            if path.name.startswith("_"):
                continue
            try:
                body = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(body, list):
                continue
            for i, skill in enumerate(body):
                if isinstance(skill, dict):
                    targets.extend(link_targets_from_skill(skill, f"{path.name}[{i}]"))
    return targets


def check_links(report: Report, token: str | None = None, root: Path = ROOT) -> None:
    grouped: dict[str, list[str]] = {}
    for where, url in iter_catalog_link_targets(root):
        grouped.setdefault(url, []).append(where)
    if not report.quiet:
        print(f"== links: {len(grouped)} unique URL(s)")
    if token is None:
        token = os.environ.get("GITHUB_TOKEN") or None
    for url, wheres in grouped.items():
        where = ", ".join(wheres)
        kind, detail, _final = probe_url(url, token)
        disp = link_disposition(url, kind)
        msg = f"{where}: {url} -> {kind} {detail}"
        if disp == "ok":
            report.ok(msg)
        elif disp == "warn":
            report.warn(msg)
        else:
            report.err(msg)


# ---------- CLI ----------

def _index_beside(target: Path) -> Path | None:
    if target.is_file() and target.name == "index.json":
        return target
    candidate = target.parent / "index.json"
    if candidate.is_file():
        return candidate
    root_index = ROOT / "index.json"
    return root_index if root_index.is_file() else None


def validate_index_tree(index_path: Path, report: Report, review_base: str | None) -> set[str]:
    ids = validate_index(index_path, report)
    log_path = index_path.parent / "reviews" / "log.jsonl"
    if log_path.is_file():
        validate_review_log(log_path, ids, report, review_base=review_base)
    return ids


def run_all(report: Report, *, check_links_flag: bool, review_base: str | None) -> None:
    index_path = ROOT / "index.json"
    ids = validate_index(index_path, report)
    log_path = ROOT / "reviews" / "log.jsonl"
    if not log_path.is_file():
        report.err(f"{log_path}: missing (append-only audit log is required)")
    else:
        base = resolve_review_base(review_base)
        if base == "":
            report.err(f"{log_path}: CI pull_request is missing GITHUB_BASE_REF")
        elif base is None:
            report.info("append-only check skipped (no base ref; CI sets GITHUB_BASE_REF / REVIEW_LOG_BASE)")
            validate_review_log(log_path, ids, report, review_base=None)
        else:
            validate_review_log(log_path, ids, report, review_base=base)
    contrib = ROOT / "contributions"
    if contrib.is_dir():
        validate_contributions(contrib, ids, report)
    else:
        report.err(f"{contrib}: missing")
    if check_links_flag:
        check_links(report)


def links_requested(explicit: bool) -> bool:
    # 现有 CI 只调用 validate.py，改不了 workflow 文件（App 无 workflows 权限）。
    # Actions 里默认探测链接；本地仍要显式 --check-links，避免离线预审被网络拖死。
    return explicit or os.environ.get("GITHUB_ACTIONS") == "true"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="skill-matcher-index machine pre-check")
    parser.add_argument("target", nargs="?", help="index.json, contributions/, or reviews/log.jsonl")
    parser.add_argument("--all", action="store_true", help="validate index, review log, and contributions")
    parser.add_argument("--check-links", action="store_true", help="probe install/homepage URLs (needs network)")
    parser.add_argument("--review-base", help="git ref; current reviews/log.jsonl must start with that blob")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)
    args.check_links = links_requested(args.check_links)
    report = Report(quiet=args.quiet)
    if args.all:
        run_all(report, check_links_flag=args.check_links, review_base=args.review_base)
        return report.finish()
    if not args.target:
        parser.print_help()
        return 2
    target = Path(args.target)
    if not target.exists():
        report.err(f"target not found: {target}")
        return report.finish()
    if target.is_dir():
        index_path = _index_beside(target)
        ids = validate_index_tree(index_path, report, args.review_base) if index_path else set()
        validate_contributions(target, ids, report)
    elif target.name == "log.jsonl" or target.suffix == ".jsonl":
        index_path = _index_beside(target)
        ids: set[str] = set()
        if index_path:
            data = load_json(index_path, Report(quiet=True))
            if isinstance(data, dict):
                ids = {s.get("id") for s in data.get("skills") or [] if isinstance(s, dict) and isinstance(s.get("id"), str)}
        validate_review_log(target, ids, report, review_base=resolve_review_base(args.review_base))
    elif target.is_file():
        validate_index_tree(target, report, resolve_review_base(args.review_base) if args.review_base else None)
        if args.check_links:
            check_links(report)
    else:
        report.err(f"target not found: {target}")
    if args.check_links and target.is_dir():
        check_links(report)
    return report.finish()


if __name__ == "__main__":
    sys.exit(main())
