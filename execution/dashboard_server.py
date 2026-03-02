"""
Dashboard Server — Lead Gen Pipeline monitoring & control.

Provides a web UI on port 8080 to:
  - Launch prospection pipelines (industry + countries + max_leads)
  - Monitor pipeline progress in real-time (steps, lead counts)
  - Track API usage vs monthly quotas

Run:
    python execution/dashboard_server.py
    # or on VPS:
    nohup python execution/dashboard_server.py > .tmp/dashboard.log 2>&1 &
"""

import os
import sys
import json
import signal
import subprocess
from pathlib import Path
from datetime import datetime

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).parent))
from api_utils import API_LIMITS, load_and_merge_tracker_snapshots

PROJECT_ROOT = Path(__file__).parent.parent
TMP_DIR = PROJECT_ROOT / ".tmp"
PYTHON = sys.executable
PIPELINE_SCRIPT = Path(__file__).parent / "run_pipeline.py"
LOG_FILE = TMP_DIR / "pipeline_output.log"
STATE_FILE = TMP_DIR / "pipeline_state.json"
PROGRESS_FILE = TMP_DIR / "pipeline_progress.json"

PIPELINE_STEPS = [
    "step1_expand",
    "step2_qualify",
    "step3_enrich",
    "step3c_score",
    "step4_hubspot",
    "step5_backup",
]

STEP_LABELS = {
    "step1_expand": "Scrape + Dedup",
    "step2_qualify": "Qualification",
    "step3_enrich": "Enrichissement",
    "step3c_score": "Scoring",
    "step4_hubspot": "Sync HubSpot",
    "step5_backup": "Backup Excel",
}

app = FastAPI(title="Lead Gen Dashboard")


# ── Helpers ──────────────────────────────────────────────────

def _is_pipeline_running() -> Optional[int]:
    """Return PID of running run_pipeline.py process, or None."""
    try:
        if sys.platform == "win32":
            r = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq python.exe", "/FO", "CSV"],
                capture_output=True, text=True,
            )
            return None
        else:
            r = subprocess.run(
                ["pgrep", "-f", "run_pipeline.py"],
                capture_output=True, text=True,
            )
            if r.returncode == 0 and r.stdout.strip():
                pids = r.stdout.strip().split("\n")
                return int(pids[0])
    except Exception:
        pass
    return None


def _read_json(path: Path) -> Optional[dict | list]:
    try:
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except (json.JSONDecodeError, OSError):
        pass
    return None


def _count_leads(filename: str) -> int:
    data = _read_json(TMP_DIR / filename)
    if isinstance(data, list):
        return len(data)
    return 0


# ── API Endpoints ────────────────────────────────────────────

@app.get("/api/status")
def get_status():
    state = _read_json(STATE_FILE) or {}
    progress = _read_json(PROGRESS_FILE) or {}
    pid = _is_pipeline_running()

    # Status from progress file (multi-country aware)
    if pid:
        effective_status = "running"
    elif progress.get("status") == "paused":
        effective_status = "paused"
    elif progress.get("status") == "completed":
        effective_status = "completed"
    elif state.get("status") == "paused":
        effective_status = "paused"
    elif progress.get("status") == "running" or state.get("status") == "running":
        effective_status = "finished"
    else:
        effective_status = "idle"

    # Per-country step tracking from the per-country state file
    steps_completed = state.get("steps_completed", [])
    current_step_idx = len(steps_completed)

    # Multi-country data from progress file
    countries = progress.get("countries", [])
    countries_done = progress.get("countries_done", [])
    countries_results = progress.get("countries_results", {})
    total_leads_all = progress.get("total_leads", 0)

    return {
        "status": effective_status,
        "pid": pid,
        "industry": progress.get("industry", state.get("industry", "")),
        "location": progress.get("current_country", state.get("location", "")),
        "max_leads": progress.get("max_leads", state.get("max_leads", 0)),
        "steps_completed": steps_completed,
        "current_step": progress.get("current_step", ""),
        "current_step_index": current_step_idx,
        "total_steps": len(PIPELINE_STEPS),
        "step_labels": STEP_LABELS,
        "pause_reason": progress.get("pause_reason", state.get("pause_reason", "")),
        "paused_at": state.get("paused_at", ""),
        "last_updated": state.get("last_updated", progress.get("started_at", "")),
        "finished_at": progress.get("finished_at", ""),
        "run_id": progress.get("run_id", state.get("run_id", "")),
        "countries": countries,
        "countries_done": countries_done,
        "countries_results": countries_results,
        "total_leads_all": total_leads_all,
        "leads": {
            "scraped": _count_leads("google_maps_results.json"),
            "qualified": _count_leads("qualified_leads.json"),
            "enriched": _count_leads("enriched_leads.json"),
        },
    }


