"""
agents.py — AI agenti pre analýzu a predikciu mapy disku

Tri specializované Claude agenti:
  1. MapAnalystAgent  — analyzuje scan report, identifikuje štruktúry
  2. MapPredictorAgent — predikuje chýbajúce časti mapy a odhaduje rozmiestnenie
  3. RecoveryPlannerAgent — zostavuje konkrétny akčný plán obnovy
"""

import json
import anthropic
from dataclasses import dataclass, field

client = anthropic.Anthropic()
MODEL = "claude-opus-4-8"


# ─────────────────────────────────────────────────────────
#  Výstupné štruktúry
# ─────────────────────────────────────────────────────────

@dataclass
class PartitionEntry:
    estimated_start: int        # byte offset
    estimated_end: int | None
    filesystem: str
    confidence: float           # 0.0 – 1.0
    evidence: str
    notes: str


@dataclass
class FileCluster:
    offset: int
    file_type: str
    estimated_size: int | None
    confidence: float
    recovery_priority: str      # "high" | "medium" | "low"


@dataclass
class DiskMap:
    device: str
    device_size: int
    partitions: list[PartitionEntry] = field(default_factory=list)
    file_clusters: list[FileCluster] = field(default_factory=list)
    analyst_summary: str = ""
    prediction_notes: str = ""


@dataclass
class RecoveryAction:
    action: str          # "carve_file" | "extract_partition" | "scan_region"
    priority: int        # 1 = highest
    offset: int
    length: int | None
    filesystem: str | None
    output_name: str
    method: str
    rationale: str


@dataclass
class RecoveryPlan:
    actions: list[RecoveryAction] = field(default_factory=list)
    summary: str = ""
    estimated_recovery_rate: str = ""
    warnings: list[str] = field(default_factory=list)


# ─────────────────────────────────────────────────────────
#  Agent 1: MapAnalystAgent
# ─────────────────────────────────────────────────────────

ANALYST_SYSTEM = """
Si expert na forenziku a obnovu dát z poškodených diskov.
Dostaneš raw scan report disku (JSON), kde sú zaznamenané
všetky nájdené signatúry (magic bytes) jednotlivých súborových
systémov a typov súborov.

Pre APFS (Apple File System) štruktúry:
- APFS_NX = NX Container Superblock (NXSB) — koreňový kontajner, obsahuje viacero volumes
- APFS_VOL = APFS Volume Superblock (APSB) — individuálny volume v rámci kontajnera
- APFS kontajner obvykle začína na začiatku Apple_APFS GPT partície
- Jeden kontajner obsahuje systémový volume (role=SYSTEM), dátový volume (role=DATA),
  Preboot, Recovery a VM volumes
- FileVault šifrovaný kontajner má incompat_features bit 0x1 (APFS_INCOMPAT_ENCRYPTED)
- Checkpoint oblasť (xp_desc_base) obsahuje históriu transakcií — dôležité pre obnovu
- V poškodených prípadoch môžu byť viditeľné iba niektoré volumes alebo žiadne

Tvoja úloha:
1. Analyzuj polohy signátur a ich kontexty
2. Identifikuj pravdepodobné partície (ich začiatky, konce, typy FS) vrátane APFS
3. Identifikuj zhluky súborov konkrétnych typov
4. Vyhodnoť integritu nálezov (môže ísť o false positives?)
5. Sumarizuj stav disku — čo je čitateľné, čo poškodené

Odpovedaj VŽDY ako JSON objekt s týmito kľúčmi:
{
  "partitions": [
    {
      "estimated_start": <int — byte offset>,
      "estimated_end": <int alebo null>,
      "filesystem": "<FAT32|NTFS|EXT4|...>",
      "confidence": <float 0-1>,
      "evidence": "<čo podporuje tento záver>",
      "notes": "<dodatočné poznámky>"
    }
  ],
  "file_clusters": [
    {
      "offset": <int>,
      "file_type": "<PDF|JPEG|...>",
      "estimated_size": <int alebo null>,
      "confidence": <float 0-1>,
      "recovery_priority": "<high|medium|low>"
    }
  ],
  "summary": "<text — zhrnutie stavu disku>"
}
""".strip()


