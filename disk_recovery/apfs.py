"""
apfs.py — APFS (Apple File System) podpora

Parsuje APFS štruktúry priamo z raw disk/image:
  - Container Superblock (NX_Superblock)
  - Volume Superblock (APFS_Superblock)
  - Checkpoint descriptor area
  - GPT partition entries (Apple_APFS type)
  - Object map záznamy

Referencia: Apple File System Reference (2023)
  https://developer.apple.com/support/downloads/Apple-File-System-Reference.pdf

APFS magic values:
  Container: 0x4253584E  "NXSB"  (little-endian)
  Volume:    0x42535041  "APSB"  (little-endian)
  Object map:0x4250414D  "MAPB"  (little-endian — OMAP)
  B-tree:    0x42545245  "ERTB"  (little-endian — BTNR root)
  SpaceMan:  0x4D415053  "SPAM"  (little-endian)
"""

import struct
import os
import json
from dataclasses import dataclass, field, asdict
from typing import Iterator


# ─── Magic constants ────────────────────────────────────────
APFS_NX_MAGIC   = 0x4253584E   # "NXSB" — Container Superblock
APFS_VOL_MAGIC  = 0x42535041   # "APSB" — Volume Superblock
APFS_OMAP_MAGIC = 0x4250414D   # "MAPB" — Object Map
APFS_BTREE_MAGIC= 0x42545245   # "ERTB" — B-Tree Root Node

# GPT partition type GUID for Apple APFS (little-endian bytes)
APFS_GPT_TYPE_GUID = bytes.fromhex("7C3457EF0000AA11AA1100306543ECAC")

# NX object type constants
OBJECT_TYPE_NX_SUPERBLOCK   = 0x00000001
OBJECT_TYPE_BTREE           = 0x00000002
OBJECT_TYPE_BTREE_NODE      = 0x00000003
OBJECT_TYPE_SPACEMAN        = 0x00000005
OBJECT_TYPE_OMAP            = 0x0000000B
OBJECT_TYPE_FS              = 0x0000000D   # APFS volume

# Volume roles
APFS_VOL_ROLE_NONE     = 0x0000
APFS_VOL_ROLE_SYSTEM   = 0x0001
APFS_VOL_ROLE_USER     = 0x0002
APFS_VOL_ROLE_RECOVERY = 0x0004
APFS_VOL_ROLE_VM       = 0x0008
APFS_VOL_ROLE_PREBOOT  = 0x0010
APFS_VOL_ROLE_DATA     = 0x0800

VOL_ROLE_NAMES = {
    APFS_VOL_ROLE_NONE:     "none",
    APFS_VOL_ROLE_SYSTEM:   "system",
    APFS_VOL_ROLE_USER:     "user",
    APFS_VOL_ROLE_RECOVERY: "recovery",
    APFS_VOL_ROLE_VM:       "vm",
    APFS_VOL_ROLE_PREBOOT:  "preboot",
    APFS_VOL_ROLE_DATA:     "data",
}

# Incompatible feature flags
APFS_INCOMPAT_CASE_INSENSITIVE = 0x00000001
APFS_INCOMPAT_DATALESS_SNAPS   = 0x00000002
APFS_INCOMPAT_ENC_ROLLED       = 0x00000004
APFS_INCOMPAT_NORMALIZATION_INSENSITIVE = 0x00000008


# ─── Data structures ────────────────────────────────────────

@dataclass
class ApfsObjectHeader:
    """obj_phys_t — common 32-byte header for all APFS objects."""
    checksum: int       # Fletcher-64
    oid: int            # object identifier
    xid: int            # transaction identifier
    obj_type: int       # type + flags
    obj_subtype: int
    # derived
    type_low: int       # obj_type & 0x0000FFFF
    flags: int          # obj_type >> 16

    @classmethod
    def from_bytes(cls, data: bytes) -> "ApfsObjectHeader":
        if len(data) < 32:
            raise ValueError("Need at least 32 bytes for object header")
        checksum, oid, xid, obj_type, obj_subtype = struct.unpack_from("<QQQQQ", data, 0)
        # obj_type and obj_subtype are actually uint32 at offset 24 and 28
        checksum, oid, xid = struct.unpack_from("<QQQ", data, 0)
        obj_type, obj_subtype = struct.unpack_from("<II", data, 24)
        return cls(
            checksum=checksum,
            oid=oid,
            xid=xid,
            obj_type=obj_type,
            obj_subtype=obj_subtype,
            type_low=obj_type & 0x0000FFFF,
            flags=(obj_type >> 16) & 0xFFFF,
        )


