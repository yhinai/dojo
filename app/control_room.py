# ruff: noqa: B018, PLR1711
import marimo

__generated_with = '0.23.0'
app = marimo.App(width='full', app_title='HERD · Collective learning')


@app.cell
def _():
    import difflib
    import html
    import json
    import math
    import os
    from herd.config import load_environment as _load_environment
    _load_environment()
    from urllib.parse import quote

    import httpx
    import marimo as mo
    return difflib, html, httpx, json, math, mo, os, quote


@app.cell
def _(mo, os):
    api_url = os.getenv("HERD_API_URL", "http://127.0.0.1:8000").rstrip("/")
    demo_mode = os.getenv("HERD_DEMO_MODE", "1").lower() not in {"0", "false", "no"}
    refresh = mo.ui.refresh(options=[5, 15, 30], default_interval=15, label="Refresh evidence")
    mo.Html("""<style>
    :root {--herd-ink:#18231c;--herd-paper:#f5f3eb;--herd-accent:#cf702d;}
    body {background:var(--herd-paper)!important;}
    .herd-header {border-top:5px solid var(--herd-ink);padding:28px 0 22px;margin-bottom:16px;color:var(--herd-ink);}
    .herd-kicker {font:11px 'Courier New',monospace;letter-spacing:3px;text-transform:uppercase;color:#777e70;}
    .herd-title {font:700 clamp(55px,8vw,100px)/.95 Georgia,serif;letter-spacing:-6px;margin:16px 0;}
    .herd-title em {font-weight:400;color:var(--herd-accent);}
    .herd-deck {font:19px/1.6 Georgia,serif;max-width:650px;}
    .herd-population {display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:12px;margin:20px 0;}
    .herd-card {padding:20px 16px;min-height:160px;background:#fffdf6;border:1px solid #dcded2;border-top:3px solid #788e70;}
    .herd-card h3 {font:26px Georgia,serif;margin:13px 0;}
    .herd-card p {font:12px/1.7 'Courier New',monospace;overflow-wrap:anywhere;}
    .herd-status {font:10px 'Courier New',monospace;text-transform:uppercase;letter-spacing:1px;color:#7a4925;}
    .herd-rounds {display:grid;grid-template-columns:repeat(3,1fr);gap:18px;margin-bottom:24px;}
    .herd-round {padding:18px;border-bottom:2px solid #b8c3ad;}
    .herd-round strong {font:25px Georgia,serif;}
    .herd-round p {font:12px 'Courier New',monospace;}
    .herd-empty {padding:24px;border:1px dashed #b9beaf;background:#eeefe6;font:15px/1.6 Georgia,serif;color:#515b4c;}
    .herd-section {font:32px Georgia,serif;color:#18231c;margin:24px 0 8px;}
    .herd-warning {padding:12px;background:#fff0d8;border-left:3px solid #c87930;}
    @media(max-width:900px){.herd-population{grid-template-columns:repeat(2,1fr)}.herd-title{letter-spacing:-3px}}
    </style><header class="herd-header"><div class="herd-kicker">Collective tool learning / Research control room</div>
    <div class="herd-title">One struggles.<br><em>Every agent learns.</em></div>
    <p class="herd-deck">Five learners. Three rounds. A shared memory that has to earn its place.</p></header>""")
    return api_url, demo_mode, refresh


@app.cell
def _(api_url, httpx, os, refresh):
    refresh.value
    try:
        _response = httpx.get(f"{api_url}/api/experiments", headers={"X-Herd-Token": os.getenv("HERD_CONTROL_TOKEN", "")}, auth=httpx.BasicAuth(os.getenv("HERD_API_BASIC_USER", ""), os.getenv("HERD_API_BASIC_PASSWORD", "")) if os.getenv("HERD_API_BASIC_USER") else None, timeout=5)
        _response.raise_for_status()
        _data = _response.json()
        experiments = _data.get("experiments", []) if isinstance(_data, dict) else _data
        service_error = None
    except (httpx.HTTPError, ValueError) as _exc:
        experiments = []
        service_error = f"Evidence service unavailable ({type(_exc).__name__}). Start herd serve to connect."
    return experiments, service_error


