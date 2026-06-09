#!/usr/bin/env python3
"""
disk_clone.py — Raw disk cloning tool

Číta dáta priamo z blokového zariadenia (bez súborového systému)
a kopíruje ich na iný disk alebo do súboru.

Použitie:
    sudo python3 disk_clone.py --src /dev/sda --dst /dev/sdb
    sudo python3 disk_clone.py --src /dev/sda --dst /backup/disk.img
    sudo python3 disk_clone.py --src /dev/sda --dst /dev/sdb --block-size 4M --skip-errors
"""

import argparse
import os
import sys
import time
import signal
from pathlib import Path


BLOCK_SIZES = {
    "512": 512,
    "4K": 4096,
    "64K": 65536,
    "1M": 1024 * 1024,
    "4M": 4 * 1024 * 1024,
    "8M": 8 * 1024 * 1024,
}

_interrupted = False


def handle_sigint(sig, frame):
    global _interrupted
    _interrupted = True
    print("\n[!] Prerušenie požadované, zastavujem po aktuálnom bloku...")


def parse_block_size(value: str) -> int:
    upper = value.upper().replace("B", "")
    if upper in BLOCK_SIZES:
        return BLOCK_SIZES[upper]
    try:
        return int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"Neplatná veľkosť bloku: {value}")


def get_device_size(fd) -> int:
    import fcntl, struct
    BLKGETSIZE64 = 0x80081272
    buf = b" " * 8
    try:
        buf = fcntl.ioctl(fd, BLKGETSIZE64, buf)
        return struct.unpack("Q", buf)[0]
    except OSError:
        return os.lseek(fd, 0, os.SEEK_END)


def human_readable(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.2f} {unit}"
        n /= 1024
    return f"{n:.2f} PB"


def clone(src_path: str, dst_path: str, block_size: int, skip_errors: bool,
          start_offset: int, count: int | None, dry_run: bool):

    signal.signal(signal.SIGINT, handle_sigint)

    src_fd = os.open(src_path, os.O_RDONLY | os.O_NONBLOCK)
    src_size = get_device_size(src_fd)

    if dry_run:
        print(f"[DRY RUN] Zdroj:      {src_path}  ({human_readable(src_size)})")
        print(f"[DRY RUN] Cieľ:       {dst_path}")
        print(f"[DRY RUN] Blok:       {human_readable(block_size)}")
        print(f"[DRY RUN] Offset:     {human_readable(start_offset)}")
        os.close(src_fd)
        return

    dst_flags = os.O_WRONLY | os.O_CREAT
    if not dst_path.startswith("/dev/"):
        dst_flags |= os.O_TRUNC
    dst_fd = os.open(dst_path, dst_flags, 0o644)

    try:
        src_size_from_offset = src_size - start_offset
        total_bytes = min(src_size_from_offset, count * block_size) if count else src_size_from_offset

        if start_offset:
            os.lseek(src_fd, start_offset, os.SEEK_SET)
            os.lseek(dst_fd, start_offset, os.SEEK_SET)

        copied = 0
        errors = 0
        start_time = time.monotonic()
        last_report = start_time

        print(f"Klonujem: {src_path} → {dst_path}")
        print(f"Veľkosť zdroja: {human_readable(src_size)}  |  Blok: {human_readable(block_size)}")
        print("-" * 60)

        blocks_done = 0
        while not _interrupted:
            if count is not None and blocks_done >= count:
                break

            remaining = total_bytes - copied
            if remaining <= 0:
                break
            read_size = min(block_size, remaining)

            try:
                data = os.read(src_fd, read_size)
            except OSError as e:
                errors += 1
                if skip_errors:
                    print(f"\n[CHYBA] offset={human_readable(start_offset + copied)}: {e} — preskakujem")
                    # posunieme sa o jeden blok ďalej
                    os.lseek(src_fd, block_size, os.SEEK_CUR)
                    os.lseek(dst_fd, block_size, os.SEEK_CUR)
                    copied += block_size
                    blocks_done += 1
                    continue
                else:
                    raise

            if not data:
                break

            os.write(dst_fd, data)
            copied += len(data)
            blocks_done += 1

            now = time.monotonic()
            if now - last_report >= 1.0:
                elapsed = now - start_time
                speed = copied / elapsed if elapsed > 0 else 0
                pct = copied / total_bytes * 100 if total_bytes > 0 else 0
                eta = (total_bytes - copied) / speed if speed > 0 else 0
                bar_filled = int(pct / 2)
                bar = "#" * bar_filled + "-" * (50 - bar_filled)
                print(
                    f"\r[{bar}] {pct:5.1f}%  "
                    f"{human_readable(copied)}/{human_readable(total_bytes)}  "
                    f"{human_readable(speed)}/s  ETA {int(eta)}s  Chyby:{errors}",
                    end="", flush=True
                )
                last_report = now

        elapsed = time.monotonic() - start_time
        speed = copied / elapsed if elapsed > 0 else 0
        print(f"\n{'=' * 60}")
        if _interrupted:
            print(f"[!] Prerušené po {human_readable(copied)}")
        else:
            print(f"[OK] Dokončené: {human_readable(copied)} za {elapsed:.1f}s  ({human_readable(speed)}/s)")
        if errors:
            print(f"[!] Celkový počet chýb čítania: {errors}")

    finally:
        os.close(src_fd)
        os.close(dst_fd)


