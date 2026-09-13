# Frozen marimo worker documentation

Source: https://docs.marimo.io/guides/reactivity/ and https://docs.marimo.io/guides/testing/pytest/
Snapshot authored before the first HERD learning round, 2026-09-13.

A marimo notebook is a Python module containing `app = marimo.App()` and functions decorated with `@app.cell`. Cell function arguments declare dependencies, and returned objects expose definitions to downstream cells. The dependency graph determines execution order; a definition may appear visually below its consumer. Do not define the same global name in multiple cells. Use underscore-prefixed local variables for intermediate work that should not create global definitions.

Import marimo as `mo` in a cell and return it to expose it. Create UI elements in one cell, then access their `.value` in another dependent cell. A form wraps an element and commits its value on submission. Keep changes reactive by deriving values from cell dependencies instead of mutating hidden state. App.run() returns outputs and a definitions mapping for programmatic testing. Preserve the named public function and outputs requested in the task, including their response to changed input values. Include `if __name__ == '__main__': app.run()` for script execution.