@app.cell
def _(demo_mode, experiments, mo, refresh, service_error):
    experiment_picker = mo.ui.dropdown(options={str(e["id"]): str(e["id"]) for e in experiments},
                                        label="Experiment")
    mo.vstack([mo.hstack([experiment_picker, refresh], justify="space-between"),
               mo.md("**Read-only demo · recorded evidence**" if demo_mode else "**Operator mode · explicit actions only**"),
               mo.callout(service_error, kind="warn") if service_error else mo.md("")])
    return (experiment_picker,)


@app.cell
def _(api_url, experiment_picker, httpx, os, quote, refresh):
    refresh.value
    selected_id = experiment_picker.value
    detail = {}
    detail_error = None
    if selected_id:
        try:
            _response = httpx.get(f"{api_url}/api/experiments/{quote(selected_id, safe='')}", headers={"X-Herd-Token": os.getenv("HERD_CONTROL_TOKEN", "")}, auth=httpx.BasicAuth(os.getenv("HERD_API_BASIC_USER", ""), os.getenv("HERD_API_BASIC_PASSWORD", "")) if os.getenv("HERD_API_BASIC_USER") else None, timeout=10)
            _response.raise_for_status()
            detail = _response.json()
        except (httpx.HTTPError, ValueError) as _exc:
            detail_error = f"Unable to load experiment ({type(_exc).__name__}). No prior state is presented as current."
    return detail, detail_error, selected_id


@app.cell
def _(detail, detail_error, html, mo):
    attempts = detail.get("attempts", [])
    lessons = detail.get("lessons", [])
    gates = detail.get("gates", [])
    events = detail.get("events", [])
    experiment = detail.get("experiment", {})
    _cards = []
    _known_ids = [f"learner-{i}" for i in range(1, 6)]
    for _index in range(5):
        _identity = _known_ids[_index] if _index < len(_known_ids) else f"learner-{_index + 1}"
        _records = [a for a in attempts if a.get("learner_id") == _identity]
        _last = _records[-1] if _records else {}
        _costs = [a.get("cost_usd") for a in _records]
        _cost = f"${sum(c for c in _costs if c is not None):.4f}" if _costs and all(c is not None for c in _costs) else "cost unavailable"
        _cards.append(f'<article class="herd-card"><span class="herd-status">{html.escape(_last.get("status", "Awaiting evidence"))}</span>'
                      f'<h3>{html.escape(_identity)}</h3><p>{html.escape(_last.get("task_id", "No task recorded"))}<br>'
                      f'Pool {html.escape(_last.get("pool_hash", "—")[:12])}<br>{_cost}</p></article>')
    _rounds = []
    for _round in range(1, 4):
        _round_records = [a for a in attempts if a.get("round_id") == _round]
        _proposals = [l for l in lessons if l.get("origin_round") == _round]
        _rounds.append(f'<div class="herd-round"><strong>0{_round} / Round {_round}</strong><p>{len(_round_records)} recorded attempts · '
                       f'{len(_proposals)} lesson proposals</p></div>')
    mo.vstack([mo.callout(detail_error, kind="danger") if detail_error else mo.md(""),
               mo.md(f"Experiment **{experiment.get('id', 'none selected')}** · Status **{experiment.get('status', 'not started')}**"),
               mo.Html('<div class="herd-population">' + ''.join(_cards) + '</div><div class="herd-rounds">' + ''.join(_rounds) + '</div>'),
               mo.Html('<div class="herd-warning"><strong>Fixture data</strong> — engineering validation, not measured agent learning.</div>')
               if experiment.get('mode', 'measured') != 'measured' or any(a.get("mode") != "measured" for a in attempts) else mo.md("")])
    return attempts, events, experiment, gates, lessons


@app.cell
def _(gates, lessons, mo):
    lesson_picker = mo.ui.dropdown(options={f"{l['lesson_id']} / {l.get('status', 'unknown')}": l['lesson_id'] for l in lessons}, label="Inspect lesson")
    gate_picker = mo.ui.dropdown(options={g['trial_id']: g['trial_id'] for g in gates}, label="Inspect admission stream")
    mo.vstack([mo.Html('<h2 class="herd-section">Memory, with receipts.</h2>'),
               mo.ui.table([{k: l.get(k) for k in ('lesson_id', 'status', 'origin_learner_id', 'scope_tags', 'paired_helpful', 'paired_harmful', 'decision_reason')} for l in lessons], selection=None)
               if lessons else mo.Html('<div class="herd-empty">The pool is empty. A lesson appears only after a recorded repair and a gate decision. An empty pool is a valid outcome.</div>'),
               mo.hstack([lesson_picker, gate_picker])])
    return gate_picker, lesson_picker


