"""
pipeline_ui.py — Local web UI for PT Research Pipeline v2
Run with: python3 pipeline_ui.py
Then open: http://localhost:5050
"""

import json
import os
import re
import subprocess
import sys
import threading
import time
import yaml
from datetime import datetime
from pathlib import Path
from flask import Flask, Response, jsonify, render_template_string, request

PIPELINE_ROOT = Path(__file__).parent.resolve()
app = Flask(__name__)

# ── State ──────────────────────────────────────────────────────────────────────
_process   = None
_log_lines = []
_log_lock  = threading.Lock()
_start_times = {}   # phase -> start timestamp
_phase_done  = {}   # phase -> end timestamp

PHASES = [
    {"id": "ingest",   "label": "Ingest",           "script": "run_ingest.py",          "est_min": 5},
    {"id": "layer0",   "label": "Layer 0 Screen",   "script": "run_layer0.py",          "est_min": 90},
    {"id": "layer2",   "label": "Layer 2 Appraise", "script": "run_layer2.py",          "est_min": 360},
    {"id": "backfill", "label": "Backfill",          "script": "run_backfill.py",        "est_min": 2},
    {"id": "cluster",  "label": "Cluster",           "script": "run_layer3_cluster.py",  "est_min": 15},
    {"id": "grade",    "label": "GRADE Synthesis",   "script": "run_layer3_grade.py",    "est_min": 45},
    {"id": "export",   "label": "Export",            "script": "run_export.py",          "est_min": 1},
    {"id": "report",   "label": "Report",            "script": "run_report.py",          "est_min": 1},
]

PHASE_MARKERS = {
    "ingest":   ["Ingest complete"],
    "layer0":   ["Layer 0 ledger saved", "Complete:"],
    "layer2":   ["Layer 2 complete"],
    "backfill": ["Metadata backfill complete"],
    "cluster":  ["Clustering complete"],
    "grade":    ["FINAL GRADE SUMMARY"],
    "export":   ["Export complete"],
    "report":   ["Report written"],
}

PHASE_START_MARKERS = {
    "ingest":   ["PT Research Pipeline v2 — Ingest"],
    "layer0":   ["Layer 0 targets"],
    "layer2":   ["Layer 2 targets"],
    "backfill": ["Articles needing metadata backfill"],
    "cluster":  ["Running dynamic clustering"],
    "grade":    ["Running GRADE synthesis"],
    "export":   ["PT Research Pipeline v2 — Export"],
    "report":   ["PT Research Pipeline v2 — Report"],
}


def _detect_phase(line: str):
    for phase_id, markers in PHASE_START_MARKERS.items():
        for m in markers:
            if m in line and phase_id not in _start_times:
                _start_times[phase_id] = time.time()
    for phase_id, markers in PHASE_MARKERS.items():
        for m in markers:
            if m in line and phase_id not in _phase_done:
                _phase_done[phase_id] = time.time()


def _stream_process(proc):
    global _process
    try:
        for raw in proc.stdout:
            line = raw.rstrip()
            _detect_phase(line)
            with _log_lock:
                _log_lines.append({"t": datetime.now().strftime("%H:%M:%S"), "msg": line})
                if len(_log_lines) > 2000:
                    _log_lines.pop(0)
    finally:
        proc.wait()
        _process = None


def get_pipeline_status():
    """Read filesystem to determine current state."""
    root = PIPELINE_ROOT
    status = {
        "ledger_rows":      0,
        "full_text_count":  0,
        "layer0_count":     0,
        "layer0_relevant":  0,
        "layer2_count":     0,
        "cluster_count":    0,
        "grade_done":       False,
        "export_exists":    False,
        "report_exists":    False,
        "active_phase":     None,
    }
    try:
        ledger = root / "ledger.csv"
        if ledger.exists():
            lines = ledger.read_text().splitlines()
            status["ledger_rows"] = max(0, len(lines) - 1)

        cache = root / "cache" / "full_text"
        if cache.exists():
            status["full_text_count"] = len(list(cache.glob("*.txt")))

        l0 = root / "layer0_ledger.csv"
        if l0.exists():
            rows = l0.read_text().splitlines()
            status["layer0_count"] = max(0, len(rows) - 1)
            status["layer0_relevant"] = sum(
                1 for r in rows[1:] if "yes" in r.lower().split(",")[5:8]
            ) if len(rows) > 1 else 0

        deep = root / "summaries" / "deep"
        if deep.exists():
            status["layer2_count"] = len(list(deep.glob("*_layer2.json")))

        cl = root / "layer3_clusters.json"
        if cl.exists():
            clusters = json.loads(cl.read_text())
            from collections import Counter
            dist = Counter(a["cluster"] for a in clusters)
            status["cluster_count"] = len([k for k in dist if k != "general_cross_cutting"])

        master = root / "summaries" / "layer3" / "MASTER_GRADE_SYNTHESIS.json"
        if master.exists():
            status["grade_done"] = True

        xlsx = list(root.glob("*.xlsx"))
        if xlsx:
            status["export_exists"] = True
            status["export_file"] = xlsx[0].name

        md = list(root.glob("*_synthesis_report_*.md"))
        if md:
            status["report_exists"] = True
            status["report_file"] = md[0].name

    except Exception as e:
        status["error"] = str(e)

    return status


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    cfg = {}
    try:
        cfg = yaml.safe_load((PIPELINE_ROOT / "config.yaml").read_text()) or {}
    except Exception:
        pass
    return render_template_string(HTML_TEMPLATE, cfg=cfg, phases=PHASES)


@app.route("/api/config", methods=["GET", "POST"])
def api_config():
    cfg_path = PIPELINE_ROOT / "config.yaml"
    if request.method == "POST":
        data = request.json
        try:
            cfg = yaml.safe_load(cfg_path.read_text()) if cfg_path.exists() else {}
            cfg["research_question"] = data.get("research_question", "")
            topic = cfg.get("topic", {})
            topic["short_name"]         = data.get("short_name", "")
            topic["relevance_criterion"] = data.get("relevance_criterion", "")
            topic["intervention_noun"]   = data.get("intervention_noun", "")
            topic["governance_focus"]    = data.get("governance_focus", "")
            cfg["topic"] = topic
            feeds = []
            for i, f in enumerate(data.get("feeds", [])):
                if f.get("url","").strip():
                    feeds.append({
                        "url":         f["url"].strip(),
                        "name":        f.get("name", f"feed_{chr(97+i)}"),
                        "description": f.get("description",""),
                    })
            cfg["feeds"] = feeds
            cfg_path.write_text(yaml.dump(cfg, allow_unicode=True, default_flow_style=False))
            return jsonify({"ok": True})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 400
    else:
        try:
            cfg = yaml.safe_load(cfg_path.read_text()) if cfg_path.exists() else {}
            return jsonify(cfg)
        except Exception as e:
            return jsonify({"error": str(e)}), 400


