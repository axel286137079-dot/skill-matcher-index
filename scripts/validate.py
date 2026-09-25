#!/usr/bin/env python3
"""skill-matcher-index 机器预审脚本（CI 与本地共用，单一事实源）。

用法:
    python3 scripts/validate.py index.json          # 校验全局目录
    python3 scripts/validate.py contributions       # 校验贡献文件 + 输出共识统计
    python3 scripts/validate.py index.json --check-review-log    # 追加：审核留痕校验
    python3 scripts/validate.py index.json --check-deadlinks     # 追加：死链探测
    python3 scripts/validate.py index.json --check-review-log --check-deadlinks --strict

检查项:
    A. JSON 合法性
    B. 字段完整性（id / name / description / install 必填）
    C. id 格式（小写字母/数字/连字符）与查重
    D. v4 元数据契约（tags 受控词表 / aliases / homepage / added_at；version >= 4 时必填）
    E. 敏感词 / 密钥 / 危险指令扫描（含新增字段，三条红线对每个字段生效）
    F. 贡献文件按 id 统计提交人数（>=3 人 → 可自动采纳）
    G. 审核留痕 review-log 的格式与「与 index.json 的双向一致」（--check-review-log）
    H. origin/homepage 死链探测（--check-deadlinks；网络不可达时降级为告警，不阻塞 CI）

    本脚本与 schema/*.schema.json 是同一契约的两份等价实现（零依赖 vs JSON Schema），
    二者一致性由 scripts/check_schema.py 在 CI 中断言。

退出码: 0 = 通过, 1 = 存在错误（warnings 不影响退出码）, 2 = 用法错误
"""
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MONTH_RE = re.compile(r"^\d{4}-\d{2}$")
TAG_RE = re.compile(r"^[a-z][a-z0-9-]*$")
HOMEPAGE_RE = re.compile(r"^https://[^\s]+$")

# --- v4 可选字段契约（必须与 schema/skill.schema.json 保持一致）---
# tags 受控词表：小写 ASCII 单词（分词器对 ASCII 取整词，命中权重最高）
TAGS = (
    "agents", "animation", "architecture", "branding", "data", "debugging", "design",
    "document", "e2e", "editing", "ffmpeg", "frontend", "gif", "image", "integration",
    "layout", "marketplace", "mcp", "media", "methodology", "pdf", "planning",
    "playwright", "presentation", "prototype", "slack", "spreadsheet", "styleguide",
    "subagents", "tdd", "testing", "video", "webapp", "workflow",
)
MAX_TAGS = 6
MAX_ALIASES = 8
KNOWN_SOURCES = ("opensource", "community", "local", "marketplace", "manual")
V4_REQUIRED_FIELDS = ("tags", "aliases", "added_at")