def run_map_analyst(scan_report_json: str) -> dict:
    """
    Agent 1 — analyzuje scan report a vracia štruktúrovanú analýzu.
    """
    print("[Agent 1 — MapAnalyst] Analyzujem scan report...")

    with client.messages.stream(
        model=MODEL,
        max_tokens=8192,
        thinking={"type": "adaptive"},
        system=ANALYST_SYSTEM,
        messages=[{
            "role": "user",
            "content": (
                "Analyzuj nasledujúci scan report disku a vráť JSON analýzu:\n\n"
                f"```json\n{scan_report_json}\n```"
            ),
        }],
    ) as stream:
        response = stream.get_final_message()

    # extract JSON from response
    text = next(b.text for b in response.content if b.type == "text")
    thinking = next((b.thinking for b in response.content if b.type == "thinking"), None)

    if thinking:
        print(f"  [Analyst thinking excerpt]: {thinking[:300]}...")

    # extract JSON block
    json_str = _extract_json(text)
    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        print(f"  [WARN] Analyst JSON parse failed, raw:\n{text[:500]}")
        return {"partitions": [], "file_clusters": [], "summary": text}


# ─────────────────────────────────────────────────────────
#  Agent 2: MapPredictorAgent
# ─────────────────────────────────────────────────────────

PREDICTOR_SYSTEM = """
Si expert na nízko-úrovňové diskové štruktúry a forenziku.
Dostaneš čiastočnú analýzu disku (kde sú nájdené signatúry)
a informácie o celkovej veľkosti disku.

Tvoja úloha JE PREDIKCIA — musíš domysleť čo nie je priamo viditeľné:
1. Na základe nájdených signátur odhadni chýbajúce časti mapy
2. Predikuj kde mohli byť ďalšie súbory (spacing, alignment, FS cluster size)
3. Identifikuj oblasti kde pravdepodobne sú dáta aj bez signátur
   (napr. uprostred fragmented file, deleted files area, journal area)
4. Vyhodnoť fragmentáciu — odhadni, či sú súbory contiguous alebo fragmentované
5. Navrhni sekvenciu scanovaných regiónov podľa priority

Použij vedomosti o:
- Typickom rozložení MBR/GPT partícií (alignment na 1MB/2048 sektorov)
- Cluster size pre rôzne FS (FAT32: 4-32KB, NTFS: 4KB, EXT4: 4KB, APFS: 4KB default)
- Kde bývajú journaly, FAT tables, inode tables atď.
- Ako vyzerá diskový priestor po zmazaní/poškodení
- APFS špecifiká: Object Map (B-Tree), Space Manager, checkpoint descriptor/data oblasti,
  Sealed volumes (macOS 11+), snapshot metadata, Fusion Drive APFS containers

Odpovedaj VŽDY ako JSON:
{
  "predicted_regions": [
    {
      "start": <int — byte offset>,
      "end": <int>,
      "region_type": "<partition_data|filesystem_metadata|file_data|free_space|unknown>",
      "filesystem": "<typ alebo null>",
      "confidence": <float 0-1>,
      "rationale": "<prečo si to myslíš>",
      "scan_priority": <int 1-10, kde 1=najvyššia>
    }
  ],
  "predicted_file_locations": [
    {
      "start": <int>,
      "end": <int>,
      "file_type": "<typ>",
      "confidence": <float>,
      "why_here": "<odôvodnenie>"
    }
  ],
  "fragmentation_assessment": "<text>",
  "prediction_notes": "<text — celkové poznámky k predikcii>"
}
""".strip()


def run_map_predictor(
    scan_report_json: str,
    analyst_result: dict,
    device_size: int,
) -> dict:
    """
    Agent 2 — predikuje chýbajúce časti mapy na základe analýzy.
    """
    print("[Agent 2 — MapPredictor] Predikujem chýbajúce oblasti mapy...")

    payload = {
        "device_size_bytes": device_size,
        "device_size_human": _human(device_size),
        "analyst_analysis": analyst_result,
        "raw_signatures_summary": json.loads(scan_report_json).get("signatures", [])[:50],
    }

    with client.messages.stream(
        model=MODEL,
        max_tokens=8192,
        thinking={"type": "adaptive"},
        system=PREDICTOR_SYSTEM,
        messages=[{
            "role": "user",
            "content": (
                "Na základe tejto analýzy predikuj chýbajúce oblasti mapy disku:\n\n"
                f"```json\n{json.dumps(payload, indent=2)}\n```"
            ),
        }],
    ) as stream:
        response = stream.get_final_message()

    text = next(b.text for b in response.content if b.type == "text")
    thinking = next((b.thinking for b in response.content if b.type == "thinking"), None)

    if thinking:
        print(f"  [Predictor thinking excerpt]: {thinking[:300]}...")

    json_str = _extract_json(text)
    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        print(f"  [WARN] Predictor JSON parse failed, raw:\n{text[:500]}")
        return {"predicted_regions": [], "predicted_file_locations": [], "prediction_notes": text}


