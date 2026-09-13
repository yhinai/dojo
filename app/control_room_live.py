# ruff: noqa: B018
"""HERD live view — watch the colony learn in real time.

Auto-refreshing. Evidence curves climb as gates evaluate pairs; the pool fills;
final arms accumulate. Same evidence API as control_room.py.
"""
import marimo

__generated_with = "0.23.0"
app = marimo.App(width="full", app_title="HERD · Live")


@app.cell
def _():
    import math
    import os
    from urllib.parse import quote

    import httpx
    import marimo as mo

    from herd.config import load_environment as _load_environment

    _load_environment()

    def fetch(path, timeout=12):
        r = httpx.get(
            os.getenv("HERD_API_URL", "http://127.0.0.1:8000").rstrip("/") + path,
            headers={"X-Herd-Token": os.getenv("HERD_CONTROL_TOKEN", "")},
            timeout=timeout,
        )
        r.raise_for_status()
        return r.json()

    return fetch, math, mo, os, quote


@app.cell
def _(mo):
    mo.Html(
        """<style>
    :root{--ink:#0f1512;--mut:#5f6963;--line:#e6e8e3;--good:#2e6b46;--bad:#b4432c;--acc:#2563eb;--bg:#fcfcfa;}
    body{background:var(--bg)!important;color:var(--ink);font-family:-apple-system,'Helvetica Neue',sans-serif;}
    .top{display:flex;align-items:baseline;justify-content:space-between;border-bottom:1px solid var(--line);padding:16px 0 10px;margin-bottom:6px;}
    .top h1{font:650 22px/1 -apple-system,sans-serif;letter-spacing:-.5px;margin:0;}
    .top h1 em{font-style:normal;color:var(--good);}
    .live{display:inline-flex;align-items:center;gap:7px;font:600 11px 'SF Mono',monospace;color:var(--bad);letter-spacing:1px;}
    .dot{width:8px;height:8px;border-radius:999px;background:var(--bad);animation:p 1.4s infinite;}
    @keyframes p{50%{opacity:.25}}
    .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:12px;margin:14px 0;}
    .m{border:1px solid var(--line);border-radius:12px;padding:14px 16px;background:#fff;}
    .m .v{font:650 30px/1 -apple-system,sans-serif;letter-spacing:-1px;}
    .m .k{font:10.5px 'SF Mono',monospace;color:var(--mut);text-transform:uppercase;letter-spacing:.7px;margin-top:6px;}
    .sec{font:600 12px 'SF Mono',monospace;color:var(--mut);text-transform:uppercase;letter-spacing:1px;margin:22px 0 8px;}
    .gate{border:1px solid var(--line);border-radius:12px;padding:12px 14px;background:#fff;margin-bottom:10px;}
    .gate .hd{display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;}
    .gate .id{font:600 12px 'SF Mono',monospace;}
    .pill{font:600 11px 'SF Mono',monospace;padding:3px 9px;border-radius:999px;}
    .pill.admit{background:#e7f2ea;color:var(--good);}
    .pill.reject{background:#fbeae5;color:var(--bad);}
    .pill.run{background:#e7eefc;color:var(--acc);}
    .bar{height:8px;border-radius:99px;background:#eef0ec;overflow:hidden;}
    .bar > i{display:block;height:100%;background:var(--acc);border-radius:99px;}
    .bar.admit > i{background:var(--good);}
    .bar.reject > i{background:var(--bad);}
    .gate .meta{font:11px 'SF Mono',monospace;color:var(--mut);margin-top:6px;}
    .note{color:var(--mut);font-size:12px;}
    .err{border:1px dashed var(--line);border-radius:12px;padding:16px;color:var(--mut);background:#fff;font-size:13.5px;}
    </style>"""
    )
    return


