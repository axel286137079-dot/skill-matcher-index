#!/usr/bin/env python3
"""用 JSON Schema 校验目录，并断言它和 scripts/validate.py 没有漂移。

schema 负责结构。密钥、危险指令、id 查重、审核日志“最新裁决”、链接探测
不在 schema 里，由 validate.py + selftest.py 负责。本脚本只证明：
schema 不是摆设（负样本会被拒），而且它和 validate.py 的结构判断一致。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import validate  # noqa: E402

try:
    from jsonschema import Draft202012Validator
    from jsonschema.exceptions import SchemaError
except ImportError:
    print("jsonschema is not installed. CI installs requirements-dev.txt; locally: python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt", file=sys.stderr)
    sys.exit(2)


def die(msg: str) -> None:
    print(f"[FAIL] {msg}")
    raise SystemExit(1)


def load_schema() -> dict:
    path = ROOT / "schema" / "catalog.schema.json"
    schema = json.loads(path.read_text(encoding="utf-8"))
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        die(f"catalog.schema.json is not a valid Draft 2020-12 schema: {exc}")
    return schema


def validator_for(schema: dict, subschema: dict) -> Draft202012Validator:
    document = {
        "$schema": schema["$schema"],
        "$id": schema["$id"],
        "$defs": schema["$defs"],
    }
    document.update(subschema)
    return Draft202012Validator(document)


def check_drift(schema: dict) -> None:
    # 字段/正则对账的实现在 validate.check_schema_drift，避免两份拷贝再漂移。
    # schema 参数保留，是为了确认调用方已经把文件解析成功。
    if not isinstance(schema, dict) or "$defs" not in schema:
        die("catalog schema missing $defs")
    report = validate.Report(quiet=True)
    validate.check_schema_drift(report)
    if report.errors:
        die("; ".join(report.errors))
    print("[PASS] schema patterns and field sets match validate.py")


def skill(**overrides) -> dict:
    base = {
        "id": "demo-skill",
        "name": "demo-skill",
        "description": "A concrete description of the skill.",
        "install": "git clone https://github.com/example/demo-skill",
    }
    base.update(overrides)
    return base


def index(skills: list | None = None, **overrides) -> dict:
    base = {
        "name": "catalog",
        "description": "catalog description",
        "version": 4,
        "updated_at": "2026-09-25",
        "skills": skills if skills is not None else [skill()],
    }
    base.update(overrides)
    return base


def code_skill_ok(value: object) -> bool:
    return not validate.structural_skill_errors(value)


def code_index_ok(value: object) -> bool:
    if validate.structural_index_errors(value):
        return False
    if isinstance(value, dict) and isinstance(value.get("skills"), list):
        return all(not validate.structural_skill_errors(item) for item in value["skills"])
    return True


def code_review_ok(value: object) -> bool:
    return not validate.structural_review_errors(value)


def run_matrix(schema: dict) -> None:
    skill_v = validator_for(schema, schema["$defs"]["skill"])
    index_v = Draft202012Validator(schema)
    review_v = validator_for(schema, schema["$defs"]["reviewRecord"])
    full = skill(
        source="opensource",
        origin="example/demo-skill",
        tags=["pdf", "document"],
        aliases=["PDF 处理", "demo"],
        homepage="https://github.com/example/demo-skill",
    )
    review = {
        "ts": "2026-09-25T00:00:01Z",
        "id": "demo-skill",
        "decision": "approved",
        "by": "maintainer",
        "reason": "回填一条足够长的裁决说明",
        "catalog_version": 4,
    }
    cases = [
        ("v3 skill without optional fields", skill_v, skill(), code_skill_ok, True),
        ("v4 skill with tags/aliases/homepage", skill_v, full, code_skill_ok, True),
        ("tags as {zh} object", skill_v, skill(tags=[{"zh": "测试"}]), code_skill_ok, False),
        ("tags as a string", skill_v, skill(tags="pdf"), code_skill_ok, False),
        ("uppercase tag", skill_v, skill(tags=["PDF"]), code_skill_ok, False),
        ("duplicate tags", skill_v, skill(tags=["pdf", "pdf"]), code_skill_ok, False),
        ("nine tags", skill_v, skill(tags=[f"t{i}" for i in range(9)]), code_skill_ok, False),
        ("unknown skill field", skill_v, skill(score=10), code_skill_ok, False),
        ("http homepage", skill_v, skill(homepage="http://github.com/example/demo"), code_skill_ok, False),
        ("homepage with userinfo", skill_v, skill(homepage="https://user:pass@github.com/example/demo"), code_skill_ok, False),
        ("ip homepage", skill_v, skill(homepage="https://127.0.0.1/secret"), code_skill_ok, False),
        ("missing install", skill_v, {k: v for k, v in skill().items() if k != "install"}, code_skill_ok, False),
        ("uppercase id", skill_v, skill(id="My-Skill"), code_skill_ok, False),
        ("short description", skill_v, skill(description="too"), code_skill_ok, False),
        ("source local", skill_v, skill(source="local"), code_skill_ok, False),
        ("empty tag item", skill_v, skill(tags=[""]), code_skill_ok, False),
        ("alias with control char", skill_v, skill(aliases=["bad\nname"]), code_skill_ok, False),
        ("v3 index", index_v, index(), code_index_ok, True),
        ("version string", index_v, index(version="4"), code_index_ok, False),
        ("version boolean", index_v, index(version=True), code_index_ok, False),
        ("bad updated_at", index_v, index(updated_at="2026/09/25"), code_index_ok, False),
        ("empty skills", index_v, index(skills=[]), code_index_ok, False),
        ("unknown top-level field", index_v, index(schema_version=4), code_index_ok, False),
        ("nested bad tag fails index", index_v, index([skill(tags=["PDF"])]), code_index_ok, False),
        ("review record", review_v, review, code_review_ok, True),
        ("review decision yes", review_v, {**review, "decision": "yes"}, code_review_ok, False),
        ("review ts with offset", review_v, {**review, "ts": "2026-09-25T00:00:01+00:00"}, code_review_ok, False),
        ("review unknown field", review_v, {**review, "note": "x"}, code_review_ok, False),
    ]
    failed = 0
    for name, validator, instance, code_ok, expect in cases:
        schema_ok = validator.is_valid(instance)
        code_result = code_ok(instance)
        if schema_ok != expect or code_result != expect:
            failed += 1
            print(f"[FAIL] {name}: schema={schema_ok} code={code_result} expected={expect}")
            if not schema_ok:
                print("       schema errors:", sorted(validator.iter_errors(instance), key=lambda e: e.path)[:3])
        else:
            print(f"[PASS] {name}")
    if failed:
        die(f"{failed} schema/code agreement case(s) failed")
    print(f"[PASS] schema agreement {len(cases)}/{len(cases)}")


def validate_repo(schema: dict) -> None:
    index_v = Draft202012Validator(schema)
    skill_v = validator_for(schema, schema["$defs"]["skill"])
    review_v = validator_for(schema, schema["$defs"]["reviewRecord"])
    index = json.loads((ROOT / "index.json").read_text(encoding="utf-8"))
    errors = sorted(index_v.iter_errors(index), key=lambda e: list(e.path))
    if errors:
        die("index.json failed schema: " + "; ".join(f"{'/'.join(map(str, e.path))}: {e.message}" for e in errors[:8]))
    print(f"[PASS] index.json satisfies catalog schema ({len(index['skills'])} skills)")
    contrib_dir = ROOT / "contributions"
    for path in sorted(contrib_dir.glob("*.json")):
        if path.name.startswith("_"):
            continue
        body = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(body, list):
            die(f"{path.name} is not an array")
        for i, item in enumerate(body):
            item_errors = list(skill_v.iter_errors(item))
            if item_errors:
                die(f"{path.name}[{i}] failed schema: {item_errors[0].message}")
    log_path = ROOT / "reviews" / "log.jsonl"
    if not log_path.is_file():
        die("reviews/log.jsonl missing")
    for i, line in enumerate(log_path.read_text(encoding="utf-8").splitlines(), 1):
        rec = json.loads(line)
        rec_errors = list(review_v.iter_errors(rec))
        if rec_errors:
            die(f"reviews/log.jsonl:{i} failed schema: {rec_errors[0].message}")
    print("[PASS] contributions and review log satisfy schema")


def main() -> int:
    schema = load_schema()
    check_drift(schema)
    run_matrix(schema)
    validate_repo(schema)
    print("[PASS] schema has teeth and matches validate.py on the structural contract")
    return 0


if __name__ == "__main__":
    sys.exit(main())
