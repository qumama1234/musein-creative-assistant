from __future__ import annotations

import copy
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal


Source = Literal["user", "skill"]
Action = Literal["set", "remove"]


@dataclass(frozen=True)
class ValueWithSource:
    value: str
    source: Source
    turn: int
    derived_from: str | None = None


@dataclass(frozen=True)
class ReferenceRole:
    asset_id: str
    role: str
    source: Source
    turn: int
    allowed_attributes: tuple[str, ...] = ()
    excluded_attributes: tuple[str, ...] = ()


@dataclass(frozen=True)
class Operation:
    action: Action
    path: str
    value: str | None = None
    source: Source = "user"
    derived_from: str | None = None


@dataclass(frozen=True)
class ReferenceOperation:
    reference: ReferenceRole


@dataclass(frozen=True)
class ChangeSet:
    operations: tuple[Operation, ...] = ()
    references: tuple[ReferenceOperation, ...] = ()
    creative_notes: tuple[str, ...] = ()
    preserve_unspecified: bool = True


@dataclass
class CreativeState:
    revision: int = 0
    skill_enabled: bool = False
    values: dict[str, ValueWithSource] = field(default_factory=dict)
    references: dict[str, ReferenceRole] = field(default_factory=dict)
    creative_notes: list[ValueWithSource] = field(default_factory=list)

    def clone(self) -> "CreativeState":
        return copy.deepcopy(self)

    def to_dict(self) -> dict[str, Any]:
        return {
            "revision": self.revision,
            "skill_enabled": self.skill_enabled,
            "values": {key: asdict(value) for key, value in sorted(self.values.items())},
            "references": {
                key: asdict(value) for key, value in sorted(self.references.items())
            },
            "creative_notes": [asdict(note) for note in self.creative_notes],
        }


@dataclass(frozen=True)
class Conflict:
    path: str
    values: tuple[str, ...]
    message: str


@dataclass(frozen=True)
class ApplyResult:
    success: bool
    state: CreativeState
    changes: tuple[str, ...] = ()
    conflicts: tuple[Conflict, ...] = ()
    questions: tuple[str, ...] = ()
    prompt: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "state": self.state.to_dict(),
            "changes": list(self.changes),
            "conflicts": [asdict(conflict) for conflict in self.conflicts],
            "questions": list(self.questions),
            "prompt": self.prompt,
        }


@dataclass(frozen=True)
class SkillConfig:
    skill_id: str
    version: str
    defaults: dict[str, str]

    @classmethod
    def load(cls, path: str | Path) -> "SkillConfig":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(
            skill_id=raw["skill_id"],
            version=raw["version"],
            defaults=dict(raw["defaults"]),
        )


class PromptRenderer:
    """Deterministically renders hard constraints; creative notes stay open-ended."""

    LABELS = {
        "purpose": "用途",
        "subject": "主体",
        "background.color": "背景颜色",
        "lighting.direction": "光线方向",
        "lighting.softness": "光线质感",
        "lighting.temperature": "光线色温",
        "composition.placement": "构图",
        "text.addition": "新增文字",
        "bottle.appearance": "瓶身外观",
        "bottle.color": "瓶身颜色",
        "label.content": "原有标签",
        "logo.appearance": "Logo",
    }

    @classmethod
    def render(cls, state: CreativeState) -> str:
        lines = ["Create an image that follows every hard constraint below:"]
        for path, item in sorted(state.values.items()):
            label = cls.LABELS.get(path, path)
            lines.append(f"- {label}: {item.value}.")

        if state.references:
            lines.append("Reference roles:")
            for ref in state.references.values():
                line = f"- {ref.asset_id}: {ref.role}"
                if ref.allowed_attributes:
                    line += f"; use only for {', '.join(ref.allowed_attributes)}"
                if ref.excluded_attributes:
                    line += f"; do not copy {', '.join(ref.excluded_attributes)}"
                lines.append(line + ".")

        if state.creative_notes:
            lines.append("Open creative direction (interpret within the hard constraints):")
            lines.extend(f"- {note.value}" for note in state.creative_notes)
        return "\n".join(lines)


