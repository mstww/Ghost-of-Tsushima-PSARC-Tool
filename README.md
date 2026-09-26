# Ghost of Tsushima DIRECTOR'S CUT — PSARC / DSAR Tool

[![Platform: Windows](https://img.shields.io/badge/Platform-Windows-blue.svg)](https://github.com/)
[![Python: 3.10+](https://img.shields.io/badge/Python-3.10%2B-brightgreen.svg)](https://www.python.org/)
[![DirectStorage: DSAR](https://img.shields.io/badge/Format-DirectStorage%20DSAR-orange.svg)](https://github.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A high-performance, memory-efficient extractor and repacker for **Ghost of Tsushima DIRECTOR'S CUT** (PC) archive files (`.psarc`).

---

## 🎯 Why This Tool?

Existing tools like `UnPSARC.exe` fail on *Ghost of Tsushima DIRECTOR'S CUT* (PC) for several reasons:

1. **DirectStorage `DSAR` Format:** Ghost of Tsushima PC uses Microsoft DirectStorage (`dstorage.dll`). The game's archives (`gapack_*.psarc`, `lang_*_audio.psarc`, etc.) are not standard Sony PSAR archives; they are **`DSAR` (DirectStorage Archive)** containers wrapping PSAR streams in 256KB LZ4 blocks.
2. **Repacking Failure in UnPSARC:** `UnPSARC.exe` only creates legacy standard Sony PSAR files—it has **no DirectStorage compressor**. Archives repacked with UnPSARC cannot be parsed by the game engine, leading to game crashes or missing assets.
3. **Extraction Crashes / Hangs:** UnPSARC frequently encounters `EndOfStreamException` or pauses execution with `Console.ReadKey()` when processing zero-size padding blocks or boundary chunks.

**`got_psarc_tool` solves all these problems** by implementing a complete, native DirectStorage DSAR decompressor and compressor designed specifically for the Ghost of Tsushima PC engine.

---

## ✨ Features

- **Full DirectStorage (DSAR) Support:** Unpacks and repacks DSAR archives with native LZ4 block compression, 16-byte alignment, and DirectStorage headers.
- **Sony PSAR Fallback:** Automatically detects and supports standard Sony `PSAR` archives.
- **Ultra-Low Memory Usage (`DSARStream`):** Reads and writes in a streaming fashion. Uses **less than 10 MB of RAM** even when processing 50+ GB archives.
- **Blazing Fast:** Extracts and repacks gigabytes of data in just 2-3 seconds.
- **Bit-Perfect Verification:** Extracted and repacked files match original game assets with 100% MD5 hash precision.
- **Manifest Preservation (`Filenames.txt`):** Automatically preserves the canonical forward-slash path formatting (`/loc_toy_kubara_outpost_a.xpps`) and file ordering required by the game engine.
- **Drag-and-Drop Ready:** Drag a `.psarc` file onto the tool to extract; drag a folder to repack!

---

## 📦 Download & Installation

### Option 1: Standalone Executable (Recommended)
Download `got_psarc_tool.exe`. No Python installation required!

### Option 2: Running with Python
1. Clone the repository:
   ```bash
   git clone https://github.com/your-username/Ghost-of-Tsushima-PSARC-Tool.git
   cd Ghost-of-Tsushima-PSARC-Tool
   ```
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

---

## 🚀 Usage

### 1. Drag & Drop
- **To Unpack:** Drag and drop any `.psarc` file onto `got_psarc_tool.exe` (or `quick_unpack.bat`). It will extract into a folder with the same name.
- **To Repack:** Drag and drop your modified folder onto `got_psarc_tool.exe` (or `quick_repack.bat`). It will compile into an engine-compatible `.psarc` archive.

---

### 2. Command Line (CLI)

#### 📂 Unpack (Extract)
```bash
# Extract archive into a folder with the same name
got_psarc_tool.exe unpack "gapack_misc_b.psarc"

# Extract archive into a custom directory
got_psarc_tool.exe unpack "gapack_misc_b.psarc" "custom_output_dir"
```

#### 📦 Pack (Repack)
```bash
# Repack folder into DSAR archive (DirectStorage format, default for GoT PC)
got_psarc_tool.exe pack "custom_output_dir"

# Repack folder with custom output archive name
got_psarc_tool.exe pack "custom_output_dir" "gapack_misc_b.psarc"

# Repack as standard Sony PSAR format (legacy)
got_psarc_tool.exe pack "custom_output_dir" "gapack_misc_b.psarc" --format psar
```

#### 📋 List Contents
```bash
# View all files and uncompressed sizes inside the archive without extracting
got_psarc_tool.exe list "gapack_misc_b.psarc"
```

---

## 🔬 DirectStorage DSAR Technical Details

For modders and reverse engineers interested in the container layout:

```
+-------------------------------------------------------------+
| Header (32 bytes, Little-Endian)                            |
| 0x00 - 0x03 : b'DSAR' (Magic)                               |
| 0x04 - 0x07 : Version (Major: 3, Minor: 1)                  |
| 0x08 - 0x0B : chunk_count (uint32)                          |
| 0x0C - 0x0F : first_chunk_offset (uint32, 16-byte aligned)  |
| 0x10 - 0x17 : total_uncompressed_size (uint64)              |
| 0x18 - 0x1F : b'PADDING*' (8 bytes)                         |
+-------------------------------------------------------------+
| Chunk Table (chunk_count entries * 32 bytes)                |
| 0x00 - 0x07 : uncompressed_offset (uint64)                  |
| 0x08 - 0x0F : compressed_offset (uint64, 16-byte aligned)   |
| 0x10 - 0x13 : uncompressed_size (uint32, max 262144 bytes)  |
| 0x14 - 0x17 : compressed_size (uint32, 0 if padding)        |
| 0x18        : compression_flag (3=LZ4 block, 0=raw, 254=pad)|
| 0x19 - 0x1F : 7 bytes padding (b'\x55'*7)                   |
+-------------------------------------------------------------+
| Payload                                                     |
| Chunk 0     : PSAR Table of Contents (LZ4 compressed)       |
| Chunk 1     : Entry 0 / Filenames list (LZ4 compressed)     |
| Chunk 2..N  : 256KB chunks of file data (LZ4 compressed)    |
+-------------------------------------------------------------+
```

---

## 🇹🇷 Türkçe Kullanım Özeti

**Ghost of Tsushima DIRECTOR'S CUT (PC)** oyunundaki `.psarc` dosyaları DirectStorage (`DSAR`) formatındadır. Eski `UnPSARC` araçları repack yaparken DirectStorage sıkıştırması uygulamadığı için oyun çöker veya dosyaları okuyamaz.

Bu araç ile:
- **Çıkarma:** `.psarc` dosyasını `got_psarc_tool.exe` üzerine sürükleyip bırakmanız yeterlidir.
- **Paketleme:** Düzenlediğiniz klasörü (içindeki `Filenames.txt` ile birlikte) `got_psarc_tool.exe` üzerine sürükleyip bırakarak oyuna %100 uyumlu `.psarc` dosyası elde edebilirsiniz.
- **Bellek Dostu:** Akışlı okuma sayesinde devasa boyutlu arşivlerde bile RAM şişmesi yaşanmaz.

---

## 🛠️ Building From Source

To build your own standalone `.exe` using PyInstaller:
```bash
build_exe.bat
```
or manually:
```bash
pyinstaller --onefile --name "got_psarc_tool" got_psarc_tool.py
```

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