@dataclass
class ApfsContainerSuperblock:
    """nx_superblock_t — APFS Container Superblock (NXSB)."""
    offset: int                 # byte offset on disk
    magic: int                  # must be APFS_NX_MAGIC
    block_size: int             # nx_block_size (typically 4096)
    block_count: int            # nx_block_count
    uuid: bytes                 # 16-byte UUID
    next_oid: int               # nx_next_oid
    next_xid: int               # nx_next_xid (latest transaction)
    xp_desc_blocks: int         # checkpoint descriptor block count
    xp_data_blocks: int         # checkpoint data block count
    xp_desc_base: int           # checkpoint descriptor area base
    xp_data_base: int           # checkpoint data area base
    spaceman_oid: int
    omap_oid: int
    reaper_oid: int
    max_file_systems: int
    fs_oid: list[int]           # volume OIDs (up to max_file_systems)
    # derived
    uuid_str: str
    total_bytes: int

    @classmethod
    def from_bytes(cls, data: bytes, offset: int) -> "ApfsContainerSuperblock":
        if len(data) < 1384:
            raise ValueError(f"Need ≥1384 bytes for NX superblock, got {len(data)}")

        hdr = ApfsObjectHeader.from_bytes(data)
        magic = struct.unpack_from("<I", data, 32)[0]
        if magic != APFS_NX_MAGIC:
            raise ValueError(f"Bad NX magic: 0x{magic:08X}")

        (block_size, block_count) = struct.unpack_from("<IQ", data, 36)
        # features at offset 44 (3 × uint64) — skip
        # incompatible_features at 52
        uuid = data[80:96]
        (next_oid, next_xid) = struct.unpack_from("<QQ", data, 96)
        (xp_desc_blocks, xp_data_blocks) = struct.unpack_from("<II", data, 112)
        xp_desc_base = struct.unpack_from("<q", data, 120)[0]
        xp_data_base = struct.unpack_from("<q", data, 128)[0]
        (spaceman_oid, omap_oid, reaper_oid) = struct.unpack_from("<QQQ", data, 152)
        max_file_systems = struct.unpack_from("<I", data, 176)[0]
        # Volume OIDs start at offset 184
        max_fs = min(max_file_systems, 100)
        fs_oid = list(struct.unpack_from(f"<{max_fs}Q", data, 184)[:max_fs])
        fs_oid = [x for x in fs_oid if x != 0]

        uuid_str = "-".join([
            uuid[:4].hex(), uuid[4:6].hex(), uuid[6:8].hex(),
            uuid[8:10].hex(), uuid[10:].hex()
        ]).upper()

        return cls(
            offset=offset,
            magic=magic,
            block_size=block_size,
            block_count=block_count,
            uuid=uuid,
            uuid_str=uuid_str,
            next_oid=next_oid,
            next_xid=next_xid,
            xp_desc_blocks=xp_desc_blocks,
            xp_data_blocks=xp_data_blocks,
            xp_desc_base=xp_desc_base,
            xp_data_base=xp_data_base,
            spaceman_oid=spaceman_oid,
            omap_oid=omap_oid,
            reaper_oid=reaper_oid,
            max_file_systems=max_file_systems,
            fs_oid=fs_oid,
            total_bytes=block_size * block_count,
        )

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("uuid", None)
        return d


