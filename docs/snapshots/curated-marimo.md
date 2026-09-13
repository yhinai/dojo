# Preauthored marimo quick reference

Authored 2026-09-13 before any measured HERD learning run. This is the curated-docs arm's additional memory, distinct from the common worker documentation. It contains generic API examples and debugging guidance, never generated lessons, task fixtures or evaluator answers. Applicable to the pinned marimo 0.24.2 runtime.

## Build a dependency graph

Create `app = marimo.App()`. Each `@app.cell` declares dependencies through its arguments and exposes definitions through its return tuple. Dependencies determine execution order; visual position does not. A global name may be defined in only one cell. Use `_temporary` for cell-local scratch work. Prefer a pure function over a mutation that another cell cannot observe. [Reactivity guide](https://docs.marimo.io/guides/reactivity/).

```python
import marimo
app = marimo.App()

@app.cell
def imports():
    import marimo as mo
    return (mo,)

@app.cell
def input_cell(mo):
    greeting = mo.ui.text(value="Hello", label="Greeting")
    greeting
    return (greeting,)

@app.cell
def output_cell(greeting, mo):
    message = greeting.value.upper()
    mo.md(message)
    return (message,)

if __name__ == "__main__":
    app.run()
```

The UI element is created in one cell and its value consumed in another. Updating the input invalidates the consumer. Keep the displayed value derived from the same named result that code exposes; a static display can hide a computation bug.

## Choose immediate or committed input

A regular input's `.value` changes as the user interacts. Wrap an input with `.form(submit_button_label="Submit")` when computation must wait for explicit submission. Read the wrapper's `.value`, not the underlying input. Before the first submission the wrapper may be `None`; choose a specified fallback or stop dependent computation with `mo.stop(...)`. Do not use `value or fallback` if `0`, `False`, or an empty string is a legitimate submitted value. Test `value is None` instead. [Form API](https://docs.marimo.io/api/inputs/form/).

```python
# Creation cell:
name_form = mo.ui.text(label="Name").form(submit_button_label="Submit")
# A separate dependent cell:
submitted_name = "anonymous" if name_form.value is None else name_form.value
```

This fragment needs separate creation and consumer cells; it is not a complete notebook. A form changes when submitted, and an immediate input changes directly. The two behaviors are different contracts.

## Expose computation and test changes

Put calculation in a pure named function when callers need to test arbitrary inputs. Its arguments should drive the calculation; avoid capturing one demonstration input or returning a precomputed literal. Preserve requested names and types. Include empty inputs, boundary conditions and changed values in your own checks. `app.run()` provides outputs and definitions for programmatic tests; looking only at notebook source or a printed success claim does not test behavior. [Programmatic testing](https://docs.marimo.io/guides/testing/pytest/).

## Diagnose by observed failure

- Multiple definitions: locate both defining cells, rename scratch variables or consolidate the definition.
- Dependency cycle: split input creation from value consumption and remove reciprocal definitions.
- Stale display: derive the output from reactive dependencies rather than mutating a shared object.
- Form updates too early: consume the form wrapper's committed value downstream.
- First load fails: handle unsubmitted forms and validate the notebook in a fresh process.
- One example passes but changed input fails: remove captured constants and test the public function directly.

These are debugging hypotheses. Keep only the change that resolves the observed execution failure and preserves the requested behavior. A structural check, programmatic test, and real UI interaction answer different questions.
