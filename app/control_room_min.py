# ruff: noqa: B018
"""HERD minimal demo view — five beats, one screen.

Same evidence API as control_room.py. Designed for the three-minute presentation:
floor (learners) → gate (PACE) → rounds (ascent) → travel (four-arm) → receipts (Weave/controls).
"""
import marimo

__generated_with = "0.23.0"
app = marimo.App(width="medium", app_title="HERD · The Ascent")


@app.cell
def _():
    import json
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
            auth=(
                httpx.BasicAuth(os.getenv("HERD_API_BASIC_USER", ""), os.getenv("HERD_API_BASIC_PASSWORD", ""))
                if os.getenv("HERD_API_BASIC_USER")
                else None
            ),
            timeout=timeout,
        )
        r.raise_for_status()
        return r.json()

    return fetch, json, math, mo, os, quote


@app.cell
def _(mo):
    mo.Html(
        """<style>
    :root{--ink:#101613;--mut:#5c665e;--line:#e4e6e0;--good:#2e6b46;--bad:#b4432c;--amber:#b5762a;--bg:#fbfbf9;}
    body{background:var(--bg)!important;color:var(--ink);font-family:-apple-system,'Helvetica Neue',Arial,sans-serif;}
    .hd{padding:34px 0 6px;border-bottom:1px solid var(--line);margin-bottom:8px;}
    .hd h1{font:600 clamp(30px,4.5vw,44px)/1.05 -apple-system,'Helvetica Neue',sans-serif;letter-spacing:-1.2px;margin:0;}
    .hd h1 em{font-style:normal;color:var(--good);}
    .hd p{color:var(--mut);font-size:15px;margin:8px 0 0;}
    .beat{display:flex;gap:14px;align-items:baseline;margin:26px 0 10px;}
    .beat .n{font:600 12px 'SF Mono',ui-monospace,monospace;color:#fff;background:var(--ink);border-radius:999px;padding:3px 9px;flex:none;}
    .beat h2{font-size:19px;font-weight:650;margin:0;letter-spacing:-.3px;}
    .beat .sub{color:var(--mut);font-size:13px;}
    .cards{display:grid;grid-template-columns:repeat(5,1fr);gap:10px;}
    .card{border:1px solid var(--line);border-radius:12px;padding:14px 12px;background:#fff;}
    .card .who{font:600 12px 'SF Mono',ui-monospace,monospace;color:var(--mut);}
    .card .st{display:inline-block;margin-top:8px;font:600 11px 'SF Mono',monospace;padding:3px 8px;border-radius:999px;}
    .ok .st{background:#e7f2ea;color:var(--good);}
    .bad .st{background:#fbeae5;color:var(--bad);}
    .wait .st{background:#eef0ec;color:var(--mut);}
    .card .task{font:11px 'SF Mono',monospace;color:var(--mut);margin-top:8px;overflow-wrap:anywhere;}
    .metric-row{display:flex;gap:26px;flex-wrap:wrap;margin:6px 0;}
    .big{font:650 34px/1 -apple-system,sans-serif;letter-spacing:-1px;}
    .lbl{font:11px 'SF Mono',monospace;color:var(--mut);text-transform:uppercase;letter-spacing:.6px;margin-top:6px;}
    .rounds{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;}
    .round{border:1px solid var(--line);border-radius:12px;padding:14px;background:#fff;}
    .round .rn{font:650 24px/1 -apple-system,sans-serif;}
    .round .rs{font:11px 'SF Mono',monospace;color:var(--mut);margin-top:6px;}
    .pill{display:inline-block;font:600 12px 'SF Mono',monospace;padding:4px 10px;border-radius:999px;}
    .pill.admit{background:#e7f2ea;color:var(--good);}
    .pill.reject,.pill.quarantine{background:#fbeae5;color:var(--bad);}
    .pill.pending{background:#fdf3e3;color:var(--amber);}
    .kv{font:12.5px 'SF Mono',monospace;color:var(--mut);}
    .note{color:var(--mut);font-size:12.5px;}
    .empty{border:1px dashed var(--line);border-radius:12px;padding:18px;color:var(--mut);font-size:13.5px;background:#fff;}
    @media(max-width:820px){.cards{grid-template-columns:repeat(2,1fr);}}
    </style>
    <div class="hd"><h1>One agent struggles.<br><em>Every agent learns.</em></h1>
    <p>Five learners · three rounds · a shared memory that has to earn its place.</p></div>"""
    )
    return


