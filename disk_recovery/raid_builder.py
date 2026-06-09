"""
raid_builder.py — Modul pre softvérovú rekonštrukciu JBOD a RAID 0 do jedného .img súboru.
"""

import os
import time

def reconstruct_raid(
    device_paths: list[str],
    output_img: str,
    mode: str = "JBOD",
    chunk_size: int = 128 * 1024,
    progress_cb=None
):
    """
    Spojí fyzické disky (device_paths) do jedného výstupného súboru (output_img).
    mode: 'JBOD' (jeden za druhým) alebo 'RAID0' (striedanie blokov veľkosti chunk_size).
    """
    fds = []
    sizes = []
    
    # Otvorenie zariadení a zistenie ich veľkostí
    for path in device_paths:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        fds.append(fd)
        
        # Zistíme veľkosť disku robustne pre macOS
        size = 0
        try:
            import subprocess
            out = subprocess.check_output(["diskutil", "info", path], text=True)
            for line in out.splitlines():
                if "Disk Size:" in line:
                    # Riadok vyzerá takto: Disk Size: 1.0 TB (1000204886016 Bytes) ...
                    parts = line.split("(")
                    if len(parts) > 1:
                        bytes_str = parts[1].split(" Bytes")[0]
                        size = int(bytes_str)
                        break
        except Exception as e:
            print(f"  [WARN] Nepodarilo sa zistiť veľkosť {path} cez diskutil: {e}")
            size = os.lseek(fd, 0, os.SEEK_END)
        
        sizes.append(size)
    
    total_size = sum(sizes)
    print(f"  Spájam {len(device_paths)} diskov, mód: {mode}, celková veľkosť: {total_size / 1024**3:.2f} GB")
    
    out_fd = os.open(output_img, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    
    try:
        if mode == "JBOD":
            bytes_written = 0
            for i, fd in enumerate(fds):
                os.lseek(fd, 0, os.SEEK_SET)
                pos = 0
                dev_size = sizes[i]
                while pos < dev_size:
                    read_len = min(1024 * 1024 * 16, dev_size - pos) # 16 MB bloky
                    data = os.read(fd, read_len)
                    if not data:
                        break
                    os.write(out_fd, data)
                    pos += len(data)
                    bytes_written += len(data)
                    
                    if progress_cb and bytes_written % (1024*1024*256) == 0:
                        progress_cb(bytes_written, total_size)
                        
        elif mode == "RAID0":
            bytes_written = 0
            # Pre RAID 0 predpokladáme rovnako veľké disky
            min_size = min(sizes)
            chunks_per_disk = min_size // chunk_size
            
            for chunk_idx in range(chunks_per_disk):
                for fd in fds:
                    os.lseek(fd, chunk_idx * chunk_size, os.SEEK_SET)
                    data = os.read(fd, chunk_size)
                    os.write(out_fd, data)
                    bytes_written += len(data)
                
                if progress_cb and bytes_written % (1024*1024*256) == 0:
                    progress_cb(bytes_written, total_size)
                    
    finally:
        for fd in fds:
            os.close(fd)
        os.close(out_fd)
        
    print(f"  Rekonštrukcia dokončená. Uložené do: {output_img}")
    return output_img