@app.cell
def _(fetch, mo):
    tick = mo.ui.refresh(options=[5, 10, 30], default_interval=10, label="live refresh")
    try:
        _exps = fetch("/api/experiments", timeout=5)
        _items = _exps.get("experiments", _exps) if isinstance(_exps, dict) else _exps
        experiments = _items if isinstance(_items, list) else []
        err = None
    except Exception as _e:  # noqa: BLE001
        experiments, err = [], f"{type(_e).__name__}: start herd serve"
    if err:
        mo.callout(err, kind="warn")
    return experiments, tick


@app.cell
def _(experiments, mo):
    picker = mo.ui.dropdown(
        options={str(e["id"]): str(e["id"]) for e in experiments},
        value=str(experiments[0]["id"]) if experiments else None,
        label="experiment",
    )
    picker
    return (picker,)


@app.cell
def _(fetch, picker, quote, tick):
    tick.value  # subscribe
    detail, gates, pairs, report, attempts, err = {}, [], [], None, [], None
    if picker.value:
        try:
            detail = fetch(f"/api/experiments/{quote(picker.value, safe='')}")
            gates = detail.get("gates", [])
            pairs = detail.get("pairs", [])
            attempts = fetch(f"/api/experiments/{quote(picker.value, safe='')}/attempts?offset=0&limit=200")["items"]
            try:
                report = fetch(f"/api/experiments/{quote(picker.value, safe='')}/report", timeout=8)
            except Exception:  # noqa: BLE001 — report not ready yet
                report = None
        except Exception as _e:  # noqa: BLE001
            err = f"{type(_e).__name__}"
    return attempts, detail, err, gates, pairs, report


@app.cell
def _(detail, mo):
    ex = detail.get("experiment", {})
    mo.Html(
        f'<div class="top"><h1>HERD · <em>live</em></h1>'
        f'<span class="live"><span class="dot"></span>{str(ex.get("status","—")).upper()} · {str(ex.get("phase","—")).upper()}</span></div>'
    )
    return


@app.cell
def _(attempts, detail, gates, mo, report):
    """Headline metrics."""
    lessons = detail.get("lessons", [])
    admitted = [l for l in lessons if str(l.get("status", "")).lower() in {"admitted", "accepted"}]
    final_eps = [a for a in attempts if a.get("phase") == "final"]
    dev_eps = [a for a in attempts if a.get("phase") in (None, "development")]
    firsts = [a for a in dev_eps if a.get("submission_index") in (None, 1)]
    succ = sum(1 for a in firsts if (a.get("result") or {}).get("success"))
    floor = f"{succ}/{len(firsts)}" if firsts else "—"
    cells = [
        (floor, "first-attempt success (dev)"),
        (str(len(admitted)), "lessons admitted to pool"),
        (str(len(gates)), "gates evaluated"),
        (f"{len(final_eps)}/720", "final episodes"),
    ]
    if report and report.get("arms"):
        ap = (report["arms"].get("admitted_pool") or {}).get("success_rate")
        np_ = (report["arms"].get("no_pool") or {}).get("success_rate")
        if ap is not None and np_ is not None:
            cells.append((f"{ap:.0%} vs {np_:.0%}", "admitted pool vs no pool"))
    mo.Html(
        '<div class="grid">'
        + "".join(f'<div class="m"><div class="v">{v}</div><div class="k">{k}</div></div>' for v, k in cells)
        + "</div>"
    )
    return admitted, dev_eps, final_eps, lessons


