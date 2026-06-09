"""
ui.py — Webové UI pre disk recovery systém

Spustenie:
  cd disk_recovery
  python3 ui.py

Otvor v prehliadači: http://localhost:5000
"""

import json
import mimetypes
import os
import platform
import subprocess
import sys
import threading
from pathlib import Path
from flask import Flask, Response, jsonify, render_template_string, request, send_file

app = Flask(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _human(n: int) -> str:
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {u}"
        n //= 1024
    return f"{n:.1f} PB"


# ── Disk detection ────────────────────────────────────────────────────────────

def list_disks() -> list[dict]:
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
                    name  = dev["name"]
                    path  = f"/dev/{name}"
                    model = (dev.get("model") or "").strip() or name
                    size  = dev.get("size", "?")
                    tran  = dev.get("tran") or "—"
                    disks.append({"path": path,
                                  "label": f"{path}  [{size}]  {model}  ({tran})",
                                  "size": size, "type": "disk"})
        except Exception:
            try:
                with open("/proc/partitions") as f:
                    for line in f:
                        parts = line.split()
                        if len(parts) == 4 and parts[3].startswith("sd"):
                            disks.append({"path": f"/dev/{parts[3]}",
                                          "label": f"/dev/{parts[3]}",
                                          "size": "", "type": "disk"})
            except Exception:
                pass

    elif system == "Darwin":
        try:
            import plistlib
            out = subprocess.check_output(["diskutil", "list", "-plist"],
                                          text=True, stderr=subprocess.DEVNULL)
            data = plistlib.loads(out.encode())
            for disk in data.get("WholeDisks", []):
                info_raw = subprocess.check_output(
                    ["diskutil", "info", "-plist", disk],
                    text=True, stderr=subprocess.DEVNULL)
                info  = plistlib.loads(info_raw.encode())
                path  = info.get("DeviceNode", f"/dev/{disk}")
                model = info.get("MediaName", disk)
                size  = info.get("TotalSize", 0)
                size_h = _human(size) if isinstance(size, int) else "?"
                disks.append({"path": path,
                               "label": f"{path}  [{size_h}]  {model}",
                               "size": size_h, "type": "disk"})
        except Exception:
            pass

    cwd = Path(__file__).parent.parent
    for img in sorted(cwd.rglob("*.img"))[:20]:
        rel   = str(img.relative_to(cwd))
        size_h = _human(img.stat().st_size)
        disks.append({"path": rel, "label": f"{rel}  [{size_h}]  disk image",
                      "size": size_h, "type": "image"})
    return disks


# ── File browser ──────────────────────────────────────────────────────────────

def browse_dir(path: str) -> dict:
    p = Path(path).expanduser().resolve()
    if not p.exists():
        p = Path.home()

    entries = []
    try:
        items = sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
        for item in items[:500]:
            try:
                is_dir = item.is_dir()
                stat   = item.stat()
                entries.append({
                    "name":     item.name,
                    "path":     str(item),
                    "is_dir":   is_dir,
                    "size":     "" if is_dir else _human(stat.st_size),
                    "size_raw": 0 if is_dir else stat.st_size,
                    "ext":      item.suffix.lower() if not is_dir else "",
                })
            except PermissionError:
                pass
    except PermissionError:
        pass

    return {
        "current": str(p),
        "parent":  str(p.parent) if p.parent != p else None,
        "entries": entries,
    }


# ── HTML ──────────────────────────────────────────────────────────────────────

HTML = r"""
<!DOCTYPE html>
<html lang="sk">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Disk Recovery AI</title>
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Segoe UI',system-ui,sans-serif;background:#0f1117;color:#e2e8f0;height:100vh;display:flex;flex-direction:column;overflow:hidden}

/* header */
header{background:#1a1d2e;border-bottom:1px solid #2d3150;padding:.75rem 1.5rem;display:flex;align-items:center;gap:.6rem;flex-shrink:0}
header h1{font-size:1.15rem;font-weight:600;color:#a78bfa}
.badge{font-size:.68rem;padding:.15rem .55rem;border-radius:9999px;font-weight:600}
.badge-ai{background:#312e81;color:#a5b4fc}
.badge-apfs{background:#1e3a5f;color:#7dd3fc}

/* layout */
main{flex:1;display:grid;grid-template-columns:370px 1fr;overflow:hidden}

/* ── left panel ── */
.lpanel{background:#1a1d2e;border-right:1px solid #2d3150;padding:1.1rem;overflow-y:auto;display:flex;flex-direction:column;gap:1rem}
.sec{font-size:.67rem;font-weight:700;text-transform:uppercase;letter-spacing:.08em;color:#64748b;margin-bottom:.35rem}
label{font-size:.81rem;color:#94a3b8;display:block;margin-bottom:.28rem}
input[type=text],select{width:100%;background:#0f1117;border:1px solid #2d3150;border-radius:6px;color:#e2e8f0;padding:.42rem .65rem;font-size:.86rem;outline:none;transition:border-color .15s}
input[type=text]:focus{border-color:#7c3aed}

.irow{display:flex;gap:.35rem}
.irow input{flex:1}
.ibtn{background:#1e2235;border:1px solid #2d3150;border-radius:6px;color:#94a3b8;cursor:pointer;padding:0 .55rem;font-size:.95rem;transition:background .15s;flex-shrink:0}
.ibtn:hover{background:#2d3150;color:#e2e8f0}

/* disk list */
.dlist{max-height:150px;overflow-y:auto;border:1px solid #2d3150;border-radius:6px;background:#0f1117}
.ditem{display:flex;align-items:center;gap:.5rem;padding:.42rem .65rem;cursor:pointer;border-bottom:1px solid #1a1d2e;font-size:.8rem;transition:background .1s}
.ditem:last-child{border-bottom:none}
.ditem:hover{background:#1a1d2e}
.ditem.sel{background:#1e1b4b;border-left:2px solid #7c3aed}
.dpath{color:#e2e8f0;font-family:monospace;font-size:.78rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;flex:1}
.dmeta{color:#64748b;font-size:.7rem}
.dsize{color:#a78bfa;font-size:.72rem;font-weight:600;flex-shrink:0}

/* toggles */
.trow{display:flex;align-items:center;justify-content:space-between;padding:.4rem 0;border-bottom:1px solid #2d3150}
.trow:last-child{border-bottom:none}
.tlbl{font-size:.82rem;color:#cbd5e1}
.tdsc{font-size:.7rem;color:#475569;margin-top:.08rem}
.sw{position:relative;width:34px;height:18px;flex-shrink:0}
.sw input{opacity:0;width:0;height:0}
.sl{position:absolute;inset:0;background:#334155;border-radius:18px;cursor:pointer;transition:background .2s}
.sl::before{content:'';position:absolute;width:12px;height:12px;left:3px;top:3px;background:#fff;border-radius:50%;transition:transform .2s}
.sw input:checked+.sl{background:#7c3aed}
.sw input:checked+.sl::before{transform:translateX(16px)}

/* buttons */
.btn{width:100%;padding:.58rem;border:none;border-radius:8px;font-size:.86rem;font-weight:600;cursor:pointer;transition:opacity .15s,transform .1s}
.btn:active{transform:scale(.98)}
.btn:disabled{opacity:.4;cursor:not-allowed;transform:none}
.btn-go{background:#7c3aed;color:#fff}
.btn-go:hover:not(:disabled){background:#6d28d9}
.btn-stop{background:#991b1b;color:#fff}
.btn-stop:hover:not(:disabled){background:#7f1d1d}
.bsm{padding:.2rem .5rem;font-size:.7rem;border:1px solid #2d3150;border-radius:4px;background:transparent;color:#64748b;cursor:pointer}
.bsm:hover{background:#1f2937;color:#94a3b8}

/* status */
.sbar{display:flex;align-items:center;gap:.45rem;padding:.5rem .65rem;background:#0f1117;border:1px solid #2d3150;border-radius:6px;font-size:.78rem}
.dot{width:7px;height:7px;border-radius:50%;flex-shrink:0}
.dot.idle{background:#334155}
.dot.run{background:#f59e0b;animation:pulse 1s infinite}
.dot.done{background:#10b981}
.dot.err{background:#ef4444}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}

/* ── right panel ── */
.rpanel{display:flex;flex-direction:column;overflow:hidden;background:#0a0c14}

/* tabs */
.tabs{background:#111827;border-bottom:1px solid #1f2937;display:flex;align-items:center;gap:0;flex-shrink:0}
.tab{padding:.5rem 1.1rem;font-size:.78rem;color:#6b7280;cursor:pointer;border-bottom:2px solid transparent;transition:color .15s,border-color .15s;user-select:none}
.tab:hover{color:#9ca3af}
.tab.active{color:#a78bfa;border-bottom-color:#7c3aed}
.tab-actions{margin-left:auto;padding:0 .75rem;display:flex;gap:.4rem;align-items:center}

/* terminal */
.terminal{flex:1;overflow-y:auto;padding:.9rem 1.1rem;font-family:'JetBrains Mono','Fira Code',monospace;font-size:.77rem;line-height:1.65;color:#d1d5db}
.ll{white-space:pre-wrap;word-break:break-all}
.ll.info{color:#d1d5db}.ll.phase{color:#a78bfa;font-weight:600}.ll.ok{color:#34d399}
.ll.warn{color:#fbbf24}.ll.err2{color:#f87171}.ll.agent{color:#7dd3fc}
.ll.think{color:#6366f1;font-style:italic}.ll.saved{color:#86efac}

/* file explorer */
.explorer{flex:1;display:flex;flex-direction:column;overflow:hidden}
.exp-toolbar{background:#111827;border-bottom:1px solid #1f2937;padding:.45rem .9rem;display:flex;align-items:center;gap:.5rem;flex-shrink:0}
.exp-path{flex:1;background:#0f1117;border:1px solid #2d3150;border-radius:5px;color:#94a3b8;font-family:monospace;font-size:.76rem;padding:.3rem .6rem;outline:none}
.exp-path:focus{border-color:#7c3aed}
.exp-nav{background:#1e2235;border:1px solid #2d3150;border-radius:5px;color:#94a3b8;cursor:pointer;padding:.28rem .55rem;font-size:.85rem}
.exp-nav:hover{background:#2d3150;color:#e2e8f0}

.exp-cols{display:flex;overflow:hidden;flex:1}

/* tree (left) */
.tree-pane{width:220px;border-right:1px solid #1f2937;overflow-y:auto;background:#0d0f1a;flex-shrink:0}
.tree-item{display:flex;align-items:center;gap:.35rem;padding:.32rem .6rem;cursor:pointer;font-size:.78rem;color:#94a3b8;transition:background .1s;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.tree-item:hover{background:#111827;color:#e2e8f0}
.tree-item.active{background:#1e1b4b;color:#a78bfa}
.tree-indent{display:inline-block;width:1rem;flex-shrink:0}

/* files (right) */
.files-pane{flex:1;overflow-y:auto;background:#0a0c14}
.files-header{display:grid;grid-template-columns:1fr 80px 90px;padding:.3rem .9rem;font-size:.68rem;color:#475569;border-bottom:1px solid #1a1d2e;text-transform:uppercase;letter-spacing:.05em}
.frow{display:grid;grid-template-columns:1fr 80px 90px;padding:.38rem .9rem;font-size:.8rem;border-bottom:1px solid #111827;cursor:pointer;transition:background .1s;align-items:center}
.frow:hover{background:#111827}
.frow.selected{background:#1e1b4b}
.fname{display:flex;align-items:center;gap:.45rem;overflow:hidden}
.fname span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.fsize{color:#64748b;font-size:.73rem;text-align:right}
.fext{color:#475569;font-size:.7rem}
.ficon{flex-shrink:0;font-size:.95rem}

/* preview bar */
.preview-bar{border-top:1px solid #1f2937;background:#0d0f1a;padding:.55rem .9rem;display:flex;align-items:center;justify-content:space-between;flex-shrink:0;min-height:44px}
.prev-info{font-size:.78rem;color:#94a3b8}
.prev-name{color:#e2e8f0;font-weight:600;margin-right:.5rem}
.prev-actions{display:flex;gap:.4rem}
.prev-btn{background:#1e2235;border:1px solid #2d3150;border-radius:5px;color:#94a3b8;cursor:pointer;padding:.28rem .7rem;font-size:.76rem;transition:background .15s}
.prev-btn:hover{background:#2d3150;color:#e2e8f0}
.prev-btn.dl{background:#1e3a5f;border-color:#0369a1;color:#7dd3fc}
.prev-btn.dl:hover{background:#1e4976}

/* results strip */
.rstrip{border-top:1px solid #1f2937;padding:.75rem 1rem;background:#0f1117;flex-shrink:0;display:none}
.rstrip.on{display:block}
.rstrip h3{font-size:.68rem;color:#64748b;text-transform:uppercase;letter-spacing:.06em;margin-bottom:.5rem}
.rgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(155px,1fr));gap:.4rem}
.rcard{background:#1a1d2e;border:1px solid #2d3150;border-radius:6px;padding:.5rem .65rem}
.rlbl{font-size:.66rem;color:#64748b}
.rval{font-size:.9rem;font-weight:600;color:#e2e8f0}

/* modal */
.ov{display:none;position:fixed;inset:0;background:rgba(0,0,0,.7);z-index:100;align-items:center;justify-content:center}
.ov.open{display:flex}
.modal{background:#1a1d2e;border:1px solid #2d3150;border-radius:10px;width:540px;max-height:68vh;display:flex;flex-direction:column;box-shadow:0 20px 60px rgba(0,0,0,.6)}
.mhd{padding:.8rem 1rem;border-bottom:1px solid #2d3150;display:flex;align-items:center;justify-content:space-between}
.mhd h2{font-size:.9rem;color:#e2e8f0}
.mcl{background:none;border:none;color:#64748b;font-size:1.1rem;cursor:pointer}
.mcl:hover{color:#e2e8f0}
.mpath{padding:.4rem .9rem;background:#0f1117;font-family:monospace;font-size:.75rem;color:#94a3b8;border-bottom:1px solid #1f2937;display:flex;align-items:center;gap:.4rem}
.mpath span{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.mlist{flex:1;overflow-y:auto}
.mitem{display:flex;align-items:center;gap:.5rem;padding:.38rem .9rem;cursor:pointer;border-bottom:1px solid #111827;font-size:.8rem;transition:background .1s}
.mitem:hover{background:#111827}
.mitem.dir{color:#7dd3fc}.mitem.file{color:#d1d5db}
.mft{padding:.6rem .9rem;border-top:1px solid #2d3150;display:flex;gap:.4rem}
.mft input{flex:1}
.mok{background:#7c3aed;color:#fff;border:none;border-radius:6px;padding:.4rem .9rem;font-size:.83rem;font-weight:600;cursor:pointer}
.mok:hover{background:#6d28d9}
</style>
</head>
<body>

<header>
  <h1>🔍 Disk Recovery AI</h1>
  <span class="badge badge-ai">Claude Opus 4.8</span>
  <span class="badge badge-apfs">APFS</span>
  <span style="margin-left:auto;font-size:.77rem;color:#475569">Multi-agent systém obnovy dát</span>
</header>

<main>
<!-- ══ LEFT PANEL ══ -->
<div class="lpanel">

  <div>
    <div class="sec">Pripojené disky a obrazy</div>
    <div class="dlist" id="diskList">
      <div class="ditem"><span style="color:#475569;font-size:.78rem">Načítavam…</span></div>
    </div>
    <div style="display:flex;justify-content:flex-end;margin-top:.28rem">
      <button class="bsm" onclick="loadDisks()">↻ Obnoviť</button>
    </div>
    <div style="margin-top:.5rem">
      <label>Alebo zadaj cestu ručne</label>
      <div class="irow">
        <input type="text" id="device" placeholder="/dev/sdb  alebo  disk.img" oninput="checkSudoNeeded()">
        <button class="ibtn" onclick="openModal('device')" title="Prehľadávať">📂</button>
      </div>
    </div>
  </div>

  <div>
    <label>Výstupný adresár</label>
    <div class="irow">
      <input type="text" id="output" value="./recovered">
      <button class="ibtn" onclick="openModal('output')" title="Prehľadávať">📂</button>
    </div>
  </div>

  <div>
    <label>Max. rozsah skenu (prázdne = celý disk)</label>
    <input type="text" id="maxScan" placeholder="napr. 500M, 2G">
  </div>

  <div>
    <div class="sec">Možnosti</div>
    <div class="trow">
      <div><div class="tlbl">Dry-run</div><div class="tdsc">Len analýza, bez fyzickej obnovy</div></div>
      <label class="sw"><input type="checkbox" id="dryRun" checked><span class="sl"></span></label>
    </div>
    <div class="trow">
      <div><div class="tlbl">Preskočiť skenovanie</div><div class="tdsc">Načítať existujúci scan JSON</div></div>
      <label class="sw"><input type="checkbox" id="skipScan" onchange="toggleLoadScan()"><span class="sl"></span></label>
    </div>
    <div id="loadScanRow" style="display:none;padding-top:.45rem">
      <div class="irow">
        <input type="text" id="loadScan" placeholder="./recovered/scan_*.json">
        <button class="ibtn" onclick="openModal('loadScan')">📂</button>
      </div>
    </div>
  </div>

  <div id="sudoRow" style="display:none">
    <label>🔐 Heslo správcu (sudo)</label>
    <input type="password" id="sudoPass" placeholder="Potrebné pre /dev/ zariadenia" autocomplete="current-password">
    <div style="font-size:.7rem;color:#475569;margin-top:.25rem">Heslo sa použije len raz a nikde neuloží</div>
  </div>

  <div>
    <div class="sec">Stav</div>
    <div class="sbar">
      <div class="dot idle" id="sDot"></div>
      <span id="sTxt">Pripravený</span>
    </div>
  </div>

  <button class="btn btn-go"   id="startBtn" onclick="startRecovery()">▶ Spustiť obnovu</button>
  <button class="btn btn-stop" id="stopBtn"  onclick="stopRecovery()" disabled>■ Zastaviť</button>
</div>

<!-- ══ RIGHT PANEL ══ -->
<div class="rpanel">

  <!-- tabs -->
  <div class="tabs">
    <div class="tab active" id="tabTerminal" onclick="switchTab('terminal')">⌨ Terminál</div>
    <div class="tab"        id="tabFiles"    onclick="switchTab('files')">🗂 Súbory</div>
    <div class="tab-actions">
      <button class="bsm" id="clearBtn" onclick="clearTerminal()">Vymazať</button>
      <button class="bsm" id="refreshBtn" onclick="refreshExplorer()" style="display:none">↻ Obnoviť</button>
    </div>
  </div>

  <!-- terminal view -->
  <div id="viewTerminal" style="display:flex;flex-direction:column;flex:1;overflow:hidden">
    <div class="terminal" id="terminal">
      <div class="ll info">Vitaj v Disk Recovery AI systéme.</div>
      <div class="ll info">Vyber disk vľavo a klikni ▶ Spustiť obnovu.</div>
    </div>
    <div class="rstrip" id="rstrip">
      <h3>Výsledky</h3>
      <div class="rgrid" id="rgrid"></div>
    </div>
  </div>

  <!-- file explorer view -->
  <div id="viewFiles" style="display:none;flex-direction:column;flex:1;overflow:hidden">
    <div class="explorer">
      <div class="exp-toolbar">
        <button class="exp-nav" onclick="expUp()" title="Hore">↑</button>
        <button class="exp-nav" onclick="expHome()" title="Domov">⌂</button>
        <input class="exp-path" id="expPath" value="./recovered"
               onkeydown="if(event.key==='Enter') expNavigate(this.value)">
        <button class="exp-nav" onclick="expNavigate(document.getElementById('expPath').value)">→</button>
        <button class="exp-nav" onclick="expOutputDir()" title="Prejsť do výstupného adresára">🎯</button>
      </div>
      <div class="exp-cols">
        <!-- tree -->
        <div class="tree-pane" id="treePane"></div>
        <!-- file list -->
        <div style="flex:1;display:flex;flex-direction:column;overflow:hidden">
          <div class="files-header">
            <div>Názov</div><div style="text-align:right">Veľkosť</div><div>Typ</div>
          </div>
          <div class="files-pane" id="filesPane"></div>
        </div>
      </div>
      <div class="preview-bar" id="previewBar">
        <span class="prev-info" id="prevInfo">Vyber súbor…</span>
        <div class="prev-actions" id="prevActions"></div>
      </div>
    </div>
  </div>

</div>
</main>

<!-- ── File picker modal ── -->
<div class="ov" id="ov" onclick="ovOutside(event)">
  <div class="modal">
    <div class="mhd">
      <h2 id="mTitle">Prehľadávať</h2>
      <button class="mcl" onclick="closeModal()">✕</button>
    </div>
    <div class="mpath">
      <button class="exp-nav" style="padding:.2rem .45rem;font-size:.8rem" onclick="mNavUp()">↑</button>
      <span id="mCurPath">/</span>
    </div>
    <div class="mlist" id="mList"></div>
    <div class="mft">
      <input type="text" id="mSel" placeholder="vybraná cesta">
      <button class="mok" onclick="confirmModal()">Vybrať</button>
    </div>
  </div>
</div>

<script>
// ═══════════════════════════════════════════════════════════════
//  STATE
// ═══════════════════════════════════════════════════════════════
let evtSrc   = null;
let running  = false;
let mTarget  = null;
let expCurrent = '';
let selectedFile = null;
let activeTab = 'terminal';

// ═══════════════════════════════════════════════════════════════
//  TABS
// ═══════════════════════════════════════════════════════════════
function switchTab(t) {
  activeTab = t;
  document.getElementById('tabTerminal').classList.toggle('active', t==='terminal');
  document.getElementById('tabFiles').classList.toggle('active',    t==='files');
  document.getElementById('viewTerminal').style.display = t==='terminal' ? 'flex' : 'none';
  document.getElementById('viewFiles').style.display    = t==='files'    ? 'flex' : 'none';
  document.getElementById('clearBtn').style.display    = t==='terminal' ? ''      : 'none';
  document.getElementById('refreshBtn').style.display  = t==='files'    ? ''      : 'none';
  if (t === 'files') expNavigate(expCurrent || document.getElementById('output').value || '.');
}

// ═══════════════════════════════════════════════════════════════
//  DISK LIST
// ═══════════════════════════════════════════════════════════════
function checkSudoNeeded() {
  const dev = document.getElementById('device').value.trim();
  document.getElementById('sudoRow').style.display = dev.startsWith('/dev/') ? 'block' : 'none';
}

async function loadDisks() {
  const list = document.getElementById('diskList');
  list.innerHTML = '<div class="ditem"><span style="color:#475569;font-size:.78rem">Načítavam…</span></div>';
  try {
    const disks = await fetch('/disks').then(r=>r.json());
    if (!disks.length) {
      list.innerHTML = '<div class="ditem"><span style="color:#475569;font-size:.78rem">Žiadne disky nenájdené</span></div>';
      return;
    }
    list.innerHTML = '';
    disks.forEach(d => {
      const el = document.createElement('div');
      el.className = 'ditem';
      el.onclick = () => {
        document.querySelectorAll('.ditem').forEach(x=>x.classList.remove('sel'));
        el.classList.add('sel');
        document.getElementById('device').value = d.path;
        checkSudoNeeded();
      };
      const ic = d.type==='disk' ? '💾' : '📄';
      el.innerHTML = `<span>${ic}</span><div style="flex:1;overflow:hidden"><div class="dpath">${d.path}</div><div class="dmeta">${d.label.replace(d.path,'').trim()}</div></div><span class="dsize">${d.size}</span>`;
      list.appendChild(el);
    });
  } catch { list.innerHTML = '<div class="ditem"><span style="color:#f87171;font-size:.78rem">Chyba načítania</span></div>'; }
}

// ═══════════════════════════════════════════════════════════════
//  FILE EXPLORER
// ═══════════════════════════════════════════════════════════════
const EXT_ICONS = {
  '.jpg':'.jpeg':'.png':'.gif':'.bmp':'.webp': '🖼',
  '.pdf': '📕', '.txt':'.log':'.md': '📄',
  '.zip':'.gz':'.7z':'.tar':'.bz2': '🗜',
  '.mp4':'.mkv':'.avi':'.mov': '🎬',
  '.mp3':'.flac':'.wav':'.aac': '🎵',
  '.db':'.sqlite': '🗃',
  '.json': '📋',
  '.img':'.iso': '💽',
  '.sh':'.py':'.js':'.ts': '⚙',
};
// simpler lookup
function extIcon(ext) {
  const map = {'🖼':['.jpg','.jpeg','.png','.gif','.bmp','.webp'],
               '📕':['.pdf'],'📄':['.txt','.log','.md','.csv'],
               '🗜':['.zip','.gz','.7z','.tar','.bz2'],
               '🎬':['.mp4','.mkv','.avi','.mov'],
               '🎵':['.mp3','.flac','.wav','.aac'],
               '🗃':['.db','.sqlite'],'📋':['.json'],
               '💽':['.img','.iso'],'⚙':['.sh','.py','.js','.ts']};
  for (const [ic, exts] of Object.entries(map)) if (exts.includes(ext)) return ic;
  return '📄';
}

async function expNavigate(path) {
  if (!path) return;
  try {
    const data = await fetch('/browse?path=' + encodeURIComponent(path)).then(r=>r.json());
    expCurrent = data.current;
    document.getElementById('expPath').value = data.current;
    renderTree(data);
    renderFiles(data);
    clearPreview();
  } catch(e) { console.error(e); }
}

function expUp()       { if (expCurrent) expNavigate(expCurrent + '/..'); }
function expHome()     { expNavigate('~'); }
function expOutputDir(){ expNavigate(document.getElementById('output').value || '.'); }
function refreshExplorer() { expNavigate(expCurrent || '.'); }

function renderTree(data) {
  const pane = document.getElementById('treePane');
  pane.innerHTML = '';

  // Breadcrumb as tree items
  const parts = data.current.split('/').filter(Boolean);
  let built = '/';
  const root = document.createElement('div');
  root.className = 'tree-item' + (data.current==='/' ? ' active' : '');
  root.innerHTML = '<span>📁</span> /';
  root.onclick = () => expNavigate('/');
  pane.appendChild(root);

  parts.forEach((p, i) => {
    built += (i === 0 ? '' : '/') + p;
    const bpath = built;
    const el = document.createElement('div');
    el.className = 'tree-item' + (i === parts.length-1 ? ' active' : '');
    el.innerHTML = `<span class="tree-indent" style="width:${(i+1)*12}px"></span><span>📁</span> ${p}`;
    el.onclick = () => expNavigate(bpath);
    pane.appendChild(el);
  });

  // Quick-access dirs from entries
  data.entries.filter(e=>e.is_dir).slice(0,30).forEach(e => {
    const el = document.createElement('div');
    el.className = 'tree-item';
    el.innerHTML = `<span class="tree-indent" style="width:${(parts.length+1)*12}px"></span><span>📁</span> ${e.name}`;
    el.onclick = () => expNavigate(e.path);
    pane.appendChild(el);
  });
}

function renderFiles(data) {
  const pane = document.getElementById('filesPane');
  pane.innerHTML = '';

  // Parent row
  if (data.parent) {
    const row = document.createElement('div');
    row.className = 'frow';
    row.onclick = () => expNavigate(data.parent);
    row.innerHTML = `<div class="fname"><span class="ficon">📁</span><span style="color:#7dd3fc">..</span></div><div class="fsize"></div><div class="fext">adresár</div>`;
    pane.appendChild(row);
  }

  data.entries.forEach(e => {
    const row = document.createElement('div');
    row.className = 'frow';
    row.onclick = () => {
      document.querySelectorAll('.frow').forEach(r=>r.classList.remove('selected'));
      row.classList.add('selected');
      if (e.is_dir) { expNavigate(e.path); }
      else          { showPreview(e); }
    };
    const ic = e.is_dir ? '📁' : extIcon(e.ext);
    const col = e.is_dir ? '#7dd3fc' : '#d1d5db';
    row.innerHTML = `
      <div class="fname"><span class="ficon">${ic}</span><span style="color:${col}">${e.name}</span></div>
      <div class="fsize">${e.size}</div>
      <div class="fext">${e.is_dir ? 'adresár' : (e.ext||'súbor')}</div>`;
    pane.appendChild(row);
  });

  if (!data.entries.length && !data.parent) {
    pane.innerHTML = '<div style="padding:2rem;color:#475569;font-size:.82rem;text-align:center">Prázdny adresár</div>';
  }
}

function clearPreview() {
  selectedFile = null;
  document.getElementById('prevInfo').innerHTML    = '<span style="color:#475569">Vyber súbor…</span>';
  document.getElementById('prevActions').innerHTML = '';
}

function showPreview(e) {
  selectedFile = e;
  document.getElementById('prevInfo').innerHTML =
    `<span class="prev-name">${e.name}</span><span style="color:#64748b">${e.size}</span>`;

  const acts = document.getElementById('prevActions');
  acts.innerHTML = '';

  // Download button always
  const dl = document.createElement('button');
  dl.className = 'prev-btn dl';
  dl.textContent = '⬇ Stiahnuť';
  dl.onclick = () => window.open('/download?path=' + encodeURIComponent(e.path));
  acts.appendChild(dl);

  // Open in new tab for previewable types
  const previewable = ['.jpg','.jpeg','.png','.gif','.bmp','.webp','.pdf','.txt','.log','.json','.md','.csv'];
  if (previewable.includes(e.ext)) {
    const pv = document.createElement('button');
    pv.className = 'prev-btn';
    pv.textContent = '👁 Zobraziť';
    pv.onclick = () => window.open('/preview?path=' + encodeURIComponent(e.path), '_blank');
    acts.appendChild(pv);
  }

  // Copy path
  const cp = document.createElement('button');
  cp.className = 'prev-btn';
  cp.textContent = '📋 Kopírovať cestu';
  cp.onclick = () => { navigator.clipboard.writeText(e.path); cp.textContent='✓ Skopírované'; setTimeout(()=>cp.textContent='📋 Kopírovať cestu',1500); };
  acts.appendChild(cp);
}

// ═══════════════════════════════════════════════════════════════
//  FILE PICKER MODAL
// ═══════════════════════════════════════════════════════════════
async function openModal(target) {
  mTarget = target;
  const titles = {device:'Vybrať disk / image', output:'Výstupný adresár', loadScan:'Scan JSON'};
  document.getElementById('mTitle').textContent = titles[target] || 'Prehľadávať';
  const start = document.getElementById(target)?.value.trim() || '.';
  await mBrowse(start);
  document.getElementById('ov').classList.add('open');
}
function closeModal() { document.getElementById('ov').classList.remove('open'); }
function ovOutside(e) { if (e.target===document.getElementById('ov')) closeModal(); }

async function mBrowse(path) {
  const data = await fetch('/browse?path='+encodeURIComponent(path)).then(r=>r.json());
  document.getElementById('mCurPath').textContent = data.current;
  document.getElementById('mSel').value = data.current;
  const list = document.getElementById('mList');
  list.innerHTML = '';
  if (data.parent) {
    const r = document.createElement('div');
    r.className='mitem dir'; r.onclick=()=>mBrowse(data.parent);
    r.innerHTML='<span>📁</span> ..'; list.appendChild(r);
  }
  data.entries.forEach(e=>{
    const r = document.createElement('div');
    r.className='mitem '+(e.is_dir?'dir':'file');
    r.onclick=()=>{ if(e.is_dir) mBrowse(e.path); else document.getElementById('mSel').value=e.path; };
    const ic = e.is_dir?'📁':extIcon(e.ext);
    r.innerHTML=`<span>${ic}</span> ${e.name} <span style="margin-left:auto;color:#475569;font-size:.7rem">${e.size}</span>`;
    list.appendChild(r);
  });
}
function mNavUp() {
  const cur = document.getElementById('mCurPath').textContent;
  fetch('/browse?path='+encodeURIComponent(cur)).then(r=>r.json()).then(d=>{ if(d.parent) mBrowse(d.parent); });
}
function confirmModal() {
  const v = document.getElementById('mSel').value.trim();
  if (mTarget && v) document.getElementById(mTarget).value = v;
  closeModal();
}

// ═══════════════════════════════════════════════════════════════
//  TOGGLES / STATUS
// ═══════════════════════════════════════════════════════════════
function toggleLoadScan() {
  document.getElementById('loadScanRow').style.display = document.getElementById('skipScan').checked?'block':'none';
}
function setStatus(s, t) {
  document.getElementById('sDot').className = 'dot '+s;
  document.getElementById('sTxt').textContent = t;
}

// ═══════════════════════════════════════════════════════════════
//  TERMINAL
// ═══════════════════════════════════════════════════════════════
function log(txt, cls='info') {
  const t = document.getElementById('terminal');
  const d = document.createElement('div');
  d.className='ll '+cls; d.textContent=txt;
  t.appendChild(d); t.scrollTop=t.scrollHeight;
}
function clearTerminal() { document.getElementById('terminal').innerHTML=''; }
function classify(l) {
  if (l.startsWith('[Fáza')||l.startsWith('===')||l.startsWith('---')) return 'phase';
  if (l.includes('[Agent')||l.includes('Agent ')) return 'agent';
  if (l.includes('thinking')||l.includes('Analyst thinking')||l.includes('Predictor')||l.includes('Planner thinking')) return 'think';
  if (l.includes('→ uložené')||l.includes('Hotovo')) return 'saved';
  if (l.includes('[WARN]')||l.includes('⚠')) return 'warn';
  if (l.includes('[CHYBA]')||l.toLowerCase().includes('error')) return 'err2';
  if (l.startsWith('  →')) return 'ok';
  return 'info';
}

// ═══════════════════════════════════════════════════════════════
//  RECOVERY
// ═══════════════════════════════════════════════════════════════
function startRecovery() {
  if (running) return;
  const params = new URLSearchParams({
    device:    document.getElementById('device').value.trim(),
    output:    document.getElementById('output').value.trim(),
    max_scan:  document.getElementById('maxScan').value.trim(),
    dry_run:   document.getElementById('dryRun').checked?'1':'0',
    load_scan: document.getElementById('skipScan').checked ? document.getElementById('loadScan').value.trim():'',
    sudo_pass: document.getElementById('sudoPass').value,
  });
  clearTerminal();
  document.getElementById('rstrip').classList.remove('on');
  document.getElementById('startBtn').disabled=true;
  document.getElementById('stopBtn').disabled=false;
  setStatus('run','Prebieha obnova…');
  running=true;
  switchTab('terminal');

  evtSrc = new EventSource('/run?'+params);
  evtSrc.addEventListener('line',      e=>log(e.data, classify(e.data)));
  evtSrc.addEventListener('result',    e=>{ try{ showResults(JSON.parse(e.data)); }catch{} });
  evtSrc.addEventListener('done',      e=>{ finish('done', e.data||'Dokončené'); autoOpenFiles(); });
  evtSrc.addEventListener('error_msg', e=>{ log('CHYBA: '+e.data,'err2'); finish('err','Chyba'); });
  evtSrc.onerror = ()=>{ if(running) finish('err','Spojenie prerušené'); };
}

function stopRecovery() {
  if(evtSrc){evtSrc.close();evtSrc=null;}
  fetch('/stop',{method:'POST'});
  finish('idle','Zastavené');
}
function finish(s,t) {
  running=false;
  if(evtSrc){evtSrc.close();evtSrc=null;}
  document.getElementById('startBtn').disabled=false;
  document.getElementById('stopBtn').disabled=true;
  setStatus(s,t);
}

function autoOpenFiles() {
  // After recovery completes, pre-load the output dir in explorer
  const outDir = document.getElementById('output').value.trim() || './recovered';
  expNavigate(outDir);
}

function showResults(data) {
  const g = document.getElementById('rgrid');
  const items = [
    {l:'Signatúr',       v:data.signatures   ??'—'},
    {l:'Partícií (AI)',  v:data.partitions   ??'—'},
    {l:'Pred. regiónov', v:data.pred_regions ??'—'},
    {l:'Akcií v pláne',  v:data.actions      ??'—'},
    {l:'Odhad obnovy',   v:data.recovery_rate??'—'},
    {l:'Výstup',         v:data.output_dir   ??'—'},
  ];
  g.innerHTML = items.map(i=>`<div class="rcard"><div class="rlbl">${i.l}</div><div class="rval">${i.v}</div></div>`).join('');
  document.getElementById('rstrip').classList.add('on');
}

// ═══════════════════════════════════════════════════════════════
//  INIT
// ═══════════════════════════════════════════════════════════════
loadDisks();
expNavigate(document.getElementById('output').value || '.');
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


@app.get("/download")
def download():
    path = request.args.get("path", "")
    p = Path(path).expanduser().resolve()
    if not p.is_file():
        return "Not found", 404
    return send_file(str(p), as_attachment=True, download_name=p.name)


@app.get("/preview")
def preview():
    path = request.args.get("path", "")
    p = Path(path).expanduser().resolve()
    if not p.is_file():
        return "Not found", 404
    mime, _ = mimetypes.guess_type(str(p))
    mime = mime or "application/octet-stream"
    return send_file(str(p), mimetype=mime)


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

    orchestrator = str(Path(__file__).parent / "orchestrator.py")
    base_cmd = [sys.executable, "-u", orchestrator,
                "--device", device, "--output", output]
    if max_scan:  base_cmd += ["--max-scan", max_scan]
    if dry_run:   base_cmd.append("--dry-run")
    if load_scan: base_cmd += ["--load-scan", load_scan]

    # Physical /dev/* devices need root on macOS/Linux
    sudo_pass = request.args.get("sudo_pass", "").strip()
    needs_sudo = device.startswith("/dev/") and os.geteuid() != 0
    cmd = base_cmd

    def generate():
        global _proc
        with _lock:
            try:
                if needs_sudo and sudo_pass:
                    # Use sudo -S to read password from stdin
                    full_cmd = ["sudo", "-S"] + base_cmd
                    _proc = subprocess.Popen(
                        full_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                        stdin=subprocess.PIPE,
                        text=True, bufsize=1, env=os.environ.copy(),
                        cwd=str(Path(__file__).parent),
                    )
                    _proc.stdin.write(sudo_pass + "\n")
                    _proc.stdin.flush()
                    _proc.stdin.close()
                elif needs_sudo and not sudo_pass:
                    yield "event: error_msg\ndata: Zariadenie /dev/ vyžaduje heslo správcu. Zadaj ho do poľa 'Sudo heslo'.\n\n"
                    return
                else:
                    _proc = subprocess.Popen(
                        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                        text=True, bufsize=1, env=os.environ.copy(),
                        cwd=str(Path(__file__).parent),
                    )
            except Exception as e:
                yield f"event: error_msg\ndata: {e}\n\n"
                return


        sig_c = part_c = reg_c = act_c = 0
        rate = ""
        for line in _proc.stdout:
            line = line.rstrip("\n")
            yield f"event: line\ndata: {line}\n\n"
            if "nájdených" in line and "signátur" in line:
                try: sig_c = int([t for t in line.split() if t.isdigit()][0])
                except: pass
            if "partícií" in line.lower() and "AI" in line:
                try: part_c = int(line.split()[1])
                except: pass
            if "Predikované regióny:" in line:
                try: reg_c = int(line.split("regióny:")[1].split(",")[0].strip())
                except: pass
            if "Akcií v pláne:" in line:
                try: act_c = int(line.split(":")[1].strip())
                except: pass
            if "Odhadov. obnova:" in line or "Odhadovaná obnova:" in line:
                rate = line.split(":", 1)[-1].strip()

        _proc.wait()
        yield f"event: result\ndata: {json.dumps({'signatures':sig_c,'partitions':part_c,'pred_regions':reg_c,'actions':act_c,'recovery_rate':rate,'output_dir':output})}\n\n"
        rc = _proc.returncode
        yield f"event: done\ndata: {'Úspešne dokončené ✓' if rc==0 else f'Ukončené s kódom {rc}'}\n\n"

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/stop")
def stop():
    global _proc
    with _lock:
        if _proc and _proc.poll() is None:
            _proc.terminate()
    return jsonify({"ok": True})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"\n  Disk Recovery UI beží na  http://localhost:{port}\n")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