@app.route("/api/ollama/chat", methods=["POST"])
def api_ollama_chat():
    """Proxy Ollama /api/chat server-side — buffered, non-streaming."""
    import urllib.request
    try:
        data = request.get_json(force=True)
        data["stream"] = False  # force non-streaming regardless of client request
        req = urllib.request.Request(
            "http://localhost:11434/api/chat",
            data=json.dumps(data).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = resp.read().decode("utf-8")
        return body, 200, {"Content-Type": "application/json"}
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/run/<script>", methods=["POST"])
def api_run(script):
    global _process, _log_lines, _start_times, _phase_done
    allowed = {p["script"] for p in PHASES}
    if script not in allowed:
        return jsonify({"ok": False, "error": "unknown script"}), 400
    if _process and _process.poll() is None:
        return jsonify({"ok": False, "error": "pipeline already running"}), 409
    _log_lines  = []
    venv_python = PIPELINE_ROOT / "venv" / "bin" / "python3"
    python      = str(venv_python) if venv_python.exists() else sys.executable
    cmd = [python, script]
    if script in ("run_layer0.py", "run_ingest.py"):
        cmd.append("--all")
    _process = subprocess.Popen(
        cmd, cwd=str(PIPELINE_ROOT), stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, bufsize=1
    )
    t = threading.Thread(target=_stream_process, args=(_process,), daemon=True)
    t.start()
    return jsonify({"ok": True, "pid": _process.pid})


@app.route("/api/run/all", methods=["POST"])
def api_run_all():
    global _process, _log_lines, _start_times, _phase_done
    if _process and _process.poll() is None:
        return jsonify({"ok": False, "error": "pipeline already running"}), 409
    _log_lines   = []
    _start_times = {}
    _phase_done  = {}
    venv_python  = PIPELINE_ROOT / "venv" / "bin" / "python3"
    python       = str(venv_python) if venv_python.exists() else sys.executable

    scripts = [p["script"] for p in PHASES]

    def run_sequence():
        global _process
        for script in scripts:
            cmd = [python, script]
            if script in ("run_layer0.py", "run_ingest.py"):
                cmd.append("--all")
            with _log_lock:
                _log_lines.append({
                    "t": datetime.now().strftime("%H:%M:%S"),
                    "msg": f"━━━ Starting {script} ━━━"
                })
            _process = subprocess.Popen(
                cmd, cwd=str(PIPELINE_ROOT), stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, bufsize=1
            )
            for raw in _process.stdout:
                line = raw.rstrip()
                _detect_phase(line)
                with _log_lock:
                    _log_lines.append({"t": datetime.now().strftime("%H:%M:%S"), "msg": line})
                    if len(_log_lines) > 2000:
                        _log_lines.pop(0)
            _process.wait()
            if _process.returncode != 0:
                with _log_lock:
                    _log_lines.append({
                        "t": datetime.now().strftime("%H:%M:%S"),
                        "msg": f"✗ {script} failed (exit {_process.returncode}) — stopping"
                    })
                break
        _process = None

    t = threading.Thread(target=run_sequence, daemon=True)
    t.start()
    return jsonify({"ok": True})


@app.route("/api/stop", methods=["POST"])
def api_stop():
    global _process
    if _process and _process.poll() is None:
        _process.terminate()
        return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "nothing running"})


@app.route("/api/status")
def api_status():
    running = bool(_process and _process.poll() is None)
    fs      = get_pipeline_status()
    phases_status = []
    now = time.time()
    for p in PHASES:
        pid   = p["id"]
        done  = pid in _phase_done
        started = pid in _start_times
        elapsed = None
        eta     = None
        if done:
            elapsed = int(_phase_done[pid] - _start_times.get(pid, _phase_done[pid]))
        elif started and running:
            elapsed = int(now - _start_times[pid])
            est_sec = p["est_min"] * 60
            eta     = max(0, int(est_sec - elapsed))
        phases_status.append({
            "id":      pid,
            "label":   p["label"],
            "done":    done,
            "running": started and not done and running,
            "elapsed": elapsed,
            "eta":     eta,
            "est_min": p["est_min"],
        })
    with _log_lock:
        logs = list(_log_lines[-150:])
    return jsonify({
        "running":      running,
        "pid":          _process.pid if running and _process else None,
        "phases":       phases_status,
        "fs":           fs,
        "logs":         logs,
        "log_total":    len(_log_lines),
    })


@app.route("/api/logs")
def api_logs():
    offset = int(request.args.get("offset", 0))
    with _log_lock:
        chunk = _log_lines[offset:]
    return jsonify({"lines": chunk, "total": len(_log_lines)})


# ── HTML ───────────────────────────────────────────────────────────────────────

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>PT Research Pipeline</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
{%- raw -%}
<style>
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

:root {
  --navy:    #0F1923;
  --navy2:   #162230;
  --navy3:   #1E2E3D;
  --teal:    #2A9D8F;
  --teal2:   #1E7268;
  --amber:   #E9C46A;
  --coral:   #E76F51;
  --steel:   #4A90A4;
  --white:   #F0F4F8;
  --grey1:   #8BA3B4;
  --grey2:   #4A6070;
  --grey3:   #2A3B48;
  --green:   #4CAF7D;
  --red:     #E05454;
  --font:    'Inter', sans-serif;
  --mono:    'JetBrains Mono', monospace;
}

html, body { height: 100%; background: var(--navy); color: var(--white); font-family: var(--font); font-size: 14px; line-height: 1.5; }