@app.get("/api/usage")
def get_usage():
    tracker_data = _read_json(TMP_DIR / "api_tracker.json")
    calls = {}
    if tracker_data and "calls" in tracker_data:
        calls = tracker_data["calls"]
    else:
        merged = load_and_merge_tracker_snapshots()
        if merged.calls:
            calls = {
                label: {
                    "total": e["total"],
                    "success": e["success"],
                    "rate_limited": e["rate_limited"],
                    "server_errors": e.get("server_errors", 0),
                    "client_errors": e.get("client_errors", 0),
                    "network_errors": e.get("network_errors", 0),
                }
                for label, e in merged.calls.items()
            }

    usage = []
    seen = set()

    primary_apis = [
        "Serper Maps", "Serper OSINT", "Firecrawl scrape",
        "Anthropic classify", "Anthropic score",
        "Hunter domain-search", "Apollo people-search",
        "MillionVerifier",
        "HubSpot contact-search",
    ]

    for label in primary_apis:
        limits = API_LIMITS.get(label, {})
        call_data = calls.get(label, {})
        quota = limits.get("monthly_quota")
        used = call_data.get("success", 0)
        total_calls = call_data.get("total", 0)
        rate_limited = call_data.get("rate_limited", 0)
        errors = (
            call_data.get("server_errors", 0)
            + call_data.get("client_errors", 0)
            + call_data.get("network_errors", 0)
        )
        pct = round(used / quota * 100, 1) if quota and quota > 0 else None

        usage.append({
            "label": label,
            "quota": quota,
            "used": used,
            "total_calls": total_calls,
            "rate_limited": rate_limited,
            "errors": errors,
            "pct": pct,
            "shared_with": limits.get("shared_with"),
            "bottleneck": limits.get("bottleneck", False),
        })
        seen.add(label)

    # Aggregate per-URL entries (e.g. "Firecrawl scrape https://...") into parent
    AGGREGATE_PREFIXES = ["Firecrawl scrape ", "HubSpot "]
    for label, call_data in calls.items():
        if label in seen:
            continue
        parent = None
        for prefix in AGGREGATE_PREFIXES:
            if label.startswith(prefix) and label != prefix.strip():
                parent = prefix.strip()
                break
        if parent:
            match = next((u for u in usage if u["label"] == parent), None)
            if match:
                match["total_calls"] += call_data.get("total", 0)
                match["used"] += call_data.get("success", 0)
                match["rate_limited"] += call_data.get("rate_limited", 0)
                match["errors"] += (
                    call_data.get("server_errors", 0)
                    + call_data.get("client_errors", 0)
                    + call_data.get("network_errors", 0)
                )
                if match["quota"] and match["quota"] > 0:
                    match["pct"] = round(match["used"] / match["quota"] * 100, 1)
            continue
        limits = API_LIMITS.get(label, {})
        quota = limits.get("monthly_quota")
        used = call_data.get("success", 0)
        pct = round(used / quota * 100, 1) if quota and quota > 0 else None
        usage.append({
            "label": label,
            "quota": quota,
            "used": used,
            "total_calls": call_data.get("total", 0),
            "rate_limited": call_data.get("rate_limited", 0),
            "errors": (
                call_data.get("server_errors", 0)
                + call_data.get("client_errors", 0)
                + call_data.get("network_errors", 0)
            ),
            "pct": pct,
            "shared_with": limits.get("shared_with"),
            "bottleneck": limits.get("bottleneck", False),
        })

    return {"usage": usage, "timestamp": tracker_data.get("timestamp", "") if tracker_data else ""}