class CreativeStateEngine:
    """Transactional state engine: invalid changes never mutate the active state."""

    def __init__(self, skill: SkillConfig):
        self.skill = skill
        self.state = CreativeState()

    def enable_skill(self) -> ApplyResult:
        candidate = self.state.clone()
        turn = candidate.revision + 1
        changes: list[str] = []
        candidate.skill_enabled = True
        for path, value in self.skill.defaults.items():
            if path not in candidate.values:
                candidate.values[path] = ValueWithSource(
                    value=value,
                    source="skill",
                    turn=turn,
                    derived_from=f"{self.skill.skill_id}@{self.skill.version}",
                )
                changes.append(f"added {path}={value} (skill)")
        candidate.revision = turn
        self.state = candidate
        return self._success(changes)

    def disable_skill(self) -> ApplyResult:
        candidate = self.state.clone()
        turn = candidate.revision + 1
        removed = [
            path for path, item in candidate.values.items() if item.source == "skill"
        ]
        for path in removed:
            del candidate.values[path]
        candidate.skill_enabled = False
        candidate.revision = turn
        self.state = candidate
        return self._success([f"removed {path} (skill)" for path in removed])

    def apply(self, change_set: ChangeSet) -> ApplyResult:
        conflicts = self._find_conflicts(change_set)
        if conflicts:
            questions = tuple(
                f"“{conflict.path}”存在冲突，请选择：{' / '.join(conflict.values)}。"
                for conflict in conflicts
            )
            return ApplyResult(
                success=False,
                state=self.state.clone(),
                conflicts=conflicts,
                questions=questions,
                prompt=PromptRenderer.render(self.state),
            )

        candidate = self.state.clone()
        turn = candidate.revision + 1
        changes: list[str] = []
        for op in change_set.operations:
            old = candidate.values.get(op.path)
            if op.action == "remove":
                if old is not None:
                    del candidate.values[op.path]
                    changes.append(f"removed {op.path}={old.value}")
                continue
            if op.value is None:
                raise ValueError(f"set operation for {op.path!r} requires a value")
            derived_from = op.derived_from
            if derived_from is None and old is not None and old.source == "skill":
                derived_from = f"skill:{old.value}"
            candidate.values[op.path] = ValueWithSource(
                value=op.value,
                source=op.source,
                turn=turn,
                derived_from=derived_from,
            )
            if old is None:
                changes.append(f"added {op.path}={op.value} ({op.source})")
            elif old.value != op.value or old.source != op.source:
                changes.append(
                    f"changed {op.path}: {old.value} ({old.source}) -> "
                    f"{op.value} ({op.source})"
                )

        for ref_op in change_set.references:
            ref = ref_op.reference
            stamped = ReferenceRole(
                asset_id=ref.asset_id,
                role=ref.role,
                source=ref.source,
                turn=turn,
                allowed_attributes=ref.allowed_attributes,
                excluded_attributes=ref.excluded_attributes,
            )
            candidate.references[ref.asset_id] = stamped
            changes.append(f"set reference {ref.asset_id} role={ref.role}")

        for note in change_set.creative_notes:
            if not any(existing.value == note for existing in candidate.creative_notes):
                candidate.creative_notes.append(
                    ValueWithSource(value=note, source="user", turn=turn)
                )
                changes.append(f"added creative note: {note}")

        candidate.revision = turn
        self.state = candidate
        return self._success(changes)

    def _success(self, changes: list[str]) -> ApplyResult:
        return ApplyResult(
            success=True,
            state=self.state.clone(),
            changes=tuple(changes),
            prompt=PromptRenderer.render(self.state),
        )

    @staticmethod
    def _find_conflicts(change_set: ChangeSet) -> tuple[Conflict, ...]:
        proposed: dict[str, set[str]] = {}
        for op in change_set.operations:
            if op.action == "set" and op.value is not None:
                proposed.setdefault(op.path, set()).add(op.value)
        conflicts = []
        for path, values in proposed.items():
            if len(values) > 1:
                ordered = tuple(sorted(values))
                conflicts.append(
                    Conflict(
                        path=path,
                        values=ordered,
                        message=f"同一轮对 {path} 提出了互斥要求",
                    )
                )
        return tuple(conflicts)