@dataclass
class ApfsVolumeSuperblock:
    """apfs_superblock_t — APFS Volume Superblock (APSB)."""
    offset: int
    magic: int
    fs_index: int               # index in container's fs_oid[]
    features: int
    incompat_features: int
    uuid: bytes
    uuid_str: str
    last_mod_time: int          # nanoseconds since Unix epoch
    fs_flags: int
    volname: str                # volume name (UTF-8, max 256 bytes)
    next_doc_id: int
    num_files: int
    num_directories: int
    num_symlinks: int
    num_other_fsobjects: int
    num_snapshots: int
    total_blocks_alloced: int
    total_blocks_freed: int
    vol_role: int
    vol_role_name: str
    case_insensitive: bool
    encrypted: bool

    @classmethod
    def from_bytes(cls, data: bytes, offset: int) -> "ApfsVolumeSuperblock":
        if len(data) < 900:
            raise ValueError(f"Need ≥900 bytes for APSB, got {len(data)}")

        hdr = ApfsObjectHeader.from_bytes(data)
        magic = struct.unpack_from("<I", data, 32)[0]
        if magic != APFS_VOL_MAGIC:
            raise ValueError(f"Bad APSB magic: 0x{magic:08X}")

        fs_index = struct.unpack_from("<I", data, 36)[0]
        features = struct.unpack_from("<Q", data, 40)[0]
        incompat_features = struct.unpack_from("<Q", data, 56)[0]

        uuid = data[80:96]
        last_mod_time = struct.unpack_from("<Q", data, 96)[0]
        fs_flags = struct.unpack_from("<Q", data, 104)[0]

        # volume name at offset 512 (max 256 bytes, null-terminated)
        name_raw = data[512:768]
        volname = name_raw.split(b"\x00")[0].decode("utf-8", errors="replace")

        next_doc_id = struct.unpack_from("<I", data, 784)[0]
        (num_files, num_dirs, num_symlinks, num_other, num_snaps) = struct.unpack_from(
            "<QQQQQ", data, 792
        )
        (total_alloced, total_freed) = struct.unpack_from("<QQ", data, 832)

        vol_role = struct.unpack_from("<H", data, 160)[0] if len(data) > 162 else 0
        vol_role_name = VOL_ROLE_NAMES.get(vol_role, f"0x{vol_role:04x}")

        uuid_str = "-".join([
            uuid[:4].hex(), uuid[4:6].hex(), uuid[6:8].hex(),
            uuid[8:10].hex(), uuid[10:].hex()
        ]).upper()

        return cls(
            offset=offset,
            magic=magic,
            fs_index=fs_index,
            features=features,
            incompat_features=incompat_features,
            uuid=uuid,
            uuid_str=uuid_str,
            last_mod_time=last_mod_time,
            fs_flags=fs_flags,
            volname=volname,
            next_doc_id=next_doc_id,
            num_files=num_files,
            num_directories=num_dirs,
            num_symlinks=num_symlinks,
            num_other_fsobjects=num_other,
            num_snapshots=num_snaps,
            total_blocks_alloced=total_alloced,
            total_blocks_freed=total_freed,
            vol_role=vol_role,
            vol_role_name=vol_role_name,
            case_insensitive=bool(incompat_features & APFS_INCOMPAT_CASE_INSENSITIVE),
            encrypted=bool(fs_flags & 0x1),
        )

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("uuid", None)
        return d


@dataclass
class ApfsGptPartition:
    """GPT partition entry s Apple_APFS type."""
    index: int
    type_guid: str
    part_guid: str
    start_lba: int
    end_lba: int
    attributes: int
    name: str
    start_byte: int
    size_bytes: int


@dataclass
class ApfsScanResult:
    """Výsledok APFS-špecifického skenu."""
    device: str
    containers: list[ApfsContainerSuperblock] = field(default_factory=list)
    volumes: list[ApfsVolumeSuperblock] = field(default_factory=list)
    gpt_apfs_partitions: list[ApfsGptPartition] = field(default_factory=list)
    raw_nx_offsets: list[int] = field(default_factory=list)
    raw_apsb_offsets: list[int] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            f"APFS scan: {self.device}",
            f"  Containers (NXSB): {len(self.containers)}  (raw hits: {len(self.raw_nx_offsets)})",
            f"  Volumes    (APSB): {len(self.volumes)}  (raw hits: {len(self.raw_apsb_offsets)})",
            f"  GPT APFS parts:    {len(self.gpt_apfs_partitions)}",
        ]
        for c in self.containers:
            lines.append(
                f"    Container @ {c.offset:>12} | block={c.block_size} "
                f"| {c.block_count} blocks ({_human(c.total_bytes)}) "
                f"| UUID={c.uuid_str} | vols={len(c.fs_oid)}"
            )
        for v in self.volumes:
            enc = " [ENC]" if v.encrypted else ""
            ci  = " [CI]"  if v.case_insensitive else ""
            lines.append(
                f"    Volume    @ {v.offset:>12} | '{v.volname}' "
                f"| role={v.vol_role_name} "
                f"| files={v.num_files} dirs={v.num_directories}"
                f"{enc}{ci}"
            )
        for p in self.gpt_apfs_partitions:
            lines.append(
                f"    GPT part  #{p.index:02d}             | '{p.name}' "
                f"| LBA {p.start_lba}–{p.end_lba} ({_human(p.size_bytes)})"
            )
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "device": self.device,
            "containers": [c.to_dict() for c in self.containers],
            "volumes": [v.to_dict() for v in self.volumes],
            "gpt_apfs_partitions": [asdict(p) for p in self.gpt_apfs_partitions],
            "raw_nx_offsets": self.raw_nx_offsets,
            "raw_apsb_offsets": self.raw_apsb_offsets,
            "errors": self.errors,
        }


