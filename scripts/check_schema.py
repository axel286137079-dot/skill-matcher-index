#!/usr/bin/env python3
"""JSON Schema 严格校验（CI 用；本地需 jsonschema，零依赖环境自动跳过）。

用法:
    python3 scripts/check_schema.py            # 未装 jsonschema 时提示并跳过（exit 0）
    python3 scripts/check_schema.py --require  # 未装 jsonschema 视为失败（CI 用）

做两件事:
  1. 用 schema/index.schema.json 校验 index.json（解析 $ref → skill.schema.json，含 v4 if/then 契约）
  2. 断言 scripts/validate.py 的镜像常量与 schema 严格一致（防止「零依赖实现」与「JSON Schema 实现」漂移）

退出码: 0 = 通过, 1 = 校验失败/漂移, 2 = 用法错误, 3 = 缺少依赖（仅非 --require 时跳过）
"""
import importlib.metadata
import importlib.util
import json
import sys
import warnings
from pathlib import Path
from urllib.parse import urljoin

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_DIR = ROOT / "schema"
INDEX_PATH = ROOT / "index.json"


def load_validator_module():
    """把 scripts/validate.py 作为模块加载（用于镜像常量断言）。"""
    spec = importlib.util.spec_from_file_location("_validate", ROOT / "scripts" / "validate.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def check_mirror_consistency(skill_schema: dict, index_schema: dict) -> list[str]:
    """断言两份契约实现没有漂移。"""
    problems: list[str] = []
    v = load_validator_module()

    schema_tags = tuple(skill_schema["properties"]["tags"]["items"]["enum"])
    if tuple(v.TAGS) != schema_tags:
        only_schema = sorted(set(schema_tags) - set(v.TAGS))
        only_validator = sorted(set(v.TAGS) - set(schema_tags))
        problems.append(
            "tags 词表漂移：仅 schema 有 "
            f"{only_schema or '∅'}；仅 validate.py 有 {only_validator or '∅'}"
        )
    if v.MAX_TAGS != skill_schema["properties"]["tags"]["maxItems"]:
        problems.append(f"MAX_TAGS 漂移：validate.py={v.MAX_TAGS}, schema={skill_schema['properties']['tags']['maxItems']}")
    if v.MAX_ALIASES != skill_schema["properties"]["aliases"]["maxItems"]:
        problems.append(f"MAX_ALIASES 漂移：validate.py={v.MAX_ALIASES}, schema={skill_schema['properties']['aliases']['maxItems']}")
    if v.ID_RE.pattern != skill_schema["properties"]["id"]["pattern"]:
        problems.append("id 正则漂移")
    if v.HOMEPAGE_RE.pattern != skill_schema["properties"]["homepage"]["pattern"]:
        problems.append("homepage 正则漂移")
    if tuple(skill_schema["required"]) != tuple(v.REQUIRED_FIELDS):
        problems.append(f"必填字段漂移：validate.py={v.REQUIRED_FIELDS}, schema={tuple(skill_schema['required'])}")
    if tuple(skill_schema["properties"]["source"]["enum"]) != tuple(v.KNOWN_SOURCES):
        problems.append("source 枚举漂移")

    then_required = index_schema.get("then", {}).get("properties", {}).get("skills", {}).get("items", {}).get("required")
    if tuple(then_required or ()) != tuple(v.V4_REQUIRED_FIELDS):
        problems.append(f"v4 必填字段漂移：validate.py={v.V4_REQUIRED_FIELDS}, schema={then_required}")
    then_min_version = index_schema.get("if", {}).get("properties", {}).get("version", {}).get("minimum")
    if then_min_version != 4:
        problems.append(f"v4 触发条件漂移：schema 用 version >= {then_min_version}")
    return problems


def _fixture_index(version=4, skills=None):
    entry = {
        "id": "demo-skill", "name": "demo-skill",
        "description": "演示技能：自证用样本。",
        "install": "git clone https://github.com/example/demo",
        "source": "opensource", "origin": "example/demo",
        "homepage": "https://github.com/example/demo",
        "tags": ["testing"], "aliases": ["示例技能"], "added_at": "2026-09-26",
    }
    return {
        "name": "t", "description": "t", "version": version, "updated_at": "2026-09-26",
        "skills": skills if skills is not None else [entry],
    }


def _without(entry, *fields):
    return {k: v for k, v in entry.items() if k not in fields}


def schema_selfcheck(validator) -> tuple[int, list[str]]:
    """自证：schema 必须真的会拒绝坏数据（否则「CI 通过」不能等价于「数据合格」）。"""
    base = _fixture_index()["skills"][0]
    cases = [
        ("v4 合法条目", _fixture_index(version=4), True),
        ("v3 旧数据（无 v4 字段）", _fixture_index(version=3, skills=[_without(base, "tags", "aliases", "added_at")]), True),
        ("v4 缺 tags", _fixture_index(version=4, skills=[_without(base, "tags")]), False),
        ("v4 缺 aliases", _fixture_index(version=4, skills=[_without(base, "aliases")]), False),
        ("v4 缺 added_at", _fixture_index(version=4, skills=[_without(base, "added_at")]), False),
        ("词表外 tag", _fixture_index(skills=[base | {"tags": ["blockchain"]}]), False),
        ("大写 tag", _fixture_index(skills=[base | {"tags": ["Testing"]}]), False),
        ("标签超 6 个", _fixture_index(skills=[base | {"tags": list("abcdefg")}]), False),
        ("别名超 8 个", _fixture_index(skills=[base | {"aliases": [f"a{i}" for i in range(9)]}]), False),
        ("http 主页", _fixture_index(skills=[base | {"homepage": "http://example.com"}]), False),
        ("非法日期", _fixture_index(skills=[base | {"added_at": "2026/09/26"}]), False),
        ("非法 id", _fixture_index(skills=[base | {"id": "Bad_ID"}]), False),
        ("缺必填字段", _fixture_index(skills=[_without(base, "install")]), False),
        ("缺 skills", {"name": "t", "description": "t", "version": 4, "updated_at": "2026-09-26"}, False),
    ]
    problems = []
    for name, instance, expect_valid in cases:
        valid = validator.is_valid(instance)
        if valid != expect_valid:
            problems.append(f"自证样本「{name}」期望 {'通过' if expect_valid else '拒绝'}，实际 {'通过' if valid else '拒绝'}")
    return len(cases), problems


def main() -> int:
    argv = sys.argv[1:]
    if [a for a in argv if not a.startswith("--")] or (set(argv) - {"--require"}):
        print(__doc__)
        return 2
    require = "--require" in argv

    try:
        import jsonschema
        from referencing import Registry, Resource
    except ImportError as e:
        msg = f"jsonschema 不可用（{e}）。安装：python3 -m pip install 'jsonschema==4.23.0'"
        if require:
            print(f"[FAIL] {msg}")
            return 3
        print(f"[SKIP] {msg}（本地零依赖可用；CI 用 --require）")
        return 0

    warnings.filterwarnings("ignore", category=DeprecationWarning)
    skill_schema = json.loads((SCHEMA_DIR / "skill.schema.json").read_text(encoding="utf-8"))
    index_schema = json.loads((SCHEMA_DIR / "index.schema.json").read_text(encoding="utf-8"))
    data = json.loads(INDEX_PATH.read_text(encoding="utf-8"))

    # $ref: skill.schema.json 相对 index.schema.json 的 $id 解析 → 注册绝对 URI 与相对键
    skill_resource = Resource.from_contents(skill_schema)
    # $ref: "skill.schema.json" 相对 index.schema.json 的 $id 解析
    registry = Registry().with_resources([
        (skill_schema["$id"], skill_resource),
        (urljoin(index_schema["$id"], "skill.schema.json"), skill_resource),
        ("skill.schema.json", skill_resource),
    ])

    validator = jsonschema.Draft7Validator(index_schema, registry=registry)
    schema_errors = sorted(validator.iter_errors(data), key=lambda e: [str(p) for p in e.absolute_path])

    try:
        version = importlib.metadata.version("jsonschema")
    except importlib.metadata.PackageNotFoundError:
        version = "unknown"
    print(f"== jsonschema {version} · {INDEX_PATH.name} vs schema/index.schema.json")
    for e in schema_errors:
        loc = "/".join(str(p) for p in e.absolute_path) or "(root)"
        print(f"[FAIL] {loc}: {e.message}")
    if not schema_errors:
        print(f"[PASS] {INDEX_PATH.name}: 符合 JSON Schema（{len(data.get('skills', []))} entries, version {data.get('version')}）")

    # 贡献文件同样按条目契约校验（有 jsonschema 时顺手做掉，零依赖环境下由 validate.py 负责）
    contrib_errors = []
    contrib_dir = ROOT / "contributions"
    skill_validator = jsonschema.Draft7Validator(skill_schema)
    contrib_files = sorted(p for p in contrib_dir.glob("*.json") if not p.name.startswith("_")) if contrib_dir.is_dir() else []
    for path in contrib_files:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            contrib_errors.append((path.name, "(root)", f"not valid JSON ({e})"))
            continue
        for i, item in enumerate(payload if isinstance(payload, list) else [payload]):
            for e in skill_validator.iter_errors(item):
                contrib_errors.append((path.name, f"[{i}]", e.message))
    print(f"== contributions: {len(contrib_files)} file(s) vs schema/skill.schema.json")
    for name, loc, msg in contrib_errors:
        print(f"[FAIL] {name}{loc}: {msg}")
    if contrib_files and not contrib_errors:
        print(f"[PASS] contributions: {len(contrib_files)} file(s) 符合条目契约")
    elif not contrib_files:
        print("[INFO] 暂无贡献文件")

    case_count, selfcheck_problems = schema_selfcheck(validator)
    for p in selfcheck_problems:
        print(f"[FAIL] schema 无约束力: {p}")
    if not selfcheck_problems:
        print(f"[PASS] schema 具备约束力：{case_count} 个正/负样本全部按预期判定")

    mirror_problems = check_mirror_consistency(skill_schema, index_schema)
    for p in mirror_problems:
        print(f"[FAIL] 契约漂移: {p}")
    if not mirror_problems:
        print("[PASS] 契约一致：validate.py 与 JSON Schema 的词表/必填/v4 规则完全等价")

    total = len(schema_errors) + len(contrib_errors) + len(selfcheck_problems) + len(mirror_problems)
    if total:
        print(f"\n❌ schema 校验失败（schema 错误 {len(schema_errors)} / 贡献文件 {len(contrib_errors)}"
              f" / 无约束力 {len(selfcheck_problems)} / 漂移 {len(mirror_problems)}）")
        return 1
    print("\n✅ schema 契约校验通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