/* ── Layout ── */
.app { display: grid; grid-template-rows: 56px 1fr; height: 100vh; overflow: hidden; }
.header { display: flex; align-items: center; justify-content: space-between; padding: 0 24px; background: var(--navy2); border-bottom: 1px solid var(--grey3); }
.header-left { display: flex; align-items: center; gap: 12px; }
.logo { width: 28px; height: 28px; background: var(--teal); border-radius: 6px; display: flex; align-items: center; justify-content: center; font-size: 14px; font-weight: 700; color: var(--navy); flex-shrink: 0; }
.header h1 { font-size: 15px; font-weight: 600; color: var(--white); letter-spacing: -0.2px; }
.header-sub { font-size: 12px; color: var(--grey1); font-weight: 400; }
.status-pill { display: flex; align-items: center; gap: 6px; padding: 5px 12px; border-radius: 20px; font-size: 12px; font-weight: 500; background: var(--grey3); color: var(--grey1); transition: all .3s; }
.status-pill.running { background: rgba(42,157,143,.15); color: var(--teal); }
.status-pill.done    { background: rgba(76,175,125,.15); color: var(--green); }
.pulse { width: 7px; height: 7px; border-radius: 50%; background: currentColor; }
.pulse.anim { animation: pulse 1.4s ease-in-out infinite; }
@keyframes pulse { 0%,100%{opacity:1;transform:scale(1)} 50%{opacity:.4;transform:scale(.7)} }

.body { display: grid; grid-template-columns: 420px 1fr; overflow: hidden; }

/* ── Left panel ── */
.left { background: var(--navy2); border-right: 1px solid var(--grey3); display: flex; flex-direction: column; overflow: hidden; }
.panel-header { padding: 16px 20px 12px; border-bottom: 1px solid var(--grey3); display: flex; align-items: center; justify-content: space-between; }
.panel-title { font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 1px; color: var(--grey1); }
.left-scroll { flex: 1; overflow-y: auto; padding: 16px 20px; }
.left-scroll::-webkit-scrollbar { width: 4px; }
.left-scroll::-webkit-scrollbar-track { background: transparent; }
.left-scroll::-webkit-scrollbar-thumb { background: var(--grey3); border-radius: 2px; }

.field-group { margin-bottom: 18px; }
.field-label { font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: .8px; color: var(--grey1); margin-bottom: 6px; display: flex; align-items: center; gap: 6px; }
.field-label span { font-size: 10px; font-weight: 400; text-transform: none; letter-spacing: 0; color: var(--grey2); }
textarea, input[type="text"] { width: 100%; background: var(--navy3); border: 1px solid var(--grey3); border-radius: 6px; color: var(--white); font-family: var(--font); font-size: 13px; padding: 10px 12px; resize: vertical; outline: none; transition: border-color .2s; }
textarea:focus, input[type="text"]:focus { border-color: var(--teal); }
textarea { min-height: 80px; }
input[type="text"] { height: 38px; }

.feed-card { background: var(--navy3); border: 1px solid var(--grey3); border-radius: 8px; padding: 12px; margin-bottom: 10px; }
.feed-label { font-size: 11px; font-weight: 600; color: var(--teal); margin-bottom: 8px; letter-spacing: .5px; }
.feed-card input { margin-bottom: 6px; }
.feed-card input:last-child { margin-bottom: 0; }

.section-divider { display: flex; align-items: center; gap: 10px; margin: 20px 0 16px; }
.section-divider span { font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 1px; color: var(--grey2); white-space: nowrap; }
.section-divider::before, .section-divider::after { content:''; flex:1; height:1px; background:var(--grey3); }

/* ── Buttons ── */
.btn-row { padding: 14px 20px; border-top: 1px solid var(--grey3); display: flex; gap: 8px; }
.btn { height: 36px; padding: 0 16px; border-radius: 6px; font-family: var(--font); font-size: 13px; font-weight: 600; cursor: pointer; border: none; transition: all .15s; display: flex; align-items: center; gap: 6px; }
.btn-primary { background: var(--teal); color: var(--navy); flex: 1; justify-content: center; }
.btn-primary:hover { background: var(--teal2); }
.btn-primary:disabled { background: var(--grey3); color: var(--grey2); cursor: not-allowed; }
.btn-secondary { background: var(--grey3); color: var(--grey1); }
.btn-secondary:hover { background: var(--grey2); color: var(--white); }
.btn-danger { background: rgba(224,84,84,.15); color: var(--red); border: 1px solid rgba(224,84,84,.3); }
.btn-danger:hover { background: rgba(224,84,84,.25); }
.btn-save { background: var(--navy3); border: 1px solid var(--grey3); color: var(--grey1); font-size: 12px; padding: 0 12px; }
.btn-save:hover { border-color: var(--teal); color: var(--teal); }

/* ── AI Config Assistant ── */
.ai-toggle { width: 100%; background: none; border: none; border-bottom: 1px solid var(--grey3); padding: 10px 20px; display: flex; align-items: center; gap: 8px; cursor: pointer; color: var(--teal); font-family: var(--font); font-size: 12px; font-weight: 600; letter-spacing: .5px; text-transform: uppercase; transition: background .15s; }
.ai-toggle:hover { background: rgba(42,157,143,.07); }
.ai-toggle .ai-icon { width: 20px; height: 20px; background: rgba(42,157,143,.15); border-radius: 4px; display: flex; align-items: center; justify-content: center; font-size: 11px; flex-shrink: 0; }
.ai-toggle .chevron { margin-left: auto; font-size: 10px; transition: transform .2s; }
.ai-toggle.open .chevron { transform: rotate(180deg); }

.ai-panel { background: var(--navy); border-bottom: 1px solid var(--grey3); display: none; flex-direction: column; height: 340px; }
.ai-panel.open { display: flex; }
.ai-messages { flex: 1; overflow-y: auto; padding: 12px 16px; display: flex; flex-direction: column; gap: 10px; }
.ai-messages::-webkit-scrollbar { width: 3px; }
.ai-messages::-webkit-scrollbar-thumb { background: var(--grey3); border-radius: 2px; }

