"""Deterministic task construction; private expectations never enter worker manifests.

Families exercise different marimo graph and UI semantics, not just arithmetic expressions.
Final families compose each operation with a held-out active-row filter.
This is synthetic transfer evaluation, not a claim of production generalization.
"""

from __future__ import annotations

import ast
import random
from dataclasses import dataclass

from herd.schemas import Partition, TaskManifest, digest


@dataclass(frozen=True)
class Family:
    name: str
    track: int
    description: str
    expression: str


FAMILIES = (
    Family("sum", 0, "sum all amounts, multiplied by the control", "sum(r['amount'] for r in rows) * value"),
    Family(
        "maximum",
        0,
        "maximum amount (zero for no rows), plus the control",
        "max([r['amount'] for r in rows], default=0) + value",
    ),
    Family(
        "minimum",
        0,
        "minimum amount (zero for no rows), minus the control",
        "min([r['amount'] for r in rows], default=0) - value",
    ),
    Family(
        "threshold_sum",
        1,
        "sum amounts greater than or equal to the control",
        "sum(r['amount'] for r in rows if r['amount'] >= value)",
    ),
    Family(
        "threshold_count",
        1,
        "count rows with amount strictly greater than the control",
        "sum(1 for r in rows if r['amount'] > value)",
    ),
    Family(
        "group_totals",
        2,
        "group by category; sum amounts at least the control; omit empty categories",
        "{k: sum(r['amount'] for r in rows if r['category'] == k and r['amount'] >= value) for k in sorted({r['category'] for r in rows if r['amount'] >= value})}",
    ),
    Family(
        "unique_sorted",
        2,
        "return sorted unique amounts greater than or equal to the control",
        "sorted({r['amount'] for r in rows if r['amount'] >= value})",
    ),
    Family(
        "committed_sum",
        3,
        "sum amounts times the committed form value; before submission use value 1",
        "sum(r['amount'] for r in rows) * value",
    ),
    Family(
        "committed_count",
        3,
        "count rows with amount at least the committed form value; before submission use value 1",
        "sum(1 for r in rows if r['amount'] >= value)",
    ),
    Family(
        "summary",
        4,
        "return a dict with count and total for rows whose amount is at least the control",
        "{'count': sum(1 for r in rows if r['amount'] >= value), 'total': sum(r['amount'] for r in rows if r['amount'] >= value)}",
    ),
    Family(
        "category_counts",
        4,
        "return category counts for amounts strictly above the control; omit empty categories",
        "{k: sum(1 for r in rows if r['category'] == k and r['amount'] > value) for k in sorted({r['category'] for r in rows if r['amount'] > value})}",
    ),
    Family(
        "scaled_sorted",
        4,
        "return every amount multiplied by the control, sorted descending, preserving duplicates",
        "sorted([r['amount'] * value for r in rows], reverse=True)",
    ),
)
TAGS = (
    "unique-global-names",
    "widget-value-dependency",
    "data-transform",
    "form-commit",
    "state-and-conditional-execution",
)


CONTRACTS = {
    "sum": "duplicate_repair",
    "maximum": "local_scope",
    "minimum": "forward_dependency",
    "threshold_sum": "slider",
    "threshold_count": "multi_checkbox",
    "group_totals": "table",
    "unique_sorted": "table",
    "committed_sum": "form",
    "committed_count": "form",
    "summary": "state",
    "category_counts": "stop",
    "scaled_sorted": "multi_offset",
}