@app.get("/api/logs")
def get_logs(lines: int = 80):
    if not LOG_FILE.exists():
        return {"lines": [], "total": 0}
    try:
        with open(LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
            all_lines = f.readlines()
        tail = all_lines[-lines:] if len(all_lines) > lines else all_lines
        return {"lines": [l.rstrip("\n") for l in tail], "total": len(all_lines)}
    except OSError:
        return {"lines": [], "total": 0}


class LaunchRequest(BaseModel):
    industry: str
    countries: List[str]
    max_leads: int = 50


@app.post("/api/launch")
def launch_pipeline(req: LaunchRequest):
    if _is_pipeline_running():
        return JSONResponse(status_code=409, content={"error": "Pipeline already running"})

    TMP_DIR.mkdir(exist_ok=True)
    countries_str = ",".join(req.countries)
    cmd = (
        f'"{PYTHON}" "{PIPELINE_SCRIPT}" '
        f'--industry "{req.industry}" '
        f'--countries "{countries_str}" '
        f'--max_leads {req.max_leads} '
        f'--workers 1'
    )

    if sys.platform == "win32":
        subprocess.Popen(
            cmd, shell=True,
            stdout=open(LOG_FILE, "w", encoding="utf-8"),
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    else:
        os.system(f"cd {PROJECT_ROOT} && nohup {cmd} > {LOG_FILE} 2>&1 &")

    return {"ok": True, "industry": req.industry, "countries": req.countries, "max_leads": req.max_leads}


@app.post("/api/stop")
def stop_pipeline():
    pid = _is_pipeline_running()
    if not pid:
        return JSONResponse(status_code=404, content={"error": "No pipeline running"})
    try:
        os.kill(pid, signal.SIGTERM)
        return {"ok": True, "killed_pid": pid}
    except OSError as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


# ── HTML Dashboard ───────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def dashboard():
    return DASHBOARD_HTML


DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Figurative — Lead Gen Dashboard</title>
<style>
:root {
  --bg: #0f1117;
  --surface: #1a1d27;
  --surface2: #232733;
  --border: #2e3345;
  --text: #e4e6ed;
  --text2: #8b8fa3;
  --accent: #6c5ce7;
  --accent2: #a29bfe;
  --green: #00b894;
  --orange: #fdcb6e;
  --red: #e17055;
  --blue: #74b9ff;
  --radius: 10px;
}
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  background: var(--bg);
  color: var(--text);
  min-height: 100vh;
}
header {
  background: var(--surface);
  border-bottom: 1px solid var(--border);
  padding: 16px 32px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}
header h1 { font-size: 1.3rem; font-weight: 600; }
header h1 span { color: var(--accent2); }
.status-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 14px;
  border-radius: 20px;
  font-size: .8rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: .5px;
}
.status-pill .dot {
  width: 8px; height: 8px; border-radius: 50%;
}
.status-idle { background: #2e334520; color: var(--text2); }
.status-idle .dot { background: var(--text2); }
.status-running { background: #00b89420; color: var(--green); }
.status-running .dot { background: var(--green); animation: pulse 1.5s infinite; }
.status-paused { background: #fdcb6e20; color: var(--orange); }
.status-paused .dot { background: var(--orange); }
.status-finished { background: #6c5ce720; color: var(--accent2); }
.status-finished .dot { background: var(--accent2); }
@keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: .3; } }

.container {
  max-width: 1280px;
  margin: 0 auto;
  padding: 24px;
  display: grid;
  grid-template-columns: 340px 1fr;
  gap: 24px;
}
@media (max-width: 900px) {
  .container { grid-template-columns: 1fr; }
}
.card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 20px;
}
.card h2 {
  font-size: .85rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: .8px;
  color: var(--text2);
  margin-bottom: 16px;
}

/* ── Left column: Launch form ── */
.form-group { margin-bottom: 14px; }
.form-group label {
  display: block;
  font-size: .8rem;
  color: var(--text2);
  margin-bottom: 5px;
  font-weight: 500;
}
.form-group input[type="text"],
.form-group input[type="number"] {
  width: 100%;
  padding: 9px 12px;
  background: var(--surface2);
  border: 1px solid var(--border);
  border-radius: 6px;
  color: var(--text);
  font-size: .9rem;
  outline: none;
  transition: border .2s;
}
.form-group input:focus {
  border-color: var(--accent);
}
.country-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 4px 8px;
  max-height: 300px;
  overflow-y: auto;
  padding: 8px;
  background: var(--surface2);
  border-radius: 6px;
  border: 1px solid var(--border);
}
.country-grid label {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: .78rem;
  color: var(--text);
  cursor: pointer;
  padding: 2px 0;
}
.country-grid input[type="checkbox"] {
  accent-color: var(--accent);
}
.btn-row {
  display: flex;
  gap: 8px;
  margin-top: 16px;
}
button {
  flex: 1;
  padding: 10px 16px;
  border: none;
  border-radius: 6px;
  font-size: .85rem;
  font-weight: 600;
  cursor: pointer;
  transition: opacity .2s, transform .1s;
}
button:active { transform: scale(.97); }
.btn-launch {
  background: var(--accent);
  color: #fff;
}
.btn-launch:hover { opacity: .85; }
.btn-launch:disabled {
  opacity: .4;
  cursor: not-allowed;
}
.btn-stop {
  background: var(--red);
  color: #fff;
  flex: 0 0 auto;
  padding: 10px 20px;
}
.btn-stop:hover { opacity: .85; }
.btn-stop:disabled { opacity: .3; cursor: not-allowed; }
.select-actions {
  display: flex;
  gap: 8px;
  margin-bottom: 6px;
}
.select-actions button {
  flex: 0;
  padding: 3px 10px;
  font-size: .7rem;
  background: var(--surface2);
  color: var(--text2);
  border: 1px solid var(--border);
  border-radius: 4px;
}
.select-actions button:hover { color: var(--text); border-color: var(--accent); }

