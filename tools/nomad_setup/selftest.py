"""Offline self-checks - no hardware, no SD card, nothing destructive.

Runs the two pieces of this tool that are worth not getting wrong: the FAT32
formatter (against a throwaway image file, checked with fsck.vfat and mtools
when they are installed) and the pre-flash partition checks.

    nomad-setup selftest
"""

from __future__ import annotations

import shutil
import struct
import subprocess
import tempfile
from pathlib import Path
from typing import List, Tuple

from . import console as c
from . import build, esp, fat32, sdcard

# Card sizes worth covering: each one lands in a different cluster-size band,
# and the >32 GB ones are exactly what Windows refuses to format.
IMAGE_SIZES = [
    ("64 MB", 64 << 20),
    ("512 MB", 512 << 20),
    ("2 GB", 2 << 30),
    ("8 GB", 8 << 30),
    ("32 GB", 32 << 30),
    ("64 GB", 64 << 30),
    ("128 GB", 128 << 30),
]


def _check_boot_sector(path: Path, start_lba: int, geo: fat32.Fat32Geometry) -> List[str]:
    """Read the boot sector back and confirm it describes what we planned."""
    problems: List[str] = []
    with open(path, "rb") as fh:
        fh.seek(start_lba * fat32.SECTOR)
        bs = fh.read(fat32.SECTOR)

    if bs[510:512] != b"\x55\xaa":
        problems.append("boot sector signature missing")
    if bs[82:90] != b"FAT32   ":
        problems.append("filesystem type is not FAT32")
    if struct.unpack_from("<H", bs, 11)[0] != fat32.SECTOR:
        problems.append("bytes-per-sector mismatch")
    if bs[13] != geo.sectors_per_cluster:
        problems.append("sectors-per-cluster mismatch")
    if struct.unpack_from("<L", bs, 32)[0] != geo.total_sectors:
        problems.append("total sector count mismatch")
    if struct.unpack_from("<L", bs, 36)[0] != geo.fat_sectors:
        problems.append("FAT size mismatch")
    if struct.unpack_from("<L", bs, 28)[0] != start_lba:
        problems.append("hidden sector count does not match the partition start")

    # The FAT must be big enough to address every cluster.
    if (geo.cluster_count + 2) * 4 > geo.fat_sectors * fat32.SECTOR:
        problems.append("FAT is too small for the cluster count")
    if geo.cluster_count < fat32.MIN_FAT32_CLUSTERS:
        problems.append("cluster count is below the FAT32 minimum")
    return problems


