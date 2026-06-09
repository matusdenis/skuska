"""
make_test_image.py — Vytvorí testovací disk image so známymi signátúrami

Generuje 10 MB image s:
  - MBR boot signatúrou
  - FAT32 signatúrou
  - Niekoľkými JPEG, PDF, ZIP "súbormi" (len magic bytes + dummy data)
  - EXT4 superblock signatúrou
"""

import struct
import os

OUT = "test_disk.img"
SIZE = 10 * 1024 * 1024   # 10 MB

img = bytearray(SIZE)


def put(offset: int, data: bytes):
    img[offset: offset + len(data)] = data


# MBR boot signature at 510-511
put(510, b"\x55\xAA")

# FAT32 signature at sector 2048 (1 MB) + offset 82
fat32_start = 2048 * 512
put(fat32_start + 3, b"FAT32   ")
put(fat32_start + 82, b"FAT32   ")
put(fat32_start + 510, b"\x55\xAA")

# NTFS at sector 4096 (2 MB)
ntfs_start = 4096 * 512
put(ntfs_start + 3, b"NTFS    ")
put(ntfs_start + 510, b"\x55\xAA")

# EXT4 superblock at 3 MB + 1024 (superblock offset)
ext4_start = 3 * 1024 * 1024 + 1024
put(ext4_start + 56, b"\x53\xEF")   # magic at offset 56 inside superblock

# JPEG at 4 MB
jpeg_off = 4 * 1024 * 1024
put(jpeg_off, b"\xFF\xD8\xFF\xE0\x00\x10JFIF\x00")
put(jpeg_off + 100, b"some image data...")
put(jpeg_off + 10000, b"\xFF\xD9")  # JPEG end marker

# PDF at 5 MB
pdf_off = 5 * 1024 * 1024
put(pdf_off, b"%PDF-1.7\n")
put(pdf_off + 8, b"1 0 obj\n<< /Type /Catalog >>\nendobj\n")
put(pdf_off + 200, b"%%EOF")

# ZIP at 6 MB
zip_off = 6 * 1024 * 1024
put(zip_off, b"PK\x03\x04")
put(zip_off + 4, b"\x14\x00\x00\x00\x00\x00")

# PNG at 7 MB
png_off = 7 * 1024 * 1024
put(png_off, b"\x89PNG\r\n\x1a\n")
put(png_off + 8, struct.pack(">I", 13) + b"IHDR")

# SQLite at 8 MB
sqlite_off = 8 * 1024 * 1024
put(sqlite_off, b"SQLite format 3\x00")

# APFS NX Container Superblock at 9 MB (magic at obj_start+32)
apfs_nx_off = 9 * 1024 * 1024
# 32-byte object header (checksum=0, oid, xid, obj_type, obj_subtype)
put(apfs_nx_off, b"\x00" * 8)                          # checksum
put(apfs_nx_off + 8, b"\x01\x00\x00\x00\x00\x00\x00\x00")  # oid
put(apfs_nx_off + 16, b"\x01\x00\x00\x00\x00\x00\x00\x00") # xid
put(apfs_nx_off + 24, b"\x01\x00\x00\x00")                  # obj_type (NX_SUPERBLOCK)
put(apfs_nx_off + 28, b"\x00\x00\x00\x00")                  # obj_subtype
put(apfs_nx_off + 32, b"BSXN")                              # APFS_NX_MAGIC (NXSB little-endian)
put(apfs_nx_off + 36, struct.pack("<I", 4096))              # block_size = 4096

# GPT header at second sector
put(512, b"EFI PART")

with open(OUT, "wb") as f:
    f.write(img)

print(f"Testovací image vytvorený: {OUT} ({len(img)} bajtov)")