/* ── Right column ── */
.right-col { display: flex; flex-direction: column; gap: 24px; }

/* Progress */
.pipeline-info {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
  gap: 10px;
  margin-bottom: 16px;
}
.info-box {
  background: var(--surface2);
  border-radius: 8px;
  padding: 12px;
  text-align: center;
}
.info-box .value {
  font-size: 1.5rem;
  font-weight: 700;
  color: var(--accent2);
}
.info-box .label {
  font-size: .7rem;
  color: var(--text2);
  margin-top: 2px;
  text-transform: uppercase;
  letter-spacing: .5px;
}
.steps-track {
  display: flex;
  gap: 4px;
  margin-bottom: 8px;
}
.step-segment {
  flex: 1;
  height: 6px;
  border-radius: 3px;
  background: var(--surface2);
  position: relative;
  overflow: hidden;
  transition: background .4s;
}
.step-segment.done { background: var(--green); }
.step-segment.active {
  background: var(--surface2);
}
.step-segment.active::after {
  content: '';
  position: absolute;
  inset: 0;
  background: linear-gradient(90deg, var(--accent), var(--accent2));
  animation: progress-slide 1.5s ease-in-out infinite;
}
@keyframes progress-slide {
  0% { transform: translateX(-100%); }
  100% { transform: translateX(100%); }
}
.steps-labels {
  display: flex;
  gap: 4px;
}
.steps-labels span {
  flex: 1;
  text-align: center;
  font-size: .65rem;
  color: var(--text2);
}
.steps-labels span.done { color: var(--green); }
.steps-labels span.active { color: var(--accent2); font-weight: 600; }
.meta-line {
  margin-top: 12px;
  font-size: .78rem;
  color: var(--text2);
  line-height: 1.6;
}
.meta-line strong { color: var(--text); }
.pause-banner {
  background: #fdcb6e15;
  border: 1px solid #fdcb6e40;
  border-radius: 6px;
  padding: 10px 14px;
  margin-top: 10px;
  font-size: .8rem;
  color: var(--orange);
}

