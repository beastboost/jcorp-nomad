"""esptool discovery, chip interrogation, and flashing.

The flash step never invents offsets. arduino-cli writes a `flash_args` file
next to the build output listing the exact flash options and every
offset/binary pair, and that file is what gets executed. The only thing this
module adds on top is a set of checks that refuse to write a firmware the chip
cannot actually run - wrong flash size, or an app bigger than the partition it
is being written into.
"""

from __future__ import annotations

import glob
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

from . import boards
from . import console as c

DEFAULT_BAUD = 921600


class EspError(RuntimeError):
    pass


# ------------------------------------------------------------- discovery --


@dataclass
class EspTool:
    command: List[str]
    version: str

    @property
    def major(self) -> int:
        m = re.match(r"v?(\d+)", self.version)
        return int(m.group(1)) if m else 4

    def sub(self, name: str) -> str:
        """esptool v5 renamed every subcommand from snake_case to kebab-case."""
        return name.replace("_", "-") if self.major >= 5 else name

    def run(self, args: List[str], dry_run=False, stream=False, timeout=600):
        cmd = self.command + args
        if dry_run:
            c.info(c.dim("[dry-run] " + " ".join(cmd)))
            return subprocess.CompletedProcess(cmd, 0, "", "")
        c.debug("$ " + " ".join(cmd))
        if stream:
            proc = subprocess.run(cmd, text=True, encoding="utf-8", errors="replace", timeout=timeout)
            return proc
        return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)


def _python_script_dirs() -> List[Path]:
    """Where pip drops console scripts. On Windows these are routinely not on
    PATH, which is why "pip install esptool" can succeed and esptool still be
    invisible to shutil.which()."""
    import site
    import sysconfig

    dirs: List[Path] = []

    def add(value):
        if value:
            dirs.append(Path(value))

    add(sysconfig.get_path("scripts"))
    try:
        add(sysconfig.get_path("scripts", f"{os.name}_user"))
    except (KeyError, ValueError):
        pass
    try:
        base = site.getuserbase()
        add(Path(base) / ("Scripts" if os.name == "nt" else "bin"))
    except AttributeError:
        pass

    if os.name == "nt":
        appdata = os.environ.get("APPDATA")
        localapp = os.environ.get("LOCALAPPDATA")
        tag = f"Python{sys.version_info.major}{sys.version_info.minor}"
        if appdata:
            dirs.append(Path(appdata) / "Python" / tag / "Scripts")
        if localapp:
            dirs.append(Path(localapp) / "Programs" / "Python" / tag / "Scripts")
    return dirs


