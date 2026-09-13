# Frozen marimo worker documentation

Source: https://docs.marimo.io/guides/reactivity/ and https://docs.marimo.io/guides/testing/pytest/
Snapshot authored before the first HERD learning round, 2026-09-13.

A marimo notebook is a Python module containing `app = marimo.App()` and functions decorated with `@app.cell`. Cell function arguments declare dependencies, and returned objects expose definitions to downstream cells. The dependency graph determines execution order; a definition may appear visually below its consumer. Do not define the same global name in multiple cells. Use underscore-prefixed local variables for intermediate work that should not create global definitions.

Import marimo as `mo` in a cell and return it to expose it. Create UI elements in one cell, then access their `.value` in another dependent cell. A form wraps an element and commits its value on submission. Keep changes reactive by deriving values from cell dependencies instead of mutating hidden state. App.run() returns outputs and a definitions mapping for programmatic testing. Preserve the named public function and outputs requested in the task, including their response to changed input values. Include `if __name__ == '__main__': app.run()` for script execution.

## Additional reactive UI patterns

- `get_value, set_value = mo.state(initial)` creates reactive state. Read by calling the getter in a downstream cell. A callback can call the setter with a value or updater function. Keep widget creation and dependent computations in separate cells.
- `mo.ui.table(data, selection="multi", initial_selection=[0])` exposes selected rows through `.value`; compute from that selection in another cell. Do not treat selected rows as the full source dataset.
- `mo.stop(condition, mo.md("Choose an input"))` stops the current cell and dependent cells when the condition is true. Outputs below the stop are not defined until the condition becomes false.
- Put slider and checkbox widgets in a creation cell and read their `.value` properties in downstream computations. Every referenced widget must be a real dependency; changing either should update the result.
- A form buffers changes. Wrap a UI element with `.form()` and consume the form's committed `.value` downstream. Unsubmitted edits must not change a committed result.
- A global variable can only be defined in one cell. Use local names beginning with `_` for independent cell-local temporary variables. Notebook display order does not impose Python script order; marimo uses dependencies.
