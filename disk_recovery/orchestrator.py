"""
orchestrator.py — Hlavný orchester multi-agentového systému obnovy dát

Postup:
  1. Scanner    → raw scan report (signatúry na disku)
  2. Agent 1    → analýza nálezov (MapAnalystAgent)
  3. Agent 2    → predikcia mapy  (MapPredictorAgent)
  4. Agent 3    → plán obnovy     (RecoveryPlannerAgent)
  5. Executor   → fyzická obnova  (CarverExecutor)

Použitie:
  sudo python3 disk_recovery/orchestrator.py --device /dev/sdb --output ./recovered
  python3 disk_recovery/orchestrator.py --device testdisk.img --output ./recovered --max-scan 100M
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path
from datetime import datetime

# Add parent dir to path so imports work when run from disk_recovery/
sys.path.insert(0, str(Path(__file__).parent))

from scanner import scan_device
from agents import run_map_analyst, run_map_predictor, run_recovery_planner
from carver import RecoveryExecutor
from apfs import scan_apfs, generate_apfs_recovery_hints


def parse_size(s: str) -> int:
    """Parsuje '100M', '2G', '512K' na bajty."""
    s = s.strip().upper()
    mul = {"B": 1, "K": 1024, "M": 1024**2, "G": 1024**3, "T": 1024**4}
    for suffix, m in mul.items():
        if s.endswith(suffix):
            return int(s[:-1]) * m
    return int(s)


def human(n: int) -> str:
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {u}"
        n //= 1024
    return f"{n:.1f} PB"


def progress(done: int, total: int):
    pct = done / total * 100 if total else 0
    bar = "#" * int(pct / 2) + "-" * (50 - int(pct / 2))
    print(f"\r  [{bar}] {pct:5.1f}%  {human(done)}/{human(total)}", end="", flush=True)


def save_artifact(data: dict | list, path: Path):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"  → uložené: {path.name}")


def run_recovery(
    device: str,
    output_dir: str,
    max_scan: int | None,
    skip_execution: bool,
    load_scan: str | None,
    load_analysis: str | None,
):
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    print("=" * 65)
    print("  AI-riadená obnova dát — multi-agentový systém")
    print("=" * 65)
    print(f"  Zariadenie:  {device}")
    print(f"  Výstup:      {out}")
    print(f"  Čas:         {ts}")
    print("=" * 65)

    # ────────────────────────────────────────────────────
    #  FÁZA 0 — Multi-device (RAID/JBOD) detekcia
    # ────────────────────────────────────────────────────
    devices = [d.strip() for d in device.split(",") if d.strip()]
    if len(devices) > 1:
        print(f"\n[Fáza 0] Zistených viacero zariadení: {devices}")
        print("         Spúšťam AI analýzu pre softvérovú rekonštrukciu poľa...")
        
        # Oskenujme začiatok každého disku pre AI
        multi_scans = {}
        for dev in devices:
            print(f"  Skenujem {dev}...")
            r = scan_device(dev, max_bytes=1024*1024*200) # Skenuj prvých 200MB
            multi_scans[dev] = json.loads(r.to_json())
            
        print("\n  Agent 1 analyzuje vzory diskov (JBOD vs RAID0)...")
        # Zavoláme špeciálnu promptu pre RAID analýzu (alebo použijeme existujúceho agenta)
        # Pre jednoduchosť tu pridáme rýchle vyhodnotenie alebo agent fallback
        raid_analysis_prompt = json.dumps(multi_scans)
        from agents import run_map_analyst
        analysis = run_map_analyst(raid_analysis_prompt)
        
        # Extrahujeme AI rozhodnutie
        mode = "JBOD"
        if "RAID0" in str(analysis).upper() or "STRIPE" in str(analysis).upper():
            mode = "RAID0"
        print(f"  AI identifikovalo mód: {mode}")
        
        from raid_builder import reconstruct_raid
        from gpt_repair import repair_apfs_gpt
        
        img_out = str(out / f"reconstructed_{ts}.img")
        print("\n[Fáza 0.5] Fyzické spájanie diskov (toto môže trvať dlho)...")
        reconstruct_raid(devices, img_out, mode=mode, chunk_size=128*1024, progress_cb=progress)
        print()
        
        print("\n[Fáza 0.6] Hľadám APFS hlavičku pre opravu GPT...")
        img_scan = scan_device(img_out, max_bytes=1024*1024*500)
        apfs_sigs = [s for s in img_scan.signatures if s.name.startswith("APFS")]
        if apfs_sigs:
            start_sector = apfs_sigs[0].sector
            print(f"  APFS nájdené na sektore {start_sector}. Opravujem partičnú mapu...")
            repair_apfs_gpt(img_out, start_sector, (os.path.getsize(img_out)//512) - start_sector - 40)
        else:
            print("  [WARN] APFS hlavička sa nenašla, zapisujem default GPT...")
            repair_apfs_gpt(img_out, 40, (os.path.getsize(img_out)//512) - 80)
            
        print("\n=" * 65)
        print("  HOTOVO! Zrekonštruovaný disk je pripravený.")
        print(f"  Súbor: {img_out}")
        print("  1. Dvojklikom na tento .img súbor vo Finderi ho pripojíš.")
        print("  2. Súbory sa zobrazia aj s pôvodnými názvami a zložkami.")
        print("=" * 65)
        
        # Koniec programu pre multi-disk, keďže výstupom je natívny .img
        print(f"event: summary\ndata: Zrekonštruovaný obraz nájdeš tu: {img_out}. Dvojklikom ho pripoj v macOS.\n\n")
        return

    # ────────────────────────────────────────────────────
    #  FÁZA 1 — Skenovanie
    # ────────────────────────────────────────────────────
    if load_scan:
        print(f"\n[Fáza 1] Načítavam existujúci scan: {load_scan}")
        with open(load_scan) as f:
            scan_dict = json.load(f)
        scan_json = json.dumps(scan_dict)
        device_size = scan_dict.get("device_size", 0)
    else:
        print(f"\n[Fáza 1] Skenujem zariadenie{' (max ' + human(max_scan) + ')' if max_scan else ''}...")
        t0 = time.monotonic()
        scan_report = scan_device(device, max_bytes=max_scan, progress_cb=progress)
        print()  # newline after progress bar
        elapsed = time.monotonic() - t0

        sig_count = len(scan_report.signatures)
        device_size = scan_report.device_size
        print(f"  Hotovo za {elapsed:.1f}s — nájdených {sig_count} signátur, "
              f"{scan_report.sectors_scanned} sektorov")

        scan_dict = json.loads(scan_report.to_json())
        scan_json = scan_report.to_json()
        scan_path = out / f"scan_{ts}.json"
        save_artifact(scan_dict, scan_path)

    if not scan_dict.get("signatures"):
        print("\n[WARN] Žiadne signátúry nenájdené. Zariadenie môže byť prázdne,")
        print("       plne zašifrované, alebo príliš poškodené.")
        print("       Pokračujem s prázdnou analýzou...")

    # ────────────────────────────────────────────────────
    #  FÁZA 1b — APFS skenovanie (ak sa nájde APFS_NX/VOL)
    # ────────────────────────────────────────────────────
    apfs_hints: list[dict] = []
    apfs_sigs = [s for s in scan_dict.get("signatures", []) if s.get("name", "").startswith("APFS")]
    device_path_for_apfs = None if load_scan else device

    if apfs_sigs and device_path_for_apfs:
        print(f"\n[Fáza 1b] Nájdených {len(apfs_sigs)} APFS signátur — spúšťam APFS skener...")
        try:
            apfs_result = scan_apfs(device_path_for_apfs, max_bytes=max_scan, progress_cb=None)
            print()
            apfs_hints = generate_apfs_recovery_hints(apfs_result)
            print(f"  APFS: {len(apfs_result.containers)} kontajner(ov), "
                  f"{len(apfs_result.volumes)} volume(s), "
                  f"{len(apfs_hints)} hints pre plánovač")
            apfs_path = out / f"apfs_{ts}.json"
            save_artifact(apfs_result.to_dict(), apfs_path)
        except Exception as e:
            print(f"  [WARN] APFS skener zlyhal: {e}")
    elif apfs_sigs:
        print(f"\n[Fáza 1b] {len(apfs_sigs)} APFS signátur v načítanom scane "
              "(APFS deep scan preskočený — pracujem z uloženého scanu)")

    # ────────────────────────────────────────────────────
    #  FÁZA 2 — AI Analýza (Agent 1)
    # ────────────────────────────────────────────────────
    if load_analysis:
        print(f"\n[Fáza 2] Načítavam existujúcu analýzu: {load_analysis}")
        with open(load_analysis) as f:
            analyst_result = json.load(f)
    else:
        print("\n[Fáza 2] Agent 1 analyzuje scan report...")
        analyst_result = run_map_analyst(scan_json)
        analysis_path = out / f"analysis_{ts}.json"
        save_artifact(analyst_result, analysis_path)

        part_count = len(analyst_result.get("partitions", []))
        file_clust = len(analyst_result.get("file_clusters", []))
        print(f"  Nájdené: {part_count} partícií, {file_clust} zhlukov súborov")
        print(f"  Zhrnutie: {analyst_result.get('summary', '')[:200]}")

    # ────────────────────────────────────────────────────
    #  FÁZA 3 — AI Predikcia mapy (Agent 2)
    # ────────────────────────────────────────────────────
    print("\n[Fáza 3] Agent 2 predikuje chýbajúce časti mapy...")
    predictor_result = run_map_predictor(scan_json, analyst_result, device_size)
    pred_path = out / f"prediction_{ts}.json"
    save_artifact(predictor_result, pred_path)

    region_count = len(predictor_result.get("predicted_regions", []))
    file_pred_count = len(predictor_result.get("predicted_file_locations", []))
    print(f"  Predikované regióny: {region_count}, súbory: {file_pred_count}")
    print(f"  Fragmentácia: {predictor_result.get('fragmentation_assessment', 'N/A')[:150]}")

    # ────────────────────────────────────────────────────
    #  FÁZA 4 — AI Plán obnovy (Agent 3)
    # ────────────────────────────────────────────────────
    print("\n[Fáza 4] Agent 3 zostavuje plán obnovy...")
    recovery_plan = run_recovery_planner(analyst_result, predictor_result, device_size,
                                         apfs_hints=apfs_hints or None)
    plan_path = out / f"plan_{ts}.json"
    save_artifact(recovery_plan, plan_path)

    actions = recovery_plan.get("actions", [])
    print(f"  Akcií v pláne: {len(actions)}")
    print(f"  Odhadovaná obnova: {recovery_plan.get('estimated_recovery_rate', 'N/A')}")
    print(f"  Zhrnutie: {recovery_plan.get('summary', '')[:200]}")

    warnings = recovery_plan.get("warnings", [])
    if warnings:
        print("\n  ⚠ Varovania:")
        for w in warnings:
            print(f"    - {w}")

    # ────────────────────────────────────────────────────
    #  VÝPIS PLÁNU
    # ────────────────────────────────────────────────────
    print("\n" + "─" * 65)
    print("  PLÁN OBNOVY")
    print("─" * 65)
    for i, act in enumerate(sorted(actions, key=lambda a: a.get("priority", 99)), 1):
        offset = act.get("offset", 0)
        length = act.get("length")
        print(f"\n  [{i}] {act.get('action','?').upper()} — priorita {act.get('priority','?')}")
        print(f"      Offset: {human(offset)} ({offset})")
        print(f"      Dĺžka:  {human(length) if length else 'do konca disku'}")
        print(f"      Výstup: {act.get('output_name','?')}")
        print(f"      Metóda: {act.get('method','')[:100]}")
        print(f"      Dôvod:  {act.get('rationale','')[:120]}")

    # ────────────────────────────────────────────────────
    #  FÁZA 5 — Exekúcia
    # ────────────────────────────────────────────────────
    if skip_execution:
        print("\n[Fáza 5] Exekúcia PRESKOČENÁ (--dry-run)")
    else:
        print(f"\n[Fáza 5] Spúšťam obnovu do {out}/...")

        if not os.path.exists(device):
            print(f"  [CHYBA] Zariadenie {device!r} neexistuje. Exekúcia preskočená.")
        else:
            executor = RecoveryExecutor(device, str(out / f"data_{ts}"))
            results = executor.execute_plan(recovery_plan)

            results_path = out / f"results_{ts}.json"
            save_artifact(results, results_path)

            success = sum(1 for r in results if r.get("success"))
            print(f"\n  Hotovo: {success}/{len(results)} akcií úspešných")

    # ────────────────────────────────────────────────────
    #  ZÁVEREČNÁ SPRÁVA
    # ────────────────────────────────────────────────────
    print("\n" + "=" * 65)
    print("  ZÁVEREČNÁ SPRÁVA")
    print("=" * 65)
    print(f"  Zariadenie:       {device}  ({human(device_size)})")
    print(f"  Signátur nájd.:   {len(scan_dict.get('signatures', []))}")
    print(f"  Partícií (AI):    {len(analyst_result.get('partitions', []))}")
    print(f"  Predik. regiónov: {len(predictor_result.get('predicted_regions', []))}")
    print(f"  Akcií v pláne:    {len(actions)}")
    print(f"  Odhadov. obnova:  {recovery_plan.get('estimated_recovery_rate', 'N/A')}")
    print(f"\n  Výstupný adresár: {out}")
    print(f"  Artefakty:        scan_*.json, analysis_*.json, prediction_*.json, plan_*.json")
    print("=" * 65)


def main():
    ap = argparse.ArgumentParser(
        description="AI-riadená obnova dát z disku bez mapy partícií",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Príklady:
  sudo python3 disk_recovery/orchestrator.py --device /dev/sdb --output ./recovered
  python3 disk_recovery/orchestrator.py --device disk.img --output ./out --max-scan 200M
  python3 disk_recovery/orchestrator.py --device disk.img --output ./out --dry-run
  python3 disk_recovery/orchestrator.py --device disk.img --output ./out \\
    --load-scan ./out/scan_20240101.json  # preskočí skenovanie
        """,
    )
    ap.add_argument("--device", required=True,
                    help="Zdrojové zariadenie alebo disk image (/dev/sdb, disk.img)")
    ap.add_argument("--output", required=True,
                    help="Výstupný adresár pre obnovené dáta a reporty")
    ap.add_argument("--max-scan", default=None,
                    help="Maximálna veľkosť skenu (napr. 100M, 2G). Default: celý disk")
    ap.add_argument("--dry-run", action="store_true",
                    help="Len analyzuj a navrhni plán, nespúšťaj obnovu")
    ap.add_argument("--load-scan",
                    help="Načítaj existujúci scan JSON (preskočí fázu 1)")
    ap.add_argument("--load-analysis",
                    help="Načítaj existujúcu analýzu JSON (preskočí fázu 2)")

    args = ap.parse_args()

    max_scan = parse_size(args.max_scan) if args.max_scan else None

    if not args.load_scan and not os.path.exists(args.device):
        print(f"[CHYBA] Zariadenie/súbor {args.device!r} neexistuje.", file=sys.stderr)
        sys.exit(1)

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("[CHYBA] Nastavte ANTHROPIC_API_KEY.", file=sys.stderr)
        sys.exit(1)

    run_recovery(
        device=args.device,
        output_dir=args.output,
        max_scan=max_scan,
        skip_execution=args.dry_run,
        load_scan=args.load_scan,
        load_analysis=args.load_analysis,
    )


if __name__ == "__main__":
    main()
