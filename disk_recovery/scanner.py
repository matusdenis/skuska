"""
scanner.py — Raw disk scanner

Číta surové sektory z disku a hľadá known signatures (magic bytes)
pre súborové systémy, partition tables a typy súborov.
"""

import os
import struct
import json
from dataclasses import dataclass, field, asdict
from typing import Generator


SECTOR_SIZE = 512

# Partition table / filesystem signatures
FS_SIGNATURES: dict[str, bytes] = {
    "MBR":         b"\x55\xAA",           # offset 510
    "GPT":         b"EFI PART",            # offset 0
    "FAT32":       b"FAT32   ",            # offset 82
    "FAT16":       b"FAT16   ",            # offset 54
    "NTFS":        b"NTFS    ",            # offset 3
    "EXT2/3/4":    b"\x53\xEF",           # offset 1080 (superblock magic)
    "XFS":         b"XFSB",               # offset 0
    "BTRFS":       b"_BHRfS_M",           # offset 65600
    "exFAT":       b"EXFAT   ",           # offset 3
    "APFS_NX":     b"NXSB",               # NXSB container magic at offset 32 in object
    "APFS_VOL":    b"APSB",               # APSB volume magic at offset 32 in object
}

# File type signatures (magic bytes at offset 0)
FILE_SIGNATURES: dict[str, tuple[bytes, int]] = {
    "PDF":       (b"%PDF",                    0),
    "ZIP":       (b"PK\x03\x04",              0),
    "DOCX/XLSX": (b"PK\x03\x04",              0),   # same as ZIP — OOXML
    "JPEG":      (b"\xFF\xD8\xFF",            0),
    "PNG":       (b"\x89PNG\r\n\x1a\n",       0),
    "GIF":       (b"GIF8",                    0),
    "MP3":       (b"\xFF\xFB",                0),
    "MP4":       (b"ftyp",                    4),
    "AVI":       (b"RIFF",                    0),
    "ELF":       (b"\x7FELF",                 0),
    "SQLite":    (b"SQLite format 3\x00",     0),
    "TAR":       (b"ustar",                   257),
    "7ZIP":      (b"7z\xBC\xAF\x27\x1C",     0),
    "GZIP":      (b"\x1F\x8B",               0),
    "ISO":       (b"CD001",                   32769),
}


@dataclass
class Signature:
    offset: int          # byte offset on disk
    sector: int
    sig_type: str        # "filesystem" | "file"
    name: str
    raw_bytes: str       # hex
    context_hex: str     # surrounding 32 bytes


@dataclass
class ScanReport:
    device: str
    device_size: int
    sector_size: int
    signatures: list[Signature] = field(default_factory=list)
    scan_errors: list[dict] = field(default_factory=list)
    sectors_scanned: int = 0

    def to_json(self) -> str:
        d = asdict(self)
        d["signatures"] = [asdict(s) for s in self.signatures]
        return json.dumps(d, indent=2)


def _get_device_size(fd: int, device_path: str = "") -> int:
    import platform
    if platform.system() == "Darwin" and device_path:
        try:
            import subprocess
            out = subprocess.check_output(["diskutil", "info", device_path], text=True)
            for line in out.splitlines():
                if "Disk Size:" in line:
                    parts = line.split("(")
                    if len(parts) > 1:
                        bytes_str = parts[1].split(" Bytes")[0]
                        return int(bytes_str)
        except Exception:
            pass
        
    import fcntl, struct as st
    try:
        buf = fcntl.ioctl(fd, 0x80081272, b" " * 8)
        return st.unpack("Q", buf)[0]
    except OSError:
        return os.lseek(fd, 0, os.SEEK_END)


def _read_sector(fd: int, sector: int, count: int = 1) -> bytes | None:
    try:
        os.lseek(fd, sector * SECTOR_SIZE, os.SEEK_SET)
        return os.read(fd, SECTOR_SIZE * count)
    except OSError:
        return None


def _check_file_sig(data: bytes, name: str, pattern: bytes, rel_offset: int) -> bool:
    if rel_offset + len(pattern) > len(data):
        return False
    return data[rel_offset: rel_offset + len(pattern)] == pattern


