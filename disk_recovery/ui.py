"""
ui.py — Webové UI pre disk recovery systém

Spustenie:
  cd disk_recovery
  python3 ui.py

Otvor v prehliadači: http://localhost:5000
"""

import json
import os
import queue
import subprocess
import sys
import threading
from pathlib import Path
from flask import Flask, Response, jsonify, render_template_string, request

app = Flask(__name__)

# ── HTML template ────────────────────────────────────────────────────────────

HTML = """
<!DOCTYPE html>
<html lang="sk">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Disk Recovery AI</title>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

  body {
    font-family: 'Segoe UI', system-ui, sans-serif;
    background: #0f1117;
    color: #e2e8f0;
    min-height: 100vh;
    display: flex;
    flex-direction: column;
  }

  header {
    background: #1a1d2e;
    border-bottom: 1px solid #2d3150;
    padding: 1rem 2rem;
    display: flex;
    align-items: center;
    gap: 0.75rem;
  }
  header h1 { font-size: 1.25rem; font-weight: 600; color: #a78bfa; }
  header span { font-size: 0.8rem; color: #64748b; }

  .badge {
    display: inline-flex; align-items: center; gap: 0.3rem;
    font-size: 0.7rem; padding: 0.2rem 0.6rem;
    border-radius: 9999px; font-weight: 600;
  }
  .badge-ai   { background: #312e81; color: #a5b4fc; }
  .badge-apfs { background: #1e3a5f; color: #7dd3fc; }

  main {
    flex: 1;
    display: grid;
    grid-template-columns: 380px 1fr;
    gap: 0;
    overflow: hidden;
  }

  /* ── Left panel ── */
  .panel {
    background: #1a1d2e;
    border-right: 1px solid #2d3150;
    padding: 1.5rem;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    gap: 1.25rem;
  }

  .section-title {
    font-size: 0.7rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: #64748b;
    margin-bottom: 0.5rem;
  }

  label { font-size: 0.85rem; color: #94a3b8; display: block; margin-bottom: 0.35rem; }

  input[type=text], select {
    width: 100%;
    background: #0f1117;
    border: 1px solid #2d3150;
    border-radius: 6px;
    color: #e2e8f0;
    padding: 0.5rem 0.75rem;
    font-size: 0.9rem;
    outline: none;
    transition: border-color 0.15s;
  }
  input[type=text]:focus, select:focus { border-color: #7c3aed; }

  .toggle-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0.5rem 0;
    border-bottom: 1px solid #2d3150;
  }
  .toggle-row:last-child { border-bottom: none; }
  .toggle-label { font-size: 0.85rem; color: #cbd5e1; }
  .toggle-desc  { font-size: 0.75rem; color: #475569; margin-top: 0.1rem; }

  /* Toggle switch */
  .switch { position: relative; width: 36px; height: 20px; flex-shrink: 0; }
  .switch input { opacity: 0; width: 0; height: 0; }
  .slider {
    position: absolute; inset: 0;
    background: #334155; border-radius: 20px;
    cursor: pointer; transition: background 0.2s;
  }
  .slider::before {
    content: ''; position: absolute;
    width: 14px; height: 14px;
    left: 3px; top: 3px;
    background: white; border-radius: 50%;
    transition: transform 0.2s;
  }
  input:checked + .slider { background: #7c3aed; }
  input:checked + .slider::before { transform: translateX(16px); }

  /* Buttons */
  .btn {
    width: 100%; padding: 0.65rem 1rem;
    border: none; border-radius: 8px;
    font-size: 0.9rem; font-weight: 600;
    cursor: pointer; transition: opacity 0.15s, transform 0.1s;
  }
  .btn:active { transform: scale(0.98); }
  .btn:disabled { opacity: 0.4; cursor: not-allowed; transform: none; }
  .btn-primary { background: #7c3aed; color: white; }
  .btn-primary:hover:not(:disabled) { background: #6d28d9; }
  .btn-danger  { background: #991b1b; color: white; }
  .btn-danger:hover:not(:disabled) { background: #7f1d1d; }

  /* Status bar */
  .status-bar {
    display: flex; align-items: center; gap: 0.5rem;
    padding: 0.6rem 0.75rem;
    background: #0f1117;
    border: 1px solid #2d3150;
    border-radius: 6px;
    font-size: 0.8rem;
  }
  .dot {
    width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0;
    background: #334155;
  }
  .dot.idle    { background: #334155; }
  .dot.running { background: #f59e0b; animation: pulse 1s infinite; }
  .dot.done    { background: #10b981; }
  .dot.error   { background: #ef4444; }
  @keyframes pulse { 0%,100% { opacity:1; } 50% { opacity:0.4; } }

  /* ── Right panel: terminal ── */
  .terminal-wrap {
    display: flex;
    flex-direction: column;
    overflow: hidden;
    background: #0a0c14;
  }

  .terminal-header {
    background: #111827;
    border-bottom: 1px solid #1f2937;
    padding: 0.5rem 1rem;
    display: flex;
    align-items: center;
    justify-content: space-between;
    flex-shrink: 0;
  }
  .terminal-title { font-size: 0.75rem; color: #6b7280; font-family: monospace; }

  .terminal {
    flex: 1;
    overflow-y: auto;
    padding: 1rem 1.25rem;
    font-family: 'JetBrains Mono', 'Fira Code', 'Cascadia Code', monospace;
    font-size: 0.8rem;
    line-height: 1.6;
    color: #d1d5db;
    scroll-behavior: smooth;
  }

  .log-line { white-space: pre-wrap; word-break: break-all; }
  .log-line.info    { color: #d1d5db; }
  .log-line.phase   { color: #a78bfa; font-weight: 600; }
  .log-line.ok      { color: #34d399; }
  .log-line.warn    { color: #fbbf24; }
  .log-line.error   { color: #f87171; }
  .log-line.sep     { color: #374151; }
  .log-line.agent   { color: #7dd3fc; }
  .log-line.think   { color: #6366f1; font-style: italic; }
  .log-line.saved   { color: #86efac; }

  /* Results panel */
  .results {
    border-top: 1px solid #1f2937;
    padding: 1rem 1.25rem;
    background: #0f1117;
    flex-shrink: 0;
    max-height: 180px;
    overflow-y: auto;
    display: none;
  }
  .results.visible { display: block; }
  .results h3 { font-size: 0.75rem; color: #64748b; text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 0.75rem; }
  .result-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 0.5rem; }
  .result-card {
    background: #1a1d2e;
    border: 1px solid #2d3150;
    border-radius: 6px;
    padding: 0.6rem 0.75rem;
  }
  .result-card .rc-label { font-size: 0.7rem; color: #64748b; }
  .result-card .rc-value { font-size: 0.95rem; font-weight: 600; color: #e2e8f0; }
  .result-card .rc-sub   { font-size: 0.7rem; color: #94a3b8; margin-top: 0.1rem; }

  /* Clear btn */
  .btn-sm {
    padding: 0.25rem 0.6rem; font-size: 0.75rem;
    border: 1px solid #2d3150; border-radius: 4px;
    background: transparent; color: #64748b;
    cursor: pointer;
  }
  .btn-sm:hover { background: #1f2937; color: #94a3b8; }
</style>
</head>
<body>

<header>
  <h1>🔍 Disk Recovery AI</h1>
  <span class="badge badge-ai">Claude Opus 4.8</span>
  <span class="badge badge-apfs">APFS</span>
  <span style="margin-left:auto; font-size:0.8rem; color:#475569">Multi-agent systém obnovy dát</span>
</header>

<main>
  <!-- ── Left panel ── -->
  <div class="panel">

    <div>
      <div class="section-title">Zariadenie / Image</div>
      <label>Cesta k disku alebo .img súboru</label>
      <input type="text" id="device" placeholder="/dev/sdb  alebo  disk.img" value="disk_recovery/test_disk.img">
    </div>

    <div>
      <label>Výstupný adresár</label>
      <input type="text" id="output" value="./recovered">
    </div>

    <div>
      <label>Maximálny rozsah skenu (prázdne = celý disk)</label>
      <input type="text" id="maxScan" placeholder="napr. 500M, 2G">
    </div>

    <div>
      <div class="section-title">Možnosti</div>
      <div class="toggle-row">
        <div>
          <div class="toggle-label">Dry-run</div>
          <div class="toggle-desc">Len analýza, žiadna fyzická obnova</div>
        </div>
        <label class="switch">
          <input type="checkbox" id="dryRun" checked>
          <span class="slider"></span>
        </label>
      </div>
      <div class="toggle-row">
        <div>
          <div class="toggle-label">Preskočiť skenovanie</div>
          <div class="toggle-desc">Načítať existujúci scan JSON</div>
        </div>
        <label class="switch">
          <input type="checkbox" id="skipScan" onchange="toggleLoadScan()">
          <span class="slider"></span>
        </label>
      </div>
      <div id="loadScanRow" style="display:none; padding-top:0.5rem;">
        <label>Cesta k scan JSON</label>
        <input type="text" id="loadScan" placeholder="./recovered/scan_*.json">
      </div>
    </div>

    <div>
      <div class="section-title">Stav</div>
      <div class="status-bar">
        <div class="dot idle" id="statusDot"></div>
        <span id="statusText">Pripravený</span>
      </div>
    </div>

    <button class="btn btn-primary" id="startBtn" onclick="startRecovery()">▶ Spustiť obnovu</button>
    <button class="btn btn-danger" id="stopBtn" onclick="stopRecovery()" disabled>■ Zastaviť</button>

  </div>

  <!-- ── Right panel ── -->
  <div class="terminal-wrap">
    <div class="terminal-header">
      <span class="terminal-title">● výstup procesu</span>
      <button class="btn-sm" onclick="clearTerminal()">Vymazať</button>
    </div>

    <div class="terminal" id="terminal">
      <div class="log-line info">Vitaj v Disk Recovery AI systéme.</div>
      <div class="log-line info">Nastav parametre vľavo a klikni ▶ Spustiť obnovu.</div>
    </div>

    <div class="results" id="resultsPanel">
      <h3>Výsledky</h3>
      <div class="result-grid" id="resultGrid"></div>
    </div>
  </div>
</main>

<script>
let evtSource = null;
let running = false;

function toggleLoadScan() {
  const show = document.getElementById('skipScan').checked;
  document.getElementById('loadScanRow').style.display = show ? 'block' : 'none';
}

function setStatus(state, text) {
  const dot = document.getElementById('statusDot');
  dot.className = 'dot ' + state;
  document.getElementById('statusText').textContent = text;
}

function appendLine(text, cls = 'info') {
  const t = document.getElementById('terminal');
  const div = document.createElement('div');
  div.className = 'log-line ' + cls;
  div.textContent = text;
  t.appendChild(div);
  t.scrollTop = t.scrollHeight;
}

function clearTerminal() {
  document.getElementById('terminal').innerHTML = '';
}

function classifyLine(line) {
  if (line.startsWith('[Fáza') || line.startsWith('===') || line.startsWith('---'))
    return 'phase';
  if (line.includes('[Agent') || line.includes('Agent '))
    return 'agent';
  if (line.includes('thinking') || line.includes('Analyst thinking') || line.includes('Predictor thinking') || line.includes('Planner thinking'))
    return 'think';
  if (line.includes('→ uložené') || line.includes('Hotovo'))
    return 'saved';
  if (line.includes('[WARN]') || line.includes('⚠'))
    return 'warn';
  if (line.includes('[CHYBA]') || line.includes('Error') || line.includes('error'))
    return 'error';
  if (line.startsWith('  →') || line.startsWith('  Hotovo'))
    return 'ok';
  return 'info';
}

function startRecovery() {
  if (running) return;

  const params = new URLSearchParams({
    device:   document.getElementById('device').value.trim(),
    output:   document.getElementById('output').value.trim(),
    max_scan: document.getElementById('maxScan').value.trim(),
    dry_run:  document.getElementById('dryRun').checked ? '1' : '0',
    load_scan: document.getElementById('skipScan').checked
                 ? document.getElementById('loadScan').value.trim() : '',
  });

  clearTerminal();
  document.getElementById('resultsPanel').classList.remove('visible');
  document.getElementById('startBtn').disabled = true;
  document.getElementById('stopBtn').disabled = false;
  setStatus('running', 'Prebieha obnova…');
  running = true;

  evtSource = new EventSource('/run?' + params.toString());

  evtSource.addEventListener('line', e => {
    const line = e.data;
    appendLine(line, classifyLine(line));
  });

  evtSource.addEventListener('result', e => {
    try {
      const data = JSON.parse(e.data);
      showResults(data);
    } catch {}
  });

  evtSource.addEventListener('done', e => {
    finish('done', e.data || 'Dokončené');
  });

  evtSource.addEventListener('error_msg', e => {
    appendLine('CHYBA: ' + e.data, 'error');
    finish('error', 'Chyba');
  });

  evtSource.onerror = () => {
    if (running) finish('error', 'Spojenie prerušené');
  };
}

function stopRecovery() {
  if (evtSource) { evtSource.close(); evtSource = null; }
  fetch('/stop', { method: 'POST' });
  finish('idle', 'Zastavené');
}

function finish(state, text) {
  running = false;
  if (evtSource) { evtSource.close(); evtSource = null; }
  document.getElementById('startBtn').disabled = false;
  document.getElementById('stopBtn').disabled = true;
  setStatus(state, text);
}

function showResults(data) {
  const grid = document.getElementById('resultGrid');
  grid.innerHTML = '';
  const items = [
    { label: 'Signatúr',        value: data.signatures    ?? '—', sub: 'nájdených' },
    { label: 'Partícií (AI)',   value: data.partitions    ?? '—', sub: 'odhadovaných' },
    { label: 'Pred. regiónov',  value: data.pred_regions  ?? '—', sub: '' },
    { label: 'Akcií v pláne',   value: data.actions       ?? '—', sub: '' },
    { label: 'Odhad obnovy',    value: data.recovery_rate ?? '—', sub: '' },
    { label: 'Výstup',          value: data.output_dir    ?? '—', sub: '' },
  ];
  items.forEach(it => {
    grid.innerHTML += `<div class="result-card">
      <div class="rc-label">${it.label}</div>
      <div class="rc-value">${it.value}</div>
      ${it.sub ? '<div class="rc-sub">' + it.sub + '</div>' : ''}
    </div>`;
  });
  document.getElementById('resultsPanel').classList.add('visible');
}
</script>
</body>
</html>
"""