@app.cell
def _(gate_picker, gates, json, lesson_picker, lessons, math, mo):
    _lesson = next((l for l in lessons if l['lesson_id'] == lesson_picker.value), None)
    _gate = next((g for g in gates if g['trial_id'] == gate_picker.value), None)
    _panels = []
    if _lesson:
        _panels += [mo.md(f"**Trigger:** {_lesson['trigger']}"), mo.md(_lesson['instruction']),
                    mo.md(f"**Does not apply:** {_lesson['does_not_apply']}"),
                    mo.accordion({"Provenance, conflicts, and immutable lesson record": mo.ui.code_editor(value=json.dumps(_lesson, indent=2), language="json", disabled=True)})]
    if _gate:
        _threshold = 1 / _gate['alpha']
        _e = math.exp(min(_gate['log_e'], 700))
        _panels += [mo.md(f"**{_gate['decision']}** · E = **{_e:.3f}** / registered threshold **{_threshold:.1f}**"),
                    mo.md(f"Wins {_gate['wins']} · Losses {_gate['losses']} · Ties {_gate['ties']} · Invalid {_gate['invalid']} · "
                          f"Remaining {max(0, _gate['max_pairs'] - len(_gate['pair_ids']))}"),
                    mo.md(f"Controls: **{_gate.get('controls_passed')}** · {_gate.get('reason', '')}"),
                    mo.accordion({"Immutable stream binding": mo.ui.code_editor(value=json.dumps(_gate['binding'], indent=2), language="json", disabled=True)})]
    mo.vstack(_panels or [mo.md("Select a lesson or gate to inspect the evidence. No admission evidence recorded yet.")])
    return


@app.cell
def _(mo):
    replay_threshold = mo.ui.slider(start=2, stop=400, step=1, value=20, label="Exploratory evidence threshold")
    return (replay_threshold,)


@app.cell
def _(detail, gate_picker, gates, math, mo, replay_threshold):
    _gate = next((g for g in gates if g['trial_id'] == gate_picker.value), None)
    _pairs = {p['pair_id']: p for p in detail.get('pairs', [])}
    _chart = mo.md('Select an admission stream to replay recorded evidence.')
    if _gate:
        _values = [0.0]
        _missing = False
        for _pair_id in _gate['pair_ids']:
            _pair = _pairs.get(_pair_id)
            if not _pair:
                _missing = True
                break
            _delta = 0.0
            if _pair.get('valid', True) and _pair['treatment_success'] != _pair['control_success']:
                _delta = math.log1p(_gate['bet'] if _pair['treatment_success'] else -_gate['bet'])
            _values.append(_values[-1] + _delta)
        if _missing:
            _chart = mo.md('Pair-level records unavailable; an evidence trajectory cannot be reconstructed.')
        else:
            _threshold_log = math.log(replay_threshold.value)
            _lo = min(-.1, min(_values))
            _hi = max(max(_values), _threshold_log) + .3
            _points = ' '.join(f'{20 + i * 720 / max(1, len(_values)-1):.1f},{190 - (v-_lo)/(_hi-_lo)*160:.1f}' for i,v in enumerate(_values))
            _line_y = 190 - (_threshold_log-_lo)/(_hi-_lo)*160
            _cross = next((i for i,v in enumerate(_values) if v >= _threshold_log), None)
            _chart = mo.vstack([mo.Html(f'<svg viewBox="0 0 760 220" role="img" aria-label="Recorded log evidence across admission pairs"><line x1="20" x2="740" y1="{_line_y}" y2="{_line_y}" stroke="#cf702d" stroke-dasharray="6 4"/><polyline points="{_points}" fill="none" stroke="#294b36" stroke-width="3"/><text x="20" y="215" fill="#555">Recorded pair order → (log evidence)</text></svg>'),
                                mo.md(f'Exploratory threshold crossing: **{_cross if _cross is not None else "not reached"}**. Controls still apply. Registered decision: **{_gate["decision"]}**.')])
    mo.vstack([replay_threshold, mo.md('**Exploratory replay only.** This changes a display threshold, not registered alpha, the pool, or the learning history.'), _chart])
    return