def _fsck(image: Path, start_lba: int, sectors: int,
          geo: fat32.Fat32Geometry) -> Tuple[bool, str]:
    """fsck.vfat only looks at a bare volume, so slice the partition out.

    Copy everything up to and including the root directory cluster - on a
    128 GB card the two FATs alone are 32 MB, and a short slice would make
    fsck report a missing volume label."""
    if not shutil.which("fsck.vfat"):
        return True, "skipped (fsck.vfat not installed)"

    metadata_sectors = geo.first_data_sector + geo.sectors_per_cluster
    with tempfile.NamedTemporaryFile(suffix=".part", delete=False) as tmp:
        part_path = Path(tmp.name)
    try:
        with open(image, "rb") as src, open(part_path, "r+b") as dst:
            src.seek(start_lba * fat32.SECTOR)
            remaining = min(metadata_sectors, sectors) * fat32.SECTOR
            while remaining > 0:
                chunk = src.read(min(remaining, 8 << 20))
                if not chunk:
                    break
                dst.write(chunk)
                remaining -= len(chunk)
            dst.truncate(sectors * fat32.SECTOR)
        proc = subprocess.run(["fsck.vfat", "-n", str(part_path)],
                              capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
        detail = ((proc.stdout or "") + (proc.stderr or "")).strip().splitlines()
        return proc.returncode == 0, (detail[-1] if detail else "clean")
    finally:
        part_path.unlink(missing_ok=True)


def _mtools_roundtrip(image: Path, start_lba: int) -> Tuple[bool, str]:
    """Write a file through an independent FAT implementation and read it back."""
    if not (shutil.which("mcopy") and shutil.which("mdir")):
        return True, "skipped (mtools not installed)"

    target = f"{image}@@{start_lba * fat32.SECTOR}"
    env = {"MTOOLS_SKIP_CHECK": "1"}
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as tmp:
        tmp.write("jcorp nomad selftest\n")
        payload = Path(tmp.name)
    try:
        proc = subprocess.run(["mcopy", "-i", target, str(payload), "::/HELLO.TXT"],
                              capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=120)
        if proc.returncode != 0:
            return False, (proc.stderr or proc.stdout or "mcopy failed").strip()[:120]
        proc = subprocess.run(["mdir", "-i", target, "::"],
                              capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=120)
        if proc.returncode != 0 or "HELLO" not in (proc.stdout or ""):
            return False, "file written but not listed back"
        return True, "wrote and read back a file"
    finally:
        payload.unlink(missing_ok=True)


def run_fat32_tests() -> int:
    c.heading("FAT32 formatter")
    failures = 0
    rows = []

    for label, size in IMAGE_SIZES:
        with tempfile.NamedTemporaryFile(suffix=".img", delete=False) as tmp:
            image = Path(tmp.name)
        try:
            # Sparse: only the structures we write consume real space.
            with open(image, "r+b") as fh:
                fh.truncate(size)
                start, sectors, geo = fat32.format_disk(fh, size // fat32.SECTOR, "NOMAD")

            problems = _check_boot_sector(image, start, geo)
            fsck_ok, fsck_note = _fsck(image, start, sectors, geo)
            mt_ok, mt_note = _mtools_roundtrip(image, start)

            ok = not problems and fsck_ok and mt_ok
            failures += 0 if ok else 1
            note = "; ".join(problems) if problems else f"{fsck_note}; {mt_note}"
            rows.append([
                label,
                "PASS" if ok else "FAIL",
                f"{geo.cluster_bytes // 1024} KB",
                f"{geo.cluster_count:,}",
                note[:52],
            ])
        except fat32.Fat32Error as exc:
            failures += 1
            rows.append([label, "FAIL", "-", "-", str(exc)[:52]])
        finally:
            image.unlink(missing_ok=True)

    c.table(["card", "result", "cluster", "clusters", "notes"], rows)
    return failures


def _fake_build(directory: Path, app_bytes: int, app_part: int, flash_mb: int) -> None:
    def entry(ptype, subtype, offset, size, label):
        return struct.pack("<2sBBLL16sL", b"\xaa\x50", ptype, subtype, offset, size,
                           label.encode().ljust(16, b"\x00"), 0)

    table = (entry(1, 2, 0x9000, 0x5000, "nvs")
             + entry(1, 0, 0xE000, 0x2000, "otadata")
             + entry(0, 0x10, 0x10000, app_part, "app0"))
    (directory / "boot.bin").write_bytes(b"\x00" * 1024)
    (directory / "parts.bin").write_bytes(table.ljust(3072, b"\xff"))
    (directory / "app.ino.bin").write_bytes(b"\x00" * app_bytes)
    (directory / "flash_args").write_text(
        f"--flash-mode dio --flash-freq 80m --flash-size {flash_mb}MB\n"
        "0x0 boot.bin\n0x8000 parts.bin\n0x10000 app.ino.bin\n"
    )


def run_preflight_tests() -> int:
    c.heading("Pre-flash checks")
    cases = [
        # name,            app,       app0 size, built-for, chip flash, chip,      expect ok
        ("healthy 16 MB",  1_450_000, 0x300000, 16, 16, "ESP32-S3", True),
        ("app > partition", 1_450_000, 0x140000, 4, 4, "ESP32-S3", False),
        ("built for bigger flash", 1_450_000, 0x300000, 16, 4, "ESP32-S3", False),
        ("smaller build on big chip", 1_450_000, 0x300000, 4, 16, "ESP32-S3", True),
        ("wrong chip family", 1_450_000, 0x300000, 16, 16, "ESP32-C3", False),
        # An unparseable chip name is our bug, not a wrong board: warn, allow.
        ("chip name unreadable", 1_450_000, 0x300000, 16, 16, "", True),
    ]

    failures = 0
    rows = []
    for name, app, part, built_mb, chip_mb, chip_name, expect_ok in cases:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            _fake_build(directory, app, part, built_mb)
            plan = esp.load_flash_plan(directory)
            result = esp.preflight(plan, esp.ChipInfo(chip=chip_name, flash_mb=chip_mb,
                                                      psram_mb=8))
            passed = result.ok == expect_ok
            failures += 0 if passed else 1
            verdict = "allowed" if result.ok else "refused"
            rows.append([name, "PASS" if passed else "FAIL", verdict,
                         (result.errors[0].split(".")[0] if result.errors else "")[:44]])

    c.table(["case", "result", "verdict", "reason"], rows)
    return failures


# Real banners. esptool changed its wording in 5.0 and the probe went on
# reporting flash, PSRAM and MAC while silently losing the chip name, which the
# pre-flash check then read as "not an S3" and refused to flash a good board.
_PROBE_CASES = [
    ("esptool 5.x", """esptool v5.3.1
Connected to ESP32-S3 on COM6:
Chip type:          ESP32-S3 (QFN56) (revision v0.2)
Features:           Wi-Fi, BLE, Embedded PSRAM 8MB (AP_3v3)
Crystal frequency:  40MHz
MAC:                3c:0f:02:d9:6b:64
Detected flash size: 16MB
""", "ESP32-S3", 16, 8),
    ("esptool 4.x", """esptool.py v4.8.1
Chip is ESP32-S3 (revision v0.2)
Features: WiFi, BLE, Embedded PSRAM 8MB (AP_3v3)
MAC: 3c:0f:02:d9:6b:64
Detected flash size: 16MB
""", "ESP32-S3", 16, 8),
    ("5.x secure download", """esptool v5.3.1
Connected to ESP32-S3 on COM6:
Chip type:          ESP32-S3 in Secure Download Mode
""", "ESP32-S3", 0, 0),
    ("non-S3 board", """esptool.py v4.8.1
Chip is ESP32-C3 (revision v0.4)
Features: WiFi, BLE
Detected flash size: 4MB
""", "ESP32-C3", 4, 0),
]


def run_chip_probe_tests() -> int:
    c.heading("Chip banner parsing")
    failures = 0
    rows = []
    for name, banner, want_chip, want_flash, want_psram in _PROBE_CASES:
        info = esp.parse_chip_output(banner)
        got = (info.chip, info.flash_mb, info.psram_mb)
        want = (want_chip, want_flash, want_psram)
        passed = got == want
        failures += 0 if passed else 1
        rows.append([name, "PASS" if passed else "FAIL", info.chip or "(none)",
                     f"{info.flash_mb} MB", f"{info.psram_mb} MB PSRAM"])
    c.table(["banner", "result", "chip", "flash", "psram"], rows)
    return failures


# Telling a broken toolchain apart from a broken sketch. Getting this wrong in
# the permissive direction sends someone off to reinstall a gigabyte over a
# typo, so the negative cases matter more than the positive ones.
_DIAGNOSIS_CASES = [
    ("esp32s3-libs, Invalid argument",
     r"unordered_map:42:10: fatal error: C:\...\tools\esp32s3-libs\3.3.11/include/"
     r"esp_pm/include/bits/range_access.h: Invalid argument", True),
    ("toolchain not a Win32 app",
     "xtensa-esp32s3-elf-g++.exe: %1 is not a valid Win32 application.", True),
    ("undeclared identifier",
     "JcorpNomadProject.ino:412:3: error: 'ui_Screen1' was not declared in this scope", False),
    ("missing library header",
     "JcorpNomadProject.ino:9:10: fatal error: ArduinoJson.h: No such file or directory", False),
    ("missing lv_conf.h",
     r"lvgl\src\lv_conf_internal.h:40:12: fatal error: ../../lv_conf.h: "
     "No such file or directory", False),
    ("nothing at all", "", False),
]


def run_diagnosis_tests() -> int:
    c.heading("Build-failure diagnosis")
    failures = 0
    rows = []
    for name, text, expect in _DIAGNOSIS_CASES:
        got = bool(build.diagnose_build_failure(text))
        passed = got == expect
        failures += 0 if passed else 1
        rows.append([name, "PASS" if passed else "FAIL",
                     "repair-core" if got else "shown as-is"])
    c.table(["compiler said", "result", "tool responds with"], rows)
    return failures


_PORTS = [("COM6", "COM6"), ("COM9", "COM9"), ("COM8", "COM8")]
_DISKS = [("/dev/sdb", "/dev/sdb  SanDisk Ultra 32 GB"),
          ("/dev/sdc", "/dev/sdc  Generic 8 GB")]
_TRICKY = [("COM3", "COM3"), ("COM1", "COM1")]      # index 1 vs a port named COM1
_AMBIG = [("COM6", "COM6"), ("COM16", "COM16")]     # "6" occurs in both

# Listing "1) COM6" and then rejecting "COM6" is indefensible. None is "refuse".
_PICKER_CASES = [
    ("port by index",          _PORTS,  "1",        "COM6"),
    ("port by name",           _PORTS,  "COM6",     "COM6"),
    ("port by name, lowercase", _PORTS, "com6",     "COM6"),
    ("port by its own digit",  _PORTS,  "6",        "COM6"),
    ("disk by path",           _DISKS,  "/dev/sdb", "/dev/sdb"),
    ("disk by bare name",      _DISKS,  "sdb",      "/dev/sdb"),
    ("disk by brand",          _DISKS,  "SanDisk",  "/dev/sdb"),
    ("index beats a lookalike name", _TRICKY, "1",  "COM3"),
    ("that lookalike by name", _TRICKY, "COM1",     "COM1"),
    ("ambiguous fragment",     _AMBIG,  "6",        None),
    ("exact wins over ambiguity", _AMBIG, "COM6",   "COM6"),
    ("matches nothing",        _PORTS,  "COM4",     None),
    ("empty",                  _PORTS,  "",         None),
]


def run_picker_tests() -> int:
    c.heading("Port and disk picker")
    failures = 0
    rows = []
    for name, options, typed, expect in _PICKER_CASES:
        index, message = c.resolve_choice(typed, options)
        got = options[index][0] if index is not None else None
        passed = got == expect
        failures += 0 if passed else 1
        rows.append([name, "PASS" if passed else "FAIL", repr(typed),
                     got if got is not None else "refused"])
    c.table(["case", "result", "typed", "selected"], rows)
    return failures


def _p(dev, desc="", vid=None, pid=None):
    return esp.SerialPort(dev, desc, vid, pid)


# 0x303A is Espressif's own VID; 0x1A86/0x10C4 are the bridges on dev boards.
# None as the expectation means "must ask" - guessing between two boards is
# worse than one question.
_PORT_CASES = [
    ("dongle among unrelated ports",
     [_p("COM6", "USB Serial Device", 0x303A, 0x1001), _p("COM9", "Bluetooth"),
      _p("COM8", "Intel AMT", 0x8086, 0x1234)], "COM6"),
    ("dongle alone", [_p("COM6", "", 0x303A, 0x1001)], "COM6"),
    ("dongle beside a CP210x board",
     [_p("COM6", "", 0x303A, 0x1001), _p("COM4", "", 0x10C4, 0xEA60)], "COM6"),
    ("two ESP32s connected",
     [_p("COM6", "", 0x303A, 0x1001), _p("COM7", "", 0x303A, 0x1001)], None),
    ("older ESP32 behind a CH340",
     [_p("COM3", "", 0x1A86, 0x7523), _p("COM9", "Bluetooth")], "COM3"),
    ("two bridges, neither native",
     [_p("COM3", "", 0x1A86, 0x7523), _p("COM4", "", 0x10C4, 0xEA60)], None),
    ("a single anonymous port", [_p("COM6", "")], "COM6"),
    ("several, none identify",
     [_p("COM9", "Bluetooth"), _p("COM8", "Intel")], None),
    ("linux native usb", [_p("/dev/ttyACM0", "", 0x303A, 0x1001)], "/dev/ttyACM0"),
]


def run_port_tests() -> int:
    c.heading("Serial port autodetection")
    failures = 0
    rows = []
    for name, ports, expect in _PORT_CASES:
        found, why = esp.autodetect_port(ports)
        device = found.device if found else None
        passed = device == expect
        failures += 0 if passed else 1
        rows.append([name, "PASS" if passed else "FAIL", device or "asks", why])
    c.table(["situation", "result", "picks", "because"], rows)
    return failures


def run_template_tests() -> int:
    """The required-files manifest is only useful if it matches the template
    actually shipped in the repo, so check the two against each other."""
    c.heading("SD card template")
    try:
        template = sdcard.find_template()
    except sdcard.SdCardError as exc:
        c.warn(str(exc).splitlines()[0])
        c.info("Skipped (run this from inside the repository to include it)")
        return 0

    plan = sdcard.plan_copy(template, include_placeholders=True)
    copied = {item.relative for item in plan.items}

    failures = 0
    rows = []

    for name in sdcard.REQUIRED_FILES:
        present = name in copied
        failures += 0 if present else 1
        rows.append([name, "PASS" if present else "FAIL",
                     "in template and copied" if present else "MISSING from the template"])

    for name in sdcard.REQUIRED_DIRS:
        has_content = any(rel.startswith(f"{name}/") for rel in copied)
        failures += 0 if has_content else 1
        rows.append([f"{name}/", "PASS" if has_content else "FAIL",
                     f"{sum(1 for r in copied if r.startswith(name + '/'))} files"])

    on_disk = {str(p.relative_to(template)).replace("\\", "/")
               for p in template.rglob("*") if p.is_file()}
    skipped = sorted(on_disk - copied)
    unexpected = [s for s in skipped if Path(s).name not in sdcard.SKIP_NAMES]
    failures += len(unexpected)
    rows.append([
        "template coverage",
        "PASS" if not unexpected else "FAIL",
        f"{len(copied)}/{len(on_disk)} copied, skipped: "
        + (", ".join(Path(s).name for s in skipped) or "nothing"),
    ])

    c.table(["item", "result", "notes"], rows)
    if unexpected:
        for name in unexpected:
            c.error(f"template file not covered by the copy plan: {name}")
    return failures


def cmd_selftest(args) -> int:
    c.heading("nomad-setup self-test")
    c.info("Nothing here touches a disk or a board.")

    failures = (run_fat32_tests() + run_chip_probe_tests()
                + run_preflight_tests() + run_diagnosis_tests()
                + run_picker_tests() + run_port_tests()
                + run_template_tests())

    c.heading("Result")
    if failures:
        c.error(f"{failures} check(s) failed")
        return 1
    c.ok("All checks passed")
    if not shutil.which("fsck.vfat"):
        c.info("Install dosfstools for a stronger filesystem check.")
    if not shutil.which("mcopy"):
        c.info("Install mtools to also verify a file round-trip.")
    return 0
