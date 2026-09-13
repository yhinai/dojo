"""Sandbox entry point. Contains no expected outputs or acceptance rules."""

import contextlib
import importlib.util
import io
import json
import sys
import traceback
from types import SimpleNamespace


def main():
    inputs = json.loads(sys.stdin.read())
    captured = io.StringIO()
    try:
        with contextlib.redirect_stdout(captured):
            spec = importlib.util.spec_from_file_location("submitted_notebook", sys.argv[1])
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            _, definitions = module.app.run()
            initial = definitions["result"]
            observed = []
            for probe in inputs:
                _, current = module.app.run(
                    defs={"records": probe["records"], "control": SimpleNamespace(value=probe["value"])}
                )
                observed.append(
                    {
                        "function": current["compute"](probe["records"], probe["value"]),
                        "reactive_result": current["result"],
                    }
                )
        response = {"initial": initial, "observed": observed}
    except Exception as exc:  # noqa: BLE001 -- isolate arbitrary notebook execution errors
        response = {
            "candidate_error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc()[-8000:],
        }
    print(json.dumps(response))


if __name__ == "__main__":
    main()