/* API Usage */
.api-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(250px, 1fr));
  gap: 12px;
}
.api-card {
  background: var(--surface2);
  border-radius: 8px;
  padding: 14px;
}
.api-card .api-name {
  font-size: .8rem;
  font-weight: 600;
  margin-bottom: 8px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.api-card .api-name .tag {
  font-size: .6rem;
  padding: 2px 6px;
  border-radius: 3px;
  font-weight: 600;
}
.tag-bottleneck { background: #e1705530; color: var(--red); }
.tag-shared { background: #74b9ff25; color: var(--blue); }
.gauge-bar {
  height: 8px;
  background: var(--border);
  border-radius: 4px;
  overflow: hidden;
  margin-bottom: 6px;
}
.gauge-fill {
  height: 100%;
  border-radius: 4px;
  transition: width .6s ease;
}
.gauge-green { background: var(--green); }
.gauge-orange { background: var(--orange); }
.gauge-red { background: var(--red); }
.api-stats {
  display: flex;
  justify-content: space-between;
  font-size: .7rem;
  color: var(--text2);
}
.api-stats .err { color: var(--red); }

/* Country progress */
.country-track {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 14px;
}
.country-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 5px 12px;
  border-radius: 6px;
  font-size: .75rem;
  font-weight: 500;
  background: var(--surface2);
  color: var(--text2);
  border: 1px solid var(--border);
}
.country-chip.done {
  background: #00b89418;
  color: var(--green);
  border-color: #00b89440;
}
.country-chip.active {
  background: #6c5ce718;
  color: var(--accent2);
  border-color: #6c5ce740;
}
.country-chip .chip-icon { font-size: .7rem; }
.country-chip .chip-count {
  font-weight: 700;
  margin-left: 2px;
}

/* Logs */
.log-box {
  background: #0a0c10;
  border-radius: 6px;
  padding: 12px;
  font-family: 'Cascadia Code', 'Fira Code', 'Consolas', monospace;
  font-size: .72rem;
  line-height: 1.55;
  max-height: 320px;
  overflow-y: auto;
  color: #9ca3af;
  white-space: pre-wrap;
  word-break: break-all;
}
.log-box::-webkit-scrollbar { width: 6px; }
.log-box::-webkit-scrollbar-track { background: transparent; }
.log-box::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }

.toast {
  position: fixed;
  bottom: 24px;
  right: 24px;
  padding: 12px 20px;
  border-radius: 8px;
  font-size: .85rem;
  font-weight: 500;
  color: #fff;
  z-index: 100;
  opacity: 0;
  transform: translateY(10px);
  transition: all .3s;
  pointer-events: none;
}
.toast.show { opacity: 1; transform: translateY(0); }
.toast-ok { background: var(--green); }
.toast-err { background: var(--red); }
</style>
</head>
<body>

<header>
  <h1><span>Figurative</span> — Lead Gen Dashboard</h1>
  <div id="statusPill" class="status-pill status-idle">
    <span class="dot"></span>
    <span id="statusText">Idle</span>
  </div>
</header>

<div class="container">
  <!-- LEFT COLUMN -->
  <div class="left-col">
    <div class="card">
      <h2>Nouvelle prospection</h2>
      <div class="form-group">
        <label for="industry">Industrie</label>
        <input type="text" id="industry" placeholder="ex: Saunas, Jacuzzis">
      </div>
      <div class="form-group">
        <label>Pays</label>
        <div class="select-actions">
          <button type="button" onclick="toggleAll(true)">Tout</button>
          <button type="button" onclick="toggleAll(false)">Aucun</button>
          <button type="button" onclick="toggleEU()">UE</button>
        </div>
        <div class="country-grid" id="countryGrid"></div>
      </div>
      <div class="form-group">
        <label for="maxLeads">Max leads par pays</label>
        <div style="display:flex;align-items:center;gap:10px">
          <input type="number" id="maxLeads" value="50" min="1" max="9999" style="flex:1">
          <label style="display:flex;align-items:center;gap:5px;font-size:.78rem;color:var(--text2);cursor:pointer;white-space:nowrap">
            <input type="checkbox" id="noLimit" onchange="toggleNoLimit()" style="accent-color:var(--accent)"> Pas de limite
          </label>
        </div>
      </div>
      <div class="btn-row">
        <button class="btn-launch" id="btnLaunch" onclick="launchPipeline()">Lancer</button>
        <button class="btn-stop" id="btnStop" onclick="stopPipeline()" disabled>Stop</button>
      </div>
    </div>
  </div>

  <!-- RIGHT COLUMN -->
  <div class="right-col">
    <div class="card">
      <h2>Progression du pipeline</h2>
      <div class="country-track" id="countryTrack"></div>
      <div class="pipeline-info">
        <div class="info-box"><div class="value" id="cntScraped">—</div><div class="label">Scrapes</div></div>
        <div class="info-box"><div class="value" id="cntQualified">—</div><div class="label">Qualifies</div></div>
        <div class="info-box"><div class="value" id="cntEnriched">—</div><div class="label">Enrichis</div></div>
        <div class="info-box"><div class="value" id="cntStep">—</div><div class="label">Etape</div></div>
      </div>
      <div class="steps-track" id="stepsTrack"></div>
      <div class="steps-labels" id="stepsLabels"></div>
      <div class="meta-line" id="metaLine"></div>
      <div class="pause-banner" id="pauseBanner" style="display:none"></div>
    </div>

    <div class="card">
      <h2>Utilisation API</h2>
      <div class="api-grid" id="apiGrid"></div>
    </div>

    <div class="card">
      <h2>Logs pipeline</h2>
      <div class="log-box" id="logBox">En attente...</div>
    </div>
  </div>
</div>

<div class="toast" id="toast"></div>

<script>
const COUNTRIES = [
  {name:"France",eu:true},{name:"Allemagne",eu:true},{name:"Belgique",eu:true},
  {name:"Pays-Bas",eu:true},{name:"Luxembourg",eu:true},{name:"Italie",eu:true},
  {name:"Espagne",eu:true},{name:"Portugal",eu:true},{name:"Autriche",eu:true},
  {name:"Irlande",eu:true},{name:"Grece",eu:true},{name:"Finlande",eu:true},
  {name:"Danemark",eu:true},{name:"Suede",eu:true},{name:"Pologne",eu:true},
  {name:"Roumanie",eu:true},{name:"Hongrie",eu:true},{name:"Republique Tcheque",eu:true},
  {name:"Bulgarie",eu:true},{name:"Croatie",eu:true},{name:"Slovaquie",eu:true},
  {name:"Slovenie",eu:true},{name:"Estonie",eu:true},{name:"Lettonie",eu:true},
  {name:"Lituanie",eu:true},{name:"Chypre",eu:true},{name:"Malte",eu:true},
  {name:"Suisse",eu:false},{name:"Norvege",eu:false},{name:"Royaume-Uni",eu:false},
  {name:"Etats-Unis",eu:false},
];

const EU_SET = new Set(COUNTRIES.filter(c=>c.eu).map(c=>c.name));

function buildCountryGrid(){
  const g = document.getElementById('countryGrid');
  COUNTRIES.forEach(c => {
    const lbl = document.createElement('label');
    lbl.innerHTML = `<input type="checkbox" value="${c.name}"> ${c.name}`;
    g.appendChild(lbl);
  });
}
buildCountryGrid();

function getSelectedCountries(){
  return [...document.querySelectorAll('#countryGrid input:checked')].map(i=>i.value);
}
function toggleAll(on){
  document.querySelectorAll('#countryGrid input').forEach(i=>i.checked=on);
}
function toggleEU(){
  document.querySelectorAll('#countryGrid input').forEach(i=>{
    i.checked = EU_SET.has(i.value);
  });
}

function toggleNoLimit(){
  const cb = document.getElementById('noLimit');
  const inp = document.getElementById('maxLeads');
  if(cb.checked){
    inp.disabled = true;
    inp.dataset.prev = inp.value;
    inp.value = '';
    inp.placeholder = 'Illimite';
  } else {
    inp.disabled = false;
    inp.value = inp.dataset.prev || '50';
    inp.placeholder = '';
  }
}

function showToast(msg, ok=true){
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.className = 'toast show ' + (ok ? 'toast-ok' : 'toast-err');
  setTimeout(()=>{ t.className = 'toast'; }, 3000);
}

async function launchPipeline(){
  const industry = document.getElementById('industry').value.trim();
  const countries = getSelectedCountries();
  const noLimit = document.getElementById('noLimit').checked;
  const maxLeads = noLimit ? 9999 : (parseInt(document.getElementById('maxLeads').value) || 50);
  if(!industry){ showToast('Industrie requise', false); return; }
  if(!countries.length){ showToast('Selectionner au moins un pays', false); return; }
  document.getElementById('btnLaunch').disabled = true;
  try {
    const r = await fetch('/api/launch', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({industry, countries, max_leads: maxLeads})
    });
    const d = await r.json();
    if(r.ok){
      showToast(`Pipeline lance : ${industry} — ${countries.join(', ')}`);
    } else {
      showToast(d.error || 'Erreur', false);
    }
  } catch(e){
    showToast('Erreur reseau', false);
  }
  setTimeout(()=>{ document.getElementById('btnLaunch').disabled = false; }, 2000);
}