.ai-msg { display: flex; gap: 8px; align-items: flex-start; }
.ai-msg.user { flex-direction: row-reverse; }
.ai-avatar { width: 22px; height: 22px; border-radius: 4px; display: flex; align-items: center; justify-content: center; font-size: 10px; font-weight: 700; flex-shrink: 0; margin-top: 1px; }
.ai-msg.assistant .ai-avatar { background: rgba(42,157,143,.2); color: var(--teal); }
.ai-msg.user .ai-avatar { background: rgba(74,144,164,.2); color: var(--steel); }
.ai-bubble { max-width: 88%; padding: 8px 11px; border-radius: 10px; font-size: 12px; line-height: 1.55; }
.ai-msg.assistant .ai-bubble { background: var(--navy2); color: var(--white); border: 1px solid var(--grey3); border-top-left-radius: 3px; }
.ai-msg.user .ai-bubble { background: rgba(42,157,143,.12); color: var(--white); border: 1px solid rgba(42,157,143,.25); border-top-right-radius: 3px; }
.ai-bubble pre { font-family: var(--mono); font-size: 11px; white-space: pre-wrap; word-break: break-word; margin-top: 6px; background: rgba(0,0,0,.3); padding: 8px; border-radius: 4px; }

.ai-apply-btn { margin-top: 8px; padding: 5px 10px; background: var(--teal); color: var(--navy); border: none; border-radius: 5px; font-family: var(--font); font-size: 11px; font-weight: 700; cursor: pointer; display: inline-flex; align-items: center; gap: 5px; }
.ai-apply-btn:hover { background: var(--teal2); color: var(--white); }

.ai-input-row { padding: 8px 12px; border-top: 1px solid var(--grey3); display: flex; gap: 6px; align-items: flex-end; background: var(--navy2); }
.ai-input-row textarea { min-height: 36px; max-height: 90px; height: 36px; resize: none; font-size: 12px; padding: 8px 10px; flex: 1; }
.ai-send { width: 34px; height: 34px; background: var(--teal); border: none; border-radius: 6px; color: var(--navy); cursor: pointer; display: flex; align-items: center; justify-content: center; font-size: 14px; flex-shrink: 0; transition: background .15s; }
.ai-send:hover { background: var(--teal2); color: var(--white); }
.ai-send:disabled { background: var(--grey3); color: var(--grey2); cursor: not-allowed; }
.ai-thinking { display: flex; gap: 4px; padding: 4px 2px; }
.ai-thinking span { width: 5px; height: 5px; border-radius: 50%; background: var(--grey1); animation: bounce 1.2s ease-in-out infinite; }
.ai-thinking span:nth-child(2) { animation-delay: .2s; }
.ai-thinking span:nth-child(3) { animation-delay: .4s; }
@keyframes bounce { 0%,100%{transform:translateY(0);opacity:.4} 50%{transform:translateY(-4px);opacity:1} }


/* Phase tracker */
.phases { padding: 16px 24px; background: var(--navy2); border-bottom: 1px solid var(--grey3); display: flex; gap: 0; align-items: center; }
.phase-item { display: flex; align-items: center; flex: 1; }
.phase-node { display: flex; flex-direction: column; align-items: center; gap: 4px; min-width: 70px; }
.phase-dot { width: 28px; height: 28px; border-radius: 50%; border: 2px solid var(--grey3); background: var(--navy); display: flex; align-items: center; justify-content: center; font-size: 11px; font-weight: 700; color: var(--grey2); transition: all .4s; position: relative; }
.phase-dot.done    { background: var(--teal); border-color: var(--teal); color: var(--navy); }
.phase-dot.running { border-color: var(--amber); color: var(--amber); animation: spin-border 2s linear infinite; }
@keyframes spin-border { 0%{box-shadow:0 0 0 0 rgba(233,196,106,.4)} 50%{box-shadow:0 0 0 6px rgba(233,196,106,0)} 100%{box-shadow:0 0 0 0 rgba(233,196,106,0)} }
.phase-label { font-size: 10px; font-weight: 500; color: var(--grey2); text-align: center; line-height: 1.3; white-space: nowrap; }
.phase-label.done    { color: var(--teal); }
.phase-label.running { color: var(--amber); }
.phase-timing { font-size: 9px; color: var(--grey2); font-family: var(--mono); text-align: center; margin-top: 1px; }
.phase-timing.running { color: var(--amber); }
.phase-connector { flex: 1; height: 2px; background: var(--grey3); margin: 0 4px; margin-bottom: 20px; transition: background .4s; }
.phase-connector.done { background: var(--teal); }

/* Stats bar */
.stats-bar { display: flex; gap: 1px; background: var(--grey3); border-bottom: 1px solid var(--grey3); }
.stat-cell { flex: 1; padding: 10px 16px; background: var(--navy2); }
.stat-val { font-size: 22px; font-weight: 700; color: var(--white); font-variant-numeric: tabular-nums; line-height: 1; }
.stat-val.teal { color: var(--teal); }
.stat-val.amber { color: var(--amber); }
.stat-val.green { color: var(--green); }
.stat-lbl { font-size: 10px; color: var(--grey1); margin-top: 3px; font-weight: 500; text-transform: uppercase; letter-spacing: .5px; }