def main():
    parser = argparse.ArgumentParser(
        description="Raw disk klonovací nástroj — číta dáta bez súborového systému",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--src", required=True,
                        help="Zdrojové zariadenie alebo súbor (napr. /dev/sda)")
    parser.add_argument("--dst", required=True,
                        help="Cieľové zariadenie alebo súbor (napr. /dev/sdb alebo /backup/disk.img)")
    parser.add_argument("--block-size", default="1M", type=parse_block_size,
                        metavar="SIZE",
                        help="Veľkosť bloku: 512, 4K, 64K, 1M, 4M, 8M alebo číslo v bajtoch (default: 1M)")
    parser.add_argument("--skip-errors", action="store_true",
                        help="Pri chybe čítania blok preskočiť (vhodné pre poškodené disky)")
    parser.add_argument("--offset", default=0, type=lambda x: int(x, 0),
                        metavar="BYTES",
                        help="Začiatočný offset v bajtoch (default: 0)")
    parser.add_argument("--count", default=None, type=int,
                        metavar="N",
                        help="Počet blokov na skopírovanie (default: celý disk)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Len zobraziť informácie, nič nekopírovať")

    args = parser.parse_args()

    if os.geteuid() != 0 and (args.src.startswith("/dev/") or args.dst.startswith("/dev/")):
        print("[!] Upozornenie: prístup k /dev/ zariadeniam zvyčajne vyžaduje root (sudo).")

    if not os.path.exists(args.src):
        print(f"[CHYBA] Zdroj neexistuje: {args.src}", file=sys.stderr)
        sys.exit(1)

    if not args.dry_run and args.dst.startswith("/dev/") and os.path.exists(args.dst):
        print(f"[!] POZOR: Prepíšete celý disk {args.dst}!")
        confirm = input("Naozaj chcete pokračovať? Zadajte 'ano': ")
        if confirm.strip().lower() != "ano":
            print("Zrušené.")
            sys.exit(0)

    try:
        clone(
            src_path=args.src,
            dst_path=args.dst,
            block_size=args.block_size,
            skip_errors=args.skip_errors,
            start_offset=args.offset,
            count=args.count,
            dry_run=args.dry_run,
        )
    except PermissionError:
        print("\n[CHYBA] Nemáte oprávnenie. Skúste spustiť so sudo.", file=sys.stderr)
        sys.exit(1)
    except OSError as e:
        print(f"\n[CHYBA] {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