@app.cell
def _(fetch, mo):
    try:
        _exps = fetch("/api/experiments", timeout=5)
        _items = _exps.get("experiments", _exps) if isinstance(_exps, dict) else _exps
        experiments = _items if isinstance(_items, list) else []
        service_error = None
    except Exception as _e:  # noqa: BLE001 — surface as UI state, never crash the stage
        experiments = []
        service_error = f"Evidence service unavailable ({type(_e).__name__}). Run: herd serve"
    if service_error:
        mo.callout(service_error, kind="warn")
    else:
        mo.md("")
    return experiments, service_error


@app.cell
def _(experiments, mo):
    picker = mo.ui.dropdown(
        options={str(e["id"]): str(e["id"]) for e in experiments},
        value=str(experiments[0]["id"]) if experiments else None,
        label="Experiment",
    )
    picker
    return (picker,)


@app.cell
def _(fetch, picker, quote):
    detail, attempts, error = {}, [], None
    if picker.value:
        try:
            detail = fetch(f"/api/experiments/{quote(picker.value, safe='')}")
            attempts = fetch(f"/api/experiments/{quote(picker.value, safe='')}/attempts?offset=0&limit=500")["items"]
        except Exception as _e:  # noqa: BLE001
            error = f"Could not load experiment ({type(_e).__name__})."
    return attempts, detail, error


@app.cell
def _(attempts, detail, error, mo):
    """BEAT 1 — the floor: five learners, round-one reds."""
    ex = detail.get("experiment", {})
    _cards = []
    for i in range(1, 6):
        ident = f"learner-{i}"
        _recs = [a for a in attempts if a.get("learner_id") == ident]
        _last = _recs[-1] if _recs else {}
        _status = (_last.get("status") or "awaiting").lower()
        _succ = (_last.get("result") or {}).get("success")
        _tone = "ok" if _succ is True else ("bad" if _succ is False else "wait")
        _label = "passed" if _succ is True else ("failed" if _succ is False else _status)
        _task = _last.get("task_id", "—")
        _cards.append(
            f'<div class="card {_tone}"><div class="who">{ident}</div>'
            f'<span class="st">{_label}</span><div class="task">{_task}</div></div>'
        )
    mo.vstack(
        [
            mo.callout(error, kind="danger") if error else mo.md(""),
            mo.Html(
                f'<div class="beat"><span class="n">1</span><h2>The floor</h2>'
                f'<span class="sub">five learners · status <b>{ex.get("status", "—")}</b> · round {ex.get("round_id", "—")}</span></div>'
            ),
            mo.Html('<div class="cards">' + "".join(_cards) + "</div>"),
            mo.md('<span class="note">Each learner begins alone. Watch where the next round starts.</span>'),
        ]
    )
    return


@app.cell
def _(detail, math, mo):
    """BEAT 2 — the gate: evidence must cross the line."""
    gates = detail.get("gates", [])
    _rows = []
    for g in gates[:6]:
        _e = math.exp(min(g.get("log_e", 0.0), 700))
        _thr = 1 / g.get("alpha", 0.05)
        _dec = g.get("decision", "pending").lower()
        _cls = "admit" if _dec in {"admit", "accepted", "accept"} else ("reject" if _dec in {"reject", "rejected", "quarantine"} else "pending")
        _rows.append(
            f'<div class="round"><span class="pill {_cls}">{_dec}</span>'
            f'<div class="rn" style="margin-top:8px">E {_e:.2f}<span style="font-size:13px;color:var(--mut)"> / {_thr:.0f}</span></div>'
            f'<div class="rs">W{g.get("wins",0)} · L{g.get("losses",0)} · T{g.get("ties",0)} · controls {g.get("controls_passed","—")}</div></div>'
        )
    _body = (
        mo.Html('<div class="rounds">' + "".join(_rows) + "</div>")
        if _rows
        else mo.Html('<div class="empty">No admission gates yet — a lesson appears here only after a recorded repair.</div>')
    )
    mo.vstack(
        [
            mo.Html(
                '<div class="beat"><span class="n">2</span><h2>The gate</h2>'
                '<span class="sub">a lesson joins the pool only when evidence crosses the threshold</span></div>'
            ),
            _body,
            mo.md('<span class="note">Sequential test (α = 0.05). Peek all you want — false admissions stay bounded. Greedy loops commit 30–42% false improvements; this one commits ≈0.</span>'),
        ]
    )
    return