@app.cell
def _(attempts, mo):
    attempt_picker = mo.ui.dropdown(options={a['run_id']: a['run_id'] for a in attempts}, label="Notebook attempt")
    mo.vstack([mo.Html('<h2 class="herd-section">Inspect the work.</h2>'), attempt_picker])
    return (attempt_picker,)


@app.cell
def _(attempt_picker, attempts, difflib, json, mo):
    _attempt = next((a for a in attempts if a['run_id'] == attempt_picker.value), None)
    if _attempt:
        _before = _attempt.get('initial_source', '')
        _after = _attempt.get('source', '')
        _diff = ''.join(difflib.unified_diff(_before.splitlines(True), _after.splitlines(True), fromfile='first submission', tofile='latest submission'))
        _notebook_panel = mo.vstack([mo.hstack([mo.ui.code_editor(value=_before, language='python', disabled=True),
                             mo.ui.code_editor(value=_after, language='python', disabled=True)], widths='equal'),
                   mo.accordion({'Repair diff': mo.ui.code_editor(value=_diff or 'No source change recorded.', disabled=True),
                                 'Behavior and interaction evidence': mo.ui.code_editor(value=json.dumps(_attempt.get('result'), indent=2), language='json', disabled=True)}),
                   mo.md('Candidate source is displayed as text. It never executes inside this control room.')])
    else:
        _notebook_panel = mo.Html('<div class="herd-empty">No notebook attempts recorded. The source comparison and actual behavioral evidence will appear here.</div>')
    _notebook_panel
    return


@app.cell
def _(detail, mo):
    _report = detail.get('report')
    _rows = []
    if _report:
        for _arm, _metrics in _report.get('arms', {}).items():
            _rows.append({'arm': _arm, **{k: v for k, v in _metrics.items() if not isinstance(v, (dict, list))}})
    mo.vstack([mo.Html('<h2 class="herd-section">Does the lesson travel?</h2>'),
               mo.md('Fresh workers · no pool / curated docs / raw memory / admitted pool'),
               mo.ui.table(_rows, selection=None) if _rows else mo.Html('<div class="herd-empty">No final comparison yet. Success rates, family-clustered intervals, and costs remain unmeasured.</div>'),
               mo.ui.table([{k: v for k, v in value.items() if k != 'paired_outcomes'} | {'comparison': key} for key, value in _report.get('comparisons', {}).items()], selection=None) if _report else mo.md(''),
               mo.md('\n'.join('- ' + note for note in _report.get('limitations', []))) if _report else mo.md('')])
    return


@app.cell
def _(events, json, mo):
    _negative = [e for e in events if any(term in e.get('event_type', '') for term in ('poison', 'control', 'reject', 'retract'))]
    _aria = [e for e in events if 'aria' in e.get('event_type', '')]
    _weave = [e for e in events if 'weave' in e.get('event_type', '')]
    mo.accordion({
        'Negative controls & rejected advice': mo.ui.table(_negative, selection=None) if _negative else mo.md('No negative-control results recorded. No rejection is implied.'),
        'ARIA · development analysis': mo.ui.code_editor(value=json.dumps(_aria, indent=2), language='json', disabled=True) if _aria else mo.md('ARIA analysis not attached. Export a development bundle and import the authentic W&B report with its resulting curriculum action.'),
        'Weave · remote evidence': mo.ui.table(_weave, selection=None) if _weave else mo.md('No remote upload acknowledgement recorded. Local evidence is authoritative; remote integration remains unverified.'),
        'Append-only event trail': mo.ui.table(events, selection=None) if events else mo.md('No events recorded.')})
    return