async function stopPipeline(){
  if(!confirm('Arreter le pipeline en cours ?')) return;
  try {
    const r = await fetch('/api/stop', {method:'POST'});
    const d = await r.json();
    if(r.ok) showToast('Pipeline arrete (PID '+d.killed_pid+')');
    else showToast(d.error || 'Erreur', false);
  } catch(e){
    showToast('Erreur reseau', false);
  }
}

const STEP_ALL = [
  {key:'step1_expand', label:'Scrape + Dedup'},
  {key:'step2_qualify', label:'Qualification'},
  {key:'step3_enrich', label:'Enrichissement'},
  {key:'step3c_score', label:'Scoring'},
  {key:'step4_hubspot', label:'Sync HubSpot'},
  {key:'step5_backup', label:'Backup'},
];

function renderSteps(completed, status){
  const track = document.getElementById('stepsTrack');
  const labels = document.getElementById('stepsLabels');
  track.innerHTML = '';
  labels.innerHTML = '';
  const doneSet = new Set(completed);
  const doneCount = completed.length;
  STEP_ALL.forEach((s, i) => {
    const seg = document.createElement('div');
    seg.className = 'step-segment';
    if(doneSet.has(s.key)) seg.classList.add('done');
    else if(i === doneCount && status === 'running') seg.classList.add('active');
    track.appendChild(seg);
    const lbl = document.createElement('span');
    lbl.textContent = s.label;
    if(doneSet.has(s.key)) lbl.classList.add('done');
    else if(i === doneCount && status === 'running') lbl.classList.add('active');
    labels.appendChild(lbl);
  });
}

