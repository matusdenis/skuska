"""
ui.py — Webové UI pre disk recovery systém

Spustenie:
  cd disk_recovery
  python3 ui.py

Otvor v prehliadači: http://localhost:5000
"""

import json
import os
import platform
import re
import subprocess
import sys
import threading
from pathlib import Path
from flask import Flask, Response, jsonify, render_template_string, request

app = Flask(__name__)


# ── Disk detection ────────────────────────────────────────────────────────────

def list_disks() -> list[dict]:
    """Vráti zoznam fyzických diskov a .img súborov."""
    disks = []
    system = platform.system()

    if system == "Linux":
        try:
            out = subprocess.check_output(
                ["lsblk", "-J", "-o", "NAME,SIZE,TYPE,MODEL,TRAN,MOUNTPOINT"],
                text=True, stderr=subprocess.DEVNULL,
            )
            data = json.loads(out)
            for dev in data.get("blockdevices", []):
                if dev.get("type") in ("disk", "loop"):
                    name = dev["name"]
                    path = f"/dev/{name}"
                    model = (dev.get("model") or "").strip() or name
                    size  = dev.get("size", "?")
                    tran  = dev.get("tran") or "—"
                    disks.append({
                        "path":  path,
                        "label": f"{path}  [{size}]  {model}  ({tran})",
                        "size":  size,
                        "type":  "disk",
                    })
        except Exception:
            # Fallback: /proc/partitions
            try:
                with open("/proc/partitions") as f:
                    for line in f:
                        parts = line.split()
                        if len(parts) == 4 and parts[3].startswith("sd"):
                            name = parts[3]
                            disks.append({
                                "path":  f"/dev/{name}",
                                "label": f"/dev/{name}",
                                "size":  "",
                                "type":  "disk",
                            })
            except Exception:
                pass

    elif system == "Darwin":  # macOS
        try:
            out = subprocess.check_output(
                ["diskutil", "list", "-plist"],
                text=True, stderr=subprocess.DEVNULL,
            )
            # Parse plist output
            import plistlib
            data = plistlib.loads(out.encode())
            for disk in data.get("WholeDisks", []):
                info_raw = subprocess.check_output(
                    ["diskutil", "info", "-plist", disk],
                    text=True, stderr=subprocess.DEVNULL,
                )
                info = plistlib.loads(info_raw.encode())
                path  = info.get("DeviceNode", f"/dev/{disk}")
                model = info.get("MediaName", disk)
                size  = info.get("TotalSize", 0)
                size_h = _human(size) if isinstance(size, int) else "?"
                disks.append({
                    "path":  path,
                    "label": f"{path}  [{size_h}]  {model}",
                    "size":  size_h,
                    "type":  "disk",
                })
        except Exception:
            pass

    # Disk images in current working tree
    cwd = Path(__file__).parent.parent
    for img in sorted(cwd.rglob("*.img"))[:20]:
        rel = str(img.relative_to(cwd))
        size_h = _human(img.stat().st_size)
        disks.append({
            "path":  rel,
            "label": f"{rel}  [{size_h}]  disk image",
            "size":  size_h,
            "type":  "image",
        })

    return disks


def browse_dir(path: str) -> dict:
    """Vráti obsah adresára pre file browser."""
    p = Path(path).expanduser().resolve()
    if not p.exists():
        p = Path.home()

    entries = []
    try:
        items = sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
        for item in items[:200]:
            try:
                is_dir = item.is_dir()
                size = "" if is_dir else _human(item.stat().st_size)
                entries.append({
                    "name":   item.name,
                    "path":   str(item),
                    "is_dir": is_dir,
                    "size":   size,
                })
            except PermissionError:
                pass
    except PermissionError:
        pass

    # Parent
    parent = str(p.parent) if p.parent != p else None

    return {
        "current": str(p),
        "parent":  parent,
        "entries": entries,
    }


def _human(n: int) -> str:
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {u}"
        n //= 1024
    return f"{n:.1f} PB"


# ── HTML ──────────────────────────────────────────────────────────────────────

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
  background: #0f1117; color: #e2e8f0;
  min-height: 100vh; display: flex; flex-direction: column;
}

