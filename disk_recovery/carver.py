"""
carver.py — Exekútor plánu obnovy

Na základe RecoveryPlan od AI agentov fyzicky kopíruje/carve-uje dáta.
"""

import os
import json
from pathlib import Path


SECTOR = 512


def _human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n //= 1024
    return f"{n:.1f} PB"


def _safe_name(name: str) -> str:
    return "".join(c if c.isalnum() or c in "._-" else "_" for c in name)


class RecoveryExecutor:
    def __init__(self, device_path: str, output_dir: str):
        self.device = device_path
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    # ── Low-level read ────────────────────────────────────────────────

    def _open_device(self):
        return os.open(self.device, os.O_RDONLY | os.O_NONBLOCK)

    def _device_size(self, fd: int) -> int:
        import fcntl, struct
        try:
            buf = fcntl.ioctl(fd, 0x80081272, b" " * 8)
            return struct.unpack("Q", buf)[0]
        except OSError:
            return os.lseek(fd, 0, os.SEEK_END)

    # ── Action handlers ──────────────────────────────────────────────

    def raw_copy(self, offset: int, length: int | None, output_name: str) -> dict:
        """Kopíruje surové bajty z disku do súboru."""
        out_path = self.output_dir / _safe_name(output_name)
        fd = self._open_device()
        dev_size = self._device_size(fd)
        copy_len = length if length else (dev_size - offset)

        print(f"  [raw_copy] {_human(offset)} + {_human(copy_len)} → {out_path.name}")
        copied = 0
        block = 1024 * 1024  # 1 MB chunks
        errors = 0

        with open(out_path, "wb") as out:
            while copied < copy_len:
                chunk = min(block, copy_len - copied)
                try:
                    os.lseek(fd, offset + copied, os.SEEK_SET)
                    data = os.read(fd, chunk)
                    if not data:
                        break
                    out.write(data)
                    copied += len(data)
                except OSError:
                    errors += 1
                    out.write(b"\x00" * chunk)
                    copied += chunk

        os.close(fd)
        return {"output": str(out_path), "bytes_copied": copied, "errors": errors}

    def file_carve(
        self,
        offset: int,
        length: int | None,
        output_name: str,
        file_type: str | None = None,
    ) -> dict:
        """
        Jednoduchý file carver — hľadá file signatures v oblasti disku
        a extrahuje nájdené súbory.
        """
        from scanner import FILE_SIGNATURES

        out_dir = self.output_dir / _safe_name(output_name)
        out_dir.mkdir(exist_ok=True)

        fd = self._open_device()
        dev_size = self._device_size(fd)
        scan_len = length if length else (dev_size - offset)

        # Filter signatures
        targets = {
            n: (p, o) for n, (p, o) in FILE_SIGNATURES.items()
            if file_type is None or n.startswith(file_type)
        }

        # Read in overlapping windows to not miss cross-boundary signatures
        window = 65536          # 64 KB read windows
        overlap = 256           # overlap between windows to catch cross-boundary sigs

        found_files: list[dict] = []
        pos = 0

        print(f"  [file_carve] skenujeme {_human(scan_len)} od offsetu {_human(offset)}")

        while pos < scan_len:
            read_start = offset + pos
            read_len = min(window, scan_len - pos)
            try:
                os.lseek(fd, read_start, os.SEEK_SET)
                data = os.read(fd, read_len)
            except OSError:
                pos += window - overlap
                continue

            # Check each target signature
            for name, (pattern, rel_off) in targets.items():
                search_start = rel_off
                while True:
                    idx = data.find(pattern, search_start - rel_off if search_start > rel_off else 0)
                    if idx == -1:
                        break
                    abs_sig_offset = read_start + idx - rel_off
                    if abs_sig_offset < offset:
                        search_start = idx + len(pattern) + rel_off
                        continue

                    # Extract up to max_size bytes
                    max_sizes = {
                        "PDF": 50 * 1024 * 1024,
                        "JPEG": 20 * 1024 * 1024,
                        "PNG":  20 * 1024 * 1024,
                        "ZIP":  200 * 1024 * 1024,
                        "MP4":  2 * 1024 * 1024 * 1024,
                        "SQLite": 100 * 1024 * 1024,
                    }
                    max_s = max_sizes.get(name, 10 * 1024 * 1024)
                    ext_map = {
                        "PDF": "pdf", "JPEG": "jpg", "PNG": "png", "GIF": "gif",
                        "ZIP": "zip", "DOCX/XLSX": "zip", "ELF": "bin",
                        "SQLite": "db", "MP3": "mp3", "MP4": "mp4",
                        "AVI": "avi", "TAR": "tar", "7ZIP": "7z", "GZIP": "gz",
                    }
                    ext = ext_map.get(name, "bin")
                    fname = f"{name}_{abs_sig_offset:016x}.{ext}"
                    fpath = out_dir / fname

                    if not fpath.exists():
                        extracted = _extract_file(fd, abs_sig_offset, max_s)
                        if extracted:
                            with open(fpath, "wb") as f:
                                f.write(extracted)
                            found_files.append({
                                "type": name,
                                "offset": abs_sig_offset,
                                "size": len(extracted),
                                "file": str(fpath),
                            })

                    search_start = idx + len(pattern) + rel_off

            pos += window - overlap

        os.close(fd)
        print(f"    → nájdených {len(found_files)} súborov v {out_dir.name}/")
        return {"output_dir": str(out_dir), "files_found": found_files}

    def partition_extract(
        self, offset: int, length: int | None, output_name: str
    ) -> dict:
        """Extrahuje partíciu ako disk image."""
        out_path = self.output_dir / _safe_name(output_name + ".img")
        result = self.raw_copy(offset, length, out_path.name)
        result["type"] = "partition_image"
        return result

    # ── Plan executor ────────────────────────────────────────────────

    def execute_plan(self, plan: dict) -> list[dict]:
        """Vykoná všetky akcie z RecoveryPlan podľa priority."""
        actions = sorted(plan.get("actions", []), key=lambda a: a.get("priority", 99))
        results = []

        print(f"\n[Executor] Spúšťam {len(actions)} akcií...")
        for i, action in enumerate(actions, 1):
            act_type = action.get("action", "raw_copy")
            offset = int(action.get("offset", 0))
            length = action.get("length")
            if length is not None:
                length = int(length)
            output_name = action.get("output_name", f"recovery_{i}")

            print(f"\n  Akcia {i}/{len(actions)}: {act_type} — {output_name}")
            print(f"    offset={_human(offset)}, length={_human(length) if length else 'EOF'}")
            print(f"    rationale: {action.get('rationale', '')[:120]}")

            try:
                if act_type == "raw_copy":
                    r = self.raw_copy(offset, length, output_name)
                elif act_type in ("file_carve",):
                    fs_type = action.get("filesystem")
                    r = self.file_carve(offset, length, output_name)
                elif act_type in ("partition_extract", "fs_scan", "journal_recovery"):
                    r = self.partition_extract(offset, length, output_name)
                else:
                    r = self.raw_copy(offset, length, output_name)

                r["action"] = act_type
                r["success"] = True
                results.append(r)
            except Exception as e:
                results.append({
                    "action": act_type,
                    "output_name": output_name,
                    "success": False,
                    "error": str(e),
                })
                print(f"    [CHYBA] {e}")

        return results


def _extract_file(fd: int, start: int, max_size: int) -> bytes | None:
    """Číta bajty od start, do max_size."""
    try:
        os.lseek(fd, start, os.SEEK_SET)
        return os.read(fd, max_size)
    except OSError:
        return None
