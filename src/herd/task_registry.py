"""Deterministic task construction; private expectations never enter worker manifests.

Families represent different operations, rather than different seeds of one task.
Final families compose each operation with a held-out active-row filter.
This is synthetic transfer evaluation, not a claim of production generalization.
"""

from __future__ import annotations

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
    "composition-startup",
)


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
        request = (
            f"Build a runnable marimo notebook: {family.description}. "
            + (
                "First exclude rows unless their active field is exactly True. "
                if partition == Partition.FINAL
                else ""
            )
            + "Define a named compute(rows, value) function in a cell, a records variable in its own cell, "
            "and a control widget in its own cell. Define result in a downstream cell by calling compute "
            "with records and control.value (use 1 if its value is None). Return these names from their cells. "
            "Use a marimo integer slider labeled 'Threshold', range -5..15, step 1, initial value 1. "
            + (
                "Wrap the slider with .form(submit_button_label='Apply'); changing it must not change result until Apply. "
                if family.track == 3
                else "Changing the slider must recompute result immediately. "
            )
            + "Render result as JSON in a visible HTML <pre id='herd-result'> element, updating reactively. "
            "Use separate cells and valid marimo dependencies. Include app = marimo.App() and the __main__ guard. "
            "Only standard library and marimo are installed. Empty inputs, negatives and duplicates must work."
        )
        return TaskManifest(
            task_id=f"{partition.value}-{digest([seed, family.name])[:16]}",
            template_id=f"{prefix}/{family.name}/v1",
            family_id=f"{prefix}/{family.name}",
            track=family.track,
            partition=partition,
            public_request=request,
            public_fixture=fixture,
            public_skill_tags=[TAGS[family.track], "reactivity"],
            runtime_lock_hash=self.runtime_hash,
            docs_snapshot_hash=self.docs_hash,
            assignment_seed=seed,
        )

    def family(self, task: TaskManifest) -> Family:
        return next(f for f in FAMILIES if f.name == task.public_fixture["operation"])

    def reference_source(self, task: TaskManifest) -> str:
        family = self.family(task)
        filter_line = (
            'rows = [r for r in rows if r.get("active") is True]\n        '
            if task.partition == Partition.FINAL
            else ""
        )
        widget = "mo.ui.slider(start=-5, stop=15, step=1, value=1, label='Threshold')"
        if task.track == 3:
            widget += ".form(submit_button_label='Apply')"
        return f"""import marimo
app = marimo.App()

@app.cell
def imports():
    import marimo as mo
    import json
    import html
    return mo, json, html

@app.cell
def calculation():
    def compute(rows, value):
        {filter_line}return {family.expression}
    return (compute,)

@app.cell
def data():
    records = {task.public_fixture["records"]!r}
    return (records,)

@app.cell
def widget(mo):
    control = {widget}
    control
    return (control,)

@app.cell
def transform(compute, records, control):
    result = compute(records, control.value if control.value is not None else 1)
    return (result,)

@app.cell
def display(mo, json, html, result):
    mo.Html('<pre id="herd-result">' + html.escape(json.dumps(result, sort_keys=True)) + '</pre>')
    return

if __name__ == '__main__':
    app.run()
"""

    def negative_source(self, task: TaskManifest) -> str:
        """Known wrong fixture: discards rows; not a model-generated failure."""
        return self.reference_source(task).replace("return " + self.family(task).expression, "return 'WRONG'")

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
        if task.partition == Partition.FINAL:
            for probe in probes[1:]:
                for row in probe["records"]:
                    row["active"] = rng.choice([True, False])
        return probes

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