class TaskRegistry:
    def __init__(self, runtime_hash: str, docs_hash: str):
        self.runtime_hash = runtime_hash
        self.docs_hash = docs_hash

    def generate(self, partition: Partition, seed: int, track: int | None = None) -> TaskManifest:
        partition = Partition(partition)
        available = [f for f in FAMILIES if track is None or f.track == track]
        if not available:
            raise ValueError("track must be 0..4")
        family = available[seed % len(available)]
        rng = random.Random(digest([partition.value, seed, family.name]))
        rows = [{"category": rng.choice(["A", "B", "C"]), "amount": rng.randint(-3, 12)} for _ in range(7)]
        rows[0]["amount"], rows[1]["amount"] = 1, 2
        prefix = "heldout-active" if partition == Partition.FINAL else partition.value
        if partition == Partition.FINAL:
            for row in rows:
                row["active"] = rng.choice([True, False])
            rows[0]["active"] = rows[1]["active"] = True
        fixture = {
            "records": rows,
            "initial_value": 1,
            "control_min": -5,
            "control_max": 15,
            "operation": family.name,
        }
        contract = CONTRACTS[family.name]
        fixture["interaction_contract"] = contract
        instructions = {
            "duplicate_repair": "Repair the starter's duplicate global 'total' definitions across cells. Keep a preparation cell defining preview_total as the sum of raw record amounts, separate from the result cell, and use cell-local names or distinct globals. Starter fragments: cell A: total = sum(r['amount'] for r in records); cell B: total = compute(records, control.value).",
            "local_scope": "Create separate positive and negative preview cells over the raw input records, both using a cell-local _preview variable; return positive_preview and negative_preview respectively. Do not create duplicate public definitions.",
            "forward_dependency": "Put the transform cell BEFORE the records, compute and control definition cells in source order. The reactive dependency graph must still resolve correctly.",
            "slider": "The slider drives the downstream result directly; do not read control.value in its defining cell.",
            "multi_checkbox": "Add an independent mo.ui.checkbox named include_negative, label 'Include negatives', initially True, in a separate cell. If unchecked exclude negative amounts before compute. Both widgets must independently drive result.",
            "table": "Add a mo.ui.table named selection_table with records as data, multi-row selection, initial_selection=[0], pagination=False and label 'Rows'. Compute only over selection_table.value, never all records. Empty selection means no rows. Slider and table selection must independently update result.",
            "form": "Wrap the slider in .form(submit_button_label='Apply'). Before first submission use value 1. Editing must leave result unchanged until Apply, then use committed value.",
            "state": "Use get_value, set_value = mo.state(1) in their own cell. Bind the slider's on_change to set_value. A separate result cell reads get_value(), not control.value, and must respond to direct state updates as well as slider callbacks.",
            "stop": "Add mo.ui.checkbox named enabled, label 'Enabled', initially True. In the result cell call mo.stop(not enabled.value, mo.md('Paused')) BEFORE computing result. When disabled, result must be undefined and downstream rendering stopped; when reenabled it must recover.",
            "multi_offset": "Add an independent mo.ui.slider named offset, label 'Offset', range -5..15, initial 0 in its own cell. Compute using value = control.value + offset.value. Either slider must update result.",
        }
        request = (
            f"Build a runnable marimo notebook: {family.description}. "
            + (
                "Inside compute, first exclude rows unless their active field is exactly True. "
                if partition == Partition.FINAL
                else ""
            )
            + "Define compute(rows, value), records from the fixture, and control in separate cells. "
            "Use a marimo integer slider named control labeled 'Threshold', range -5..15, step 1, initial 1. "
            + instructions[contract]
            + " "
            "Define result in a downstream cell using compute and the inputs described above. "
            "Return all public names from their cells. Render result as JSON in a visible HTML "
            "<pre id='herd-result'> element updating reactively (except while stopped). "
            "Use valid marimo dependencies, app = marimo.App(), and a __main__ guard. "
            "Only standard library and marimo are installed. Empty inputs, negatives and duplicates must work."
        )
        return TaskManifest(
            task_id=f"{partition.value}-{digest(['marimo-contracts-v2', seed, family.name])[:16]}",
            template_id=f"{prefix}/{family.name}/v2",
            family_id=f"{prefix}/{family.name}",
            track=family.track,
            partition=partition,
            public_request=request,
            public_fixture=fixture,
            public_skill_tags=[TAGS[family.track], contract, "reactivity"],
            runtime_lock_hash=self.runtime_hash,
            docs_snapshot_hash=self.docs_hash,
            oracle_version="herd-marimo-contracts-v2",
            assignment_seed=seed,
        )

    def family(self, task: TaskManifest) -> Family:
        return next(f for f in FAMILIES if f.name == task.public_fixture["operation"])

    def reference_source(self, task: TaskManifest) -> str:
        family = self.family(task)
        filter_line = (
            'rows = [r for r in rows if r.get("active") is True]\n    '
            if task.partition == Partition.FINAL
            else ""
        )
        kind = CONTRACTS[family.name]
        widget = (
            "mo.ui.slider(start=-5, stop=15, step=1, value=1, label='Threshold'"
            + (", on_change=set_value" if kind == "state" else "")
            + ")"
        )
        if kind == "form":
            widget += ".form(submit_button_label='Apply')"
        cells = [
            ("imports", "", "import marimo as mo\nimport json\nimport html\nreturn mo, json, html"),
            (
                "calculation",
                "",
                f"def compute(rows, value):\n    {filter_line}return {family.expression}\nreturn (compute,)",
            ),
            ("data", "", f"records = {task.public_fixture['records']!r}\nreturn (records,)"),
        ]
        if kind == "state":
            cells.append(
                ("state_cell", "mo", "get_value, set_value = mo.state(1)\nreturn get_value, set_value")
            )
        cells.append(
            (
                "widget",
                "mo, set_value" if kind == "state" else "mo",
                f"control = {widget}\ncontrol\nreturn (control,)",
            )
        )
        args, rows, value, before = (
            "compute, records, control",
            "records",
            "control.value if control.value is not None else 1",
            "",
        )
        if kind == "table":
            cells.append(
                (
                    "table_cell",
                    "mo, records",
                    "selection_table = mo.ui.table(records, selection='multi', initial_selection=[0] if records else [], pagination=False, label='Rows')\nselection_table\nreturn (selection_table,)",
                )
            )
            args += ", selection_table"
            rows = "selection_table.value"
        elif kind == "multi_checkbox":
            cells.append(
                (
                    "filter_widget",
                    "mo",
                    "include_negative = mo.ui.checkbox(value=True, label='Include negatives')\ninclude_negative\nreturn (include_negative,)",
                )
            )
            args += ", include_negative"
            rows = "[r for r in records if include_negative.value or r['amount'] >= 0]"
        elif kind == "multi_offset":
            cells.append(
                (
                    "offset_widget",
                    "mo",
                    "offset = mo.ui.slider(start=-5, stop=15, value=0, label='Offset')\noffset\nreturn (offset,)",
                )
            )
            args += ", offset"
            value = "control.value + offset.value"
        elif kind == "state":
            args = "compute, records, get_value"
            value = "get_value()"
        elif kind == "stop":
            cells.append(
                (
                    "enable_widget",
                    "mo",
                    "enabled = mo.ui.checkbox(value=True, label='Enabled')\nenabled\nreturn (enabled,)",
                )
            )
            args += ", mo, enabled"
            before = "mo.stop(not enabled.value, mo.md('Paused'))\n"
        elif kind == "duplicate_repair":
            cells.append(
                (
                    "preparation",
                    "records",
                    "_total = sum(r['amount'] for r in records)\npreview_total = _total\nreturn (preview_total,)",
                )
            )
        elif kind == "local_scope":
            cells.extend(
                [
                    (
                        "positive",
                        "records",
                        "_preview = [r for r in records if r['amount'] >= 0]\npositive_preview = _preview\nreturn (positive_preview,)",
                    ),
                    (
                        "negative",
                        "records",
                        "_preview = [r for r in records if r['amount'] < 0]\nnegative_preview = _preview\nreturn (negative_preview,)",
                    ),
                ]
            )
        transform = ("transform", args, before + f"result = compute({rows}, {value})\nreturn (result,)")
        cells.insert(1, transform) if kind == "forward_dependency" else cells.append(transform)
        cells.append(
            (
                "display",
                "mo, json, html, result",
                "mo.Html('<pre id=\"herd-result\">' + html.escape(json.dumps(result, sort_keys=True)) + '</pre>')\nreturn",
            )
        )
        source = "import marimo\napp = marimo.App()\n"
        for name, args, body in cells:
            source += (
                f"\n@app.cell\ndef {name}({args}):\n"
                + "\n".join("    " + line for line in body.splitlines())
                + "\n"
            )
        return source + "\nif __name__ == '__main__':\n    app.run()\n"

    def negative_source(self, task: TaskManifest) -> str:
        """Authored marimo-specific regressions, never presented as worker failures."""
        source = self.reference_source(task)
        kind = CONTRACTS[self.family(task).name]
        changes = {
            "duplicate_repair": ("preview_total = _total", "result = _total\n    preview_total = result"),
            "local_scope": ("_preview =", "preview ="),
            "forward_dependency": (
                "def transform(compute, records, control):",
                "def transform(compute, records, control):\n    records = []",
            ),
            "slider": ("control.value if control.value is not None else 1", "1"),
            "multi_checkbox": ("include_negative.value or r['amount'] >= 0", "True"),
            "table": ("compute(selection_table.value,", "compute(records,"),
            "form": (".form(submit_button_label='Apply')", ""),
            "state": ("on_change=set_value", "on_change=lambda value: None"),
            "stop": ("mo.stop(not enabled.value, mo.md('Paused'))", "mo.stop(False, mo.md('Paused'))"),
            "multi_offset": ("control.value + offset.value", "control.value"),
        }
        return source.replace(*changes[kind])

    def private_probes(self, task: TaskManifest) -> list[dict]:
        rng = random.Random(digest([task.task_id, "oracle-private-v1"]))
        probes = [
            {"records": task.public_fixture["records"], "value": 1},
            {"records": [], "value": 2},
            {
                "records": [
                    {"category": "A", "amount": 2},
                    {"category": "A", "amount": 2},
                    {"category": "B", "amount": -2},
                ],
                "value": 2,
            },
        ]
        for _ in range(3):
            probes.append(
                {
                    "records": [
                        {"category": rng.choice(["A", "B", "Z"]), "amount": rng.randint(-8, 20)}
                        for _ in range(9)
                    ],
                    "value": rng.randint(-4, 12),
                }
            )
        probes[3] = {
            "records": [{"category": "A", "amount": -2}, {"category": "B", "amount": 4}],
            "value": -3,
        }
        if task.partition == Partition.FINAL:
            for probe in probes[1:]:
                for row in probe["records"]:
                    row["active"] = rng.choice([True, False])
        if task.partition == Partition.FINAL:
            probes[3]["records"][0]["active"] = True
        kind = CONTRACTS[self.family(task).name]
        for index, probe in enumerate(probes):
            probe["contract"] = kind
            probe["selection"] = [i for i in range(len(probe["records"])) if (i + index) % 2 == 0]
            probe["include_negative"] = index % 2 == 0
            probe["offset"] = [-2, 0, 3][index % 3]
            probe["enabled"] = index % 2 == 0
            probe["state_value"] = probe["value"] + 1
        return probes

    def structure_requirements(self, task: TaskManifest, source: str) -> list[tuple[str, bool]]:
        """Only enforce structures explicitly requested in this public task, without cell-name matching."""
        cells: dict[str, set[int]] = {}

        def bindings(node):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                yield node.name
                return  # Function-local variables aren't marimo globals.
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                yield node.id
            for child in ast.iter_child_nodes(node):
                yield from bindings(child)

        for node in ast.parse(source).body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            decorators = [d.func if isinstance(d, ast.Call) else d for d in node.decorator_list]
            if not any(isinstance(d, ast.Attribute) and d.attr == "cell" for d in decorators):
                continue
            for statement in node.body:
                for name in bindings(statement):
                    cells.setdefault(name, set()).add(node.lineno)
        kind = CONTRACTS[self.family(task).name]
        if kind == "forward_dependency":
            locations = [cells.get(name, set()) for name in ("result", "records", "compute", "control")]
            valid = all(len(locations_) == 1 for locations_ in locations)
            return [
                (
                    "structure_forward_dependency",
                    bool(valid and min(locations[0]) < min(set.union(*locations[1:]))),
                )
            ]
        if kind in ("local_scope", "duplicate_repair"):
            names = (
                ("positive_preview", "negative_preview")
                if kind == "local_scope"
                else ("preview_total", "result")
            )
            left, right = (cells.get(name, set()) for name in names)
            return [
                (
                    "structure_separate_previews" if kind == "local_scope" else "structure_repair_cells",
                    len(left) == len(right) == 1 and left.isdisjoint(right),
                )
            ]
        return []

    def expected_result(self, task: TaskManifest, probe: dict | None = None):
        kind = CONTRACTS[self.family(task).name]
        rows = task.public_fixture["records"] if probe is None else probe["records"]
        value = 1 if probe is None else probe["value"]
        if kind == "table":
            indices = [0] if probe is None and rows else ([] if probe is None else probe["selection"])
            rows = [rows[i] for i in indices]
        elif kind == "multi_checkbox" and probe is not None and not probe["include_negative"]:
            rows = [r for r in rows if r["amount"] >= 0]
        elif kind == "multi_offset" and probe is not None:
            value += probe["offset"]
        elif kind == "stop" and probe is not None and not probe["enabled"]:
            return None
        return self.expected(task, rows, value)

    def expected(self, task: TaskManifest, rows: list[dict], value: int):
        """Independent host-side oracle; never shipped in the sandbox mount."""
        op = self.family(task).name
        if task.partition == Partition.FINAL:
            rows = [r for r in rows if r.get("active") is True]
        amounts = [r["amount"] for r in rows]
        selected = [r for r in rows if r["amount"] >= value]
        if op in ("sum", "committed_sum"):
            return sum(amounts) * value
        if op == "maximum":
            return (max(amounts) if amounts else 0) + value
        if op == "minimum":
            return (min(amounts) if amounts else 0) - value
        if op == "threshold_sum":
            return sum(r["amount"] for r in selected)
        if op == "threshold_count":
            return len([a for a in amounts if a > value])
        if op == "unique_sorted":
            return sorted({r["amount"] for r in selected})
        if op == "committed_count":
            return len(selected)
        if op == "summary":
            return {"count": len(selected), "total": sum(r["amount"] for r in selected)}
        if op == "scaled_sorted":
            return sorted((a * value for a in amounts), reverse=True)
        groups = {}
        for row in rows:
            if row["amount"] >= value if op == "group_totals" else row["amount"] > value:
                groups[row["category"]] = groups.get(row["category"], 0) + (
                    row["amount"] if op == "group_totals" else 1
                )
        return groups