def find_esptool(explicit: Optional[str] = None,
                 arduino_data_dir: Optional[Path] = None) -> EspTool:
    candidates: List[List[str]] = []
    looked: List[str] = []   # everything tried, so a failure can say where

    def consider(cmd: List[str], note: str = "") -> None:
        candidates.append(cmd)
        looked.append(" ".join(cmd) + (f"   ({note})" if note else ""))

    if explicit:
        consider([explicit], "--esptool")

    # The copy bundled with the installed ESP32 core is always the right version
    # for the core that produced the binaries, so prefer it.
    search_roots = []
    if arduino_data_dir:
        search_roots.append(Path(arduino_data_dir))
    search_roots += [Path.home() / ".arduino15",
                     Path.home() / "Library" / "Arduino15"]
    for var in ("LOCALAPPDATA", "APPDATA"):
        base = os.environ.get(var)
        if base:                      # empty on non-Windows; skip rather than
            search_roots.append(Path(base) / "Arduino15")   # build a relative path

    seen_roots = set()
    for root in search_roots:
        if not root.is_absolute() or str(root) in seen_roots:
            continue
        seen_roots.add(str(root))
        pattern = str(root / "packages" / "esp32" / "tools" / "esptool_py" / "*" / "esptool*")
        hits = sorted(glob.glob(pattern), reverse=True)
        if not hits:
            looked.append(f"{pattern}   (ESP32 core bundle)")
        for path in hits:
            if os.path.isfile(path):
                consider([path], "ESP32 core bundle")

    # As a module, under this interpreter and any other Python we can find. A
    # pip install may well have landed in a different one.
    consider([sys.executable, "-m", "esptool"], "this interpreter")
    for launcher in (["py", "-3"], ["python"], ["python3"]):
        exe = shutil.which(launcher[0])
        if exe:
            consider([exe] + launcher[1:] + ["-m", "esptool"], "other interpreter")

    # Console scripts, on PATH and in the script directories pip actually uses.
    for name in ("esptool", "esptool.py", "esptool.exe"):
        found = shutil.which(name)
        if found:
            consider([found], "on PATH")
    for directory in _python_script_dirs():
        for name in ("esptool.exe", "esptool", "esptool.py"):
            path = directory / name
            if path.is_file():
                consider([str(path)], "pip scripts dir")
        looked.append(f"{directory}   (pip scripts dir)")

    for cmd in candidates:
        try:
            proc = subprocess.run(cmd + ["version"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
            if proc.returncode != 0:
                proc = subprocess.run(cmd + ["--version"], capture_output=True, text=True, encoding="utf-8", errors="replace",
                                      timeout=60)
            if proc.returncode == 0:
                out = (proc.stdout or proc.stderr or "").strip().splitlines()
                version = ""
                for line in out:
                    m = re.search(r"v?(\d+\.\d+[\.\w]*)", line)
                    if m:
                        version = m.group(1)
                        break
                return EspTool(cmd, version or "unknown")
        except (OSError, subprocess.SubprocessError):
            continue

    tried = "\n".join(f"    {entry}" for entry in looked) or "    (nothing)"
    invocation = ".\\nomad-setup.bat" if os.name == "nt" else "nomad-setup"
    hint = (f'"{sys.executable}" -m pip install esptool'
            if os.name == "nt" else f"{sys.executable} -m pip install esptool")
    raise EspError(
        "esptool not found.\n\n"
        "  Looked in:\n" + tried + "\n\n"
        "  If it is installed, it is under a different Python than the one\n"
        "  running this tool. Installing it into this one always works:\n\n"
        f"      {hint}\n\n"
        "  Or point straight at it:  --esptool C:\\path\\to\\esptool.exe\n\n"
        "  Easiest of all, if arduino-cli is installed: the ESP32 core ships an\n"
        "  esptool, and this fetches it along with everything needed to build:\n\n"
        f"      {invocation} flash --install-deps"
    )


# A board that identifies itself over USB should not be something you are asked
# to find in a list. 0x303A is Espressif's own VID, used by the S3's native
# USB-CDC - which is what this dongle enumerates as. The rest are the USB-UART
# bridges soldered to dev boards; they say "an ESP is probably behind this", not
# "this is an ESP", so they rank lower.
ESPRESSIF_VID = 0x303A
BRIDGE_VIDS = {
    0x10C4: "Silicon Labs CP210x",
    0x1A86: "WCH CH340/CH9102",
    0x0403: "FTDI",
    0x067B: "Prolific PL2303",
}

KIND_NATIVE = "esp32"
KIND_BRIDGE = "usb-serial"
KIND_OTHER = "other"


@dataclass
class SerialPort:
    device: str
    description: str = ""
    vid: Optional[int] = None
    pid: Optional[int] = None

    @property
    def kind(self) -> str:
        if self.vid == ESPRESSIF_VID:
            return KIND_NATIVE
        if self.vid in BRIDGE_VIDS:
            return KIND_BRIDGE
        return KIND_OTHER

    @property
    def note(self) -> str:
        if self.kind == KIND_NATIVE:
            return "ESP32 (Espressif USB)"
        if self.kind == KIND_BRIDGE:
            return BRIDGE_VIDS.get(self.vid or 0, "USB-serial bridge")
        return self.description

    @property
    def label(self) -> str:
        bits = [self.device]
        note = self.note or self.description
        if note:
            bits.append(note)
        return "  ".join(bits)


def _sysfs_ids(device: str) -> Tuple[Optional[int], Optional[int]]:
    name = os.path.basename(device)
    base = Path("/sys/class/tty") / name / "device"
    for _ in range(4):                      # walk up to the USB device node
        try:
            vid = (base / "idVendor").read_text().strip()
            pid = (base / "idProduct").read_text().strip()
            return int(vid, 16), int(pid, 16)
        except Exception:
            base = base / ".."
    return None, None


_WIN_PORT_RE = re.compile(r"\((COM\d+)\)")
_WIN_VIDPID_RE = re.compile(r"VID_([0-9A-F]{4})&PID_([0-9A-F]{4})", re.I)


def _windows_ports() -> List[SerialPort]:
    """No pyserial: ask Windows itself. GetPortNames() returns bare names with
    no identity, which is what left people picking COM ports by hand."""
    script = (
        "Get-CimInstance Win32_PnPEntity | "
        "Where-Object { $_.Name -match '\\(COM\\d+\\)' } | "
        "ForEach-Object { \"$($_.Name)|$($_.DeviceID)\" }"
    )
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
        )
    except Exception:
        return []

    found: List[SerialPort] = []
    for line in (proc.stdout or "").splitlines():
        line = line.strip()
        if not line:
            continue
        name, _, device_id = line.partition("|")
        m = _WIN_PORT_RE.search(name)
        if not m:
            continue
        vid = pid = None
        ids = _WIN_VIDPID_RE.search(device_id)
        if ids:
            vid, pid = int(ids.group(1), 16), int(ids.group(2), 16)
        desc = _WIN_PORT_RE.sub("", name).strip()
        found.append(SerialPort(m.group(1), desc, vid, pid))

    if found:
        return found
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "[System.IO.Ports.SerialPort]::GetPortNames()"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
        )
        return [SerialPort(p.strip()) for p in (proc.stdout or "").split() if p.strip()]
    except Exception:
        return []


