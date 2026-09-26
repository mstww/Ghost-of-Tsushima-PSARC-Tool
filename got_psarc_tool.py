#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Ghost of Tsushima DIRECTOR'S CUT - PSARC / DSAR Tool
Specialized extraction and repacking utility for Sony PSAR and PC DirectStorage DSAR archives.
Developed for Ghost of Tsushima PC.
"""

import sys
import os
import io
import struct
import hashlib
import zlib
import bisect
import argparse
import time

try:
    import lz4.block
except ImportError:
    print("Error: 'lz4' library is required. Install it using: pip install lz4", file=sys.stderr)
    sys.exit(1)


class DSARStream(io.RawIOBase):
    """
    Virtual seekable read stream for DirectStorage Archives (DSAR).
    Decompresses 256KB LZ4 chunks on-the-fly with an in-memory cache,
    allowing instant random access and low memory usage ( < 10 MB RAM )
    even on 10+ GB archives.
    """
    def __init__(self, f):
        self.f = f
        self.f.seek(0)
        hdr = self.f.read(32)
        if len(hdr) < 32:
            raise ValueError("File is too small to be a valid DSAR archive.")
        magic, maj, min_v, chunk_cnt, first_off = struct.unpack('<4sHHII', hdr[:16])
        if magic != b'DSAR':
            raise ValueError(f"Invalid DSAR magic: {magic}")
        self.total_uncomp = struct.unpack('<Q', hdr[16:24])[0]
        self.chunk_cnt = chunk_cnt
        self.first_chunk_offset = first_off

        self.chunks = []
        self.uoffsets = []
        for _ in range(chunk_cnt):
            entry = self.f.read(32)
            if len(entry) < 32:
                raise ValueError("Corrupted DSAR chunk table.")
            uoff, coff, usz, csz, cflag = struct.unpack('<QQIIB', entry[:25])
            self.chunks.append((uoff, coff, usz, csz, cflag))
            self.uoffsets.append(uoff)

        self.pos = 0
        self._cache = {}  # idx -> decompressed bytes
        self._cache_keys = []
        self._max_cache = 8  # 8 chunks x 256KB = 2MB buffer

    def seekable(self):
        return True

    def readable(self):
        return True

    def seek(self, offset, whence=io.SEEK_SET):
        if whence == io.SEEK_SET:
            self.pos = offset
        elif whence == io.SEEK_CUR:
            self.pos += offset
        elif whence == io.SEEK_END:
            self.pos = self.total_uncomp + offset
        else:
            raise ValueError(f"Invalid whence: {whence}")
        return self.pos

    def tell(self):
        return self.pos

    def _get_chunk_data(self, idx):
        if idx in self._cache:
            return self._cache[idx]

        uoff, coff, usz, csz, cflag = self.chunks[idx]
        if csz == 0 or cflag == 254:
            data = b'\x00' * usz
        else:
            self.f.seek(coff)
            raw = self.f.read(csz)
            if cflag == 3:  # LZ4 block compressed
                data = lz4.block.decompress(raw, uncompressed_size=usz)
            elif cflag == 0:  # Uncompressed
                data = raw
            else:
                data = raw

        if len(self._cache_keys) >= self._max_cache:
            oldest = self._cache_keys.pop(0)
            self._cache.pop(oldest, None)

        self._cache[idx] = data
        self._cache_keys.append(idx)
        return data

    def readinto(self, b):
        if self.pos >= self.total_uncomp:
            return 0
        to_read = min(len(b), self.total_uncomp - self.pos)
        bytes_read = 0

        while bytes_read < to_read:
            cur_pos = self.pos
            idx = bisect.bisect_right(self.uoffsets, cur_pos) - 1
            if idx < 0 or idx >= len(self.chunks):
                break

            chunk_uoff, _, chunk_usz, _, _ = self.chunks[idx]
            offset_in_chunk = cur_pos - chunk_uoff
            chunk_data = self._get_chunk_data(idx)

            avail = len(chunk_data) - offset_in_chunk
            if avail <= 0:
                break

            take = min(avail, to_read - bytes_read)
            b[bytes_read : bytes_read + take] = chunk_data[offset_in_chunk : offset_in_chunk + take]

            bytes_read += take
            self.pos += take

        return bytes_read


def open_archive(path):
    """
    Detects DSAR vs PSAR and returns an open stream positioned at the PSAR header.
    """
    f = open(path, 'rb')
    magic = f.read(4)
    f.seek(0)
    if magic == b'DSAR':
        return io.BufferedReader(DSARStream(f)), f
    elif magic == b'PSAR':
        return f, f
    else:
        f.close()
        raise ValueError(f"Unknown archive format (magic: {magic})")


def unpack_archive(archive_path, output_dir=None, verbose=True):
    """
    Extracts all files from a Ghost of Tsushima PSARC (DSAR/PSAR) archive.
    """
    if output_dir is None:
        base_name = os.path.splitext(os.path.basename(archive_path))[0]
        output_dir = os.path.join(os.path.dirname(archive_path), base_name)

    t0 = time.time()
    stream, raw_f = open_archive(archive_path)

    try:
        hdr = stream.read(32)
        if len(hdr) < 32:
            raise ValueError("Archive is too small or corrupted.")

        magic, ver_maj, ver_min, comp_type, toc_sz, entry_sz, num_entries, block_sz, flags = struct.unpack(
            '>4sHH4sIIIII', hdr
        )

        if magic != b'PSAR':
            raise ValueError(f"Inner PSAR header invalid: {magic}")

        comp_type_str = comp_type.decode('ascii', errors='replace').strip('\x00')
        if verbose:
            print(f"[+] Archive: {os.path.basename(archive_path)}")
            print(f"    PSAR Version: {ver_maj}.{ver_min} | Compression: {comp_type_str}")
            print(f"    TOC Size: {toc_sz} bytes | Total Entries: {num_entries} (Files: {num_entries - 1})")
            print(f"    Target Directory: {output_dir}")

        entries = []
        for _ in range(num_entries):
            e_data = stream.read(entry_sz)
            md5_hash = e_data[:16]
            zidx = struct.unpack('>I', e_data[16:20])[0]
            usz = int.from_bytes(e_data[20:25], 'big')
            off = int.from_bytes(e_data[25:30], 'big')
            entries.append((md5_hash, zidx, usz, off))

        # Read zsizes table
        zsizes_start = 32 + num_entries * entry_sz
        zsizes_count = (toc_sz - zsizes_start) // 2
        zsizes_raw = stream.read(zsizes_count * 2)
        zsizes = [struct.unpack('>H', zsizes_raw[i*2 : (i+1)*2])[0] for i in range(zsizes_count)]

        # Entry 0 is the manifest / filenames table
        e0_md5, e0_zidx, e0_usz, e0_off = entries[0]
        stream.seek(e0_off)
        e0_raw = stream.read(e0_usz)

        # Decompress Entry 0 if zlib-compressed
        try:
            e0_decomp = zlib.decompress(e0_raw)
        except Exception:
            e0_decomp = e0_raw

        filenames_raw = [fn.decode('utf-8', errors='replace') for fn in e0_decomp.split(b'\x00') if fn]

        fn_map = {}
        for fn in filenames_raw:
            h = hashlib.md5(fn.encode('utf-8')).digest()
            fn_map[h] = fn

        os.makedirs(output_dir, exist_ok=True)

        # Write Filenames.txt for repacking
        filenames_txt_path = os.path.join(output_dir, 'Filenames.txt')
        with open(filenames_txt_path, 'w', encoding='utf-8') as f:
            for fn in filenames_raw:
                f.write(fn + '\n')

        if verbose:
            print(f"    Resolved {len(fn_map)} filenames from manifest.")
            print("[-] Extracting files...")

        extracted_count = 0
        total_extracted_bytes = 0

        for idx in range(1, num_entries):
            md5_hash, zidx, usz, off = entries[idx]
            fn = fn_map.get(md5_hash, f"/unknown_files/file_{idx:05d}_{md5_hash.hex()}.bin")

            rel_path = fn.lstrip('/').replace('/', os.sep)
            out_file_path = os.path.join(output_dir, rel_path)
            os.makedirs(os.path.dirname(out_file_path), exist_ok=True)

            stream.seek(off)
            cur_z = zidx
            bytes_written = 0

            with open(out_file_path, 'wb') as out_f:
                while bytes_written < usz:
                    needed = usz - bytes_written
                    cur_uncomp = min(block_sz, needed)

                    if cur_z < len(zsizes):
                        zs = zsizes[cur_z]
                        cur_z += 1
                    else:
                        zs = 0

                    if zs == 0:
                        block_data = stream.read(cur_uncomp)
                        out_f.write(block_data)
                        bytes_written += len(block_data)
                    else:
                        block_raw = stream.read(zs)
                        if zs == cur_uncomp:
                            out_f.write(block_raw)
                            bytes_written += len(block_raw)
                        else:
                            try:
                                decomp = zlib.decompress(block_raw)
                                out_f.write(decomp)
                                bytes_written += len(decomp)
                            except Exception:
                                out_f.write(block_raw)
                                bytes_written += len(block_raw)

            extracted_count += 1
            total_extracted_bytes += usz

            if verbose:
                pct = (extracted_count / (num_entries - 1)) * 100
                usz_mb = usz / (1024 * 1024)
                print(f"  [{extracted_count}/{num_entries - 1}] ({pct:5.1f}%) {fn} ({usz_mb:6.2f} MB)")

        elapsed = time.time() - t0
        mb_total = total_extracted_bytes / (1024 * 1024)
        if verbose:
            print(f"[+] Done! Extracted {extracted_count} files ({mb_total:.2f} MB) in {elapsed:.2f}s.")
            print(f"    Filenames manifest saved to: {filenames_txt_path}")

    finally:
        raw_f.close()


def pack_archive(input_dir, output_path=None, format_type='dsar', verbose=True):
    """
    Repacks an unpacked directory back into a Ghost of Tsushima PSARC (DSAR/PSAR).
    """
    if not os.path.isdir(input_dir):
        raise ValueError(f"Input directory does not exist: {input_dir}")

    if output_path is None:
        norm = os.path.normpath(input_dir)
        output_path = norm + ".psarc"

    t0 = time.time()
    filenames_txt = os.path.join(input_dir, 'Filenames.txt')

    file_names = []
    if os.path.isfile(filenames_txt):
        with open(filenames_txt, 'r', encoding='utf-8') as f:
            for line in f:
                stripped = line.strip()
                if stripped:
                    file_names.append(stripped)

    # Scan directory for any extra or modified files
    scanned_map = {}
    for root, dirs, files in os.walk(input_dir):
        for file in files:
            if file == 'Filenames.txt':
                continue
            full_path = os.path.join(root, file)
            rel_path = os.path.relpath(full_path, input_dir).replace('\\', '/')
            canon_name = '/' + rel_path
            scanned_map[canon_name.lower()] = (canon_name, full_path)

    # Reconcile files: start with Filenames.txt order, then add new ones
    ordered_files = []
    seen = set()
    for fn in file_names:
        key = fn.lower()
        if key in scanned_map:
            canon_name, full_path = scanned_map[key]
            ordered_files.append((canon_name, full_path))
            seen.add(key)
        else:
            rel = fn.lstrip('/')
            full_path = os.path.join(input_dir, rel.replace('/', os.sep))
            if os.path.isfile(full_path):
                ordered_files.append((fn, full_path))
                seen.add(key)

    for key, (canon_name, full_path) in scanned_map.items():
        if key not in seen:
            ordered_files.append((canon_name, full_path))

    if not ordered_files:
        raise ValueError(f"No files found to pack in {input_dir}")

    # Gather file metadata
    file_records = []
    total_raw_bytes = 0
    for canon_name, full_path in ordered_files:
        sz = os.path.getsize(full_path)
        file_records.append((canon_name, full_path, sz))
        total_raw_bytes += sz

    if verbose:
        print(f"[+] Packing directory: {input_dir}")
        print(f"    Target Archive: {output_path} | Format: {format_type.upper()}")
        print(f"    Total Files: {len(file_records)} | Total Uncompressed Size: {total_raw_bytes / (1024*1024):.2f} MB")

    # Build Filenames table for Entry 0
    all_canon_names = [r[0] for r in file_records]
    filenames_bytes = b'\x00'.join(fn.encode('utf-8') for fn in all_canon_names)

    num_entries = len(file_records) + 1
    entry_sz = 30
    block_sz = 65536

    # Calculate zsizes
    all_zsizes = []

    # Entry 0 zsizes (uncompressed)
    for i in range(0, len(filenames_bytes), block_sz):
        blk_len = min(block_sz, len(filenames_bytes) - i)
        all_zsizes.append(0 if blk_len == block_sz else blk_len)
    if not all_zsizes:
        all_zsizes = [0]

    # File zsizes
    files_with_meta = []
    for canon_name, full_path, sz in file_records:
        zidx = len(all_zsizes)
        if sz == 0:
            all_zsizes.append(0)
        else:
            for i in range(0, sz, block_sz):
                blk_len = min(block_sz, sz - i)
                all_zsizes.append(0 if blk_len == block_sz else blk_len)
        files_with_meta.append((canon_name, full_path, sz, zidx))

    toc_sz = 32 + num_entries * entry_sz + len(all_zsizes) * 2
    e0_off = toc_sz
    curr_uoff = toc_sz + len(filenames_bytes)

    # Build entries list
    entries_list = [(16 * b'\x00', 0, len(filenames_bytes), e0_off)]

    final_file_records = []
    for canon_name, full_path, sz, zidx in files_with_meta:
        h = hashlib.md5(canon_name.encode('utf-8')).digest()
        off = curr_uoff
        entries_list.append((h, zidx, sz, off))
        final_file_records.append((canon_name, full_path, sz, zidx, off))
        curr_uoff += sz

    # Sort entries 1..N by MD5 hash
    sorted_entries = [entries_list[0]] + sorted(entries_list[1:], key=lambda x: x[0])

    # Build PSAR TOC
    psar_hdr = struct.pack('>4sHH4sIIIII', b'PSAR', 1, 4, b'zlib', toc_sz, entry_sz, num_entries, block_sz, 14)
    entries_bytes = bytearray()
    for h, zidx, usz, off in sorted_entries:
        entries_bytes += h + struct.pack('>I', zidx) + usz.to_bytes(5, 'big') + off.to_bytes(5, 'big')

    zsizes_bytes = bytearray()
    for zs in all_zsizes:
        zsizes_bytes += struct.pack('>H', zs)

    toc_data = bytes(psar_hdr) + bytes(entries_bytes) + bytes(zsizes_bytes)
    assert len(toc_data) == toc_sz

    CHUNK_MAX = 262144

    if format_type.lower() == 'dsar':
        # DirectStorage DSAR container
        chunk_count = 2  # TOC + Entry 0
        for _, _, sz, _, _ in final_file_records:
            if sz == 0:
                chunk_count += 1
            else:
                chunk_count += (sz + CHUNK_MAX - 1) // CHUNK_MAX

        first_chunk_offset = (32 + chunk_count * 32 + 15) & ~15
        total_uncomp = curr_uoff

        chunks_meta = []  # (uoff, coff, usz, csz, cflag)

        temp_output = output_path + ".tmp"
        with open(temp_output, 'wb') as out_f:
            out_f.seek(first_chunk_offset)
            cur_coff = first_chunk_offset

            # Chunk 0: PSAR TOC
            c_toc = lz4.block.compress(toc_data, store_size=False)
            cflag = 3 if len(c_toc) < len(toc_data) else 0
            cdata = c_toc if cflag == 3 else toc_data
            csz = len(cdata)
            out_f.write(cdata)
            chunks_meta.append((0, cur_coff, len(toc_data), csz, cflag))
            cur_coff += csz
            pad = (16 - (cur_coff % 16)) % 16
            if pad:
                out_f.write(b'\x00' * pad)
                cur_coff += pad

            # Chunk 1: Entry 0 (filenames)
            c_fn = lz4.block.compress(filenames_bytes, store_size=False)
            cflag = 3 if len(c_fn) < len(filenames_bytes) else 0
            cdata = c_fn if cflag == 3 else filenames_bytes
            csz = len(cdata)
            out_f.write(cdata)
            chunks_meta.append((e0_off, cur_coff, len(filenames_bytes), csz, cflag))
            cur_coff += csz
            pad = (16 - (cur_coff % 16)) % 16
            if pad:
                out_f.write(b'\x00' * pad)
                cur_coff += pad

            # Chunks for each file
            file_idx = 0
            for canon_name, full_path, sz, zidx, off in final_file_records:
                file_idx += 1
                if sz == 0:
                    chunks_meta.append((off, 0, 0, 0, 254))
                    continue

                with open(full_path, 'rb') as in_f:
                    file_uoff = off
                    while True:
                        buf = in_f.read(CHUNK_MAX)
                        if not buf:
                            break
                        c_buf = lz4.block.compress(buf, store_size=False)
                        cflag = 3 if len(c_buf) < len(buf) else 0
                        cdata = c_buf if cflag == 3 else buf
                        csz = len(cdata)
                        out_f.write(cdata)
                        chunks_meta.append((file_uoff, cur_coff, len(buf), csz, cflag))
                        file_uoff += len(buf)
                        cur_coff += csz
                        pad = (16 - (cur_coff % 16)) % 16
                        if pad:
                            out_f.write(b'\x00' * pad)
                            cur_coff += pad

                if verbose and (file_idx % 25 == 0 or file_idx == len(final_file_records)):
                    pct = (file_idx / len(final_file_records)) * 100
                    print(f"  [Packing {file_idx}/{len(final_file_records)}] ({pct:5.1f}%) {canon_name}")

            # Write header and chunk table at offset 0
            out_f.seek(0)
            dsar_hdr = bytearray(32)
            dsar_hdr[:4] = b'DSAR'
            struct.pack_into('<HHI', dsar_hdr, 4, 3, 1, len(chunks_meta))
            struct.pack_into('<I', dsar_hdr, 12, first_chunk_offset)
            struct.pack_into('<Q', dsar_hdr, 16, total_uncomp)
            dsar_hdr[24:32] = b'PADDING*'
            out_f.write(dsar_hdr)

            for uoff, coff, usz, csz, cflag in chunks_meta:
                entry = struct.pack('<QQIIB7s', uoff, coff, usz, csz, cflag, b'\x55'*7)
                out_f.write(entry)

        if os.path.isfile(output_path):
            os.remove(output_path)
        os.rename(temp_output, output_path)

    elif format_type.lower() == 'psar':
        # Standard uncompressed/zlib Sony PSAR
        temp_output = output_path + ".tmp"
        with open(temp_output, 'wb') as out_f:
            out_f.write(toc_data)
            out_f.write(filenames_bytes)
            file_idx = 0
            for canon_name, full_path, sz, zidx, off in final_file_records:
                file_idx += 1
                with open(full_path, 'rb') as in_f:
                    while True:
                        buf = in_f.read(CHUNK_MAX)
                        if not buf:
                            break
                        out_f.write(buf)

                if verbose and (file_idx % 25 == 0 or file_idx == len(final_file_records)):
                    pct = (file_idx / len(final_file_records)) * 100
                    print(f"  [Packing {file_idx}/{len(final_file_records)}] ({pct:5.1f}%) {canon_name}")

        if os.path.isfile(output_path):
            os.remove(output_path)
        os.rename(temp_output, output_path)

    else:
        raise ValueError(f"Unknown format: {format_type}. Choose 'dsar' or 'psar'.")

    elapsed = time.time() - t0
    final_sz = os.path.getsize(output_path)
    if verbose:
        print(f"[+] Successfully repacked into {output_path}")
        print(f"    Final Archive Size: {final_sz / (1024*1024):.2f} MB | Elapsed: {elapsed:.2f}s")


def list_archive(archive_path):
    """
    Lists all files inside an archive without extracting.
    """
    stream, raw_f = open_archive(archive_path)
    try:
        hdr = stream.read(32)
        magic, ver_maj, ver_min, comp_type, toc_sz, entry_sz, num_entries, block_sz, flags = struct.unpack(
            '>4sHH4sIIIII', hdr
        )
        if magic != b'PSAR':
            raise ValueError("Invalid PSAR header.")

        entries = []
        for _ in range(num_entries):
            e_data = stream.read(entry_sz)
            md5_hash = e_data[:16]
            zidx = struct.unpack('>I', e_data[16:20])[0]
            usz = int.from_bytes(e_data[20:25], 'big')
            off = int.from_bytes(e_data[25:30], 'big')
            entries.append((md5_hash, zidx, usz, off))

        e0_md5, e0_zidx, e0_usz, e0_off = entries[0]
        stream.seek(e0_off)
        e0_raw = stream.read(e0_usz)
        try:
            e0_decomp = zlib.decompress(e0_raw)
        except Exception:
            e0_decomp = e0_raw

        filenames = [fn.decode('utf-8', errors='replace') for fn in e0_decomp.split(b'\x00') if fn]
        fn_map = {hashlib.md5(fn.encode('utf-8')).digest(): fn for fn in filenames}

        print(f"\nArchive: {os.path.basename(archive_path)}")
        print(f"Total Files: {num_entries - 1}")
        print("-" * 75)
        print(f"{'Index':<6} {'Size (Bytes)':<14} {'Size (MB)':<12} {'Filename'}")
        print("-" * 75)

        total_bytes = 0
        for idx in range(1, num_entries):
            md5_hash, zidx, usz, off = entries[idx]
            fn = fn_map.get(md5_hash, f"unknown_file_{idx}")
            mb = usz / (1024 * 1024)
            print(f"{idx:<6} {usz:<14} {mb:<12.2f} {fn}")
            total_bytes += usz

        print("-" * 75)
        print(f"Total Size: {total_bytes / (1024*1024):.2f} MB ({total_bytes} bytes)\n")

    finally:
        raw_f.close()


def main():
    parser = argparse.ArgumentParser(
        description="Ghost of Tsushima DIRECTOR'S CUT - PSARC / DSAR Unpacker & Repacker",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Unpack archive into folder:
  python got_psarc_tool.py unpack gapack_misc_b.psarc
  python got_psarc_tool.py unpack gapack_misc_b.psarc custom_output_dir

  # Repack folder back into PSARC (DSAR DirectStorage format for PC):
  python got_psarc_tool.py pack gapack_misc_b
  python got_psarc_tool.py pack custom_output_dir repacked_archive.psarc

  # Repack as standard Sony PSAR:
  python got_psarc_tool.py pack custom_output_dir repacked.psarc --format psar

  # List files in archive without extracting:
  python got_psarc_tool.py list gapack_misc_b.psarc
        """
    )

    subparsers = parser.add_subparsers(dest='command', help='Command to execute')

    # unpack
    p_unpack = subparsers.add_parser('unpack', aliases=['x', 'extract'], help='Extract archive contents')
    p_unpack.add_argument('archive', help='Path to .psarc file')
    p_unpack.add_argument('output', nargs='?', default=None, help='Output directory (optional)')

    # pack
    p_pack = subparsers.add_parser('pack', aliases=['c', 'repack'], help='Repack directory into .psarc archive')
    p_pack.add_argument('directory', help='Input directory to pack')
    p_pack.add_argument('output', nargs='?', default=None, help='Output .psarc path (optional)')
    p_pack.add_argument('--format', choices=['dsar', 'psar'], default='dsar', help="Archive format ('dsar' for GoT PC DirectStorage, 'psar' for Sony standard)")

    # list
    p_list = subparsers.add_parser('list', aliases=['l'], help='List archive contents without extracting')
    p_list.add_argument('archive', help='Path to .psarc file')

    # Handle drag-and-drop or single argument
    if len(sys.argv) == 2:
        arg = sys.argv[1]
        if arg in ('-h', '--help'):
            parser.print_help()
            return
        if os.path.isfile(arg):
            print(f"[Drag-and-Drop] Detected archive file: {arg}")
            unpack_archive(arg)
            input("\nPress Enter to exit...")
            return
        elif os.path.isdir(arg):
            print(f"[Drag-and-Drop] Detected directory: {arg}")
            pack_archive(arg)
            input("\nPress Enter to exit...")
            return

    if len(sys.argv) == 1:
        parser.print_help()
        return

    args = parser.parse_args()

    if args.command in ('unpack', 'x', 'extract'):
        unpack_archive(args.archive, args.output)
    elif args.command in ('pack', 'c', 'repack'):
        pack_archive(args.directory, args.output, format_type=args.format)
    elif args.command in ('list', 'l'):
        list_archive(args.archive)
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
