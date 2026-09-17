from __future__ import annotations

import unittest
from pathlib import Path

from app.creative_state import CreativeStateEngine, RuleBasedChineseParser, SkillConfig


ROOT = Path(__file__).resolve().parents[1]


class CreativeStateConversationTests(unittest.TestCase):
    def setUp(self) -> None:
        skill = SkillConfig.load(ROOT / "config" / "commercial_product_photography.json")
        self.engine = CreativeStateEngine(skill)
        self.parser = RuleBasedChineseParser()
        self.engine.enable_skill()

    def apply(self, text: str):
        return self.engine.apply(self.parser.parse(text))

    def start_required_conversation(self) -> None:
        result = self.apply(
            "用 image_A 的产品做电商主图，image_B 只参考光影。"
            "白底，不要添加文字，瓶身、原有标签和 Logo 不变。"
        )
        self.assertTrue(result.success)

    def test_partial_edits_preserve_existing_constraints_and_reference_roles(self) -> None:
        self.start_required_conversation()
        self.apply("只把光线改暖一点，其他不变。")
        result = self.apply("背景改成浅灰，其他不变。")

        state = result.state
        self.assertEqual(state.values["background.color"].value, "light gray")
        self.assertEqual(state.values["lighting.temperature"].value, "warm")
        self.assertEqual(state.values["text.addition"].value, "forbidden")
        self.assertEqual(state.values["bottle.appearance"].value, "preserve original")
        self.assertEqual(state.references["image_A"].role, "subject identity and product appearance")
        self.assertEqual(state.references["image_B"].allowed_attributes, ("lighting",))
        self.assertIn("product", state.references["image_B"].excluded_attributes)

    def test_user_value_overrides_skill_default_and_tracks_derivation(self) -> None:
        result = self.apply("只把光线改暖一点，其他不变。")

        temperature = result.state.values["lighting.temperature"]
        self.assertEqual(temperature.source, "user")
        self.assertEqual(temperature.value, "warm")
        self.assertEqual(result.state.values["lighting.softness"].source, "skill")

    def test_disabling_skill_removes_only_skill_values(self) -> None:
        self.start_required_conversation()
        self.apply("只把光线改暖一点，其他不变。")
        result = self.engine.disable_skill()

        self.assertNotIn("lighting.direction", result.state.values)
        self.assertNotIn("lighting.softness", result.state.values)
        self.assertNotIn("composition.placement", result.state.values)
        self.assertEqual(result.state.values["lighting.temperature"].value, "warm")
        self.assertEqual(result.state.values["background.color"].value, "white")
        self.assertEqual(result.state.values["text.addition"].value, "forbidden")

    def test_conflicting_turn_does_not_mutate_last_valid_state(self) -> None:
        self.start_required_conversation()
        before = self.engine.state.to_dict()
        result = self.apply("保持瓶身颜色不变，同时把瓶身改成红色。")

        self.assertFalse(result.success)
        self.assertEqual(result.conflicts[0].path, "bottle.color")
        self.assertEqual(self.engine.state.to_dict(), before)
        self.assertEqual(result.state.to_dict(), before)
        self.assertIsNotNone(result.prompt)

    def test_specific_color_preservation_does_not_expand_to_all_appearance(self) -> None:
        change_set = self.parser.parse("保持瓶身颜色不变。")
        paths = [operation.path for operation in change_set.operations]

        self.assertIn("bottle.color", paths)
        self.assertNotIn("bottle.appearance", paths)

    def test_unknown_subjective_language_is_preserved_as_creative_note(self) -> None:
        # Boundary case: subjective language should not be discarded or forced
        # into a misleading rigid field.
        result = self.apply("整体更高级一点，但不要显得冰冷。")

        self.assertTrue(result.success)
        self.assertEqual(
            result.state.creative_notes[-1].value,
            "整体更高级一点，但不要显得冰冷。",
        )
        self.assertIn("Open creative direction", result.prompt or "")

    def test_subjective_note_survives_next_to_a_structured_edit(self) -> None:
        result = self.apply("背景改成浅灰，整体更高级一点。")

        self.assertEqual(result.state.values["background.color"].value, "light gray")
        self.assertEqual(result.state.creative_notes[-1].value, "整体更高级一点")

    def test_reenabling_skill_does_not_overwrite_user_value(self) -> None:
        # Boundary case: toggling a skill must be idempotent with respect to
        # fields the user has explicitly taken ownership of.
        self.start_required_conversation()
        self.apply("只把光线改暖一点，其他不变。")
        self.engine.disable_skill()
        result = self.engine.enable_skill()

        self.assertEqual(result.state.values["lighting.temperature"].value, "warm")
        self.assertEqual(result.state.values["lighting.temperature"].source, "user")
        self.assertEqual(result.state.values["composition.placement"].source, "skill")


if __name__ == "__main__":
    unittest.main()