/* Log stream */
.log-area { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
.log-header { padding: 10px 20px; background: var(--navy2); border-bottom: 1px solid var(--grey3); display: flex; align-items: center; justify-content: space-between; }
.log-title { font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 1px; color: var(--grey1); display: flex; align-items: center; gap: 8px; }
.log-count { font-family: var(--mono); font-size: 10px; color: var(--grey2); }
.log-scroll { flex: 1; overflow-y: auto; padding: 12px 20px; font-family: var(--mono); font-size: 12px; line-height: 1.7; }
.log-scroll::-webkit-scrollbar { width: 4px; }
.log-scroll::-webkit-scrollbar-track { background: transparent; }
.log-scroll::-webkit-scrollbar-thumb { background: var(--grey3); border-radius: 2px; }
.log-line { display: flex; gap: 12px; padding: 1px 0; }
.log-time { color: var(--grey2); flex-shrink: 0; }
.log-msg  { color: var(--grey1); word-break: break-all; }
.log-msg.info  { color: #8BA3B4; }
.log-msg.ok    { color: var(--green); }
.log-msg.warn  { color: var(--amber); }
.log-msg.error { color: var(--red); }
.log-msg.head  { color: var(--teal); font-weight: 500; }
.log-empty { color: var(--grey2); font-style: italic; padding: 20px 0; }

.right-inner { display: flex; flex-direction: column; overflow: hidden; }

/* toast */
.toast { position: fixed; bottom: 24px; right: 24px; padding: 10px 18px; border-radius: 8px; font-size: 13px; font-weight: 500; opacity: 0; transform: translateY(8px); transition: all .25s; pointer-events: none; z-index: 100; }
.toast.show { opacity: 1; transform: translateY(0); }
.toast.ok  { background: rgba(42,157,143,.9); color: #fff; }
.toast.err { background: rgba(224,84,84,.9);  color: #fff; }
</style>
{%- endraw -%}
</head>
<body data-phases='{{ phases | tojson }}'>
<div class="app">

<!-- Header -->
<header class="header">
  <div class="header-left">
    <div class="logo">P</div>
    <div>
      <h1>PT Research Pipeline <span style="font-weight:300;color:var(--grey1)">v2</span></h1>
      <div class="header-sub">Evidence synthesis · Local LLM · Open access</div>
    </div>
  </div>
  <div id="statusPill" class="status-pill">
    <div class="pulse" id="statusDot"></div>
    <span id="statusText">Idle</span>
  </div>
</header>

<div class="body">

<!-- Left: Config -->
<div class="left">
  <div class="panel-header">
    <span class="panel-title">Pipeline Configuration</span>
    <button class="btn btn-save" onclick="saveConfig()">Save config</button>
  </div>

  <!-- AI Config Assistant -->
  <button class="ai-toggle" id="aiToggle" onclick="toggleAI()">
    <span class="ai-icon">✦</span>
    Configure with AI
    <span class="chevron">▼</span>
  </button>
  <div class="ai-panel" id="aiPanel">
    <div class="ai-messages" id="aiMessages"></div>
    <div class="ai-input-row">
      <textarea id="aiInput" placeholder="Describe your clinical topic…" rows="1"
        onkeydown="if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();sendAI()}"
        oninput="this.style.height='36px';this.style.height=Math.min(this.scrollHeight,90)+'px'"></textarea>
      <button class="ai-send" id="aiSend" onclick="sendAI()" title="Send">➤</button>
    </div>
  </div>

  <div class="left-scroll">

    <div class="field-group">
      <div class="field-label">Research Question</div>
      <textarea id="rq" rows="4" placeholder="In adults with myofascial pain syndrome, does dry needling produce clinically meaningful reductions in pain intensity…"></textarea>
    </div>

    <div class="field-group">
      <div class="field-label">Topic Short Name <span>used in filenames and report titles</span></div>
      <input type="text" id="shortName" placeholder="e.g. dry needling, myofascial pain">
    </div>

    <div class="field-group">
      <div class="field-label">Relevance Criterion <span>Layer 0 screening gate</span></div>
      <textarea id="relevanceCriterion" rows="3" placeholder="The article concerns dry needling as an intervention for myofascial pain syndrome…"></textarea>
    </div>

    <div class="field-group">
      <div class="field-label">Intervention Noun</div>
      <input type="text" id="interventionNoun" placeholder="e.g. dry needling intervention">
    </div>

    <div class="field-group">
      <div class="field-label">Governance Focus</div>
      <textarea id="governanceFocus" rows="2" placeholder="scope of practice, training requirements, adverse event reporting…"></textarea>
    </div>

    <div class="section-divider"><span>PubMed RSS Feeds</span></div>

    <div class="feed-card">
      <div class="feed-label">Feed A</div>
      <input type="text" id="feedA-url" placeholder="https://pubmed.ncbi.nlm.nih.gov/rss/search/…">
      <input type="text" id="feedA-desc" placeholder="Description — e.g. Systematic reviews and meta-analyses">
    </div>

    <div class="feed-card">
      <div class="feed-label">Feed B</div>
      <input type="text" id="feedB-url" placeholder="https://pubmed.ncbi.nlm.nih.gov/rss/search/…">
      <input type="text" id="feedB-desc" placeholder="Description — e.g. RCTs and clinical trials">
    </div>

    <div class="feed-card">
      <div class="feed-label">Feed C</div>
      <input type="text" id="feedC-url" placeholder="https://pubmed.ncbi.nlm.nih.gov/rss/search/…">
      <input type="text" id="feedC-desc" placeholder="Description — e.g. Safety, governance, scope of practice">
    </div>

  </div><!-- /left-scroll -->

  <div class="btn-row">
    <button id="btnRun" class="btn btn-primary" onclick="runAll()">▶  Run full pipeline</button>
    <button id="btnStop" class="btn btn-danger" onclick="stopPipeline()" style="display:none">■  Stop</button>
  </div>
  <div class="btn-row" style="padding-top:0">
    <button id="btnArchive" class="btn" onclick="archiveAndReset()" style="flex:1;justify-content:center;background:var(--navy3);border:1px solid var(--grey3);color:var(--grey1);font-size:12px" title="Move outputs to archive/ and reset working folders">📦  Archive &amp; Reset</button>
  </div>
  <div style="font-size:11px;color:var(--grey2);padding:4px 20px 12px;line-height:1.4">Run after reviewing outputs. Moves everything to archive/ and clears working folders for next topic.</div>
</div><!-- /left -->

<!-- Right: Status + Logs -->
<div class="right">

  <!-- Phase tracker -->
  <div class="phases" id="phaseTracker"></div>

  <div class="right-inner">
    <!-- Stats bar -->
    <div class="stats-bar">
      <div class="stat-cell"><div class="stat-val" id="sLedger">—</div><div class="stat-lbl">Ingested</div></div>
      <div class="stat-cell"><div class="stat-val teal" id="sL0">—</div><div class="stat-lbl">Screened</div></div>
      <div class="stat-cell"><div class="stat-val amber" id="sRelevant">—</div><div class="stat-lbl">Relevant</div></div>
      <div class="stat-cell"><div class="stat-val" id="sL2">—</div><div class="stat-lbl">Appraised</div></div>
      <div class="stat-cell"><div class="stat-val teal" id="sClusters">—</div><div class="stat-lbl">Clusters</div></div>
      <div class="stat-cell"><div class="stat-val green" id="sExport">—</div><div class="stat-lbl">Output</div></div>
    </div>

    <!-- Log -->
    <div class="log-area">
      <div class="log-header">
        <span class="log-title">
          <span style="color:var(--teal)">⬤</span> Live output
        </span>
        <span class="log-count" id="logCount">0 lines</span>
      </div>
      <div class="log-scroll" id="logScroll">
        <div class="log-empty">Pipeline output will appear here when running.</div>
      </div>
    </div>
  </div>

</div><!-- /right -->
</div><!-- /body -->
</div><!-- /app -->

<div class="toast" id="toast"></div>

{%- raw -%}
<script>
let logOffset = 0;
let autoScroll = true;
let phases = JSON.parse(document.body.dataset.phases || '[]');
let lastLogCount = 0;

// ── Init ──────────────────────────────────────────────────────────────────────
async function loadConfig() {
  try {
    const r = await fetch('/api/config');
    const cfg = await r.json();
    if (cfg.research_question)        document.getElementById('rq').value = cfg.research_question.trim();
    if (cfg.topic?.short_name)        document.getElementById('shortName').value = cfg.topic.short_name;
    if (cfg.topic?.relevance_criterion) document.getElementById('relevanceCriterion').value = cfg.topic.relevance_criterion.trim();
    if (cfg.topic?.intervention_noun) document.getElementById('interventionNoun').value = cfg.topic.intervention_noun;
    if (cfg.topic?.governance_focus)  document.getElementById('governanceFocus').value = cfg.topic.governance_focus.trim();
    const feeds = cfg.feeds || [];
    ['A','B','C'].forEach((l,i) => {
      const f = feeds[i] || {};
      document.getElementById(`feed${l}-url`).value  = f.url  || '';
      document.getElementById(`feed${l}-desc`).value = f.description || '';
    });
  } catch(e) { console.warn('Config load failed', e); }
}

async function saveConfig() {
  const feeds = ['A','B','C'].map((l,i) => ({
    url:  document.getElementById(`feed${l}-url`).value.trim(),
    name: `feed_${l.toLowerCase()}`,
    description: document.getElementById(`feed${l}-desc`).value.trim(),
  })).filter(f => f.url);

  const body = {
    research_question:   document.getElementById('rq').value.trim(),
    short_name:          document.getElementById('shortName').value.trim(),
    relevance_criterion: document.getElementById('relevanceCriterion').value.trim(),
    intervention_noun:   document.getElementById('interventionNoun').value.trim(),
    governance_focus:    document.getElementById('governanceFocus').value.trim(),
    feeds,
  };
  try {
    const r = await fetch('/api/config', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body) });
    const d = await r.json();
    showToast(d.ok ? 'Config saved' : d.error, d.ok ? 'ok' : 'err');
  } catch(e) { showToast('Save failed', 'err'); }
}

// ── Pipeline controls ─────────────────────────────────────────────────────────
async function runAll() {
  await saveConfig();
  logOffset = 0; lastLogCount = 0;
  document.getElementById('logScroll').innerHTML = '';
  const r = await fetch('/api/run/all', { method:'POST' });
  const d = await r.json();
  if (!d.ok) showToast(d.error, 'err');
}

// ── AI Config Assistant ──────────────────────────────────────────────
const AI_SYSTEM = `You are helping a physical therapist configure an automated evidence synthesis pipeline. The pipeline searches PubMed, screens articles with AI, performs 7-stage clinical appraisal, and produces GRADE-rated evidence syntheses.

Your job is to ask the user 7 questions ONE AT A TIME to understand their topic, then generate the exact configuration fields they need.

Ask these questions in order, one at a time. Wait for the answer before asking the next one:

1. CLINICAL TOPIC — What clinical topic, intervention, or clinical question do you want to review? Describe it in plain language — the intervention, what condition it treats, and what aspect interests you most (effectiveness, safety, technique, governance, dosage, comparison with other treatments, etc.)

2. AUDIENCE AND PURPOSE — Who will read this synthesis and what decision are they trying to make? (e.g. a SIG of practicing PTs deciding whether to adopt a technique, a manager designing a training program, a clinician writing a practice guideline)

3. SCOPE — Should this be a broad scoping review (map the entire literature) or a focused review (answer a specific clinical question)? If focused, what is the specific question using PICO format?

4. POPULATION — Who is the patient population? Be specific — age range, condition severity, chronicity, clinical setting, any important subgroups.

5. GOVERNANCE ANGLE — What governance, safety, or scope-of-practice questions are relevant? (e.g. training requirements, adverse event protocols, contraindications, scope of practice for a specific license type)

6. DATE RANGE AND EVIDENCE TYPE — How far back should the search go? Are you most interested in systematic reviews, RCTs, all study types, or a specific design?

7. COMPARISON — For a focused question: what is the intervention being compared against? (Sham, active control, standard care, no treatment, another technique, or not applicable)

After all 7 answers, output EXACTLY this block with no extra text before or after the markers:

===CONFIG_START===
FIELD1_RESEARCH_QUESTION: [single well-formed clinical research question]
FIELD2_SHORT_NAME: [2-4 words, lowercase]
FIELD3_RELEVANCE_CRITERION: [2-4 sentences starting with "The article concerns..."]
FIELD4_INTERVENTION_NOUN: [short phrase]
FIELD5_GOVERNANCE_FOCUS: [2-4 sentences naming specific regulatory bodies, license types, training standards]
FIELD6_FEED_A_DESC: [one sentence — systematic reviews and meta-analyses]
FIELD7_FEED_B_DESC: [one sentence — RCTs and clinical trials]
FIELD8_FEED_C_DESC: [one sentence — governance, safety, implementation]
FEED_A_SEARCH: [PubMed search string using MeSH and Title/Abstract tags, end with AND free full text[Filter]]
FEED_B_SEARCH: [PubMed search string, end with AND free full text[Filter]]
FEED_C_SEARCH: [PubMed search string, no free full text filter]
===CONFIG_END===

Be specific, clinical, and precise. Each field must be immediately usable without editing.`;

let aiHistory = [];
let aiStreaming = false;

function toggleAI() {
  const panel = document.getElementById('aiPanel');
  const toggle = document.getElementById('aiToggle');
  const isOpen = panel.classList.toggle('open');
  toggle.classList.toggle('open', isOpen);
  if (isOpen && aiHistory.length === 0) {
    appendAIMessage('assistant', "Hi! I'll help you configure the pipeline. Tell me about the clinical topic you want to review — what's the intervention, what condition does it treat, and what aspect are you most interested in?");
    aiHistory.push({ role: 'assistant', content: "Hi! I'll help you configure the pipeline. Tell me about the clinical topic you want to review — what's the intervention, what condition does it treat, and what aspect are you most interested in?" });
  }
}

function appendAIMessage(role, content) {
  const msgs = document.getElementById('aiMessages');
  const id = 'ai-msg-' + Date.now();
  const avatar = role === 'assistant' ? '✦' : 'You';
  const parsed = parseAIContent(content);
  const div = document.createElement('div');
  div.className = 'ai-msg ' + role;
  div.id = id;
  div.innerHTML = '<div class="ai-avatar">' + avatar + '</div><div class="ai-bubble">' + parsed + '</div>';
  msgs.appendChild(div);
  msgs.scrollTop = msgs.scrollHeight;
  return id;
}

function updateAIMessage(id, content) {
  const el = document.getElementById(id);
  if (!el) return;
  const bubble = el.querySelector('.ai-bubble');
  if (bubble) bubble.innerHTML = parseAIContent(content);
  document.getElementById('aiMessages').scrollTop = 99999;
}

function parseAIContent(text) {
  if (text.includes('===CONFIG_START===')) {
    const before = text.split('===CONFIG_START===')[0].trim();
    const block  = (text.split('===CONFIG_START===')[1] || '').split('===CONFIG_END===')[0].trim();
    const fields = parseConfigBlock(block);
    let html = before ? '<p>' + escHtml(before) + '</p>' : '';
    html += '<p style="margin-top:6px;color:var(--teal);font-weight:600;font-size:11px">✓ Configuration ready</p>';
    if (fields) {
      html += '<pre>' + escHtml(block) + '</pre>';
      html += '<button class="ai-apply-btn" onclick=\'applyAIConfig(' + JSON.stringify(JSON.stringify(fields)) + ')\'>⬆ Apply to config fields</button>';
    }
    return html;
  }
  return escHtml(text).replace(/\n/g, '<br>');
}

function escHtml(s) {
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function parseConfigBlock(block) {
  const lines = block.split('\n');
  const fields = {};
  for (const line of lines) {
    const m = line.match(/^(FIELD\d+_\w+|FEED_[ABC]_(?:SEARCH|DESC)):\s*(.+)/);
    if (m) fields[m[1]] = m[2].trim();
  }
  return Object.keys(fields).length > 0 ? fields : null;
}

function applyAIConfig(fieldsJson) {
  const fields = JSON.parse(fieldsJson);
  const set = function(id, key) { const el = document.getElementById(id); if (el && fields[key]) el.value = fields[key]; };
  set('rq',                'FIELD1_RESEARCH_QUESTION');
  set('shortName',         'FIELD2_SHORT_NAME');
  set('relevanceCriterion','FIELD3_RELEVANCE_CRITERION');
  set('interventionNoun',  'FIELD4_INTERVENTION_NOUN');
  set('governanceFocus',   'FIELD5_GOVERNANCE_FOCUS');
  set('feedA-desc',        'FIELD6_FEED_A_DESC');
  set('feedB-desc',        'FIELD7_FEED_B_DESC');
  set('feedC-desc',        'FIELD8_FEED_C_DESC');

  if (fields.FEED_A_SEARCH || fields.FEED_B_SEARCH || fields.FEED_C_SEARCH) {
    const msgs = document.getElementById('aiMessages');
    const div = document.createElement('div');
    div.className = 'ai-msg assistant';
    div.innerHTML = '<div class="ai-avatar">✦</div><div class="ai-bubble">' +
      '<p style="color:var(--teal);font-weight:600;margin-bottom:6px">✓ Fields applied! Paste these into PubMed to create your RSS feeds:</p>' +
      '<p style="font-size:11px;color:var(--grey1);margin-bottom:4px;font-weight:600">FEED A SEARCH</p><pre>' + escHtml(fields.FEED_A_SEARCH||'') + '</pre>' +
      '<p style="font-size:11px;color:var(--grey1);margin:6px 0 4px;font-weight:600">FEED B SEARCH</p><pre>' + escHtml(fields.FEED_B_SEARCH||'') + '</pre>' +
      '<p style="font-size:11px;color:var(--grey1);margin:6px 0 4px;font-weight:600">FEED C SEARCH</p><pre>' + escHtml(fields.FEED_C_SEARCH||'') + '</pre>' +
      '<p style="font-size:11px;color:var(--grey1);margin-top:8px">Paste each into PubMed → Create RSS (100 items) → paste the RSS URL into the Feed URL fields above.</p>' +
      '</div>';
    msgs.appendChild(div);
    msgs.scrollTop = msgs.scrollHeight;
  }

  showToast('Config fields populated from AI', 'ok');
}

async function sendAI() {
  if (aiStreaming) return;
  const input = document.getElementById('aiInput');
  const msg = input.value.trim();
  if (!msg) return;

  input.value = '';
  input.style.height = '36px';
  aiHistory.push({ role: 'user', content: msg });
  appendAIMessage('user', msg);

  const msgs = document.getElementById('aiMessages');
  const thinkId = 'think-' + Date.now();
  const thinkDiv = document.createElement('div');
  thinkDiv.className = 'ai-msg assistant';
  thinkDiv.id = thinkId;
  thinkDiv.innerHTML = '<div class="ai-avatar">✦</div><div class="ai-bubble"><div class="ai-thinking"><span></span><span></span><span></span></div></div>';
  msgs.appendChild(thinkDiv);
  msgs.scrollTop = msgs.scrollHeight;

  document.getElementById('aiSend').disabled = true;
  aiStreaming = true;

  let full = '';
  const msgId = 'stream-' + Date.now();

  try {
    const cfg = await (await fetch('/api/config')).json();
    const model = (cfg.model && cfg.model.layer0) || 'qwen3.6:35b-a3b';

    const res = await fetch('/api/ollama/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        model: model,
        stream: false,
        think: false,
        options: { temperature: 0.4, num_predict: 2000, num_ctx: 8192 },
        messages: [{ role: 'system', content: AI_SYSTEM }].concat(aiHistory.slice(0, -1))
      })
    });

    if (!res.ok) {
      const errText = await res.text();
      throw new Error('Ollama returned ' + res.status + ': ' + errText.slice(0, 200));
    }

    const thinkEl = document.getElementById(thinkId);
    if (thinkEl) thinkEl.remove();

    const data = await res.json();
    full = (data.message && data.message.content) ? data.message.content : '';
    if (!full) throw new Error('Empty response from model');
    appendAIMessage('assistant', full);
  } catch (e) {
    const thinkEl = document.getElementById(thinkId);
    if (thinkEl) thinkEl.remove();
    appendAIMessage('assistant', 'Error: ' + (e.message || 'Could not reach Ollama — make sure it is running on localhost:11434.'));
    full = 'error';
  }


  if (full && full !== 'error') {
    aiHistory.push({ role: 'assistant', content: full });
  }
  aiStreaming = false;
  document.getElementById('aiSend').disabled = false;
}


