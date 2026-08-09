"""nomad-setup - prepare an SD card and flash the Jcorp Nomad firmware.

Run with no arguments for a guided setup, or use the subcommands for scripting.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional

from . import boards, build, console as c, disks, esp, sdcard, selftest

VERSION = "1.0.0"


def _cli_name() -> str:
    r"""How to invoke this tool on the current platform, for use in messages.
    PowerShell will not run a script from the working directory without the
    leading .\ , and telling people to type a command that then fails is worse
    than saying nothing."""
    return ".\\nomad-setup.bat" if sys.platform == "win32" else "nomad-setup"

if sys.version_info < (3, 8):  # pragma: no cover - guard for old interpreters
    sys.exit(
        f"nomad-setup needs Python 3.8 or newer; this is "
        f"{sys.version_info.major}.{sys.version_info.minor}."
    )


# ============================================================== SD card ====


def _pick_disk(args) -> disks.Disk:
    found = disks.list_disks(include_fixed=args.allow_fixed)

    if not found:
        raise disks.DiskError(
            "No removable disks found.\n"
            "  - Insert the microSD card (in a reader, or in the Nomad stick "
            "booted into USB mass-storage mode by holding its button).\n"
            "  - Pass --allow-fixed if your reader reports the card as a fixed disk."
        )

    if args.disk:
        wanted = args.disk.rstrip("/\\")
        for d in found:
            # Accept "/dev/sdb", "sdb", the raw node, or a bare Windows number.
            short = d.identifier[5:] if d.identifier.startswith("/dev/") else d.identifier
            if wanted in (d.identifier, d.raw_path, short):
                return d
        raise disks.DiskError(
            f"{args.disk} is not in the list of available disks. "
            f"Run '{_cli_name()} list-disks' to see them."
        )

    options = [(d, d.summary()) for d in found]
    chosen = c.choose("Which disk is the SD card?", options)
    if chosen is None:
        raise disks.DiskError("No disk selected")
    return chosen


def _check_mount_target(path: str) -> None:
    """--mount bypasses every disk safety check, so sanity-check it here."""
    import os

    target = Path(path).resolve()
    if not target.is_dir():
        raise sdcard.SdCardError(f"{path} is not a directory")

    forbidden = {Path("/"), Path.home().resolve()}
    if os.name == "nt":
        forbidden.add(Path(os.environ.get("SystemDrive", "C:") + "\\").resolve())
    if target in forbidden:
        raise sdcard.SdCardError(
            f"Refusing to write the SD card layout into {target}. "
            "Point --mount at the mounted card, not a system directory."
        )
    if not os.access(target, os.W_OK):
        raise sdcard.SdCardError(f"{target} is not writable")


def cmd_sdcard(args) -> int:
    c.heading("SD card")

    template = Path(args.template) if args.template else sdcard.find_template()
    c.ok(f"Template: {template}")

    plan = sdcard.plan_copy(template, include_placeholders=not args.no_placeholders)
    c.info(f"{plan.count} files, {c.human_bytes(plan.total_bytes)}"
           + (f" ({plan.skipped_placeholders} placeholder files skipped)"
              if plan.skipped_placeholders else ""))

    # --mount skips all disk handling and writes into a card that is already
    # mounted, which is also the escape hatch if the disk layer misreads a
    # particular reader.
    if args.mount:
        mount_path = args.mount
        disk = None
        _check_mount_target(mount_path)
        c.warn(f"Writing into {mount_path} without formatting")
    else:
        disk = _pick_disk(args)

        c.heading("Target")
        print()
        print(f"    {c.bold(disk.identifier)}  {c.human_bytes(disk.size)}")
        print(f"    {disk.description}")
        if disk.mountpoints:
            print(f"    currently mounted at: {', '.join(disk.mountpoints)}")
        if not disk.removable:
            c.warn("This disk is NOT removable. Be certain before continuing.")

        if args.no_format:
            if not disk.mountpoints:
                raise disks.DiskError(
                    "--no-format needs the card already mounted; none found. "
                    "Mount it and pass --mount <path>, or drop --no-format."
                )
            mount_path = disk.mountpoints[0]
            c.info(f"Keeping the existing filesystem at {mount_path}")
        else:
            print()
            print(c.red("    Everything on this disk will be erased."))
            if not c.confirm_destructive(
                    f"Erase {disk.identifier} and format it as FAT32?", "ERASE"):
                c.info("Cancelled.")
                return 1

            c.heading("Formatting")
            mount_path = disks.prepare_card(disk, args.label, dry_run=args.dry_run)
            c.ok(f"FAT32 card mounted at {mount_path}")

    c.heading("Copying files")
    written, problems = sdcard.copy_to_card(
        plan, mount_path, dry_run=args.dry_run, verify=not args.no_verify
    )
    c.ok(f"Wrote {c.human_bytes(written)} in {plan.count} files")
    c.info("Created: " + ", ".join(sdcard.MEDIA_DIRS))

    # Confirm the card now holds everything the firmware serves by name, rather
    # than trusting that the copy loop covered it.
    if not args.dry_run:
        missing, optional = sdcard.check_card_contents(mount_path)
        if missing:
            problems += [f"missing from the finished card: {m}" for m in missing]
        else:
            c.ok(f"All {len(sdcard.REQUIRED_FILES)} files the firmware serves are present")
        for note in optional:
            c.debug(f"not shipped: {note}")

    if problems:
        c.heading("Problems")
        for p in problems[:20]:
            c.error(p)
        if len(problems) > 20:
            c.error(f"... and {len(problems) - 20} more")
        return 1

    if disk and not args.keep_mounted:
        disks.flush_and_eject(mount_path, disk, dry_run=args.dry_run)

    c.heading("SD card ready")
    c.info("Put your own media into Movies / Shows / Books / Music / Gallery / Files,")
    c.info("then run a Full Scan from the Nomad admin page once it boots.")
    return 0


# =============================================================== flash ====


def _pick_port(args) -> str:
    if args.port:
        return args.port
    ports = esp.list_serial_ports_detailed()
    if not ports and args.dry_run:
        c.warn("No serial port found; using a placeholder for the dry run")
        return "DRY-RUN-PORT"
    if not ports:
        raise esp.EspError(
            "No serial ports found.\n"
            "  These sticks have no reset button: unplug it, hold the boot "
            "button, plug it back in while holding, then re-run."
        )

    # The board says what it is over USB. Asking anyway is just make-work.
    found, why = esp.autodetect_port(ports)
    if found is not None:
        c.ok(f"Board on {found.device} - {why}")
        c.info(c.dim(f"Override with --port if that is wrong "
                     f"({', '.join(p.device for p in ports)})"))
        return found.device

    c.warn(f"Cannot tell which port is the board: {why}.")
    options = [(p.device, p.label) for p in ports]
    chosen = c.choose("Which serial port is the board on?", options)
    if not chosen:
        raise esp.EspError("No port selected")
    return chosen


def cmd_flash(args) -> int:
    board = boards.BOARDS[args.board]

    c.heading("Firmware")
    c.info(f"Board: {board.name}")

    cli = build.find_arduino_cli(args.arduino_cli)

    # ---- toolchain first ---------------------------------------------------
    # The ESP32 core ships an esptool, so installing it is often what makes
    # esptool exist at all. Looking for esptool before this point made
    # --install-deps impossible to run: the command that fixes the problem
    # would abort on the problem it was meant to fix.
    sketch = None
    if not args.firmware:
        if not cli:
            raise build.BuildError("arduino-cli not found.\n  " + build.install_hint())
        c.ok(f"arduino-cli {cli.version}")

        c.heading("Toolchain")
        build.ensure_core(cli, install=args.install_deps, dry_run=args.dry_run)
        build.ensure_libraries(cli, install=args.install_deps, dry_run=args.dry_run)

        sketch = Path(args.sketch) if args.sketch else build.find_sketch()
        build.ensure_lv_conf(cli, sketch, dry_run=args.dry_run)

    # ---- now esptool, which the core install may just have provided --------
    try:
        tool = esp.find_esptool(args.esptool, cli.data_dir() if cli else None)
    except esp.EspError as exc:
        if cli and not args.install_deps:
            raise esp.EspError(
                str(exc) + "\n\n"
                f"  arduino-cli is installed, so this should fetch it:\n"
                f"      {_cli_name()} flash --install-deps"
            )
        raise
    c.ok(f"esptool {tool.version}")

    port = _pick_port(args)
    chip = None
    try:
        if args.dry_run and port == "DRY-RUN-PORT":
            raise esp.EspError("dry run: not probing the board")
        c.step(f"Probing the board on {port}")
        chip = esp.probe_chip(tool, port)
        c.ok(f"{chip.label}, {chip.flash_mb} MB flash"
             + (f", {chip.psram_mb} MB PSRAM" if chip.psram_mb else ", no PSRAM reported"))
        c.debug(chip.raw.strip())
        if chip.mac:
            c.info(f"MAC {chip.mac}")
    except esp.EspError as exc:
        if not (args.firmware or args.dry_run):
            raise
        c.warn(str(exc).splitlines()[0])
        if not args.dry_run:
            c.warn("Continuing with the supplied firmware; flash size unverified.")

    flash_mb = (chip.flash_mb if chip and chip.flash_mb else board.default_flash_mb)
    if not chip or not chip.flash_mb:
        c.warn(f"Assuming {flash_mb} MB of flash")

    # ---- where the binaries come from -----------------------------------
    if args.firmware:
        artifacts = Path(args.firmware)
        c.info(f"Using prebuilt firmware from {artifacts}")
    else:
        c.heading("Build")
        artifacts = build.compile_firmware(
            cli, board, flash_mb, sketch, dry_run=args.dry_run, clean=args.clean,
            extra_properties=args.build_property,
        )

    if args.dry_run and not args.firmware:
        c.info(c.dim("[dry-run] skipping flash verification and write"))
        return 0

    # ---- verify before writing -------------------------------------------
    c.heading("Checks")
    plan = esp.load_flash_plan(artifacts)
    result = esp.preflight(plan, chip)

    if result.app_partition and result.app_size:
        pct = result.app_size * 100 // result.app_partition.size
        c.info(f"Firmware {c.human_bytes(result.app_size)} into "
               f"'{result.app_partition.label}' "
               f"{c.human_bytes(result.app_partition.size)} ({pct}%)")
    for entry in plan.entries:
        c.debug(f"{hex(entry[0])}  {entry[1].name}")

    for w in result.warnings:
        c.warn(w)
    for e in result.errors:
        c.error(e)
    if not result.ok:
        c.error("Refusing to flash - fix the above first.")
        return 1
    c.ok("Partition layout and flash size check out")

    # ---- write ------------------------------------------------------------
    c.heading("Flashing")
    # The build took minutes. Re-check rather than trust a port number noted
    # before it started - they move whenever a board re-enumerates.
    if not args.dry_run:
        port, moved = esp.recheck_port(port, explicit=bool(args.port))
        if moved:
            c.warn(moved)

    if not args.yes and not c.confirm(f"Write the firmware to {port}?", default=True):
        c.info("Cancelled.")
        return 1

    if args.erase:
        c.step("Erasing the whole flash first")
        esp.erase_flash(tool, port, baud=args.baud, dry_run=args.dry_run)

    esp.flash(tool, plan, port, baud=args.baud, dry_run=args.dry_run)

    c.heading("Firmware flashed")
    c.info("The board reboots on its own. With a prepared card inserted it")
    c.info("brings up the Wi-Fi network shown on its screen.")
    return 0


# ============================================================== doctor ====


def cmd_doctor(args) -> int:
    state = {"cli": False, "core": False, "libs": False, "esptool": False,
             "ports": False, "disks": False, "elevated": False}

    c.heading("Environment")
    c.info(f"nomad-setup {VERSION}")
    c.info(f"Python {sys.version.split()[0]} on {sys.platform}")
    state["elevated"] = disks.is_privileged()
    c.info(f"Administrator/root: {'yes' if state['elevated'] else 'no'}")
    if not disks.is_privileged():
        c.warn(f"Formatting a card needs elevation. {disks.privilege_hint()}")

    c.heading("Repository")
    try:
        c.ok(f"SD template: {sdcard.find_template()}")
    except sdcard.SdCardError as exc:
        c.error(str(exc))
    try:
        c.ok(f"Sketch: {build.find_sketch()}")
    except build.BuildError as exc:
        c.error(str(exc))

    c.heading("Build tools")
    cli = build.find_arduino_cli(args.arduino_cli)
    if cli:
        state["cli"] = True
        c.ok(f"arduino-cli {cli.version} ({cli.path})")
        version = build.core_installed(cli)
        if version:
            state["core"] = True
            c.ok(f"esp32 core {version}")
        else:
            c.warn("esp32 core not installed (--install-deps will fetch it)")
        have = build.installed_libraries(cli)
        missing_libs = 0
        for name, want in build.REQUIRED_LIBRARIES:
            if name in have:
                c.ok(f"{name} {have[name]}")
            else:
                missing_libs += 1
                c.warn(f"{name} missing (wanted {want})")
        state["libs"] = missing_libs == 0
    else:
        c.warn("arduino-cli not found - you can still flash prebuilt binaries")
        c.info(build.install_hint())

    c.heading("Flash tools")
    try:
        tool = esp.find_esptool(args.esptool, cli.data_dir() if cli else None)
        state["esptool"] = True
        c.ok(f"esptool {tool.version} ({' '.join(tool.command)})")
    except esp.EspError as exc:
        c.error(str(exc))

    c.heading("Serial ports")
    ports = esp.list_serial_ports()
    state["ports"] = bool(ports)
    if ports:
        c.table(["port", "description"], [[d, desc] for d, desc in ports])
    else:
        c.info("none detected")

    # Show every disk, not just the ones we would offer, with the reason each is
    # or is not selectable. "nothing detected" on its own is useless when you
    # are looking straight at the card.
    c.heading("Disks")
    try:
        every = disks.list_disks(include_fixed=True)
        offered = {d.identifier for d in disks.list_disks(include_fixed=False)}
        if every:
            rows = []
            for d in every:
                if d.identifier in offered:
                    why = "offered"
                elif not d.removable:
                    why = "skipped: not removable (--allow-fixed to include)"
                else:
                    why = "skipped"
                rows.append([d.identifier, c.human_bytes(d.size), d.description[:34], why])
            c.table(["disk", "size", "model", "status"], rows)
        else:
            c.info("no disks reported at all")
        state["disks"] = bool(offered)
        if not offered:
            c.warn("No card is selectable. Things to check:")
            c.info("  - Is the microSD in a card reader that is plugged in?")
            c.info("  - The Nomad stick itself cannot show you the card until the")
            c.info("    firmware is flashed and it is booted into USB mass-storage")
            c.info("    mode, so use a reader for the first setup.")
            c.info("  - Some built-in readers report the card as a fixed disk;")
            c.info("    'nomad-setup list-disks --allow-fixed' will show it.")
    except disks.DiskError as exc:
        c.error(str(exc))

    _doctor_next_step(state)
    return 0


def _doctor_next_step(state: dict) -> None:
    """End with one concrete thing to do, rather than leaving the reader to
    work it out from the warnings above."""
    c.heading("Next step")

    if not state["cli"] and not state["esptool"]:
        c.info("You have neither build nor flash tools. Installing arduino-cli")
        c.info("solves both, because the ESP32 core it fetches bundles esptool:")
        print()
        c.info(f"    {c.bold(build.install_command())}")
        print()
        c.info("Then reopen your terminal so PATH updates, and run:")
        c.info(f"    {c.bold(_cli_name() + ' flash --install-deps')}")
        return

    if not state["cli"]:
        c.info("No arduino-cli, so the firmware cannot be built here. Either:")
        c.info(f"    {c.bold(build.install_command())}")
        c.info("or build in the Arduino IDE and flash what it produces:")
        c.info(f"    {c.bold(_cli_name() + ' flash --firmware <build output dir>')}")
        return

    if not state["esptool"]:
        c.info("arduino-cli is here but esptool is not. Installing the ESP32")
        c.info("core brings a copy along with everything else needed to build:")
        c.info(f"    {c.bold(_cli_name() + ' flash --install-deps')}")
        return

    if not (state["core"] and state["libs"]):
        c.info("Tools are in place; the ESP32 core or libraries still need")
        c.info("fetching. This is a one-off download of roughly a gigabyte:")
        c.info(f"    {c.bold(_cli_name() + ' flash --install-deps')}")
        return

    if not state["ports"]:
        c.info("Everything is installed, but no board is showing up. Plug the")
        c.info("stick in; if it still does not appear, unplug it, hold the boot")
        c.info("button, plug it back in while holding, then re-run.")
        return

    if not state["disks"]:
        c.info("Ready to flash the firmware:")
        c.info(f"    {c.bold(_cli_name() + ' flash')}")
        print()
        c.info("The card step needs a reader (the stick cannot expose its own")
        c.info("card until the firmware is on it). With one plugged in:")
        c.info(f"    {c.bold(_cli_name() + ' sdcard')}")
        if not state["elevated"]:
            c.info("    ...from an Administrator prompt - formatting needs elevation.")
        return

    c.ok("Everything is in place. Run the guided setup:")
    c.info(f"    {c.bold(_cli_name())}")
    if not state["elevated"]:
        c.warn("Use an Administrator prompt so the card step can format.")


def cmd_repair_core(args) -> int:
    """For when the board package installed but did not install correctly."""
    c.heading("Repairing the ESP32 board package")
    cli = build.find_arduino_cli(getattr(args, "arduino_cli", None))
    if not cli:
        c.error("arduino-cli not found.")
        c.info(build.install_hint())
        return 1
    c.ok(f"arduino-cli {cli.version}")

    current = build.core_installed(cli)
    c.info(f"Installed now: {current or 'none'}")
    version = args.core_version or (current or "")
    c.info("This removes the board package and its build caches, then downloads")
    c.info("it again - roughly a gigabyte. Nothing else on the system is touched.")
    if not (args.yes or c.confirm("Go ahead?", default=True)):
        c.info("Nothing changed.")
        return 0

    build.repair_core(cli, version=version, dry_run=args.dry_run)
    c.info(f"Now run: {c.bold(_cli_name() + ' flash')}")
    return 0


def cmd_list_disks(args) -> int:
    found = disks.list_disks(include_fixed=args.allow_fixed)
    if not found:
        c.info("No removable disks found.")
        return 0
    for d in found:
        c.info(d.summary())
    return 0


def cmd_list_ports(args) -> int:
    ports = esp.list_serial_ports_detailed()
    if not ports:
        c.info("No serial ports found.")
        return 0
    rows = []
    for p in ports:
        ids = f"{p.vid:04X}:{p.pid:04X}" if p.vid is not None and p.pid is not None else ""
        rows.append([p.device, p.kind, ids, p.note or p.description])
    c.table(["port", "kind", "usb id", "what it is"], rows)
    found, why = esp.autodetect_port(ports)
    if found is not None:
        c.ok(f"Would use {found.device} - {why}")
    else:
        c.info(f"Would ask: {why}")
    return 0


# ================================================================ all =====


def cmd_all(args) -> int:
    c.heading("Jcorp Nomad setup")
    c.info("Two steps: flash the firmware, then prepare the SD card.")
    c.info("Ctrl-C backs out at any point; nothing is written until you confirm.")

    if not args.skip_flash:
        rc = cmd_flash(args)
        if rc != 0:
            return rc
    else:
        c.info("Skipping the firmware step (--skip-flash)")

    if args.skip_sdcard:
        c.info("Skipping the SD card step (--skip-sdcard)")
        return 0

    c.heading("Next: the SD card")
    c.info("Put the card in a reader, or leave it in the stick and boot the")
    c.info("stick into USB mass-storage mode (hold the boot button while")
    c.info("plugging it in) so the card shows up as a removable drive.")
    print()
    if not c.confirm("Ready to prepare the card?", default=True):
        c.info("Stopping here. Run 'nomad-setup sdcard' when you are ready.")
        return 0

    return cmd_sdcard(args)


# ================================================================ CLI =====


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="nomad-setup",
        description="Prepare an SD card and flash the Jcorp Nomad firmware.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  nomad-setup                       guided setup, both steps\n"
            "  nomad-setup doctor                check the environment\n"
            "  nomad-setup sdcard --disk /dev/sdb\n"
            "  nomad-setup flash --port /dev/ttyACM0 --install-deps\n"
            "  nomad-setup flash --firmware firmware/JcorpNomadProject/build/esp32.esp32.esp32s3\n"
        ),
    )
    parser.add_argument("--version", action="version", version=f"nomad-setup {VERSION}")

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--board", choices=sorted(boards.BOARDS), default=boards.DEFAULT_BOARD,
                        help="target board (default: %(default)s)")
    common.add_argument("-v", "--verbose", action="store_true", help="show every command run")
    common.add_argument("-n", "--dry-run", action="store_true",
                        help="print what would happen without touching anything")
    common.add_argument("-y", "--yes", action="store_true",
                        help="accept ordinary prompts (erasing a disk still asks)")
    common.add_argument("--i-know-what-im-doing", dest="force_destructive", action="store_true",
                        help="with --yes, also skip the erase confirmation")
    common.add_argument("--arduino-cli", help="path to the arduino-cli binary")
    common.add_argument("--esptool", help="path to the esptool binary")
    common.add_argument("--allow-fixed", action="store_true",
                        help="also list non-removable disks (dangerous)")

    sd_opts = argparse.ArgumentParser(add_help=False)
    sd_opts.add_argument("--disk", help="disk to use, e.g. /dev/sdb, /dev/disk4, or 2 on Windows")
    sd_opts.add_argument("--label", default="NOMAD", help="volume label (default: %(default)s)")
    sd_opts.add_argument("--template", help="path to SD_Card_Template")
    sd_opts.add_argument("--mount", help="write into this already-mounted path, no formatting")
    sd_opts.add_argument("--no-format", action="store_true",
                         help="keep the existing filesystem, just copy the files")
    sd_opts.add_argument("--no-placeholders", action="store_true",
                         help="skip the demo media, copy only the web interface")
    sd_opts.add_argument("--no-verify", action="store_true",
                         help="skip the post-copy size check")
    sd_opts.add_argument("--keep-mounted", action="store_true",
                         help="leave the card mounted when finished")

    fw_opts = argparse.ArgumentParser(add_help=False)
    fw_opts.add_argument("--port", help="serial port of the board")
    fw_opts.add_argument("--baud", type=int, default=esp.DEFAULT_BAUD,
                         help="flash baud rate (default: %(default)s)")
    fw_opts.add_argument("--firmware", help="flash prebuilt binaries from this build directory")
    fw_opts.add_argument("--sketch", help="path to firmware/JcorpNomadProject")
    fw_opts.add_argument("--install-deps", action="store_true",
                         help="install the ESP32 core and libraries if missing")
    fw_opts.add_argument("--clean", action="store_true", help="force a full rebuild")
    fw_opts.add_argument("--erase", action="store_true",
                         help="erase the entire flash before writing")
    fw_opts.add_argument("--build-property", action="append", default=[], dest="build_property",
                         metavar="KEY=VALUE",
                         help="extra arduino-cli build property (repeatable)")

    sub = parser.add_subparsers(dest="command")

    p_all = sub.add_parser("all", parents=[common, sd_opts, fw_opts],
                           help="flash the firmware and prepare the card (default)")
    p_all.add_argument("--skip-flash", action="store_true")
    p_all.add_argument("--skip-sdcard", action="store_true")
    p_all.set_defaults(func=cmd_all)

    sub.add_parser("sdcard", parents=[common, sd_opts],
                   help="format an SD card and copy the Nomad files onto it"
                   ).set_defaults(func=cmd_sdcard)

    sub.add_parser("flash", parents=[common, fw_opts],
                   help="build (or take prebuilt) firmware and write it to the board"
                   ).set_defaults(func=cmd_flash)

    sub.add_parser("doctor", parents=[common],
                   help="report on tools, ports and disks without changing anything"
                   ).set_defaults(func=cmd_doctor)

    sub.add_parser("selftest", parents=[common],
                   help="verify the FAT32 formatter and the pre-flash checks offline"
                   ).set_defaults(func=selftest.cmd_selftest)

    p_repair = sub.add_parser(
        "repair-core", parents=[common],
        help="reinstall the ESP32 board package and clear the build caches")
    p_repair.add_argument("--core-version", default="",
                          help="pin a version, e.g. 3.3.11 (default: latest)")
    p_repair.set_defaults(func=cmd_repair_core)

    sub.add_parser("list-disks", parents=[common]).set_defaults(func=cmd_list_disks)
    sub.add_parser("list-ports", parents=[common]).set_defaults(func=cmd_list_ports)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()

    # No subcommand -> the guided path, which is what most people want.
    known = {"all", "sdcard", "flash", "doctor", "selftest", "repair-core",
             "list-disks", "list-ports"}
    if not argv or argv[0] not in known and argv[0] not in ("-h", "--help", "--version"):
        argv = ["all"] + argv

    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 0

    c.set_verbose(getattr(args, "verbose", False))
    c.set_assume_yes(getattr(args, "yes", False))
    c.set_force_destructive(getattr(args, "force_destructive", False))

    # Defaults for options a given subcommand does not define.
    for name, default in (
        ("skip_flash", False), ("skip_sdcard", False), ("disk", None), ("label", "NOMAD"),
        ("template", None), ("mount", None), ("no_format", False), ("no_placeholders", False),
        ("no_verify", False), ("keep_mounted", False), ("port", None),
        ("baud", esp.DEFAULT_BAUD), ("firmware", None), ("sketch", None),
        ("install_deps", False), ("clean", False), ("erase", False), ("allow_fixed", False),
        ("build_property", []),
    ):
        if not hasattr(args, name):
            setattr(args, name, default)

    try:
        return args.func(args)
    except KeyboardInterrupt:
        print()
        c.info("Interrupted.")
        return 130
    except (disks.DiskError, esp.EspError, build.BuildError, sdcard.SdCardError) as exc:
        print()
        c.error(str(exc))
        return 1


if __name__ == "__main__":
    sys.exit(main())