# ─── GPT scanner ────────────────────────────────────────────

def _parse_gpt_apfs_partitions(fd: int, block_size: int = 512) -> list[ApfsGptPartition]:
    """
    Číta GPT partition table a vracia iba Apple_APFS záznamy.
    GPT header je na LBA 1, partition array na LBA 2.
    """
    results = []

    # Read GPT header at LBA 1
    try:
        os.lseek(fd, block_size, os.SEEK_SET)
        hdr = os.read(fd, 512)
    except OSError:
        return results

    if hdr[:8] != b"EFI PART":
        return results

    (_, _, _, _, _, _, first_usable, last_usable,
     disk_guid, part_entry_lba, num_parts, part_entry_size,
     _crc) = struct.unpack_from("<4sIIIIIQQ16sQII4s", hdr, 0)

    if part_entry_size < 128:
        return results

    # Read partition array
    try:
        os.lseek(fd, part_entry_lba * block_size, os.SEEK_SET)
        raw = os.read(fd, num_parts * part_entry_size)
    except OSError:
        return results

    for i in range(num_parts):
        entry = raw[i * part_entry_size: (i + 1) * part_entry_size]
        if len(entry) < 128:
            break
        type_guid = entry[0:16]
        if type_guid == bytes(16):
            continue   # empty entry

        part_guid = entry[16:32]
        start_lba, end_lba, attrs = struct.unpack_from("<QQQ", entry, 32)
        name_raw = entry[56:128]
        name = name_raw.decode("utf-16-le", errors="replace").rstrip("\x00")

        # Check if this is an Apple_APFS partition
        # type GUID: 7C3457EF-0000-11AA-AA11-00306543ECAC
        type_hex = type_guid[:4][::-1].hex() + "-" + \
                   type_guid[4:6][::-1].hex() + "-" + \
                   type_guid[6:8][::-1].hex() + "-" + \
                   type_guid[8:10].hex() + "-" + \
                   type_guid[10:16].hex()

        is_apfs = type_hex.upper() == "7C3457EF-0000-11AA-AA11-00306543ECAC"
        is_apfs_recovery = type_hex.upper() == "52637664-0000-11AA-AA11-00306543ECAC"

        if is_apfs or is_apfs_recovery:
            results.append(ApfsGptPartition(
                index=i,
                type_guid=type_hex.upper(),
                part_guid=_format_guid(part_guid),
                start_lba=start_lba,
                end_lba=end_lba,
                attributes=attrs,
                name=name,
                start_byte=start_lba * block_size,
                size_bytes=(end_lba - start_lba + 1) * block_size,
            ))

    return results


def _format_guid(b: bytes) -> str:
    return (
        b[:4][::-1].hex() + "-" +
        b[4:6][::-1].hex() + "-" +
        b[6:8][::-1].hex() + "-" +
        b[8:10].hex() + "-" +
        b[10:16].hex()
    ).upper()


# ─── Main APFS scanner ──────────────────────────────────────

# NXSB magic as bytes (little-endian): "NXSB" = 4E 58 42 53
NXSB_MAGIC_BYTES = struct.pack("<I", APFS_NX_MAGIC)  # b'NXSB'
APSB_MAGIC_BYTES = struct.pack("<I", APFS_VOL_MAGIC)  # b'APSB'