function updateStatus(d){
  const pill = document.getElementById('statusPill');
  const txt = document.getElementById('statusText');
  const labels = {idle:'Idle', running:'En cours', paused:'En pause', finished:'Termine', completed:'Termine'};
  const pillClass = d.status === 'completed' ? 'finished' : d.status;
  pill.className = 'status-pill status-' + pillClass;
  txt.textContent = labels[d.status] || d.status;

  document.getElementById('btnStop').disabled = d.status !== 'running';

  // Show total leads across all countries when available
  const totalAll = d.total_leads_all || 0;
  document.getElementById('cntScraped').textContent = d.leads.scraped || '—';
  document.getElementById('cntQualified').textContent = d.leads.qualified || '—';
  document.getElementById('cntEnriched').textContent = d.leads.enriched || '—';

  const isActive = d.status === 'running' || d.status === 'paused';
  document.getElementById('cntStep').textContent =
    (d.status === 'idle') ? '—' :
    (d.status === 'completed' || d.status === 'finished')
      ? (totalAll > 0 ? totalAll : '—')
      : `${d.current_step_index}/${d.total_steps}`;

  // Update step counter label for completed state
  const stepLabel = document.querySelector('#cntStep + .label');
  if(stepLabel) stepLabel.textContent =
    (d.status === 'completed' || d.status === 'finished') && totalAll > 0
      ? 'TOTAL LEADS' : 'ETAPE';

  renderSteps(d.steps_completed, d.status);
  renderCountryChips(d);

  const meta = document.getElementById('metaLine');
  if(d.industry){
    let txt = `<strong>Industrie :</strong> ${d.industry}`;
    if(d.countries && d.countries.length){
      txt += ` &nbsp;|&nbsp; <strong>Pays :</strong> ${d.countries.join(', ')}`;
    } else if(d.location){
      txt += ` &nbsp;|&nbsp; <strong>Pays :</strong> ${d.location}`;
    }
    if(d.max_leads) txt += ` &nbsp;|&nbsp; <strong>Max :</strong> ${d.max_leads >= 9999 ? 'Illimite' : d.max_leads}`;
    if(d.finished_at) txt += `<br><strong>Termine :</strong> ${d.finished_at}`;
    else if(d.last_updated) txt += `<br><strong>Maj :</strong> ${d.last_updated}`;
    meta.innerHTML = txt;
  } else {
    meta.innerHTML = '<em>Aucun pipeline actif</em>';
  }

  const banner = document.getElementById('pauseBanner');
  if(d.status === 'paused' && d.pause_reason){
    banner.style.display = 'block';
    banner.innerHTML = `En pause — <strong>${d.pause_reason}</strong>` +
      (d.paused_at ? ` depuis ${d.paused_at}` : '');
  } else {
    banner.style.display = 'none';
  }
}