class RuleBasedChineseParser:
    """A deliberately limited parser for the documented Chinese command shapes.

    It recognizes common attribute edits and preservation constraints. Unknown text
    is kept as an open creative note instead of being silently discarded.
    """

    COLOR_MAP = {
        "白": "white",
        "纯白": "pure white",
        "浅灰": "light gray",
        "灰": "gray",
        "黑": "black",
        "红": "red",
        "蓝": "blue",
        "绿": "green",
    }

    def parse(self, text: str) -> ChangeSet:
        operations: list[Operation] = []
        references: list[ReferenceOperation] = []
        recognized_spans: list[str] = []

        if "电商主图" in text:
            operations.append(Operation("set", "purpose", "e-commerce hero image"))
            recognized_spans.append("电商主图")

        subject_match = re.search(r"用\s*(image_[A-Za-z0-9_-]+)\s*的产品", text, re.I)
        if subject_match:
            asset_id = subject_match.group(1)
            operations.append(Operation("set", "subject", f"product from {asset_id}"))
            references.append(
                ReferenceOperation(
                    ReferenceRole(
                        asset_id=asset_id,
                        role="subject identity and product appearance",
                        source="user",
                        turn=0,
                        allowed_attributes=("product appearance",),
                    )
                )
            )
            recognized_spans.append(subject_match.group(0))

        lighting_ref = re.search(
            r"(image_[A-Za-z0-9_-]+)\s*(?:只|仅)\s*参考光影", text, re.I
        )
        if lighting_ref:
            asset_id = lighting_ref.group(1)
            references.append(
                ReferenceOperation(
                    ReferenceRole(
                        asset_id=asset_id,
                        role="lighting reference only",
                        source="user",
                        turn=0,
                        allowed_attributes=("lighting",),
                        excluded_attributes=("product", "background", "text"),
                    )
                )
            )
            recognized_spans.append(lighting_ref.group(0))

        background = re.search(r"(?:背景(?:改成|换成|为)?|)(纯白|浅灰|白|灰|黑|红|蓝|绿)(?:色)?(?:背景|底)", text)
        if not background:
            background = re.search(r"背景(?:改成|换成|为)\s*(纯白|浅灰|白|灰|黑|红|蓝|绿)(?:色)?", text)
        if background:
            operations.append(
                Operation("set", "background.color", self.COLOR_MAP[background.group(1)])
            )
            recognized_spans.append(background.group(0))

        if re.search(r"(?:不要|禁止)(?:添加|新增)?文字", text):
            operations.append(Operation("set", "text.addition", "forbidden"))
            recognized_spans.append("禁止新增文字")

        if re.search(r"光线.*(?:暖一点|调暖|暖一些)", text):
            operations.append(Operation("set", "lighting.temperature", "warm"))
            recognized_spans.append("光线调暖")

        # Bind “不变” only to the clause immediately preceding it. Longest
        # phrases win, so “瓶身颜色” does not also become “瓶身外观”.
        preserve_clauses = re.findall(r"(?:保持\s*)?([^，。；]*?)\s*不变", text, re.I)
        for clause in preserve_clauses:
            normalized = clause.strip()
            if "瓶身颜色" in normalized:
                operations.append(Operation("set", "bottle.color", "preserve original"))
            elif "瓶身" in normalized:
                operations.append(Operation("set", "bottle.appearance", "preserve original"))
            if "原有标签" in normalized or "标签" in normalized:
                operations.append(Operation("set", "label.content", "preserve original"))
            if re.search(r"logo", normalized, re.I):
                operations.append(Operation("set", "logo.appearance", "preserve original"))
            recognized_spans.append(f"{normalized}不变")

        bottle_color = re.search(r"(?:把)?瓶身(?:颜色)?(?:改成|变成|换成)\s*(红|蓝|绿|黑|白)(?:色)?", text)
        if bottle_color:
            operations.append(
                Operation("set", "bottle.color", self.COLOR_MAP[bottle_color.group(1)])
            )
            recognized_spans.append(bottle_color.group(0))

        note_items: list[str] = []
        if not operations and not references and text.strip():
            # Preserve a fully subjective instruction verbatim; splitting it can
            # destroy relations such as “高级，但不要冰冷”.
            note_items.append(text.strip())
        else:
            for raw_clause in re.split(r"[，。；]", text):
                clause = raw_clause.strip()
                if clause and not self._is_control_clause(clause):
                    note_items.append(clause)
        creative_notes = tuple(note_items)

        return ChangeSet(
            operations=tuple(operations),
            references=tuple(references),
            creative_notes=creative_notes,
            preserve_unspecified=True,
        )

    @staticmethod
    def _is_control_clause(clause: str) -> bool:
        patterns = (
            r"其他不变",
            r"电商主图",
            r"用\s*image_[A-Za-z0-9_-]+\s*的产品",
            r"image_[A-Za-z0-9_-]+\s*(?:只|仅)\s*参考光影",
            r"(?:纯白|浅灰|白|灰|黑|红|蓝|绿)(?:色)?(?:背景|底)",
            r"背景(?:改成|换成|为)",
            r"(?:不要|禁止)(?:添加|新增)?文字",
            r"光线.*(?:暖一点|调暖|暖一些)",
            r"不变",
            r"瓶身(?:颜色)?(?:改成|变成|换成)",
        )
        return any(re.search(pattern, clause, re.I) for pattern in patterns)
