from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.creative_state import CreativeStateEngine, RuleBasedChineseParser, SkillConfig


def show(title: str, result) -> None:
    print(f"\n=== {title} ===")
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))


def main() -> None:
    skill = SkillConfig.load(ROOT / "config" / "commercial_product_photography.json")
    engine = CreativeStateEngine(skill)
    parser = RuleBasedChineseParser()

    show("开启 Skill", engine.enable_skill())
    messages = [
        "用 image_A 的产品做电商主图，image_B 只参考光影。白底，不要添加文字，瓶身、原有标签和 Logo 不变。",
        "只把光线改暖一点，其他不变。",
        "背景改成浅灰，其他不变。",
    ]
    for index, message in enumerate(messages, start=1):
        show(f"用户轮次 {index}: {message}", engine.apply(parser.parse(message)))

    show("关闭 Skill", engine.disable_skill())
    conflict = "保持瓶身颜色不变，同时把瓶身改成红色。"
    show(f"冲突轮次: {conflict}", engine.apply(parser.parse(conflict)))


if __name__ == "__main__":
    main()
