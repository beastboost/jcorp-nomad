# Porting Nomad to the ESP32-P4 (Guition JC-ESP32P4-M3-DEV)

Status: **groundwork only.** Nothing here has run on hardware. The board profile
builds and the probe sketch exists; the port itself is not started, deliberately,
because one unknown decides whether it is worth doing at all.

---

## Why this board is interesting

| | S3 dongle | P4 dev board |
| --- | --- | --- |
| CPU | 240 MHz Xtensa dual | 360–400 MHz RISC-V dual |
| PSRAM | 8 MB octal | **32 MB** |
| Flash | 16 MB | 16 MB |
| SD | plain SPI, ~20 MHz | **4-bit SDIO** |
| USB | 1.1 full-speed | **2.0 high-speed OTG + a second host port** |
| Ethernet | none | 100M (IP101 PHY) |
| Wi-Fi | native | **none — see below** |
| Screen | 0.96" SPI | none fitted (MIPI-DSI connector) |

The SD bus alone is the strongest argument. The dongle streams video off a card
running plain SPI; 4-bit SDIO is a different class of thing. The USB host port is
what you were really after — an external drive would lift the storage ceiling
completely.

## The one thing that decides it

**The ESP32-P4 has no radio.** Wi-Fi comes from the on-board ESP32-C6 over
SDIO, using ESP-Hosted. Nomad is a captive portal and nothing else — every
feature is reached through `WiFi.softAP()`, `DNSServer`, `AsyncWebServer`, and
`WiFi.softAPgetStationNum()`. If SoftAP over the hosted link is not solid, there
is no Nomad on this board, and no amount of porting changes that.

What is known:

* The Arduino WiFi library **does** compile for the P4 — it is gated on
  `SOC_WIFI_SUPPORTED || CONFIG_ESP_HOSTED_ENABLED`, and the P4 takes the second
  branch.
* ESP-Hosted's protocol **does** carry SoftAP frames (`ESP_AP_IF`), so it is not
  station-only by design.
* P4 support has been in the Arduino core since 3.1.0 (ESP-IDF 5.3).

What is not known, and cannot be settled from a desk:

* Whether SoftAP over hosted is *reliable*. Association problems on P4+C6 over
  SDIO are actively reported, e.g.
  [esphome/esphome#10956](https://github.com/esphome/esphome/issues/10956).
* Whether the C6's pre-flashed slave firmware matches what a current Arduino core
  expects. Boards ship ESP-Hosted slave **v0.0.6**; newer cores want newer, and
  the mismatch is reported as a version warning followed by a link that does not
  work. Fixing it means flashing the C6 separately, through its own USB port.
* This board's **SD pin map**. It is not in any datasheet I could verify.

So: probe first, port second.

## Run this first

```
nomad-setup flash --board p4-dev --sketch firmware/NomadP4Probe
```

Serial monitor at 115200. `NomadP4Probe` exercises the exact stack Nomad needs
and nothing else:

1. Chip, flash, PSRAM — is the 32 MB actually visible?
2. The C6 hosted link — does `WiFi.mode()` take, and is the MAC real?
3. `WiFi.softAP()` with Nomad's own arguments — **the decisive step**
4. `DNSServer` + `AsyncWebServer` on port 80, serving a real page
5. microSD over SDMMC, sweeping candidate pin sets
6. A live client counter — connect a phone and watch it register

It prints a verdict at the end. Step 5 sweeps rather than assumes: the S3 port
started with a guessed pin map that was wrong on every pin, and that is not a
mistake worth repeating.

## What the port looks like, once the probe passes

**Run it headless.** No panel is fitted, and that is a feature — the display
layer was the bulk of the S3 port (`Display_Driver`, LVGL, SquareLine UI,
`ui_screen_mini.c`), and on this board all of it drops out. Nomad's screen only
ever showed the SSID, the IP and a client count, all of which the web UI already
has. A fourth `NOMAD_LCD_NONE` profile is much less work than a DSI driver.

Ordered by effort, smallest first:

1. **`board_config.h` profile** — `NOMAD_BOARD_P4_DEV 4`, SD pins from the
   probe, `NOMAD_SD_BUS_SDMMC`, no LCD, no LED.
2. **Compile-guard the display** — `#if NOMAD_HAS_DISPLAY` around the LVGL init,
   the tick handler and the `NomadUI_*` calls. They are already funnelled through
   a small set of functions, so this is narrow.
3. **Check the RISC-V build** — the S3 code is plain C++ and should port, but
   LVGL ships Xtensa assembly optimisations that must be off.
4. **USB mass-storage mode** — the S3 exposes the card over TinyUSB when you hold
   the button. On the P4 with hwcdc this needs rechecking, and the board has no
   equivalent button.
5. **USB host / external drive** — the interesting one, and the least ready.
   The P4 has the hardware, but reading a USB drive needs the ESP-IDF USB host
   MSC class, which the Arduino core does not usefully expose today. Treat it as
   a research task, not a port task.

Ethernet is a free bonus worth taking later: a Nomad that can also sit on a wired
LAN is genuinely more useful than one that cannot.

## What exists now

* `firmware/NomadP4Probe/NomadP4Probe.ino` — the probe described above
* `tools/nomad_setup/boards.py` — `p4-dev` profile, FQBN
  `esp32:esp32:esp32p4` with `PSRAM=enabled` (the P4 has no opi/qspi choice) and
  `app3M_fat9M_16MB`
* The pre-flash check is no longer hardcoded to the S3. It takes the expected
  chip from the board profile, so an S3 build cannot be written to a P4 or the
  reverse — different ISAs, and the failure would be baffling.

Not written: any `board_config.h` entry. That waits for the probe to report real
pins.