header {
  background: #1a1d2e; border-bottom: 1px solid #2d3150;
  padding: 1rem 2rem; display: flex; align-items: center; gap: 0.75rem;
}
header h1 { font-size: 1.25rem; font-weight: 600; color: #a78bfa; }
.badge {
  display: inline-flex; align-items: center;
  font-size: 0.7rem; padding: 0.2rem 0.6rem;
  border-radius: 9999px; font-weight: 600;
}
.badge-ai   { background: #312e81; color: #a5b4fc; }
.badge-apfs { background: #1e3a5f; color: #7dd3fc; }

main {
  flex: 1; display: grid; grid-template-columns: 400px 1fr;
  overflow: hidden;
}

/* ── Left panel ── */
.panel {
  background: #1a1d2e; border-right: 1px solid #2d3150;
  padding: 1.25rem; overflow-y: auto;
  display: flex; flex-direction: column; gap: 1.1rem;
}
.section-title {
  font-size: 0.68rem; font-weight: 700; text-transform: uppercase;
  letter-spacing: 0.08em; color: #64748b; margin-bottom: 0.4rem;
}
label { font-size: 0.82rem; color: #94a3b8; display: block; margin-bottom: 0.3rem; }

input[type=text], select {
  width: 100%; background: #0f1117; border: 1px solid #2d3150;
  border-radius: 6px; color: #e2e8f0; padding: 0.45rem 0.7rem;
  font-size: 0.88rem; outline: none; transition: border-color 0.15s;
}
input[type=text]:focus, select:focus { border-color: #7c3aed; }

/* Input with button */
.input-row { display: flex; gap: 0.4rem; }
.input-row input { flex: 1; }
.icon-btn {
  background: #1e2235; border: 1px solid #2d3150; border-radius: 6px;
  color: #94a3b8; cursor: pointer; padding: 0 0.6rem; font-size: 1rem;
  transition: background 0.15s; white-space: nowrap; flex-shrink: 0;
}
.icon-btn:hover { background: #2d3150; color: #e2e8f0; }

/* Disk selector */
.disk-list {
  max-height: 160px; overflow-y: auto;
  border: 1px solid #2d3150; border-radius: 6px;
  background: #0f1117;
}
.disk-item {
  display: flex; align-items: center; gap: 0.6rem;
  padding: 0.5rem 0.75rem; cursor: pointer;
  border-bottom: 1px solid #1a1d2e; font-size: 0.82rem;
  transition: background 0.1s;
}
.disk-item:last-child { border-bottom: none; }
.disk-item:hover { background: #1a1d2e; }
.disk-item.selected { background: #1e1b4b; border-left: 2px solid #7c3aed; }
.disk-icon { font-size: 1rem; flex-shrink: 0; }
.disk-info { flex: 1; overflow: hidden; }
.disk-path { color: #e2e8f0; font-family: monospace; font-size: 0.8rem;
             white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.disk-meta { color: #64748b; font-size: 0.72rem; }
.disk-size { color: #a78bfa; font-size: 0.75rem; font-weight: 600; flex-shrink: 0; }
.disk-refresh {
  display: flex; justify-content: flex-end; margin-top: 0.3rem;
}

/* Toggle */
.toggle-row {
  display: flex; align-items: center; justify-content: space-between;
  padding: 0.45rem 0; border-bottom: 1px solid #2d3150;
}
.toggle-row:last-child { border-bottom: none; }
.toggle-label { font-size: 0.83rem; color: #cbd5e1; }
.toggle-desc  { font-size: 0.72rem; color: #475569; margin-top: 0.1rem; }
.switch { position: relative; width: 36px; height: 20px; flex-shrink: 0; }
.switch input { opacity: 0; width: 0; height: 0; }
.slider {
  position: absolute; inset: 0; background: #334155;
  border-radius: 20px; cursor: pointer; transition: background 0.2s;
}
.slider::before {
  content: ''; position: absolute; width: 14px; height: 14px;
  left: 3px; top: 3px; background: white; border-radius: 50%;
  transition: transform 0.2s;
}
input:checked + .slider { background: #7c3aed; }
input:checked + .slider::before { transform: translateX(16px); }

/* Buttons */
.btn {
  width: 100%; padding: 0.6rem 1rem; border: none; border-radius: 8px;
  font-size: 0.88rem; font-weight: 600; cursor: pointer;
  transition: opacity 0.15s, transform 0.1s;
}
.btn:active { transform: scale(0.98); }
.btn:disabled { opacity: 0.4; cursor: not-allowed; transform: none; }
.btn-primary { background: #7c3aed; color: white; }
.btn-primary:hover:not(:disabled) { background: #6d28d9; }
.btn-danger  { background: #991b1b; color: white; }
.btn-danger:hover:not(:disabled)  { background: #7f1d1d; }

.btn-sm {
  padding: 0.22rem 0.55rem; font-size: 0.72rem;
  border: 1px solid #2d3150; border-radius: 4px;
  background: transparent; color: #64748b; cursor: pointer;
}
.btn-sm:hover { background: #1f2937; color: #94a3b8; }

/* Status */
.status-bar {
  display: flex; align-items: center; gap: 0.5rem;
  padding: 0.55rem 0.7rem; background: #0f1117;
  border: 1px solid #2d3150; border-radius: 6px; font-size: 0.8rem;
}
.dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.dot.idle    { background: #334155; }
.dot.running { background: #f59e0b; animation: pulse 1s infinite; }
.dot.done    { background: #10b981; }
.dot.error   { background: #ef4444; }
@keyframes pulse { 0%,100%{opacity:1}50%{opacity:.4} }

/* ── Right: terminal ── */
.terminal-wrap { display: flex; flex-direction: column; overflow: hidden; background: #0a0c14; }
.terminal-header {
  background: #111827; border-bottom: 1px solid #1f2937;
  padding: 0.5rem 1rem; display: flex; align-items: center;
  justify-content: space-between; flex-shrink: 0;
}
.terminal-title { font-size: 0.75rem; color: #6b7280; font-family: monospace; }
.terminal {
  flex: 1; overflow-y: auto; padding: 1rem 1.25rem;
  font-family: 'JetBrains Mono','Fira Code',monospace;
  font-size: 0.78rem; line-height: 1.6; color: #d1d5db;
}
.log-line { white-space: pre-wrap; word-break: break-all; }
.log-line.info  { color: #d1d5db; }
.log-line.phase { color: #a78bfa; font-weight: 600; }
.log-line.ok    { color: #34d399; }
.log-line.warn  { color: #fbbf24; }
.log-line.error { color: #f87171; }
.log-line.agent { color: #7dd3fc; }
.log-line.think { color: #6366f1; font-style: italic; }
.log-line.saved { color: #86efac; }

/* Results */
.results {
  border-top: 1px solid #1f2937; padding: 1rem 1.25rem;
  background: #0f1117; flex-shrink: 0; max-height: 160px;
  overflow-y: auto; display: none;
}
.results.visible { display: block; }
.results h3 { font-size: 0.72rem; color: #64748b; text-transform: uppercase;
              letter-spacing: 0.06em; margin-bottom: 0.6rem; }
.result-grid { display: grid; grid-template-columns: repeat(auto-fill,minmax(170px,1fr)); gap: 0.45rem; }
.result-card {
  background: #1a1d2e; border: 1px solid #2d3150;
  border-radius: 6px; padding: 0.55rem 0.7rem;
}
.rc-label { font-size: 0.68rem; color: #64748b; }
.rc-value { font-size: 0.92rem; font-weight: 600; color: #e2e8f0; }
.rc-sub   { font-size: 0.68rem; color: #94a3b8; margin-top: 0.1rem; }

/* ── File browser modal ── */
.modal-overlay {
  display: none; position: fixed; inset: 0;
  background: rgba(0,0,0,0.7); z-index: 100;
  align-items: center; justify-content: center;
}
.modal-overlay.open { display: flex; }
.modal {
  background: #1a1d2e; border: 1px solid #2d3150; border-radius: 10px;
  width: 560px; max-height: 70vh; display: flex; flex-direction: column;
  box-shadow: 0 20px 60px rgba(0,0,0,0.6);
}
.modal-header {
  padding: 0.9rem 1.1rem; border-bottom: 1px solid #2d3150;
  display: flex; align-items: center; justify-content: space-between;
}
.modal-header h2 { font-size: 0.95rem; color: #e2e8f0; }
.modal-close { background: none; border: none; color: #64748b;
               font-size: 1.2rem; cursor: pointer; }
.modal-close:hover { color: #e2e8f0; }
.modal-path {
  padding: 0.5rem 1rem; background: #0f1117;
  font-family: monospace; font-size: 0.78rem; color: #94a3b8;
  border-bottom: 1px solid #1f2937; display: flex; align-items: center; gap: 0.5rem;
}
.modal-path span { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.file-list { flex: 1; overflow-y: auto; }
.file-item {
  display: flex; align-items: center; gap: 0.6rem;
  padding: 0.45rem 1rem; cursor: pointer;
  border-bottom: 1px solid #111827; font-size: 0.82rem;
  transition: background 0.1s;
}
.file-item:hover { background: #111827; }
.file-item:last-child { border-bottom: none; }
.file-item.is-dir { color: #7dd3fc; }
.file-item.is-file { color: #d1d5db; }
.file-icon { width: 1.2rem; text-align: center; flex-shrink: 0; }
.file-name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.file-size { font-size: 0.7rem; color: #475569; flex-shrink: 0; }
.modal-footer {
  padding: 0.7rem 1rem; border-top: 1px solid #2d3150;
  display: flex; align-items: center; gap: 0.5rem;
}
.modal-footer input { flex: 1; }
.modal-select-btn {
  background: #7c3aed; color: white; border: none; border-radius: 6px;
  padding: 0.45rem 1rem; font-size: 0.85rem; font-weight: 600; cursor: pointer;
}
.modal-select-btn:hover { background: #6d28d9; }
</style>
</head>
<body>

<header>
  <h1>🔍 Disk Recovery AI</h1>
  <span class="badge badge-ai">Claude Opus 4.8</span>
  <span class="badge badge-apfs">APFS</span>
  <span style="margin-left:auto;font-size:.8rem;color:#475569">Multi-agent systém obnovy dát</span>
</header>

<main>
<!-- ── Left panel ── -->
<div class="panel">

  <div>
    <div class="section-title">Fyzické disky a obrazy</div>
    <div class="disk-list" id="diskList">
      <div class="disk-item"><span style="color:#475569;font-size:.8rem;padding:.3rem">Načítavam disky…</span></div>
    </div>
    <div class="disk-refresh">
      <button class="btn-sm" onclick="loadDisks()">↻ Obnoviť</button>
    </div>
    <div style="margin-top:.5rem">
      <label>Alebo zadaj cestu ručne</label>
      <div class="input-row">
        <input type="text" id="device" placeholder="/dev/sdb  alebo  disk.img">
        <button class="icon-btn" onclick="openBrowser('device')" title="Prehľadávať">📂</button>
      </div>
    </div>
  </div>

  <div>
    <label>Výstupný adresár</label>
    <div class="input-row">
      <input type="text" id="output" value="./recovered">
      <button class="icon-btn" onclick="openBrowser('output')" title="Prehľadávať">📂</button>
    </div>
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
      <label class="switch"><input type="checkbox" id="dryRun" checked><span class="slider"></span></label>
    </div>
    <div class="toggle-row">
      <div>
        <div class="toggle-label">Preskočiť skenovanie</div>
        <div class="toggle-desc">Načítať existujúci scan JSON</div>
      </div>
      <label class="switch"><input type="checkbox" id="skipScan" onchange="toggleLoadScan()"><span class="slider"></span></label>
    </div>
    <div id="loadScanRow" style="display:none;padding-top:.5rem">
      <div class="input-row">
        <input type="text" id="loadScan" placeholder="./recovered/scan_*.json">
        <button class="icon-btn" onclick="openBrowser('loadScan')" title="Prehľadávať">📂</button>
      </div>
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
  <button class="btn btn-danger"  id="stopBtn"  onclick="stopRecovery()" disabled>■ Zastaviť</button>
</div>

<!-- ── Right panel ── -->
<div class="terminal-wrap">
  <div class="terminal-header">
    <span class="terminal-title">● výstup procesu</span>
    <button class="btn-sm" onclick="clearTerminal()">Vymazať</button>
  </div>
  <div class="terminal" id="terminal">
    <div class="log-line info">Vitaj v Disk Recovery AI systéme.</div>
    <div class="log-line info">Vyber disk zo zoznamu vľavo a klikni ▶ Spustiť obnovu.</div>
  </div>
  <div class="results" id="resultsPanel">
    <h3>Výsledky</h3>
    <div class="result-grid" id="resultGrid"></div>
  </div>
</div>
</main>

<!-- ── File browser modal ── -->
<div class="modal-overlay" id="modalOverlay" onclick="closeModalOutside(event)">
  <div class="modal">
    <div class="modal-header">
      <h2 id="modalTitle">Prehľadávať</h2>
      <button class="modal-close" onclick="closeModal()">✕</button>
    </div>
    <div class="modal-path">
      <button class="icon-btn" style="padding:0 .4rem;font-size:.85rem" onclick="navParent()">↑</button>
      <span id="modalCurrentPath">/</span>
    </div>
    <div class="file-list" id="fileList"></div>
    <div class="modal-footer">
      <input type="text" id="modalSelected" placeholder="vybraná cesta">
      <button class="modal-select-btn" onclick="confirmSelect()">Vybrať</button>
    </div>
  </div>
</div>

<script>
// ── State ──────────────────────────────────────────────────────────────────
let evtSource = null;
let running   = false;
let modalTarget = null;   // which input to fill: 'device' | 'output' | 'loadScan'
let currentBrowsePath = '';

// ── Disk list ──────────────────────────────────────────────────────────────
async function loadDisks() {
  const list = document.getElementById('diskList');
  list.innerHTML = '<div class="disk-item"><span style="color:#475569;font-size:.8rem;padding:.3rem">Načítavam…</span></div>';
  try {
    const res = await fetch('/disks');
    const disks = await res.json();
    if (!disks.length) {
      list.innerHTML = '<div class="disk-item"><span style="color:#475569;font-size:.8rem;padding:.3rem">Žiadne disky nenájdené</span></div>';
      return;
    }
    list.innerHTML = '';
    disks.forEach(d => {
      const div = document.createElement('div');
      div.className = 'disk-item';
      div.onclick = () => selectDisk(d.path, div);
      const icon = d.type === 'disk' ? '💾' : '📄';
      div.innerHTML = `
        <span class="disk-icon">${icon}</span>
        <div class="disk-info">
          <div class="disk-path">${d.path}</div>
          <div class="disk-meta">${d.label.replace(d.path,'').trim()}</div>
        </div>
        <span class="disk-size">${d.size}</span>`;
      list.appendChild(div);
    });
  } catch(e) {
    list.innerHTML = '<div class="disk-item"><span style="color:#f87171;font-size:.8rem;padding:.3rem">Chyba načítania diskov</span></div>';
  }
}

function selectDisk(path, el) {
  document.querySelectorAll('.disk-item').forEach(d => d.classList.remove('selected'));
  el.classList.add('selected');
  document.getElementById('device').value = path;
}

// ── File browser ───────────────────────────────────────────────────────────
async function openBrowser(target) {
  modalTarget = target;
  const titles = { device: 'Vybrať disk / image', output: 'Výstupný adresár', loadScan: 'Scan JSON súbor' };
  document.getElementById('modalTitle').textContent = titles[target] || 'Prehľadávať';

  const startPath = document.getElementById(target)?.value.trim() || '.';
  await browseTo(startPath);
  document.getElementById('modalOverlay').classList.add('open');
}

function closeModal() {
  document.getElementById('modalOverlay').classList.remove('open');
}
function closeModalOutside(e) {
  if (e.target === document.getElementById('modalOverlay')) closeModal();
}

async function browseTo(path) {
  try {
    const res = await fetch('/browse?path=' + encodeURIComponent(path));
    const data = await res.json();
    currentBrowsePath = data.current;
    document.getElementById('modalCurrentPath').textContent = data.current;
    document.getElementById('modalSelected').value = data.current;

    const fl = document.getElementById('fileList');
    fl.innerHTML = '';

    // Parent ".."
    if (data.parent) {
      const row = document.createElement('div');
      row.className = 'file-item is-dir';
      row.onclick = () => browseTo(data.parent);
      row.innerHTML = '<span class="file-icon">📁</span><span class="file-name">..</span>';
      fl.appendChild(row);
    }

    data.entries.forEach(e => {
      const row = document.createElement('div');
      row.className = 'file-item ' + (e.is_dir ? 'is-dir' : 'is-file');
      row.onclick = () => {
        if (e.is_dir) {
          browseTo(e.path);
        } else {
          document.getElementById('modalSelected').value = e.path;
        }
      };
      const icon = e.is_dir ? '📁' : (e.name.endsWith('.img') ? '💽' : (e.name.endsWith('.json') ? '📋' : '📄'));
      row.innerHTML = `<span class="file-icon">${icon}</span>
        <span class="file-name">${e.name}</span>
        <span class="file-size">${e.size}</span>`;
      fl.appendChild(row);
    });
  } catch(err) {
    console.error(err);
  }
}

function navParent() {
  const cur = document.getElementById('modalCurrentPath').textContent;
  fetch('/browse?path=' + encodeURIComponent(cur))
    .then(r => r.json())
    .then(d => { if (d.parent) browseTo(d.parent); });
}

function confirmSelect() {
  const val = document.getElementById('modalSelected').value.trim();
  if (modalTarget && val) document.getElementById(modalTarget).value = val;
  closeModal();
}

// ── Toggles ────────────────────────────────────────────────────────────────
function toggleLoadScan() {
  document.getElementById('loadScanRow').style.display =
    document.getElementById('skipScan').checked ? 'block' : 'none';
}

// ── Status ─────────────────────────────────────────────────────────────────
function setStatus(state, text) {
  document.getElementById('statusDot').className = 'dot ' + state;
  document.getElementById('statusText').textContent = text;
}

// ── Terminal ───────────────────────────────────────────────────────────────
function appendLine(text, cls = 'info') {
  const t = document.getElementById('terminal');
  const div = document.createElement('div');
  div.className = 'log-line ' + cls;
  div.textContent = text;
  t.appendChild(div);
  t.scrollTop = t.scrollHeight;
}
function clearTerminal() { document.getElementById('terminal').innerHTML = ''; }

function classifyLine(line) {
  if (line.startsWith('[Fáza') || line.startsWith('===') || line.startsWith('---')) return 'phase';
  if (line.includes('[Agent') || line.includes('Agent ')) return 'agent';
  if (line.includes('thinking') || line.includes('Analyst thinking') ||
      line.includes('Predictor thinking') || line.includes('Planner thinking')) return 'think';
  if (line.includes('→ uložené') || line.includes('Hotovo')) return 'saved';
  if (line.includes('[WARN]') || line.includes('⚠')) return 'warn';
  if (line.includes('[CHYBA]') || line.includes('Error') || line.includes('error')) return 'error';
  if (line.startsWith('  →') || line.startsWith('  Hotovo')) return 'ok';
  return 'info';
}

// ── Recovery ───────────────────────────────────────────────────────────────
function startRecovery() {
  if (running) return;
  const params = new URLSearchParams({
    device:    document.getElementById('device').value.trim(),
    output:    document.getElementById('output').value.trim(),
    max_scan:  document.getElementById('maxScan').value.trim(),
    dry_run:   document.getElementById('dryRun').checked ? '1' : '0',
    load_scan: document.getElementById('skipScan').checked
                 ? document.getElementById('loadScan').value.trim() : '',
  });

  clearTerminal();
  document.getElementById('resultsPanel').classList.remove('visible');
  document.getElementById('startBtn').disabled = true;
  document.getElementById('stopBtn').disabled  = false;
  setStatus('running', 'Prebieha obnova…');
  running = true;

  evtSource = new EventSource('/run?' + params);

  evtSource.addEventListener('line',      e => appendLine(e.data, classifyLine(e.data)));
  evtSource.addEventListener('result',    e => { try { showResults(JSON.parse(e.data)); } catch{} });
  evtSource.addEventListener('done',      e => finish('done',  e.data || 'Dokončené'));
  evtSource.addEventListener('error_msg', e => { appendLine('CHYBA: ' + e.data, 'error'); finish('error','Chyba'); });
  evtSource.onerror = () => { if (running) finish('error', 'Spojenie prerušené'); };
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
  document.getElementById('stopBtn').disabled  = true;
  setStatus(state, text);
}

function showResults(data) {
  const grid = document.getElementById('resultGrid');
  const items = [
    { label: 'Signatúr',       value: data.signatures    ?? '—', sub: 'nájdených' },
    { label: 'Partícií (AI)',  value: data.partitions    ?? '—', sub: 'odhadovaných' },
    { label: 'Pred. regiónov', value: data.pred_regions  ?? '—', sub: '' },
    { label: 'Akcií v pláne',  value: data.actions       ?? '—', sub: '' },
    { label: 'Odhad obnovy',   value: data.recovery_rate ?? '—', sub: '' },
    { label: 'Výstup',         value: data.output_dir    ?? '—', sub: '' },
  ];
  grid.innerHTML = items.map(it => `
    <div class="result-card">
      <div class="rc-label">${it.label}</div>
      <div class="rc-value">${it.value}</div>
      ${it.sub ? '<div class="rc-sub">'+it.sub+'</div>' : ''}
    </div>`).join('');
  document.getElementById('resultsPanel').classList.add('visible');
}

// ── Init ───────────────────────────────────────────────────────────────────
loadDisks();
</script>
</body>
</html>
"""


# ── Flask routes ──────────────────────────────────────────────────────────────

_proc: subprocess.Popen | None = None
_lock = threading.Lock()


@app.get("/")
def index():
    return render_template_string(HTML)


@app.get("/disks")
def disks():
    return jsonify(list_disks())


@app.get("/browse")
def browse():
    path = request.args.get("path", str(Path.home()))
    return jsonify(browse_dir(path))


@app.get("/run")
def run():
    global _proc

    device    = request.args.get("device", "")
    output    = request.args.get("output", "./recovered")
    max_scan  = request.args.get("max_scan", "").strip()
    dry_run   = request.args.get("dry_run", "0") == "1"
    load_scan = request.args.get("load_scan", "").strip()

    if not device:
        return Response("event: error_msg\ndata: Nezvolené zariadenie\n\n",
                        mimetype="text/event-stream")

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
        with _lock:
            try:
                _proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True, bufsize=1,
                    env=os.environ.copy(),
                    cwd=str(Path(__file__).parent),
                )
            except Exception as e:
                yield f"event: error_msg\ndata: {e}\n\n"
                return

        sig_count = part_count = region_count = action_count = 0
        recovery_rate = ""

        for line in _proc.stdout:
            line = line.rstrip("\n")
            yield f"event: line\ndata: {line}\n\n"

            if "nájdených" in line and "signátur" in line:
                try: sig_count = int([t for t in line.split() if t.isdigit()][0])
                except Exception: pass
            if "partícií" in line.lower() and "AI" in line:
                try: part_count = int(line.split()[1])
                except Exception: pass
            if "Predikované regióny:" in line:
                try: region_count = int(line.split("regióny:")[1].split(",")[0].strip())
                except Exception: pass
            if "Akcií v pláne:" in line:
                try: action_count = int(line.split(":")[1].strip())
                except Exception: pass
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
        yield f"event: done\ndata: {'Úspešne dokončené ✓' if rc == 0 else f'Ukončené s kódom {rc}'}\n\n"

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/stop")
def stop():
    global _proc
    with _lock:
        if _proc and _proc.poll() is None:
            _proc.terminate()
    return jsonify({"ok": True})


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"\n  Disk Recovery UI beží na  http://localhost:{port}\n")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
