# Porting Nomad to the ESP32-P4 (Guition JC-ESP32P4-M3-DEV)

Status: **confirmed working on hardware.** `NomadP4Probe` came up on a real
JC-ESP32P4-M3-DEV: SoftAP up, captive-portal stack serving, 32 MB PSRAM
visible, microSD mounted 4-bit, client counter tracking a connected phone.

```
Nomad P4 probe
The async web server works on this board.
  * PSRAM: 32 MB
  * SD: default pins, 4-bit
  * Clients: 1
```

That settles the one open question. Wi-Fi over the C6 hosted link works, and
**SoftAP specifically works** — which is all Nomad uses. The full firmware has
not been run yet, but nothing structural stands in its way.

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
| Wi-Fi | native | **none — via the on-module C6** |
| Screen | 0.96" SPI | none fitted (MIPI-DSI connector) |

The SD bus alone is the strongest argument. The dongle streams video off a card
running plain SPI; 4-bit SDIO is a different class of thing. The USB host port is
what you were really after — an external drive would lift the storage ceiling
completely.

## Wi-Fi comes from the C6

The P4 has no radio; the on-board ESP32-C6 provides it over SDIO using
ESP-Hosted. This is Espressif's designed and supported arrangement for the
part — the C6 ships pre-flashed and the Arduino core builds for it — so it is
not exotic, and it is not a reason to hold off porting.

The one thing to check early is that **SoftAP** specifically works, since Nomad
is a captive portal and nothing else: `WiFi.softAP()`, `DNSServer`,
`AsyncWebServer`, `WiFi.softAPgetStationNum()`. Station mode gets far more
testing than SoftAP does.

What is known:

* The Arduino WiFi library **does** compile for the P4 — it is gated on
  `SOC_WIFI_SUPPORTED || CONFIG_ESP_HOSTED_ENABLED`, and the P4 takes the second
  branch.
* ESP-Hosted's protocol **does** carry SoftAP frames (`ESP_AP_IF`), so it is not
  station-only by design.
* P4 support has been in the Arduino core since 3.1.0 (ESP-IDF 5.3).

### Pin map, confirmed against the schematic