async function stopPipeline() {
  const r = await fetch('/api/stop', { method:'POST' });
  const d = await r.json();
  showToast(d.ok ? 'Pipeline stopped' : d.error, d.ok ? 'ok' : 'err');
}

async function archiveAndReset() {
  if (lastRunning) {
    showToast('Pipeline is still running — wait for it to finish first', 'err');
    return;
  }
  if (!confirm('This will move this run\'s outputs into archive/{topic}_{date}/ and reset the working folders to empty. Continue?')) {
    return;
  }
  logOffset = 0; lastLogCount = 0;
  document.getElementById('logScroll').innerHTML = '';
  const r = await fetch('/api/run/run_archive.py', { method:'POST' });
  const d = await r.json();
  if (!d.ok) showToast(d.error, 'err');
  else showToast('Archiving...', 'ok');
}

// ── Status polling ────────────────────────────────────────────────────────────
async function poll() {
  try {
    const r = await fetch('/api/status');
    const d = await r.json();
    updateStatus(d);
    updatePhases(d.phases);
    updateStats(d.fs);
    appendLogs(d.logs, d.log_total);
  } catch(e) {}
}

function updateStatus(d) {
  const pill = document.getElementById('statusPill');
  const dot  = document.getElementById('statusDot');
  const txt  = document.getElementById('statusText');
  const btnRun  = document.getElementById('btnRun');
  const btnStop = document.getElementById('btnStop');

  if (d.running) {
    pill.className = 'status-pill running';
    dot.className  = 'pulse anim';
    txt.textContent = `Running — PID ${d.pid}`;
    btnRun.style.display  = 'none';
    btnStop.style.display = '';
  } else {
    const anyDone = d.phases?.some(p => p.done);
    pill.className = anyDone ? 'status-pill done' : 'status-pill';
    dot.className  = 'pulse';
    txt.textContent = anyDone ? 'Complete' : 'Idle';
    btnRun.style.display  = '';
    btnStop.style.display = 'none';
  }
}