def _scan_window(data: bytes, base_offset: int) -> list[tuple[str, str, int]]:
    """Returns list of (sig_type, name, abs_offset)."""
    found = []

    # Filesystem signatures (checked at specific relative positions)
    if len(data) >= 512:
        # MBR boot signature at byte 510
        if data[510:512] == FS_SIGNATURES["MBR"]:
            found.append(("filesystem", "MBR", base_offset + 510))
        # GPT header
        if data[:8] == FS_SIGNATURES["GPT"]:
            found.append(("filesystem", "GPT", base_offset))
        # NTFS
        if data[3:11] == FS_SIGNATURES["NTFS"]:
            found.append(("filesystem", "NTFS", base_offset + 3))
        # FAT32
        if len(data) >= 90 and data[82:90] == FS_SIGNATURES["FAT32"]:
            found.append(("filesystem", "FAT32", base_offset + 82))
        # exFAT
        if len(data) >= 11 and data[3:11] == FS_SIGNATURES["exFAT"]:
            found.append(("filesystem", "exFAT", base_offset + 3))
        # XFS
        if data[:4] == FS_SIGNATURES["XFS"]:
            found.append(("filesystem", "XFS", base_offset))

    # EXT2/3/4 superblock — we'd need to be at offset 1024 within the partition
    if len(data) >= 1082:
        if data[1080:1082] == FS_SIGNATURES["EXT2/3/4"]:
            found.append(("filesystem", "EXT2/3/4", base_offset + 1080))

    # APFS: magic bytes sit at byte 32 within each APFS object (after the 32-byte obj header)
    apfs_nx = FS_SIGNATURES["APFS_NX"]
    apfs_vol = FS_SIGNATURES["APFS_VOL"]
    search_pos = 0
    while search_pos + 36 <= len(data):
        idx = data.find(apfs_nx, search_pos)
        if idx == -1:
            break
        if idx >= 32:
            found.append(("filesystem", "APFS_NX", base_offset + idx - 32))
        search_pos = idx + 4
    search_pos = 0
    while search_pos + 36 <= len(data):
        idx = data.find(apfs_vol, search_pos)
        if idx == -1:
            break
        if idx >= 32:
            found.append(("filesystem", "APFS_VOL", base_offset + idx - 32))
        search_pos = idx + 4

    # File type signatures
    for name, (pattern, rel_off) in FILE_SIGNATURES.items():
        if _check_file_sig(data, name, pattern, rel_off):
            found.append(("file", name, base_offset + rel_off))

    return found


def scan_device(
    device_path: str,
    block_size: int = 512 * 64,   # 32 KB read blocks
    max_bytes: int | None = None,
    progress_cb=None,
) -> ScanReport:
    """
    Skenuje zariadenie alebo disk image a vracia ScanReport.
    """
    fd = os.open(device_path, os.O_RDONLY | os.O_NONBLOCK)
    dev_size = _get_device_size(fd, device_path)

    report = ScanReport(
        device=device_path,
        device_size=dev_size,
        sector_size=SECTOR_SIZE,
    )

    scan_limit = min(dev_size, max_bytes) if max_bytes else dev_size
    offset = 0

    try:
        while offset < scan_limit:
            read_len = min(block_size, scan_limit - offset)
            try:
                os.lseek(fd, offset, os.SEEK_SET)
                data = os.read(fd, read_len)
            except OSError as e:
                report.scan_errors.append({"offset": offset, "error": str(e)})
                offset += block_size
                continue

            if not data:
                break

            hits = _scan_window(data, offset)
            for sig_type, name, abs_offset in hits:
                ctx_start = max(0, abs_offset - 16)
                ctx_len = 32
                os.lseek(fd, ctx_start, os.SEEK_SET)
                ctx_data = os.read(fd, ctx_len)
                sig = Signature(
                    offset=abs_offset,
                    sector=abs_offset // SECTOR_SIZE,
                    sig_type=sig_type,
                    name=name,
                    raw_bytes=data[abs_offset - offset: abs_offset - offset + 8].hex(),
                    context_hex=ctx_data.hex(),
                )
                report.signatures.append(sig)

            report.sectors_scanned += len(data) // SECTOR_SIZE
            offset += len(data)

            if progress_cb:
                progress_cb(offset, scan_limit)
    finally:
        os.close(fd)

    return report