def list_serial_ports_detailed() -> List[SerialPort]:
    try:
        from serial.tools import list_ports  # type: ignore

        out = [SerialPort(p.device, (p.description or "").strip(), p.vid, p.pid)
               for p in list_ports.comports()]
        if out:
            return out
    except Exception:
        pass

    if sys.platform == "win32":
        return _windows_ports()

    patterns = (["/dev/cu.usbmodem*", "/dev/cu.usbserial*", "/dev/cu.wchusbserial*"]
                if sys.platform == "darwin"
                else ["/dev/ttyACM*", "/dev/ttyUSB*"])
    found: List[SerialPort] = []
    for pattern in patterns:
        for dev in sorted(glob.glob(pattern)):
            vid, pid = (_sysfs_ids(dev) if sys.platform != "darwin" else (None, None))
            found.append(SerialPort(dev, "", vid, pid))
    return found


def list_serial_ports() -> List[Tuple[str, str]]:
    """[(device, description)] - kept for callers that only want the names."""
    return [(p.device, p.description) for p in list_serial_ports_detailed()]


def autodetect_port(ports: List[SerialPort]) -> Tuple[Optional[SerialPort], str]:
    """Pick the board without asking, when the answer is not in doubt.

    Returns (port, why). A None port means it is genuinely ambiguous and the
    user has to choose - never a guess between two equally likely boards.
    """
    native = [p for p in ports if p.kind == KIND_NATIVE]
    if len(native) == 1:
        return native[0], "the only Espressif USB device connected"
    if len(native) > 1:
        return None, f"{len(native)} Espressif devices are connected"

    bridge = [p for p in ports if p.kind == KIND_BRIDGE]
    if len(bridge) == 1 and not native:
        return bridge[0], f"the only {bridge[0].note} adapter connected"
    if len(bridge) > 1:
        return None, f"{len(bridge)} USB-serial adapters are connected"

    if len(ports) == 1:
        return ports[0], "the only serial port on the system"
    return None, "no port identifies itself as an ESP32"


def recheck_port(port: str, explicit: bool = False) -> Tuple[str, str]:
    """Confirm `port` is still there, just before writing to it.

    COM numbers are not stable. A build takes minutes, and an ESP32-S3 that
    gets replugged or bounced into download mode in that window comes back on a
    different number - so the port picked before the compile can be gone by the
    time we flash. Returns (port to use, note); the note is empty when nothing
    moved.
    """
    ports = list_serial_ports_detailed()
    if not ports:
        return port, ""                       # nothing to check against
    if any(p.device == port for p in ports):
        return port, ""
    if explicit:
        return port, ""                       # the user named it; do not override

    found, why = autodetect_port(ports)
    if found is None:
        return port, ""
    return found.device, (f"{port} is gone - the board is on {found.device} now "
                          f"({why}). COM numbers move when a board re-enumerates.")


# ------------------------------------------------------------ chip probe --


@dataclass
class ChipInfo:
    chip: str = ""            # "" means we could not tell, not "no chip"
    flash_mb: int = 0
    psram_mb: int = 0
    mac: str = ""
    features: str = ""
    raw: str = ""

    @property
    def label(self) -> str:
        return self.chip or "chip type not reported"


_FLASH_RE = re.compile(r"[Dd]etected flash size:\s*(\d+)\s*MB")
_MAC_RE = re.compile(r"MAC:\s*([0-9a-fA-F:]+)")
_FEATURES_RE = re.compile(r"Features:\s*(.+)")
_PSRAM_RE = re.compile(r"PSRAM\s*(\d+)\s*MB", re.IGNORECASE)