@app.cell
def _(gates, math, mo, pairs):
    """Live PACE evidence — each gate's E climbing toward its threshold."""
    _pairs = {p["pair_id"]: p for p in pairs}
    blocks = []
    for g in gates:
        e = math.exp(min(g.get("log_e", 0.0), 700))
        thr = 1 / g.get("alpha", 0.05)
        dec = str(g.get("decision", "running")).lower()
        cls = "admit" if dec in {"admit", "accepted"} else ("reject" if dec in {"reject", "quarantine"} else "run")
        pct = max(2, min(100, (math.log(max(e, 1e-9)) - 0) / (math.log(thr) - 0) * 100)) if e > 0 else 2
        blocks.append(
            f'<div class="gate"><div class="hd"><span class="id">{g.get("trial_id","")[:18]}</span>'
            f'<span class="pill {cls}">{dec} · E {e:.2f}/{thr:.0f}</span></div>'
            f'<div class="bar {cls}"><i style="width:{pct:.0f}%"></i></div>'
            f'<div class="meta">W{g.get("wins",0)} · L{g.get("losses",0)} · T{g.get("ties",0)} · pairs {len(g.get("pair_ids",[]))}/{g.get("max_pairs",64)}</div></div>'
        )
    mo.vstack(
        [mo.Html('<div class="sec">Evidence crossing the threshold — live</div>')]
        + ([mo.Html("".join(blocks))] if blocks else [mo.Html('<div class="err">No gates yet.</div>')])
    )
    return


@app.cell
def _(dev_eps, mo):
    """The floor per round, from live attempt data."""
    rows = []
    for r in range(1, 4):
        recs = [a for a in dev_eps if a.get("round_id") == r]
        firsts = [a for a in recs if a.get("submission_index") in (None, 1)]
        succ = sum(1 for a in firsts if (a.get("result") or {}).get("success"))
        pct = (succ / len(firsts) * 100) if firsts else 0
        rows.append(
            f'<div class="gate"><div class="hd"><span class="id">Round {r}</span>'
            f'<span class="pill {"admit" if firsts else "run"}">{succ}/{len(firsts) if firsts else "—"} first-attempt</span></div>'
            f'<div class="bar {"admit" if firsts else "run"}"><i style="width:{pct:.0f}%"></i></div></div>'
        )
    mo.vstack(
        [mo.Html('<div class="sec">The floor rises — first-attempt success by round</div>')]
        + [mo.Html("".join(rows))]
    )
    return


@app.cell
def _(final_eps, mo, report):
    """Final four-arm accumulation."""
    arms = {}
    for a in final_eps:
        arm = a.get("arm", "unknown")
        arms.setdefault(arm, []).append(a)
    rows = []
    for arm in ("no_pool", "curated_docs", "raw_memory", "admitted_pool"):
        recs = arms.get(arm, [])
        succ = sum(1 for a in recs if (a.get("result") or {}).get("success"))
        pct = (succ / len(recs) * 100) if recs else 0
        rows.append(
            f'<div class="gate"><div class="hd"><span class="id">{arm}</span>'
            f'<span class="pill {"admit" if arm=="admitted_pool" else "run"}">{succ}/{len(recs) if recs else 0}</span></div>'
            f'<div class="bar {"admit" if arm=="admitted_pool" else "run"}"><i style="width:{pct:.0f}%"></i></div></div>'
        )
    mo.vstack(
        [mo.Html('<div class="sec">Does it travel — fresh workers, four arms (accumulating)</div>')]
        + [mo.Html("".join(rows))]
        + [mo.md('<span class="note">Arms fill as the final comparison runs. The admitted_pool bar is the vaccination story.</span>')]
    )
    return


@app.cell
def _(admitted, lessons, mo):
    """The pool as it grows."""
    rows = "".join(
        f'<div class="gate"><div class="hd"><span class="id">{l.get("lesson_id","")[:18]}</span>'
        f'<span class="pill admit">{l.get("status","")}</span></div>'
        f'<div class="meta">{(l.get("instruction") or l.get("trigger") or "")[:140]}</div></div>'
        for l in admitted[:8]
    )
    mo.vstack(
        [mo.Html(f'<div class="sec">The pool — {len(admitted)} admitted of {len(lessons)} proposed</div>')]
        + ([mo.Html(rows)] if admitted else [mo.Html('<div class="err">No admitted lessons yet — a lesson appears only after a gate admits it.</div>')])
    )
    return


if __name__ == "__main__":
    app.run()
