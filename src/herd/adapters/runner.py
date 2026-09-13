"""Sandbox entry point. Exercises actual marimo objects; contains no expected outputs.

The pinned marimo UIElement._update method converts frontend values and calls
on_change; app.run(defs=...) then reexecutes dependent cells headlessly. Browser
controls separately validate the frontend event-to-kernel transport.

Protocol integrity. The submitted notebook is untrusted code running in this
interpreter, so it must not be able to author the verdict the host reads:

  * The notebook executes in a forked child whose fd 1 and fd 2 point at
    /dev/null, so `os.write(1, ...)` cannot reach the host pipe and `os._exit()`
    cannot truncate the protocol -- the parent still emits a response.
  * The child returns observations on an explicit pipe; the parent, which never
    executes notebook code, frames them with a host-supplied nonce delivered on
    stdin. A response without the matching nonce is rejected by the evaluator.

Residual risk, stated plainly: untrusted code sharing an interpreter can still
scan open descriptors and attempt a correctly shaped forgery on the result pipe.
The host-side AST harness checks (marimo import, App construction, @app.cell
count, required widget constructor) and the independent browser oracle are the
cross-checks that make such a forgery fail rather than merely be difficult.
"""

import contextlib
import importlib.util
import io
import json
import os
import sys
import traceback


def observe(inputs, path):
    """Run the submitted notebook and collect behaviour. Executes untrusted code."""
    captured = io.StringIO()
    with contextlib.redirect_stdout(captured):
        import marimo as mo
        from marimo._runtime.state import State

        spec = importlib.util.spec_from_file_location("submitted_notebook", path)
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
    return {"initial": initial, "observed": observed, "actual_ui_objects": True}


def run_isolated(inputs, path):
    """Execute the notebook in a child that cannot reach the host's stdout."""
    read_fd, write_fd = os.pipe()
    pid = os.fork()
    if pid == 0:  # child: untrusted code runs here and never sees the real fd 1
        code = 0
        try:
            os.close(read_fd)
            devnull = os.open(os.devnull, os.O_WRONLY)
            os.dup2(devnull, 1)
            os.dup2(devnull, 2)
            try:
                payload = observe(inputs, path)
            except BaseException as exc:  # noqa: BLE001 -- any notebook failure is behavioural
                payload = {
                    "candidate_error": f"{type(exc).__name__}: {exc}",
                    "traceback": traceback.format_exc()[-8000:],
                }
            os.write(write_fd, json.dumps(payload).encode())
            os.close(write_fd)
        except BaseException:  # noqa: BLE001 -- the parent reports an empty/short read
            code = 1
        finally:
            os._exit(code)
    os.close(write_fd)
    chunks = []
    with os.fdopen(read_fd, "rb") as stream:
        while chunk := stream.read(65536):
            chunks.append(chunk)
            if sum(map(len, chunks)) > 4_000_000:
                break
    _, status = os.waitpid(pid, 0)
    raw = b"".join(chunks)
    if not raw:
        return {"candidate_error": f"Notebook process produced no result (wait status {status})"}
    try:
        payload = json.loads(raw)
    except ValueError:
        return {"candidate_error": "Notebook process returned a malformed result"}
    return payload if isinstance(payload, dict) else {"candidate_error": "Result was not an object"}


def main():
    request = json.loads(sys.stdin.read())
    # Accept the historical bare-list payload so an older evaluator still runs.
    nonce = request.get("nonce") if isinstance(request, dict) else None
    inputs = request.get("probes") if isinstance(request, dict) else request
    try:
        response = run_isolated(inputs, sys.argv[1])
    except Exception as exc:  # noqa: BLE001 -- harness failure, not a candidate verdict
        response = {"candidate_error": f"{type(exc).__name__}: {exc}"}
    if nonce is not None:
        response["nonce"] = nonce
    sys.stdout.write(json.dumps(response))
    sys.stdout.flush()


if __name__ == "__main__":
    main()
