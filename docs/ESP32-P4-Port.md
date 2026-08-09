# Porting Nomad to the ESP32-P4 (Guition JC-ESP32P4-M3-DEV)

Status: **headless port written, not yet run on hardware.** The board profile,
the headless UI path and the probe sketch are in. Nothing has touched real
silicon — the board has not shipped, and this repo's CI cannot reach Espressif's
toolchain host, so the firmware has been verified by preprocessing all four
board profiles rather than by compiling.

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

### The `esp32p4` FQBN is the EV board, not a generic P4

This is the most important thing on this page. `arduino-esp32`'s `esp32p4`
variant header says so in its own comment — *"ESP32-P4 EV Function board
specific definitions"* — and it hardcodes, among other things, **the SDIO pins
that carry the C6 Wi-Fi link**:

```c
#define BOARD_SDIO_ESP_HOSTED_CLK   18
#define BOARD_SDIO_ESP_HOSTED_CMD   19
#define BOARD_SDIO_ESP_HOSTED_D0    14   // D1 15, D2 16, D3 17
#define BOARD_SDIO_ESP_HOSTED_RESET 54
```

Those are Espressif's EV-board pins. If Guition wired the C6 to anything else,
Wi-Fi cannot come up and nothing in Nomad can fix it — it needs a custom
variant. `NomadP4Probe` now prints these numbers so they can be compared
against the schematic; that is the first thing to rule out if the radio is dead.

The same header also carries two things the S3 has no equivalent of, both easy
to miss:

* `BOARD_SDMMC_POWER_PIN 45` (active **LOW**) — the card slot has a power
  switch. Miss it and the card never powers up, which reads as bad wiring.
* `BOARD_PERIMAN_IO_LDO0_*` — GPIO **39–48 sit behind on-chip LDO VO4** at
  3300 mV and are dead until it is enabled. The SD data pins are in that range.

Worth checking on arrival, none of which blocks the port:

* Whether the C6's pre-flashed slave firmware matches what a current Arduino
  core expects. Boards ship ESP-Hosted slave **v0.0.6**; newer cores want newer,
  and the mismatch shows up as a version warning followed by a link that does
  not work. The fix is flashing the C6 separately, through its own USB port.
* SoftAP stability. Association problems on P4+C6 over SDIO get reported (e.g.
  [esphome/esphome#10956](https://github.com/esphome/esphome/issues/10956)),
  though mostly against station mode.
* This board's **SD pin map**. Slot 0's IOMUX pins are CLK 43, CMD 44, D0–D3
  39–42 (ESP-IDF `soc/esp32p4/include/soc/sdmmc_pins.h`), and the profile uses
  those — but the P4 also supports SDMMC over the GPIO matrix
  (`SOC_SDMMC_USE_GPIO_MATRIX`), so this board is free to have wired the card
  somewhere else. Guition publish no schematic I could find.

### Sourcing note

Pin numbers on this page come from ESP-IDF and `arduino-esp32` headers, cited
inline. Nothing here is from Guition, because I could not reach any
manufacturer documentation — their manual pages and the ESPHome device entry
are both blocked from this environment. So these are *the reference design's*
pins, which this board may or may not follow. Treat every number as needing
confirmation against the hardware.

An earlier version of `NomadP4Probe` swept three "candidate" SD pin sets that
were invented rather than sourced, and two of them were actively harmful:
`{18,19,14,15,16,17}` are the C6's SDIO link and `{...37,38}` are the console
UART. Driving either as an SD bus breaks the thing under test. The sweep is now
a single sourced entry.

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