# esptool renamed its chip banner in 5.0. 4.x printed one line:
#     Chip is ESP32-S3 (revision v0.2)
# 5.x prints two, and neither says "Chip is":
#     Connected to ESP32-S3 on COM6:
#     Chip type:          ESP32-S3 (QFN56) (revision v0.2)
# Everything else we read - flash size, Features, MAC - kept its wording, so a
# 5.x probe used to come back fully populated except for the chip name.
_CHIP_RES = (
    re.compile(r"Chip is\s+(\S+)"),                 # esptool 4.x
    re.compile(r"Chip type:\s*(\S+)"),              # esptool 5.x
    re.compile(r"Connected to\s+(ESP\S*)\s+on\b"),  # esptool 5.x banner
)


def parse_chip_output(out: str) -> ChipInfo:
    """Pull what we can out of an esptool banner. Split out from probe_chip so
    the self-test can check it against real output without a board attached."""
    info = ChipInfo(raw=out)
    for pattern in _CHIP_RES:
        m = pattern.search(out)
        if m:
            info.chip = m.group(1).rstrip(",")
            break
    m = _FLASH_RE.search(out)
    if m:
        info.flash_mb = int(m.group(1))
    m = _MAC_RE.search(out)
    if m:
        info.mac = m.group(1)
    m = _FEATURES_RE.search(out)
    if m:
        info.features = m.group(1).strip()
        p = _PSRAM_RE.search(info.features)
        if p:
            info.psram_mb = int(p.group(1))
    return info


def probe_chip(tool: EspTool, port: str, baud: int = 115200) -> ChipInfo:
    proc = tool.run(["--port", port, "--baud", str(baud), tool.sub("flash_id")], timeout=120)
    out = (proc.stdout or "") + (proc.stderr or "")

    if proc.returncode != 0:
        raise EspError(
            f"Could not talk to the board on {port}.\n"
            "  - Is it plugged in and not held open by a serial monitor?\n"
            "  - These sticks have no reset button: hold the boot button while\n"
            "    plugging it in to force download mode, then try again.\n\n"
            + out.strip()
        )

    return parse_chip_output(out)


# ------------------------------------------------------------ flash plan --


@dataclass
class FlashPlan:
    directory: Path
    options: List[str]                       # --flash-mode dio --flash-freq 80m ...
    entries: List[Tuple[int, Path]] = field(default_factory=list)  # (offset, file)
    flash_size_mb: int = 0

    def total_bytes(self) -> int:
        return sum(p.stat().st_size for _, p in self.entries if p.is_file())

    def highest_end(self) -> int:
        return max((off + p.stat().st_size for off, p in self.entries if p.is_file()),
                   default=0)


def load_flash_plan(directory: Path) -> FlashPlan:
    """Parse the `flash_args` file arduino-cli leaves beside the binaries."""
    directory = Path(directory)
    args_file = directory / "flash_args"
    if not args_file.is_file():
        raise EspError(
            f"No flash_args in {directory}.\n"
            "Point --firmware at an arduino-cli build output directory "
            "(build/esp32.esp32.esp32s3), or let the tool build the firmware."
        )

    lines = [ln.strip() for ln in args_file.read_text().splitlines() if ln.strip()]
    if not lines:
        raise EspError(f"{args_file} is empty")

    options = lines[0].split()
    plan = FlashPlan(directory=directory, options=options)

    m = re.search(r"--flash[-_]size\s+(\d+)MB", lines[0])
    if m:
        plan.flash_size_mb = int(m.group(1))

    for line in lines[1:]:
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        offset_text, filename = parts
        filename = filename.strip().strip('"')
        path = directory / filename
        if not path.is_file():
            raise EspError(f"{filename} listed in flash_args but missing from {directory}")
        plan.entries.append((int(offset_text, 0), path))

    if not plan.entries:
        raise EspError(f"{args_file} lists no binaries to write")
    return plan


@dataclass
class PreflightResult:
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    app_size: int = 0
    app_partition: Optional[boards.Partition] = None

    @property
    def ok(self) -> bool:
        return not self.errors


