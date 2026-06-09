"""
gpt_repair.py — Generovanie a oprava GPT (GUID Partition Table)
"""

import os
import struct
import zlib
import uuid

SECTOR_SIZE = 512

def _crc32(data: bytes) -> int:
    return zlib.crc32(data) & 0xFFFFFFFF

def repair_apfs_gpt(image_path: str, apfs_start_sector: int, apfs_sector_count: int):
    """
    Zapíše novú ochrannú MBR a GPT na začiatok a koniec obrazu.
    Predpokladá sa, že disk obsahuje jednu hlavnú APFS partíciu.
    """
    fd = os.open(image_path, os.O_RDWR)
    try:
        total_size = os.lseek(fd, 0, os.SEEK_END)
        total_sectors = total_size // SECTOR_SIZE
        
        last_lba = total_sectors - 1
        
        # 1. Protective MBR (LBA 0)
        mbr = bytearray(512)
        mbr_size = min(total_sectors - 1, 0xFFFFFFFF)
        mbr[446:462] = struct.pack("<B 3B B 3B I I",
            0x00, 0xFF, 0xFF, 0xFF, 0xEE, 0xFF, 0xFF, 0xFF, 1, mbr_size)
        mbr[510:512] = b"\x55\xAA"
        
        os.lseek(fd, 0, os.SEEK_SET)
        os.write(fd, mbr)
        
        # 2. GPT Partition Entries (LBA 2)
        # APFS GUID: 7C3457EF-0000-11AA-AA11-00306543ECAC
        apfs_type_guid = bytes.fromhex("7C3457EF0000AA11AA1100306543ECAC")
        part_uuid = uuid.uuid4().bytes_le
        
        entries = bytearray(128 * 128) # 128 entries
        
        # Entry 0: EFI System Partition (optional, ale dobré pridať pre istotu)
        efi_type = bytes.fromhex("28732AC11FF8D211BA4B00A0C93EC93B")
        efi_uuid = uuid.uuid4().bytes_le
        entries[0:128] = struct.pack("<16s 16s Q Q Q 72s",
            efi_type, efi_uuid, 40, 409600, 0, "EFI System Partition".encode("utf-16le").ljust(72, b"\x00")
        )
        
        # Entry 1: APFS
        entries[128:256] = struct.pack("<16s 16s Q Q Q 72s",
            apfs_type_guid, part_uuid, apfs_start_sector, apfs_start_sector + apfs_sector_count - 1,
            0, "Apple_APFS".encode("utf-16le").ljust(72, b"\x00")
        )
        
        entries_crc = _crc32(entries)
        
        # 3. GPT Header (LBA 1)
        header_uuid = uuid.uuid4().bytes_le
        header = bytearray(92)
        
        struct.pack_into("<8s I I I I Q Q Q Q 16s Q I I", header, 0,
            b"EFI PART", 0x00010000, 92, 0, 0, # signature, rev, size, crc (0), reserved
            1, last_lba, 34, last_lba - 34, # current, backup, first usable, last usable
            header_uuid, 2, 128, 128 # guid, entries lba, num entries, entry size
        )
        
        struct.pack_into("<I", header, 88, entries_crc)
        
        header_crc = _crc32(header)
        struct.pack_into("<I", header, 16, header_crc)
        
        # Zapíš Header a Entries
        os.lseek(fd, SECTOR_SIZE, os.SEEK_SET)
        os.write(fd, header.ljust(512, b"\x00"))
        os.write(fd, entries)
        
        print("  GPT partičná mapa bola úspešne zapísaná.")
        
    finally:
        os.close(fd)