Guition publish nothing, but there is a community mirror of the manufacturer
schematics:
[p1ngb4ck/unofficial_guition_esp32p4_repo](https://github.com/p1ngb4ck/unofficial_guition_esp32p4_repo/tree/main/JC-ESP32P4-M3-Dev/schematics).
Every number below is read off sheets 3 and 4, not inferred from the reference
design.

| what | pins | source |
| --- | --- | --- |
| microSD | CLK 43, CMD 44, D0–D3 39–42 | sheet 4 |
| Boot button | GPIO35 (`BOOTMODE`), SW1 to GND, R34 10K pull-up — active low | sheet 4 |
| Reset button | SW2 on `CHIP_PU` | sheet 4 |
| SD power | `ESP_LDO_VO4` → AO3401 P-FET → `TF_VCC` | sheet 3 |
| C6 reset | GPIO54 (`C6_CHIP_PU`) | sheet 4 |
| P4 ↔ C6 SDIO | GPIO14–19, internal to the module | sheet 4 (by absence) |

The card sits on **slot 0's IOMUX pins**, so this board follows the reference
design exactly and the stock `esp32p4` variant is correct for it.

**The C6 link is fine.** This was the one thing flagged as potentially fatal:
the stock `esp32p4` variant is the ESP32-P4 *Function EV Board* and hardcodes
the hosted SDIO pins (CLK 18, CMD 19, D0–D3 14–17, reset 54). Sheet 4 settles
it — GPIO14–19 appear on no module pin at all, which is precisely the block the
reference design reserves for that link, and `C6_CHIP_PU` is on GPIO54, the
same reset pin. The C6 is inside the module, wired the standard way. No custom
variant is needed.

### Two traps in the power tree

* **GPIO45 is not connected here.** The EV board switches SD power with it, and
  the variant defines `BOARD_SDMMC_POWER_PIN 45` accordingly — but on sheet 3
  the resistor from GPIO45 to the FET gate (`R10`) is marked **NC**. The gate is
  held low by `R13` (10K), so the FET conducts by default and the card is
  powered whenever VO4 is up. Driving GPIO45 does nothing.
* **LDO VO4 is the thing that actually matters.** GPIO39–48 sit behind it at
  3300 mV and are dead until it is enabled — and every SD data line is in that
  range. The stock variant brings it up automatically
  (`BOARD_PERIMAN_IO_LDO_AUTO`). Any custom variant must carry that over, or the
  card simply never appears, which reads as bad wiring.

### GPIO35 is double-booked

Sheet 4 puts both `BOOTMODE` (SW1) and `RMII_TXD1` on GPIO35. The boot button
and the Ethernet PHY cannot both be live; whichever is added second has to move.
Worth knowing before anyone wires up the RJ45.

Worth checking on arrival, none of which blocks the port:

* Whether the C6's pre-flashed slave firmware matches what a current Arduino
  core expects. Boards ship ESP-Hosted slave **v0.0.6**; newer cores want newer,
  and the mismatch shows up as a version warning followed by a link that does
  not work. The fix is flashing the C6 separately, through its own USB port.
* SoftAP stability. Association problems on P4+C6 over SDIO get reported (e.g.
  [esphome/esphome#10956](https://github.com/esphome/esphome/issues/10956)),
  though mostly against station mode.

### Sourcing note

Pin numbers come from the manufacturer schematics linked above, plus ESP-IDF and
`arduino-esp32` headers where noted. They have been read off a drawing, not off
a working board, so a misread is still possible — but nothing here is a guess.

An earlier version of `NomadP4Probe` swept three "candidate" SD pin sets that
were invented rather than sourced, and two were actively harmful:
`{18,19,14,15,16,17}` is the C6's SDIO link and `{...37,38}` is the console
UART. Driving either as an SD bus breaks the thing under test. The sweep is now
a single schematic-sourced entry.

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
5. microSD over SDMMC, on the schematic's pins
6. A live client counter — connect a phone and watch it register

It prints a verdict at the end.

## The headless port (done)

No panel is fitted, and that turns out to be a feature. The display layer was the
bulk of the S3 port — `Display_Driver`, `LVGL_Driver`, the SquareLine UI,
`ui_screen_mini.c` — and on this board all of it compiles out. Nomad's screen
only ever showed SSID, IP, client count and SD usage, every one of which the web
UI already has.

`NOMAD_HAS_DISPLAY` is the switch. It defaults to 1, so only a profile with no
panel opts out and adding a board cannot silently lose its screen.

What changed:

* **`board_config.h`** — `NOMAD_BOARD_P4_DEV 4`, `NOMAD_UI_HEADLESS` layout,
  `NOMAD_SD_BUS_SDMMC`, no LCD, no LED.
* **`nomad_ui.cpp`** — a second implementation of the same 19-function API.
  Values that change rarely (SSID, IP, client count, SD state) print to serial
  once each; the polled ones stay quiet so the log survives. This is the payoff
  for the firmware talking to the screen through `NomadUI_*` rather than poking
  widgets.
* **Four new API calls** — `NomadUI_SetRotation`, `NomadUI_BootComplete`,
  `NomadUI_Tick`, `NomadUI_Lock`/`Unlock`. The `.ino` had ~22 raw `lv_*`/`LCD_*`
  calls left over; these absorbed them, so the sketch no longer names LVGL at
  all except behind one guard.
* **`Display_Driver.cpp` / `LVGL_Driver.cpp`** wrapped in `#if
  NOMAD_HAS_DISPLAY`. Arduino compiles every file in the sketch folder, so
  without this a headless build still tries to compile them and fails on the
  `LCD_PIN_*` macros that do not exist. `ui_Screen1.c` and `ui_screen_mini.c`
  were already gated on `NOMAD_UI_LAYOUT` and need nothing.

One subtlety worth recording. The queue drain used to hold the LVGL lock across
the whole batch and skip draining entirely if it could not get it, so messages
stayed queued rather than being dropped. Routing it through `NomadUI_Message`
would have dequeued first and dropped on a failed lock. `NomadUI_Lock`/`Unlock`
preserve the original ordering — the mutex is recursive, so the setters can
still take it inside.

## Still to do

1. **Check the RISC-V build.** The S3 code is plain C++ and should port, but
   LVGL ships Xtensa assembly optimisations that must be off. Headless does not
   compile LVGL at all, so this only matters if a DSI panel is added later.
2. **USB mass-storage mode.** The S3 exposes the card over TinyUSB on a long
   button press. On the P4 with hwcdc this needs rechecking.
3. **USB host / external drive** — the interesting one, and the least ready.
   The P4 has the hardware, but reading a USB drive needs the ESP-IDF USB host
   MSC class, which the Arduino core does not usefully expose today. A research
   task, not a port task.
4. **Ethernet.** Free bonus on this board; a Nomad that can also sit on a wired
   LAN is more useful than one that cannot.

Ethernet is a free bonus worth taking later: a Nomad that can also sit on a wired
LAN is genuinely more useful than one that cannot.

## Building it

```
nomad-setup flash --board p4-dev
```

FQBN `esp32:esp32:esp32p4` with `PSRAM=enabled` (the P4 has no opi/qspi choice)
and `app3M_fat9M_16MB`. The pre-flash check is no longer hardcoded to the S3 —
it takes the expected chip from the board profile, so an S3 build cannot be
written to a P4 or the reverse. Different ISAs; that failure would be baffling
on the bench.

## How this was verified without hardware

Neither the board nor an ESP32 toolchain is available here, so instead: every
`board_config.h` macro referenced in code the preprocessor actually keeps was
resolved against all four profiles, using `gcc -E -fdirectives-only` so that
`#if`-excluded regions do not produce false alarms. All four come out clean.
Separately, all 19 functions declared in `nomad_ui.h` are confirmed present in
both the display and headless branches, and the `#if`/`#endif` counts balance in
every file touched.

That catches the failure this port is most prone to — a macro or function that
only exists on one profile — but it is not a compile, and it is certainly not a
boot.