function renderCountryChips(d){
  const track = document.getElementById('countryTrack');
  const countries = d.countries || [];
  if(!countries.length){ track.innerHTML = ''; return; }
  const doneSet = new Set(d.countries_done || []);
  const results = d.countries_results || {};
  const current = d.location || '';
  track.innerHTML = countries.map(c => {
    const isDone = doneSet.has(c);
    const isActive = (c === current && d.status === 'running');
    const cls = isDone ? 'done' : (isActive ? 'active' : '');
    const icon = isDone ? '&#10003;' : (isActive ? '&#9654;' : '&#9679;');
    const count = isDone && results[c] !== undefined ? `<span class="chip-count">${results[c]}</span>` : '';
    return `<div class="country-chip ${cls}"><span class="chip-icon">${icon}</span>${c}${count}</div>`;
  }).join('');
}

function renderUsage(items){
  const grid = document.getElementById('apiGrid');
  grid.innerHTML = '';
  items.forEach(a => {
    const card = document.createElement('div');
    card.className = 'api-card';
    let tags = '';
    if(a.bottleneck) tags += '<span class="tag tag-bottleneck">BOTTLENECK</span>';
    if(a.shared_with) tags += `<span class="tag tag-shared">= ${a.shared_with}</span>`;
    const pct = a.pct !== null ? a.pct : 0;
    const color = pct >= 80 ? 'red' : (pct >= 50 ? 'orange' : 'green');
    const quotaTxt = a.quota ? a.quota.toLocaleString() : 'illimite';
    const errTxt = a.rate_limited > 0
      ? `<span class="err">${a.rate_limited} x 429</span>`
      : (a.errors > 0 ? `<span class="err">${a.errors} err</span>` : '');
    card.innerHTML = `
      <div class="api-name">${a.label} ${tags}</div>
      <div class="gauge-bar"><div class="gauge-fill gauge-${color}" style="width:${a.quota ? pct : 0}%"></div></div>
      <div class="api-stats">
        <span>${a.used} / ${quotaTxt}</span>
        <span>${a.quota ? pct+'%' : '—'}</span>
        ${errTxt}
      </div>`;
    grid.appendChild(card);
  });
}

function renderLogs(lines){
  const box = document.getElementById('logBox');
  if(!lines.length){
    box.textContent = 'Aucun log disponible.';
    return;
  }
  box.textContent = lines.join('\n');
  box.scrollTop = box.scrollHeight;
}

async function refresh(){
  try {
    const [statusR, usageR, logsR] = await Promise.all([
      fetch('/api/status'), fetch('/api/usage'), fetch('/api/logs?lines=60')
    ]);
    const [statusD, usageD, logsD] = await Promise.all([
      statusR.json(), usageR.json(), logsR.json()
    ]);
    updateStatus(statusD);
    renderUsage(usageD.usage || []);
    renderLogs(logsD.lines || []);
  } catch(e){
    console.error('Refresh error:', e);
  }
}

refresh();
setInterval(refresh, 5000);
</script>
</body>
</html>"""


# ── Entrypoint ───────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    TMP_DIR.mkdir(exist_ok=True)
    print(f"Dashboard: http://0.0.0.0:8080")
    uvicorn.run(app, host="0.0.0.0", port=8080, log_level="info")