@app.cell
def _(attempts, detail, mo):
    """BEAT 3 — the ascent: the floor rises across rounds."""
    lessons = detail.get("lessons", [])
    _blocks = []
    for r in range(1, 4):
        _recs = [a for a in attempts if a.get("round_id") == r]
        _firsts = [a for a in _recs if a.get("submission_index") in (None, 1)]
        _succ = sum(1 for a in _firsts if (a.get("result") or {}).get("success"))
        _rate = f"{_succ}/{len(_firsts)}" if _firsts else "—"
        _props = len([l for l in lessons if l.get("origin_round") == r])
        _blocks.append(
            f'<div class="round"><div class="rn">R{r}</div>'
            f'<div class="rs">first-attempt success <b>{_rate}</b></div>'
            f'<div class="rs">{len(_recs)} attempts · {_props} lessons proposed</div></div>'
        )
    mo.vstack(
        [
            mo.Html(
                '<div class="beat"><span class="n">3</span><h2>The ascent</h2>'
                '<span class="sub">each round starts where the last round\'s best ended</span></div>'
            ),
            mo.Html('<div class="rounds">' + "".join(_blocks) + "</div>"),
            mo.md('<span class="note">Harder tasks, deeper lessons. Not sharing — ascent.</span>'),
        ]
    )
    return lessons


@app.cell
def _(fetch, lessons, mo, picker, quote):
    """BEAT 4 — does it travel: fresh workers, four arms (loaded on demand)."""
    btn = mo.ui.run_button(label="Load final comparison")
    mo.vstack(
        [
            mo.Html(
                '<div class="beat"><span class="n">4</span><h2>Does it travel?</h2>'
                f'<span class="sub">{len(lessons)} admitted lessons · fresh workers, four arms</span></div>'
            ),
            btn,
        ]
    )
    return (btn,)


@app.cell
def _(btn, fetch, mo, picker, quote):
    _rows2, _note = [], None
    if picker.value and btn.value:
        try:
            _rep = fetch(f"/api/experiments/{quote(picker.value, safe='')}/report", timeout=20)
            for arm, m in _rep.get("arms", {}).items():
                _rows2.append({"arm": arm, **{k: v for k, v in m.items() if not isinstance(v, (dict, list))}})
            if _rep.get("limitations"):
                _note = " · ".join(_rep["limitations"][:2])
        except Exception:  # noqa: BLE001
            _note = None
    if _rows2:
        _out = mo.ui.table(_rows2, selection=None)
    else:
        _out = mo.Html('<div class="empty">Final comparison not measured yet — no_pool / curated_docs / raw_memory / admitted_pool.</div>')
    mo.vstack([_out, mo.md(f'<span class="note">{_note}</span>') if _note else mo.md("")])
    return


@app.cell
def _(detail, mo):
    """BEAT 5 — receipts: negative controls + Weave links."""
    _nc = detail.get("negative_controls", [])
    _wl = detail.get("weave_links", [])
    _rejected = [c for c in _nc if c.get("rejected") or c.get("decision") in {"reject", "quarantine"}]
    _pills = "".join(
        f'<span class="pill reject">false lesson rejected</span> ' for _ in (_rejected[:4] or [])
    ) or '<span class="pill pending">controls pending</span>'
    _links = "".join(
        f'<div class="kv">↗ {w.get("label") or w.get("url") or w}</div>' for w in _wl[:4]
    )
    mo.vstack(
        [
            mo.Html(
                '<div class="beat"><span class="n">5</span><h2>Receipts</h2>'
                '<span class="sub">the loop defends itself — and the evidence is public</span></div>'
            ),
            mo.Html(f"<div>{_pills}</div>"),
            mo.Html(f'<div style="margin-top:8px">{_links}</div>') if _links else mo.md('<span class="note">Weave: wandb.ai/yahya-dojo-hacks/dojo/weave</span>'),
        ]
    )
    return


if __name__ == "__main__":
    app.run()
