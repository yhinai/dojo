"""Sandbox entry point. Exercises actual marimo objects; contains no expected outputs.

The pinned marimo UIElement._update method converts frontend values and calls
on_change; app.run(defs=...) then reexecutes dependent cells headlessly. Browser
controls separately validate the frontend event-to-kernel transport.
"""

import contextlib
import importlib.util
import io
import json
import sys
import traceback


def main():
    inputs = json.loads(sys.stdin.read())
    captured = io.StringIO()
    try:
        with contextlib.redirect_stdout(captured):
            import marimo as mo
            from marimo._runtime.state import State

            spec = importlib.util.spec_from_file_location("submitted_notebook", sys.argv[1])
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            _, definitions = module.app.run()
            initial = definitions["result"]
            kind = inputs[0]["contract"]
            required = {"control": mo.ui.form if kind == "form" else mo.ui.slider}
            if kind == "table":
                required["selection_table"] = mo.ui.table
            elif kind == "multi_checkbox":
                required["include_negative"] = mo.ui.checkbox
            elif kind == "multi_offset":
                required["offset"] = mo.ui.slider
            elif kind == "stop":
                required["enabled"] = mo.ui.checkbox
            elif kind == "state":
                required["get_value"] = State
            for name, cls in required.items():
                if not isinstance(definitions.get(name), cls):
                    raise TypeError(f"{name} must be an actual marimo {cls.__name__}")
            observed = []
            for probe in inputs:
                _, fresh = module.app.run(defs={"records": probe["records"]})
                control = fresh["control"]
                control._update(probe["value"])
                overrides = {"records": probe["records"], "control": control}
                for name, field in (
                    ("selection_table", "selection"),
                    ("include_negative", "include_negative"),
                    ("offset", "offset"),
                    ("enabled", "enabled"),
                ):
                    if name in required:
                        fresh[name]._update(probe[field])
                        overrides[name] = fresh[name]
                if kind == "state":
                    overrides.update(get_value=fresh["get_value"], set_value=fresh["set_value"])
                _, current = module.app.run(defs=overrides)
                item = {
                    "function": current["compute"](probe["records"], probe["value"]),
                    "reactive_result": current.get("result"),
                    "result_defined": "result" in current,
                }
                for field in ("positive_preview", "negative_preview", "preview_total"):
                    if field in current:
                        item[field] = current[field]
                if kind == "state":
                    fresh["set_value"](probe["state_value"])
                    _, changed = module.app.run(defs=overrides)
                    item["direct_state_result"] = changed.get("result")
                observed.append(item)
        response = {"initial": initial, "observed": observed, "actual_ui_objects": True}
    except Exception as exc:  # noqa: BLE001 -- isolate arbitrary notebook execution errors
        response = {
            "candidate_error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc()[-8000:],
        }
    print(json.dumps(response))


if __name__ == "__main__":
    main()