function updatePhases(phases) {
  const container = document.getElementById('phaseTracker');
  if (!phases?.length) return;
  container.innerHTML = '';
  phases.forEach((p, i) => {
    const item = document.createElement('div');
    item.className = 'phase-item';

    const node = document.createElement('div');
    node.className = 'phase-node';

    const dotCls = p.done ? 'done' : p.running ? 'running' : '';
    const icon   = p.done ? '✓' : p.running ? '…' : (i+1);

    let timingHtml = '';
    if (p.done && p.elapsed != null) {
      timingHtml = `<div class="phase-timing done">${fmtSec(p.elapsed)}</div>`;
    } else if (p.running && p.eta != null) {
      timingHtml = `<div class="phase-timing running">~${fmtSec(p.eta)} left</div>`;
    } else if (!p.done && !p.running) {
      timingHtml = `<div class="phase-timing">~${p.est_min}m</div>`;
    }

    node.innerHTML = `
      <div class="phase-dot ${dotCls}">${icon}</div>
      <div class="phase-label ${dotCls}">${p.label}</div>
      ${timingHtml}
    `;
    item.appendChild(node);

    if (i < phases.length - 1) {
      const conn = document.createElement('div');
      conn.className = 'phase-connector' + (p.done ? ' done' : '');
      item.appendChild(conn);
    }

    container.appendChild(item);
  });
}