def scan_apfs(
    device_path: str,
    block_size: int = 4096,
    max_bytes: int | None = None,
    progress_cb=None,
) -> ApfsScanResult:
    """
    Skenuje zariadenie a vracia všetky APFS štruktúry:
      - NX Container Superblocks (NXSB)
      - Volume Superblocks (APSB)
      - GPT APFS partition entries

    APFS magic bytes sú vždy na začiatku bloku (offset 32 v obj header),
    takže skenujeme po block_size krokoch + sliding window pre fragmentované disky.
    """
    result = ApfsScanResult(device=device_path)

    fd = os.open(device_path, os.O_RDONLY | os.O_NONBLOCK)
    try:
        # Get device size
        import fcntl as _fcntl
        try:
            buf = _fcntl.ioctl(fd, 0x80081272, b" " * 8)
            dev_size = struct.unpack("Q", buf)[0]
        except OSError:
            dev_size = os.lseek(fd, 0, os.SEEK_END)

        scan_limit = min(dev_size, max_bytes) if max_bytes else dev_size

        # First: parse GPT (at fixed location)
        try:
            result.gpt_apfs_partitions = _parse_gpt_apfs_partitions(fd, 512)
        except Exception as e:
            result.errors.append(f"GPT parse error: {e}")

        # Sliding window scan — read 64 KB at a time, check every 4096 boundary
        window = 65536
        overlap = 4096   # ensure we don't miss structs crossing windows
        pos = 0
        seen_nx: set[int] = set()
        seen_apsb: set[int] = set()

        while pos < scan_limit:
            read_len = min(window, scan_limit - pos)
            try:
                os.lseek(fd, pos, os.SEEK_SET)
                data = os.read(fd, read_len)
            except OSError as e:
                result.errors.append(f"Read error @ {pos}: {e}")
                pos += window - overlap
                continue

            if not data:
                break

            # Search for NXSB (magic at byte 32 of a block-aligned address)
            search = data
            local_off = 0
            while True:
                idx = search.find(NXSB_MAGIC_BYTES, local_off)
                if idx == -1:
                    break
                # magic is at offset 32 within the object → object starts at idx-32
                obj_start_local = idx - 32
                obj_start_abs = pos + obj_start_local
                if obj_start_local >= 0 and obj_start_abs not in seen_nx:
                    result.raw_nx_offsets.append(obj_start_abs)
                    seen_nx.add(obj_start_abs)
                    # Try to parse full container superblock
                    try:
                        os.lseek(fd, obj_start_abs, os.SEEK_SET)
                        sb_data = os.read(fd, 1400)
                        csb = ApfsContainerSuperblock.from_bytes(sb_data, obj_start_abs)
                        result.containers.append(csb)
                    except Exception as e:
                        result.errors.append(
                            f"NXSB parse @ {obj_start_abs}: {e}"
                        )
                local_off = idx + 4

            # Search for APSB (Volume Superblock)
            local_off = 0
            while True:
                idx = search.find(APSB_MAGIC_BYTES, local_off)
                if idx == -1:
                    break
                obj_start_local = idx - 32
                obj_start_abs = pos + obj_start_local
                if obj_start_local >= 0 and obj_start_abs not in seen_apsb:
                    result.raw_apsb_offsets.append(obj_start_abs)
                    seen_apsb.add(obj_start_abs)
                    try:
                        os.lseek(fd, obj_start_abs, os.SEEK_SET)
                        vol_data = os.read(fd, 1024)
                        vsb = ApfsVolumeSuperblock.from_bytes(vol_data, obj_start_abs)
                        result.volumes.append(vsb)
                    except Exception as e:
                        result.errors.append(
                            f"APSB parse @ {obj_start_abs}: {e}"
                        )
                local_off = idx + 4

            pos += len(data) - overlap
            if progress_cb:
                progress_cb(pos, scan_limit)

    finally:
        os.close(fd)

    return result


# ─── Checkpoint area reader ──────────────────────────────────

def read_checkpoint_area(
    device_path: str,
    container: ApfsContainerSuperblock,
) -> list[dict]:
    """
    Číta checkpoint descriptor area kontajnera a vracia
    záznamy o transakciách (xid, typ objektu, blok číslo).
    Toto umožňuje nájsť staršie verzie volume superblocks.
    """
    block_size = container.block_size
    base = container.xp_desc_base * block_size  # abs byte offset
    count = container.xp_desc_blocks
    records = []

    fd = os.open(device_path, os.O_RDONLY | os.O_NONBLOCK)
    try:
        for i in range(count):
            off = base + i * block_size
            try:
                os.lseek(fd, off, os.SEEK_SET)
                data = os.read(fd, block_size)
            except OSError:
                continue
            if len(data) < 32:
                continue
            # Parse object header
            try:
                hdr = ApfsObjectHeader.from_bytes(data)
                records.append({
                    "block_index": i,
                    "offset": off,
                    "oid": hdr.oid,
                    "xid": hdr.xid,
                    "type_low": hdr.type_low,
                    "flags": hdr.flags,
                })
            except Exception:
                pass
    finally:
        os.close(fd)

    return records


