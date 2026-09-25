#!/usr/bin/env python3
"""skill-matcher-index 机器预审脚本（CI 与本地共用，单一事实源）。

用法:
    python3 scripts/validate.py index.json          # 校验全局目录
    python3 scripts/validate.py contributions       # 校验贡献文件 + 输出共识统计

检查项:
    1. JSON 合法性
    2. 字段完整性（id / name / description / install 必填）
    3. id 格式（小写字母/数字/连字符）与查重
    4. 敏感词 / 密钥 / 危险指令扫描（三条红线中的「不含密钥」「不含危险指令」）
    5. 贡献文件按 id 统计提交人数，输出共识状态（≥3 人 → 可自动采纳）

退出码: 0 = 通过, 1 = 存在错误（warnings 不影响退出码）
"""
import json
import re
import sys
from pathlib import Path

ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

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
    (r"rm\s+-rf?\s+(~|\$HOME|/)\b", "dangerous recursive delete"),
    (r"\bmkfs\b", "filesystem format command"),
    (r"\bdd\s+if=", "raw disk write"),
    (r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:", "fork bomb"),
    (r">\s*/dev/sd[a-z]", "overwrite block device"),
]

WARN_PATTERNS = [
    (r"(curl|wget)\b[^\n|]*\|\s*(sudo\s+)?(ba|z|da)?sh\b", "pipe-to-shell install (manual review suggested)"),
]

REQUIRED_FIELDS = ("id", "name", "description", "install")
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
    install = skill.get("install", "")
    if isinstance(install, str) and install.strip():
        scan_secrets(install, f"{where} ({sid}).install")
    for field in ("description", "install", "origin", "name"):
        value = skill.get(field)
        if isinstance(value, str):
            scan_secrets(value, f"{where} ({sid}).{field}")
    return sid


def validate_index(path: Path) -> set[str]:
    print(f"== index: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        err(f"{path}: not valid JSON ({e})")
        return set()
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
        return set()

    seen: dict[str, int] = {}
    for i, skill in enumerate(skills):
        sid = check_skill(skill, f"{path}.skills[{i}]")
        if sid:
            seen[sid] = seen.get(sid, 0) + 1
    dupes = [sid for sid, n in seen.items() if n > 1]
    if dupes:
        err(f"{path}: duplicate skill ids: {', '.join(dupes)}")
    else:
        ok(f"{path}: {len(seen)} skills, ids unique")
    return set(seen)


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


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    target = Path(sys.argv[1])
    if target.is_file():
        validate_index(target)
    elif target.is_dir():
        index_path = target.parent / "index.json"
        indexed_ids = validate_index(index_path) if index_path.is_file() else set()
        validate_contributions(target, indexed_ids)
    else:
        err(f"target not found: {target}")
    print()
    if errors:
        print(f"❌ {len(errors)} error(s), {len(warnings)} warning(s)")
        return 1
    print(f"✅ all checks passed ({len(warnings)} warning(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