function updateStats(fs) {
  if (!fs) return;
  set('sLedger',   fs.ledger_rows    || '—');
  set('sL0',       fs.layer0_count   || '—');
  set('sRelevant', fs.layer0_relevant || '—');
  set('sL2',       fs.layer2_count   || '—');
  set('sClusters', fs.cluster_count  || '—');
  set('sExport',   fs.export_exists ? '✓' : '—');
}

function set(id, val) {
  const el = document.getElementById(id);
  if (el) el.textContent = val;
}

// ── Log rendering ─────────────────────────────────────────────────────────────
function appendLogs(lines, total) {
  if (!lines?.length) return;
  const scroll  = document.getElementById('logScroll');
  const wasBottom = scroll.scrollHeight - scroll.scrollTop - scroll.clientHeight < 60;

  // Clear placeholder
  const empty = scroll.querySelector('.log-empty');
  if (empty) empty.remove();

  lines.forEach(l => {
    const div  = document.createElement('div');
    div.className = 'log-line';
    const cls = classifyLog(l.msg);
    div.innerHTML = `<span class="log-time">${l.t}</span><span class="log-msg ${cls}">${escHtml(l.msg)}</span>`;
    scroll.appendChild(div);
  });

  document.getElementById('logCount').textContent = `${total} lines`;
  logOffset = total;

  if (wasBottom) scroll.scrollTop = scroll.scrollHeight;
}

function classifyLog(msg) {
  if (!msg) return '';
  if (msg.includes('✓') || msg.includes('complete') || msg.includes('saved') || msg.includes('written')) return 'ok';
  if (msg.includes('[ERROR]') || msg.includes('failed') || msg.includes('FAIL')) return 'error';
  if (msg.includes('[WARNING]') || msg.includes('WARN')) return 'warn';
  if (msg.includes('━━━') || msg.includes('===') || msg.includes('GRADE SUMMARY')) return 'head';
  if (msg.includes('[INFO]')) return 'info';
  return '';
}

function escHtml(s) {
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function fmtSec(s) {
  if (s < 60) return `${s}s`;
  const m = Math.floor(s/60), r = s%60;
  return r ? `${m}m${r}s` : `${m}m`;
}

// ── Toast ─────────────────────────────────────────────────────────────────────
function showToast(msg, type='ok') {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.className = `toast ${type} show`;
  setTimeout(() => t.className = `toast ${type}`, 2200);
}

// ── Boot ──────────────────────────────────────────────────────────────────────
loadConfig();
poll();
setInterval(poll, 1500);
</script>
{%- endraw -%}
</body>
</html>
"""

if __name__ == "__main__":
    os.chdir(PIPELINE_ROOT)
    print("PT Research Pipeline UI")
    print(f"  Root: {PIPELINE_ROOT}")
    print(f"  Open: http://localhost:5050")
    app.run(host="0.0.0.0", port=5050, debug=False, threaded=True)