# ─── Recovery helpers ────────────────────────────────────────

def extract_apfs_container(
    device_path: str,
    container: ApfsContainerSuperblock,
    output_path: str,
    progress_cb=None,
) -> dict:
    """
    Extrahuje celý APFS kontajner (všetky bloky) do image súboru.
    """
    start = container.offset
    # Container offset je offset NX superblock — nie nevyhnutne začiatok partície.
    # Ak je container na 0, kopírujeme od 0; inak berieme celú veľkosť.
    length = container.total_bytes if container.total_bytes > 0 else None
    block_size = container.block_size

    fd_in = os.open(device_path, os.O_RDONLY | os.O_NONBLOCK)
    total = length or (os.lseek(fd_in, 0, os.SEEK_END) - start)
    copied = 0
    errors = 0

    with open(output_path, "wb") as f_out:
        while copied < total:
            chunk = min(block_size * 256, total - copied)
            try:
                os.lseek(fd_in, start + copied, os.SEEK_SET)
                data = os.read(fd_in, chunk)
                if not data:
                    break
                f_out.write(data)
                copied += len(data)
            except OSError:
                f_out.write(b"\x00" * chunk)
                copied += chunk
                errors += 1
            if progress_cb:
                progress_cb(copied, total)

    os.close(fd_in)
    return {
        "output": output_path,
        "bytes_copied": copied,
        "read_errors": errors,
        "container_uuid": container.uuid_str,
        "volumes": len(container.fs_oid),
    }


def generate_apfs_recovery_hints(result: ApfsScanResult) -> list[dict]:
    """
    Na základe APFS skenu generuje konkrétne recovery hints
    pre RecoveryPlannerAgent — zoznam oblastí a odporúčaných akcií.
    """
    hints = []

    for c in result.containers:
        hints.append({
            "type": "apfs_container",
            "offset": c.offset,
            "length": c.total_bytes,
            "block_size": c.block_size,
            "uuid": c.uuid_str,
            "num_volumes": len(c.fs_oid),
            "latest_xid": c.next_xid,
            "action": "extract_apfs_container",
            "priority": 1,
            "note": (
                f"APFS Container s {len(c.fs_oid)} volume(s). "
                f"Block size {c.block_size}. "
                f"Posledná transakcia xid={c.next_xid}. "
                "Odporúča sa extrahovať celý kontajner a použiť apfs-fuse alebo macOS."
            ),
        })

    for v in result.volumes:
        hints.append({
            "type": "apfs_volume",
            "offset": v.offset,
            "length": None,
            "uuid": v.uuid_str,
            "name": v.volname,
            "role": v.vol_role_name,
            "files": v.num_files,
            "dirs": v.num_directories,
            "snapshots": v.num_snapshots,
            "encrypted": v.encrypted,
            "action": "apfs_volume_scan",
            "priority": 2,
            "note": (
                f"APFS Volume '{v.volname}' ({v.vol_role_name}). "
                f"{v.num_files} súborov, {v.num_directories} adresárov. "
                + (" [ŠIFROVANÉ — potrebný FileVault kľúč]" if v.encrypted else "")
                + (f" [{v.num_snapshots} snímok — možné obnovenie zo snapshotu]"
                   if v.num_snapshots > 0 else "")
            ),
        })

    for p in result.gpt_apfs_partitions:
        hints.append({
            "type": "apfs_gpt_partition",
            "offset": p.start_byte,
            "length": p.size_bytes,
            "name": p.name,
            "action": "extract_apfs_container",
            "priority": 1,
            "note": (
                f"GPT partícia '{p.name}' s APFS typom. "
                f"LBA {p.start_lba}–{p.end_lba} ({_human(p.size_bytes)}). "
                "Obsahuje APFS kontajner — extrahovať ako celok."
            ),
        })

    return hints


# ─── Helpers ────────────────────────────────────────────────

def _human(n: int) -> str:
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {u}"
        n //= 1024
    return f"{n:.1f} PB"