# ── Flask routes ─────────────────────────────────────────────────────────────

_proc: subprocess.Popen | None = None
_lock = threading.Lock()


@app.get("/")
def index():
    return render_template_string(HTML)


@app.get("/run")
def run():
    global _proc

    device    = request.args.get("device", "")
    output    = request.args.get("output", "./recovered")
    max_scan  = request.args.get("max_scan", "").strip()
    dry_run   = request.args.get("dry_run", "0") == "1"
    load_scan = request.args.get("load_scan", "").strip()

    if not device:
        return Response("data: missing device\n\n", mimetype="text/event-stream")

    cmd = [
        sys.executable, "-u",
        str(Path(__file__).parent / "orchestrator.py"),
        "--device", device,
        "--output", output,
    ]
    if max_scan:
        cmd += ["--max-scan", max_scan]
    if dry_run:
        cmd.append("--dry-run")
    if load_scan:
        cmd += ["--load-scan", load_scan]

    def generate():
        global _proc
        env = os.environ.copy()

        with _lock:
            try:
                _proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    env=env,
                    cwd=str(Path(__file__).parent),
                )
            except Exception as e:
                yield f"event: error_msg\ndata: {e}\n\n"
                return

        # Summary stats collected while streaming
        stats: dict = {}
        sig_count = part_count = region_count = action_count = 0
        recovery_rate = ""

        for line in _proc.stdout:
            line = line.rstrip("\n")
            yield f"event: line\ndata: {line}\n\n"

            # Harvest stats from output
            if "nájdených" in line and "signátur" in line:
                try:
                    sig_count = int([t for t in line.split() if t.isdigit()][0])
                except Exception:
                    pass
            if "partícií" in line.lower() and "AI" in line:
                try:
                    part_count = int(line.split()[1])
                except Exception:
                    pass
            if "Predikované regióny:" in line:
                try:
                    region_count = int(line.split("regióny:")[1].split(",")[0].strip())
                except Exception:
                    pass
            if "Akcií v pláne:" in line:
                try:
                    action_count = int(line.split(":")[1].strip())
                except Exception:
                    pass
            if "Odhadov. obnova:" in line or "Odhadovaná obnova:" in line:
                recovery_rate = line.split(":", 1)[-1].strip()

        _proc.wait()
        stats = {
            "signatures":    sig_count,
            "partitions":    part_count,
            "pred_regions":  region_count,
            "actions":       action_count,
            "recovery_rate": recovery_rate,
            "output_dir":    output,
        }
        yield f"event: result\ndata: {json.dumps(stats)}\n\n"
        rc = _proc.returncode
        msg = "Úspešne dokončené ✓" if rc == 0 else f"Ukončené s kódom {rc}"
        yield f"event: done\ndata: {msg}\n\n"

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/stop")
def stop():
    global _proc
    with _lock:
        if _proc and _proc.poll() is None:
            _proc.terminate()
    return jsonify({"ok": True})


# ── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"\n  Disk Recovery UI beží na  http://localhost:{port}\n")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