# ─────────────────────────────────────────────────────────
#  Agent 3: RecoveryPlannerAgent
# ─────────────────────────────────────────────────────────

PLANNER_SYSTEM = """
Si expert na obnovu dát s praktickými skúsenosťami s nástrojmi
ako testdisk, photorec, ddrescue a vlastnými skriptami.

Dostaneš:
- Analýzu disku (Agent 1)
- Predikciu mapy (Agent 2)
- Veľkosť disku

Tvoja úloha je AKČNÝ PLÁN OBNOVY — konkrétne kroky v správnom poradí:
1. Zoraď akcie podľa priority (čo prinesie najviac dát s najmenším rizikom)
2. Pre každú akciu špecifikuj presné parametre (offsets, lengty, metódy)
3. Navrhni metódu pre každú akciu (file carving, partition extract, raw copy)
4. Upozorni na riziká (overwrite, partial recovery, corruption)

Metódy:
- "raw_copy": dd-like kopírovanie oblasti bez interpretácie
- "file_carve": carving na základe file signatures (ako photorec)
- "partition_extract": extrahovanie celej partície a mountovanie
- "fs_scan": skenovanie a rekonštrukcia súborového systému
- "journal_recovery": obnovenie z journalu (EXT4, NTFS)
- "apfs_container_extract": extrahovanie celého APFS kontajnera ako image
- "apfs_volume_scan": skenovanie APFS volumes v rámci kontajnera a obnova súborov

Odpovedaj VŽDY ako JSON:
{
  "actions": [
    {
      "action": "<raw_copy|file_carve|partition_extract|fs_scan|journal_recovery|apfs_container_extract|apfs_volume_scan>",
      "priority": <int 1=first>,
      "offset": <byte offset kde začať>,
      "length": <počet bajtov alebo null=do konca>,
      "filesystem": "<typ alebo null>",
      "output_name": "<názov výstupného súboru/adresára>",
      "method": "<konkrétny postup — môže byť dd command, photorec config...>",
      "rationale": "<prečo táto akcia>"
    }
  ],
  "summary": "<stručný prehľad stratégie>",
  "estimated_recovery_rate": "<odhadované % obnoviteľných dát>",
  "warnings": ["<varovanie 1>", ...]
}
""".strip()


def run_recovery_planner(
    analyst_result: dict,
    predictor_result: dict,
    device_size: int,
    apfs_hints: list[dict] | None = None,
) -> dict:
    """
    Agent 3 — zostavuje akčný plán obnovy.
    """
    print("[Agent 3 — RecoveryPlanner] Zostavujem plán obnovy...")

    payload = {
        "device_size_bytes": device_size,
        "analyst_analysis": analyst_result,
        "predictor_map": predictor_result,
    }
    if apfs_hints:
        payload["apfs_recovery_hints"] = apfs_hints

    with client.messages.stream(
        model=MODEL,
        max_tokens=8192,
        thinking={"type": "adaptive"},
        system=PLANNER_SYSTEM,
        messages=[{
            "role": "user",
            "content": (
                "Na základe tejto analýzy a predikcie mapy navrhni konkrétny plán obnovy:\n\n"
                f"```json\n{json.dumps(payload, indent=2)}\n```"
            ),
        }],
    ) as stream:
        response = stream.get_final_message()

    text = next(b.text for b in response.content if b.type == "text")
    thinking = next((b.thinking for b in response.content if b.type == "thinking"), None)

    if thinking:
        print(f"  [Planner thinking excerpt]: {thinking[:300]}...")

    json_str = _extract_json(text)
    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        print(f"  [WARN] Planner JSON parse failed, raw:\n{text[:500]}")
        return {"actions": [], "summary": text, "warnings": []}


# ─────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────

def _extract_json(text: str) -> str:
    """Extrahuje JSON blok z textu (medzi ``` alebo priamo)."""
    import re
    # Try ```json ... ``` block
    m = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", text)
    if m:
        return m.group(1)
    # Try first { ... } spanning the whole string
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1:
        return text[start: end + 1]
    return text


def _human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n //= 1024
    return f"{n:.1f} PB"