# 三条红线之「不含密钥」：常见密钥/令牌形态
SECRET_PATTERNS = [
    (r"AKIA[0-9A-Z]{16}", "AWS Access Key"),
    (r"\b(ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36,}\b", "GitHub token"),
    (r"github_pat_[A-Za-z0-9_]{20,}", "GitHub fine-grained PAT"),
    (r"\bsk-[A-Za-z0-9]{20,}\b", "OpenAI-style API key"),
    (r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b", "Slack token"),
    (r"-----BEGIN [A-Z ]*PRIVATE KEY-----", "private key block"),
    (r"//[^\s:/@]+:[^\s@/]+@", "credentials in URL (user:pass@host)"),
]

# 三条红线之「不含危险指令」
DANGEROUS_PATTERNS = [
    # 注意：这里不能用 \b —— '~' 与 '/' 都不是单词字符，`rm -rf ~` / `rm -rf /` 会漏检。
    # 必须同时做到：目标参数「独立成词」（否则 `rm -rf /tmp/build` 误报），
    # 且 home 清空形式 `~` 与 `~/` 都要覆盖（`rm -rf ~/x` 这类子目录清理不算）。
    (r"rm\s+-\S*(?:rf|fr)\S*(?:\s+-\S+)*\s+"
     r"(?:~/?(?=\s|$|;|&|\||\"|')|\$\{?HOME\}?/?|/)"
     r"(?:\s|$|;|&|\||\"|')", "dangerous recursive delete"),
    (r"\bmkfs\b", "filesystem format command"),
    (r"\bdd\s+if=", "raw disk write"),
    (r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:", "fork bomb"),
    (r">\s*/dev/sd[a-z]", "overwrite block device"),
]

WARN_PATTERNS = [
    (r"(curl|wget)\b[^\n|]*\|\s*(sudo\s+)?(ba|z|da)?sh\b", "pipe-to-shell install (manual review suggested)"),
]

REQUIRED_FIELDS = ("id", "name", "description", "install")
REVIEW_DECISIONS = ("approved", "pending", "rejected")
USER_AGENT = "skill-matcher-index-validator/1.0 (+https://github.com/axel286137079-dot/skill-matcher-index)"
errors = []
warnings = []


def err(msg: str) -> None:
    errors.append(msg)
    print(f"[FAIL] {msg}")


def warn(msg: str) -> None:
    warnings.append(msg)
    print(f"[WARN] {msg}")


def ok(msg: str) -> None:
    print(f"[PASS] {msg}")


def scan_secrets(text: str, where: str) -> None:
    for pattern, label in SECRET_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            err(f"{where}: possible secret detected ({label})")
    for pattern, label in DANGEROUS_PATTERNS:
        if re.search(pattern, text):
            err(f"{where}: dangerous command detected ({label})")
    for pattern, label in WARN_PATTERNS:
        if re.search(pattern, text):
            warn(f"{where}: {label}")


def check_optional_fields(skill: dict, where: str, sid: str) -> None:
    """v4 可选元数据校验，与 schema/skill.schema.json 等价。"""
    label = f"{where} ({sid})"

    source = skill.get("source")
    if source is not None and (not isinstance(source, str) or source not in KNOWN_SOURCES):
        err(f"{label}.source: 必须是 {', '.join(KNOWN_SOURCES)} 之一（got {source!r}）")

    origin = skill.get("origin")
    if origin is not None and not (isinstance(origin, str) and origin.strip()):
        err(f"{label}.origin: 必须是非空字符串")

    homepage = skill.get("homepage")
    if homepage is not None and not (isinstance(homepage, str) and HOMEPAGE_RE.match(homepage)):
        err(f"{label}.homepage: 必须是 https:// 开头的 URL（got {homepage!r}）")

    tags = skill.get("tags")
    if tags is not None:
        if not isinstance(tags, list) or not tags:
            err(f"{label}.tags: 必须是非空数组（受控词表见 schema/README.md）")
        else:
            if len(tags) > MAX_TAGS:
                err(f"{label}.tags: 最多 {MAX_TAGS} 个（got {len(tags)}）")
            seen: dict[str, int] = {}
            for tag in tags:
                if not isinstance(tag, str) or not TAG_RE.match(tag):
                    err(f"{label}.tags: 标签必须是小写 ASCII 单词（got {tag!r}）")
                    continue
                if tag not in TAGS:
                    err(f"{label}.tags: 词表外的标签 {tag!r}（受控词表见 schema/README.md）")
                seen[tag] = seen.get(tag, 0) + 1
            dupes = [t for t, n in seen.items() if n > 1]
            if dupes:
                err(f"{label}.tags: 标签重复 {', '.join(dupes)}")

    aliases = skill.get("aliases")
    if aliases is not None:
        if not isinstance(aliases, list) or not aliases:
            err(f"{label}.aliases: 必须是非空数组（中英皆可，用于提升召回）")
        else:
            if len(aliases) > MAX_ALIASES:
                err(f"{label}.aliases: 最多 {MAX_ALIASES} 个（got {len(aliases)}）")
            seen_alias: dict[str, int] = {}
            for alias in aliases:
                if not isinstance(alias, str) or not alias.strip():
                    err(f"{label}.aliases: 别名必须是非空字符串（got {alias!r}）")
                    continue
                if len(alias) > 64:
                    err(f"{label}.aliases: 别名过长（> 64 字符）：{alias[:32]!r}…")
                key = alias.strip().casefold()
                seen_alias[key] = seen_alias.get(key, 0) + 1
            dupes = [f"{k}×{n}" for k, n in seen_alias.items() if n > 1]
            if dupes:
                err(f"{label}.aliases: 别名重复（大小写不敏感）：{', '.join(dupes)}")

    added_at = skill.get("added_at")
    if added_at is not None and not (isinstance(added_at, str) and DATE_RE.match(added_at)):
        err(f"{label}.added_at: 必须是 YYYY-MM-DD（got {added_at!r})")


def check_skill(skill: dict, where: str) -> str | None:
    """校验单个技能对象，返回 id（合法时）。"""
    if not isinstance(skill, dict):
        err(f"{where}: entry must be a JSON object")
        return None
    for field in REQUIRED_FIELDS:
        value = skill.get(field)
        if not isinstance(value, str) or not value.strip():
            err(f"{where}: missing or empty required field '{field}'")
            return None
    sid = skill.get("id", "")
    if sid and not ID_RE.match(sid):
        err(f"{where} ({sid}): invalid id format (expected lowercase letters/digits/hyphens, e.g. 'my-skill')")
        return None
    desc = skill.get("description", "")
    if isinstance(desc, str) and len(desc.strip()) < 8:
        err(f"{where} ({sid}): description too short (< 8 chars), 越具体匹配越准")
    if isinstance(skill.get("install"), str) and skill["install"].strip():
        scan_secrets(skill["install"], f"{where} ({sid}).install")
    for field in ("description", "install", "origin", "name", "homepage"):
        value = skill.get(field)
        if isinstance(value, str):
            scan_secrets(value, f"{where} ({sid}).{field}")
    # 新增字段同样受三条红线约束
    for field in ("tags", "aliases"):
        value = skill.get(field)
        if isinstance(value, list):
            scan_secrets(" ".join(str(v) for v in value), f"{where} ({sid}).{field}")
    check_optional_fields(skill, where, sid)
    return sid


def validate_index(path: Path) -> tuple[set[str], list[tuple[str, str]]]:
    """校验 index.json，返回 (id 集合, [(id, 待探测 URL)])。"""
    print(f"== index: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        err(f"{path}: not valid JSON ({e})")
        return set(), []
    ok(f"{path}: valid JSON")

    for field in ("name", "description"):
        if not isinstance(data.get(field), str) or not data.get(field).strip():
            err(f"{path}: top-level field '{field}' missing or empty")
    version = data.get("version")
    if not isinstance(version, int) or version < 1:
        err(f"{path}: 'version' must be a positive integer (got {version!r})")
    updated = data.get("updated_at", "")
    if not (isinstance(updated, str) and DATE_RE.match(updated)):
        err(f"{path}: 'updated_at' must be YYYY-MM-DD (got {updated!r})")

    skills = data.get("skills")
    if not isinstance(skills, list) or not skills:
        err(f"{path}: 'skills' must be a non-empty array")
        return set(), []

    # v4 条件契约：version >= 4 时，每条目必须带 tags/aliases/added_at
    enforce_v4 = isinstance(version, int) and version >= 4
    seen: dict[str, int] = {}
    probes: list[tuple[str, str]] = []
    for i, skill in enumerate(skills):
        sid = check_skill(skill, f"{path}.skills[{i}]")
        if not sid:
            continue
        if enforce_v4 and isinstance(skill, dict):
            for field in V4_REQUIRED_FIELDS:
                if field not in skill:
                    err(f"{path}.skills[{i}] ({sid}): version >= 4 要求字段 '{field}'（见 schema/index.schema.json）")
        seen[sid] = seen.get(sid, 0) + 1
        if isinstance(skill, dict):
            url = skill.get("homepage")
            if not url and isinstance(skill.get("origin"), str):
                url = f"https://github.com/{skill['origin'].strip()}"
            if isinstance(url, str) and url:
                probes.append((sid, url))
    dupes = [sid for sid, n in seen.items() if n > 1]
    if dupes:
        err(f"{path}: duplicate skill ids: {', '.join(dupes)}")
    else:
        ok(f"{path}: {len(seen)} skills, ids unique")
        if enforce_v4:
            ok(f"{path}: version {version} — v4 元数据契约（tags/aliases/added_at）齐全")
    return set(seen), probes


def validate_contributions(directory: Path, indexed_ids: set[str]) -> None:
    files = sorted(p for p in directory.glob("*.json") if not p.name.startswith("_"))
    print(f"== contributions: {directory} ({len(files)} file(s), '_'-prefixed ignored)")
    if not files:
        print("[INFO] no contribution files yet — 欢迎成为第一个贡献者 🎉")
        return

    submitters: dict[str, list[str]] = {}
    for path in files:
        where = f"{path.name}"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            err(f"{where}: not valid JSON ({e})")
            continue
        if not isinstance(data, list):
            err(f"{where}: contribution file must be a JSON array")
            continue
        ok(f"{where}: valid JSON array with {len(data)} entr{'y' if len(data) == 1 else 'ies'}")
        local_ids: set[str] = set()
        for i, skill in enumerate(data):
            sid = check_skill(skill, f"{where}[{i}]")
            if sid:
                if sid in local_ids:
                    err(f"{where}: duplicate id '{sid}' within the same file")
                local_ids.add(sid)
                if path.name not in submitters.setdefault(sid, []):
                    submitters[sid].append(path.name)

    # 查重：与已入库条目
    for sid in sorted(submitters):
        if sid in indexed_ids:
            print(f"[INFO] {sid}: 已在 index.json 中（{len(submitters[sid])} 份重复提交将不重复入库）")
    # 共识统计（按不同贡献者文件去重计数）
    pending = {sid: fs for sid, fs in sorted(submitters.items()) if sid not in indexed_ids}
    for sid, fs in sorted(pending.items()):
        n = len(fs)
        if n >= 3:
            ok(f"consensus: {sid} 被 {n} 个不同贡献者提交（{', '.join(fs)}）→ 达到自动采纳阈值")
        else:
            print(f"[INFO] pending: {sid} 目前 {n}/3 个贡献者（{', '.join(fs)}），未达共识")


def validate_review_log(directory: Path, indexed_ids: set[str], strict: bool) -> None:
    """审核留痕：格式 + 与 index.json 的双向一致。

    规则（详见 review-log/README.md）:
      * 文件名 YYYY-MM.json，顶层 month 必须与文件名一致
      * 每条裁决必填 id/date/decision/decided_by/basis；decision ∈ approved|pending|rejected
      * 同一 id 在一个月内可以有多条（当月状态变更/更正）；但同一天不能有两个不同裁决
      * 一致性以「每个 id 的最新裁决」为准（append-only：历史记录保留，当前状态看最新一条）：
          - 最新裁决 = approved ⇒ 该 id 必须在 index.json 中
          - 最新裁决 = pending/rejected ⇒ 该 id 不得出现在 index.json 中
        （不用「任何一条 approved 都得在库」，否则条目一旦被合法移除，历史记录会永久报错）
      * 每条已入库条目都应至少有一条 approved 留痕（--strict 下缺失即错误）
    """
    files = sorted(directory.glob("*.json")) if directory.is_dir() else []
    print(f"== review-log: {directory} ({len(files)} file(s))")
    if not files:
        msg = f"{directory}: 未找到留痕文件（每条入库裁决都应留痕，见 review-log/README.md）"
        (err if strict else warn)(msg)
        return

    logged: dict[str, list[str]] = {}
    for path in files:
        where = path.name
        if not MONTH_RE.match(path.stem):
            err(f"{where}: 文件名必须是 YYYY-MM.json（如 2026-09.json）")
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            err(f"{where}: not valid JSON ({e})")
            continue
        if not isinstance(data, dict):
            err(f"{where}: 留痕文件必须是 JSON 对象")
            continue
        if data.get("month") != path.stem:
            err(f"{where}: 顶层 'month' 必须等于文件名（got {data.get('month')!r}）")
        decisions = data.get("decisions")
        if not isinstance(decisions, list) or not decisions:
            err(f"{where}: 'decisions' 必须是非空数组")
            continue
        ok(f"{where}: {len(decisions)} 条裁决记录")
        local_ids: set[str] = set()
        same_day: dict[tuple[str, str], str] = {}
        for i, d in enumerate(decisions):
            lw = f"{where}[{i}]"
            if not isinstance(d, dict):
                err(f"{lw}: 裁决记录必须是 JSON 对象")
                continue
            for field in ("id", "date", "decision", "decided_by"):
                if not isinstance(d.get(field), str) or not d[field].strip():
                    err(f"{lw}: 缺少必填字段 '{field}'")
            did = d.get("id", "") if isinstance(d.get("id"), str) else ""
            decision = d.get("decision", "")
            if did and not ID_RE.match(did):
                err(f"{lw}: id 格式非法（{did!r}）")
            if decision and decision not in REVIEW_DECISIONS:
                err(f"{lw}: decision 必须是 {', '.join(REVIEW_DECISIONS)} 之一（got {decision!r}）")
            date = d.get("date", "")
            if not (isinstance(date, str) and DATE_RE.match(date)):
                err(f"{lw}: date 必须是 YYYY-MM-DD（got {date!r}）")
            elif isinstance(path.stem, str) and not date.startswith(path.stem):
                err(f"{lw}: date {date} 不在 {path.stem} 月份内")
            basis = d.get("basis")
            if not isinstance(basis, list) or not basis or not all(isinstance(b, str) and b.strip() for b in basis):
                err(f"{lw}: 'basis' 必须是非空字符串数组（裁决依据是留痕的核心价值）")
            evidence = d.get("evidence")
            if evidence is not None:
                if not isinstance(evidence, list):
                    err(f"{lw}: 'evidence' 必须是数组")
                else:
                    for e in evidence:
                        if not (isinstance(e, str) and e.startswith("https://")):
                            err(f"{lw}: evidence 必须是 https:// URL（got {e!r}）")
            if not did:
                continue
            # 同一 id 在一个文件里可以出现多条（当月内状态变更/更正）；但同一天不能有两个不同裁决，
            # 否则「最新裁决」无法确定。
            local_ids.add(did)
            key = (did, str(date))
            prev_decision = same_day.get(key)
            if prev_decision is not None and prev_decision != decision:
                err(f"{where}: '{did}' 在 {date} 有两条不同裁决（{prev_decision} / {decision}），无法确定最新状态")
            same_day[key] = decision
            if decision in REVIEW_DECISIONS:
                logged.setdefault(did, []).append((str(date), decision, where))

    # 每个 id 取最新裁决（同日多条按文件/条目先后，后者胜）
    latest: dict[str, tuple[str, str, str]] = {}
    for sid, records in logged.items():
        best = records[0]
        for rec in records[1:]:
            if rec[0] >= best[0]:
                best = rec
        latest[sid] = best

    if indexed_ids:
        for sid, (date, decision, where) in sorted(latest.items()):
            if decision == "approved" and sid not in indexed_ids:
                err(f"{where}: '{sid}' 最新裁决是 approved（{date}）但不在 index.json 中（留痕与数据不一致）")
            elif decision in ("pending", "rejected") and sid in indexed_ids:
                err(f"{where}: '{sid}' 最新裁决是 {decision}（{date}）但仍在 index.json 中（留痕与数据不一致）")
        missing = sorted(sid for sid in indexed_ids if not any(d == "approved" for _, d, _ in logged.get(sid, [])))
        if missing:
            shown = ", ".join(missing[:8]) + (" …" if len(missing) > 8 else "")
            msg = f"{directory}: {len(missing)} 条已入库条目缺少 approved 留痕：{shown}"
            (err if strict else warn)(msg)
        else:
            ok(f"{directory}: {len(indexed_ids)} 条入库条目均有 approved 留痕")
        not_indexed = sorted(sid for sid in logged if sid not in indexed_ids)
        if not_indexed:
            detail = ", ".join(f"{sid}({latest[sid][1]})" for sid in not_indexed[:8])
            print(f"[INFO] {directory}: {len(not_indexed)} 条留痕当前不在 index.json 中：{detail}")


def _probe(url: str, timeout: int = 8) -> tuple[str, str]:
    """探测单个 URL。返回 (结论, 说明)，结论 ∈ {'ok', 'dead', 'unknown'}。"""
    headers = {"User-Agent": USER_AGENT}
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    # 安全：只按 hostname 判断，绝不能用子串匹配 —— 否则 https://evil.example/?x=github.com
    # 这类 URL 会骗走 CI 的 token（该防护有专门的回归用例 TestProbeSecurity）
    host = (urlsplit(url).hostname or "").lower()
    if token and (host == "github.com" or host.endswith(".github.com")):
        headers["Authorization"] = f"Bearer {token}"
    for method in ("HEAD", "GET"):
        req = urllib.request.Request(url, method=method, headers=headers)
        if method == "GET":
            req.add_header("Range", "bytes=0-0")  # 只取首字节，避免整文件下载
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status < 400:
                    return "ok", f"HTTP {resp.status}"
                return "dead", f"HTTP {resp.status}"
        except urllib.error.HTTPError as e:
            if e.code in (404, 410):
                return "dead", f"HTTP {e.code}"
            if e.code in (403, 429):
                return "unknown", f"HTTP {e.code}（限流/被拒，无法判定）"
            if e.code in (405, 501) and method == "HEAD":
                continue  # 该服务器不支持 HEAD，改用 GET 重试
            return "unknown", f"HTTP {e.code}"
        except Exception as e:  # URLError / timeout / DNS / TLS
            return "unknown", f"网络不可达（{type(e).__name__}）"
    return "unknown", "HEAD/GET 均被拒"


def check_deadlinks(probes: list[tuple[str, str]]) -> None:
    """死链探测：同一 URL 只探一次。网络异常降级为告警（不阻塞 CI）。"""
    by_url: dict[str, list[str]] = {}
    for sid, url in probes:
        by_url.setdefault(url, []).append(sid)
    print(f"== deadlinks: {len(by_url)} unique URL(s) from {len(probes)} entr(y|ies)")
    dead = unknown = 0
    for url, sids in sorted(by_url.items()):
        verdict, detail = _probe(url)
        who = ", ".join(sids[:4]) + (" …" if len(sids) > 4 else "")
        if verdict == "ok":
            ok(f"deadlink ok: {url}（{detail}；{len(sids)} 条：{who}）")
        elif verdict == "dead":
            dead += 1
            err(f"deadlink: {url} 已失效（{detail}；影响 {len(sids)} 条：{who}）")
        else:
            unknown += 1
            warn(f"deadlink 未判定: {url}（{detail}；不影响 CI）")
    if dead:
        print(f"[INFO] {dead} 个 URL 判定为死链")
    elif unknown == len(by_url):
        print("[INFO] 全部探测因网络不可达而未判定 → 按设计降级为告警，不阻塞 CI")


def main() -> int:
    argv = sys.argv[1:]
    flags = {a for a in argv if a.startswith("--")}
    args = [a for a in argv if not a.startswith("--")]
    known_flags = {"--strict", "--check-review-log", "--check-deadlinks"}
    if len(args) != 1 or (flags - known_flags):
        print(__doc__)
        return 2
    strict = "--strict" in flags

    target = Path(args[0])
    indexed_ids: set[str] = set()
    probes: list[tuple[str, str]] = []
    if target.is_file():
        root = target.parent
        indexed_ids, probes = validate_index(target)
    elif target.is_dir():
        root = target.parent
        index_path = root / "index.json"
        if index_path.is_file():
            indexed_ids, probes = validate_index(index_path)
        else:
            warn(f"{root}: 未找到 index.json，跳过目录校验")
        validate_contributions(target, indexed_ids)
    else:
        err(f"target not found: {target}")
        root = Path(".")

    if "--check-review-log" in flags:
        validate_review_log(root / "review-log", indexed_ids, strict)
    if "--check-deadlinks" in flags:
        if probes:
            check_deadlinks(probes)
        else:
            warn("没有可探测的条目（缺少 index.json 或 origin/homepage）")

    print()
    if errors:
        print(f"❌ {len(errors)} error(s), {len(warnings)} warning(s)")
        return 1
    print(f"✅ all checks passed ({len(warnings)} warning(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
