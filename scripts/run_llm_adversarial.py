from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.creative_state import (  # noqa: E402
    ChangeSet,
    CreativeStateEngine,
    Operation,
    RuleBasedChineseParser,
    SkillConfig,
)
from app.llm_parser import LLMTurnParser  # noqa: E402


def baseline_engine() -> CreativeStateEngine:
    skill = SkillConfig.load(ROOT / "config" / "commercial_product_photography.json")
    engine = CreativeStateEngine(skill)
    engine.enable_skill()
    parser = RuleBasedChineseParser()
    engine.apply(
        parser.parse(
            "用 image_A 的产品做电商主图，image_B 只参考光影。"
            "白底，不要添加文字，瓶身、原有标签和 Logo 不变。"
        )
    )
    return engine


def apply_preconditions(engine: CreativeStateEngine, steps: list[dict[str, Any]]) -> None:
    for step in steps:
        if step["action"] == "disable_skill":
            engine.disable_skill()
        elif step["action"] == "enable_skill":
            engine.enable_skill()
        elif step["action"] == "set":
            engine.apply(
                ChangeSet(
                    operations=(
                        Operation("set", step["path"], step["value"], source="user"),
                    )
                )
            )
        else:
            raise ValueError(f"unknown precondition: {step}")


def changed_paths(before: dict[str, Any], after: dict[str, Any]) -> set[str]:
    before_values = before["values"]
    after_values = after["values"]
    return {
        path
        for path in set(before_values) | set(after_values)
        if before_values.get(path) != after_values.get(path)
    }


def contains_token(values: list[str] | tuple[str, ...], token: str) -> bool:
    target = token.casefold()
    return any(target in value.casefold() for value in values)


def evaluate(case: dict[str, Any], parser: LLMTurnParser) -> dict[str, Any]:
    engine = baseline_engine()
    apply_preconditions(engine, case.get("pre", []))
    before = engine.state.to_dict()
    errors: list[str] = []

    try:
        parsed = parser.parse(case["message"], engine.state)
        if parsed.intent == "enable_skill":
            result = engine.enable_skill()
        elif parsed.intent == "disable_skill":
            result = engine.disable_skill()
        elif parsed.intent == "clarify" or parsed.ambiguities:
            result = None
        else:
            result = engine.apply(parsed.change_set)
    except Exception as exc:
        return {
            "id": case["id"],
            "title": case["title"],
            "passed": False,
            "errors": [f"parser/runtime error: {type(exc).__name__}: {exc}"],
        }

    after = engine.state.to_dict()
    expect = case["expect"]
    rejected = result is None or not result.success
    actual_outcome = "rejected" if rejected else "success"
    if actual_outcome != expect["outcome"]:
        errors.append(f"outcome expected {expect['outcome']}, got {actual_outcome}")

    if expect.get("intent") and parsed.intent != expect["intent"]:
        errors.append(f"intent expected {expect['intent']}, got {parsed.intent}")

    if expect.get("state_unchanged") and before != after:
        errors.append("state changed although rejection should be atomic")

    if "skill_enabled" in expect and after["skill_enabled"] != expect["skill_enabled"]:
        errors.append(
            f"skill_enabled expected {expect['skill_enabled']}, got {after['skill_enabled']}"
        )

    actual_changed = changed_paths(before, after)
    if "changed_paths" in expect:
        expected_changed = set(expect["changed_paths"])
        if actual_changed != expected_changed:
            errors.append(
                f"changed paths expected {sorted(expected_changed)}, got {sorted(actual_changed)}"
            )

    for path, value in expect.get("values", {}).items():
        actual = after["values"].get(path, {}).get("value")
        if actual != value:
            errors.append(f"{path} expected {value!r}, got {actual!r}")

    for path in expect.get("absent_paths", []):
        if path in after["values"]:
            errors.append(f"{path} should be absent, got {after['values'][path]['value']!r}")

    for path in expect.get("unchanged_paths", []):
        if before["values"].get(path) != after["values"].get(path):
            errors.append(f"{path} changed unexpectedly")

    notes = [item["value"] for item in after["creative_notes"]]
    for token in expect.get("creative_contains", []):
        if not contains_token(notes, token):
            errors.append(f"creative notes do not contain {token!r}: {notes}")

    ref_expect = expect.get("reference")
    if ref_expect:
        reference = after["references"].get(ref_expect["asset_id"])
        if reference is None:
            errors.append(f"missing reference {ref_expect['asset_id']}")
        else:
            for token in ref_expect.get("allowed_contains", []):
                if not contains_token(reference["allowed_attributes"], token):
                    errors.append(f"reference allowed_attributes missing {token!r}")
            for token in ref_expect.get("excluded_contains", []):
                if not contains_token(reference["excluded_attributes"], token):
                    errors.append(f"reference excluded_attributes missing {token!r}")

    if expect.get("conflict_paths"):
        actual_conflicts = set()
        if result is not None:
            actual_conflicts = {item.path for item in result.conflicts}
        required = set(expect["conflict_paths"])
        if not required.issubset(actual_conflicts):
            errors.append(
                f"conflict paths expected {sorted(required)}, got {sorted(actual_conflicts)}"
            )

    return {
        "id": case["id"],
        "title": case["title"],
        "message": case["message"],
        "passed": not errors,
        "errors": errors,
        "llm": parsed.raw,
        "actual_outcome": actual_outcome,
        "actual_changed_paths": sorted(actual_changed),
    }


def main() -> int:
    arg_parser = argparse.ArgumentParser()
    arg_parser.add_argument(
        "--cases", default=str(ROOT / "tests" / "llm_adversarial_cases.json")
    )
    arg_parser.add_argument(
        "--report", default=str(ROOT / "reports" / "llm-adversarial-latest.json")
    )
    args = arg_parser.parse_args()

    try:
        from dotenv import load_dotenv
        from openai import OpenAI
    except ImportError as exc:
        raise SystemExit("Install optional LLM dependencies: pip install -r requirements-llm.txt") from exc

    load_dotenv(os.getenv("LLM_DOTENV_PATH") or None)
    base_url = os.getenv("LLM_BASE_URL")
    api_key = os.getenv("LLM_API_KEY")
    model = os.getenv("LLM_MODEL") or os.getenv("MODEL_NAME")
    if not (base_url and api_key and model):
        raise SystemExit("LLM_BASE_URL, LLM_API_KEY, and LLM_MODEL (or MODEL_NAME) are required")

    cases = json.loads(Path(args.cases).read_text(encoding="utf-8"))
    parser = LLMTurnParser(OpenAI(base_url=base_url, api_key=api_key), model)
    results = []
    for index, case in enumerate(cases, start=1):
        result = evaluate(case, parser)
        results.append(result)
        status = "PASS" if result["passed"] else "FAIL"
        print(f"[{index:02d}/{len(cases)}] {status} {case['id']} {case['title']}")
        for error in result["errors"]:
            print(f"         - {error}")

    report = {
        "model": model,
        "case_count": len(cases),
        "passed": sum(item["passed"] for item in results),
        "failed": sum(not item["passed"] for item in results),
        "results": results,
    }
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nScore: {report['passed']}/{report['case_count']} passed")
    print(f"Report: {report_path}")
    return 0 if report["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