def preflight(plan: FlashPlan, chip: Optional[ChipInfo],
              board: Optional["boards.Board"] = None) -> PreflightResult:
    """Refuse combinations that would produce a board that does not boot."""
    result = PreflightResult()

    # Which entry is the partition table, and which is the app?
    part_blob: Optional[bytes] = None
    app_path: Optional[Path] = None
    for offset, path in plan.entries:
        if offset == 0x8000:
            part_blob = path.read_bytes()
        elif offset == 0x10000 or path.name.endswith(".ino.bin"):
            app_path = path

    if app_path:
        result.app_size = app_path.stat().st_size

    if part_blob:
        table = boards.parse_partition_table(part_blob)
        app_part = boards.first_app_partition(table)
        result.app_partition = app_part
        if app_part and result.app_size:
            if result.app_size > app_part.size:
                result.errors.append(
                    f"Firmware is {c.human_bytes(result.app_size)} but the "
                    f"'{app_part.label}' partition is only "
                    f"{c.human_bytes(app_part.size)}. Rebuild with a larger "
                    "partition scheme - the tool picks one automatically from "
                    "the detected flash size."
                )
            elif result.app_size > app_part.size * 0.9:
                result.warnings.append(
                    f"Firmware fills {result.app_size * 100 // app_part.size}% of "
                    f"the '{app_part.label}' partition."
                )
        if table:
            table_end = max(p.end for p in table)
            if chip and chip.flash_mb and table_end > chip.flash_mb * 1024 * 1024:
                result.errors.append(
                    f"The partition table needs {c.human_bytes(table_end)} of flash "
                    f"but the chip reports {chip.flash_mb} MB."
                )
    else:
        result.warnings.append("No partition table at 0x8000 in this build - not verified.")

    if chip and chip.flash_mb and plan.flash_size_mb:
        if plan.flash_size_mb > chip.flash_mb:
            result.errors.append(
                f"Firmware was built for {plan.flash_size_mb} MB of flash but the "
                f"chip has {chip.flash_mb} MB."
            )
        elif plan.flash_size_mb < chip.flash_mb:
            result.warnings.append(
                f"Firmware was built for {plan.flash_size_mb} MB of flash; the chip "
                f"has {chip.flash_mb} MB, so the extra space will go unused."
            )

    # Only block on a chip we positively identified as something else. Failing
    # to parse a name is a problem with our regexes, not evidence of the wrong
    # board, and it must not stand between a correct board and a flash.
    want = (board.chip_match if board else "S3").upper()
    want_name = board.chip_name if board else "ESP32-S3"
    if chip:
        name = chip.chip.strip().upper()
        if name and name != "UNKNOWN":
            if want not in name:
                result.errors.append(
                    f"This build is for the {want_name}; the board reports "
                    f"'{chip.chip}'. Pass --board to match the hardware."
                )
        else:
            result.warnings.append(
                f"Could not read the chip type from esptool's output, so the "
                f"{want_name} check was skipped. Flash size and PSRAM did read "
                "back, so the board is talking - run with --verbose for the raw "
                "output."
            )

    if chip and chip.flash_mb and chip.psram_mb == 0:
        result.warnings.append(
            "The chip did not report any PSRAM. On an N16R8 that usually means "
            "the module is a different variant - the firmware still runs, but "
            "check the board menu if the display misbehaves."
        )

    return result


def flash(tool: EspTool, plan: FlashPlan, port: str, baud: int = DEFAULT_BAUD,
          erase_all: bool = False, dry_run: bool = False) -> None:
    args = [
        "--chip", "esp32s3",
        "--port", port,
        "--baud", str(baud),
        "--before", tool.sub("default_reset"),
        "--after", tool.sub("hard_reset"),
        tool.sub("write_flash"),
    ]
    if erase_all:
        args.append("--erase-all")
    args += ["-z"]
    args += plan.options
    for offset, path in plan.entries:
        args += [hex(offset), str(path)]

    proc = tool.run(args, dry_run=dry_run, stream=True, timeout=1800)
    if not dry_run and proc.returncode != 0:
        raise EspError(
            "esptool failed to write the firmware. If it could not enter the "
            "bootloader, unplug the stick, hold the boot button, plug it back "
            "in, and run the flash step again."
        )


def erase_flash(tool: EspTool, port: str, baud: int = DEFAULT_BAUD, dry_run: bool = False) -> None:
    proc = tool.run(
        ["--chip", "esp32s3", "--port", port, "--baud", str(baud), tool.sub("erase_flash")],
        dry_run=dry_run, stream=True, timeout=900,
    )
    if not dry_run and proc.returncode != 0:
        raise EspError("esptool could not erase the flash")