@app.cell
def _(demo_mode, mo):
    control_action = mo.ui.dropdown(options=['resume', 'pause', 'cancel'], value='resume', label='Run action')
    action_button = mo.ui.run_button(label='Apply run action', disabled=demo_mode)
    lifecycle_action = mo.ui.dropdown(options=['retract', 'rollback', 'supersede', 'resolve_conflict'], value='retract', label='Pool action')
    lifecycle_lessons = mo.ui.text(label='Affected lesson IDs (comma separated)')
    lifecycle_target = mo.ui.text(label='Target pool hash / replacement lesson ID')
    lifecycle_reason = mo.ui.text_area(label='Evidence and reason for pool change')
    lifecycle_button = mo.ui.run_button(label='Queue pool change', disabled=demo_mode)
    curriculum_report = mo.ui.text(label='Imported ARIA report ID')
    curriculum_weights = mo.ui.text(value='{"0":1,"1":1,"2":1,"3":1,"4":1}', label='Track weights (JSON)')
    curriculum_reason = mo.ui.text_area(label='Development curriculum reason')
    curriculum_button = mo.ui.run_button(label='Queue curriculum change', disabled=demo_mode)
    mo.vstack([mo.Html('<h2 class="herd-section">Operator desk.</h2>'),
        mo.md('Commands are durable. Pause and cancel stop at the next safe checkpoint. Cancellation is terminal.'),
        mo.hstack([control_action, action_button]),
        mo.accordion({'Pool lifecycle': mo.vstack([lifecycle_action, lifecycle_lessons, lifecycle_target, lifecycle_reason, lifecycle_button]),
                      'Development curriculum': mo.vstack([curriculum_report, curriculum_weights, curriculum_reason, curriculum_button])}),
        mo.md('Controls are disabled in read-only demo mode.' if demo_mode else 'Pool and curriculum changes are audited and applied at eligible boundaries; final evaluation remains frozen.')])
    return (action_button, control_action, curriculum_button, curriculum_reason, curriculum_report,
            curriculum_weights, lifecycle_action, lifecycle_button, lifecycle_lessons, lifecycle_reason, lifecycle_target)


@app.cell
def _(action_button, api_url, control_action, curriculum_button, curriculum_reason,
      curriculum_report, curriculum_weights, demo_mode, httpx, json, lifecycle_action,
      lifecycle_button, lifecycle_lessons, lifecycle_reason, lifecycle_target, mo, os, quote, selected_id):
    _action_panel = mo.md('')
    if not demo_mode and selected_id and (action_button.value or lifecycle_button.value or curriculum_button.value):
        _headers = {'X-Herd-Token': os.getenv('HERD_CONTROL_TOKEN', '')}
        try:
            _body = None
            _endpoint = control_action.value
            if lifecycle_button.value:
                _endpoint = 'lifecycle'
                _body = {'action': lifecycle_action.value, 'reason': lifecycle_reason.value,
                         'lesson_ids': [v.strip() for v in lifecycle_lessons.value.split(',') if v.strip()],
                         'target_pool_hash': lifecycle_target.value or None if lifecycle_action.value == 'rollback' else None,
                         'replacement_id': lifecycle_target.value or None if lifecycle_action.value == 'supersede' else None}
            elif curriculum_button.value:
                _endpoint = 'curriculum'
                _body = {'report_id': curriculum_report.value, 'track_weights': json.loads(curriculum_weights.value), 'reason': curriculum_reason.value}
            _action = httpx.post(f"{api_url}/api/experiments/{quote(selected_id, safe='')}/{_endpoint}", headers=_headers, auth=httpx.BasicAuth(os.getenv("HERD_API_BASIC_USER", ""), os.getenv("HERD_API_BASIC_PASSWORD", "")) if os.getenv("HERD_API_BASIC_USER") else None, json=_body, timeout=15)
            if _action.is_success:
                _action_panel = mo.callout(f'Action recorded for {selected_id}. Refresh to inspect status.', kind='success')
            else:
                _action_panel = mo.callout(f'Action rejected: {_action.json().get("detail", _action.status_code)}', kind='warn')
        except (httpx.HTTPError, ValueError) as _exc:
            _action_panel = mo.callout(f'Action unavailable ({type(_exc).__name__}). Inspect evidence before retrying.', kind='danger')
    _action_panel
    return


@app.cell
def _(detail, json, mo):
    mo.accordion({'Pending control and lifecycle decisions': mo.ui.code_editor(value=json.dumps({key: detail.get(key) for key in ('control', 'lifecycle_requests', 'curriculum_decisions')}, indent=2), language='json', disabled=True),
                  'Deliberately false lessons · separate diagnostic evidence': mo.ui.code_editor(value=json.dumps({'controls': detail.get('negative_controls', []), 'gates': detail.get('control_gates', [])}, indent=2), language='json', disabled=True),
                  'Draft review records': mo.ui.table(detail.get('draft_reviews', []), selection=None) if detail.get('draft_reviews') else mo.md('No draft reviews recorded.'),
                  'Published evidence links': mo.ui.table(detail.get('weave_links', []), selection=None) if detail.get('weave_links') else mo.md('No remote publication acknowledged.')})
    return


if __name__ == '__main__':
    app.run()
