// board_config.h - Jcorp Nomad hardware profiles
//
// Everything that differs between supported boards lives here. Pick a board by
// changing NOMAD_BOARD below (or by passing -DNOMAD_BOARD=... from the build),
// and nothing else in the firmware needs to be touched.
//
// Supported boards
//   NOMAD_BOARD_POCKET_DONGLE_S3   GNPE Pocket-Dongle-S3-0.96. USB-A stick,
//                                  ESP32-S3 N16R8, 0.96" ST7735 160x80, microSD in
//                                  the USB shell. Pin map from the seller's
//                                  schematic - it is NOT a LilyGO clone.
//   NOMAD_BOARD_TDONGLE_S3         LilyGO T-Dongle-S3. Same form factor and panel,
//                                  completely different wiring, plus an APA102 LED.
//   NOMAD_BOARD_WAVESHARE_LCD147   Waveshare ESP32-S3-LCD-1.47 (the original Nomad
//                                  target), 1.47" ST7789 172x320, WS2812 RGB LED.
//
// If your dongle turns out to be wired differently from the profile below, the
// only file you need to edit is this one. Flash firmware/NomadHardwareTest to
// probe the real wiring - it brute-forces the SD pinout and sweeps the LCD.

#ifndef NOMAD_BOARD_CONFIG_H
#define NOMAD_BOARD_CONFIG_H

// ---------------------------------------------------------------- board ids
#define NOMAD_BOARD_WAVESHARE_LCD147 1
#define NOMAD_BOARD_POCKET_DONGLE_S3 2
#define NOMAD_BOARD_TDONGLE_S3       3
#define NOMAD_BOARD_P4_DEV           4

#ifndef NOMAD_BOARD
#define NOMAD_BOARD NOMAD_BOARD_POCKET_DONGLE_S3
#endif

// ------------------------------------------------------- capability tokens
#define NOMAD_LCD_ST7789 1
#define NOMAD_LCD_ST7735 2

#define NOMAD_LED_NONE   0
#define NOMAD_LED_WS2812 1
#define NOMAD_LED_APA102 2

#define NOMAD_UI_PORTRAIT_TALL  1  // 172x320, the original SquareLine layout
#define NOMAD_UI_LANDSCAPE_MINI 2  // 160x80, the dongle layout
#define NOMAD_UI_HEADLESS       3  // no panel; status goes to serial and the web UI

// How the microSD is wired. SDMMC is the 4-bit bus the Waveshare and LilyGO
// boards use; SPI is a plain 4-wire card on its own SPI host.
#define NOMAD_SD_BUS_SDMMC 1
#define NOMAD_SD_BUS_SPI   2

// =========================================================================
#if NOMAD_BOARD == NOMAD_BOARD_POCKET_DONGLE_S3
// =========================================================================
#define NOMAD_BOARD_NAME "GNPE Pocket-Dongle-S3 0.96"

// Pin map from the schematic the seller supplies on request. This board shares
// the T-Dongle-S3's form factor and panel but none of its wiring, so do not
// mix the two profiles up.
//
// The seller documents the card with SPI names because their example drives it
// over SPI. The same six pins are a full 4-bit SD bus, under the usual dual
// naming: MISO is DAT0, MOSI is CMD, CS is DAT3. That is what the SDMMC block
// below uses; NomadSD_Mount falls back to 1-bit if 4-bit does not come up.

// ---- display: 0.96" IPS, ST7735(S) controller, 160x80 landscape ----------
#define NOMAD_LCD_CONTROLLER NOMAD_LCD_ST7735
#define LCD_WIDTH  160
#define LCD_HEIGHT 80

// ST7735S. Natively 80x160 portrait inside a 132x160 GRAM with portrait
// offsets x=26 y=1. We drive it landscape (MADCTL MV), which swaps those into
// x=1 y=26. Cross-checked against USBArmyKnife's LovyanGFX config for this
// exact board (offset_x 26, offset_y 1, memory 132x160, 27 MHz).
#define LCD_OFFSET_X 1
#define LCD_OFFSET_Y 26
#define LCD_MADCTL   0xA8  // MY | MV | BGR
#define LCD_INVERT_COLORS 1

#define LCD_PIN_MISO -1
#define LCD_PIN_MOSI 11
#define LCD_PIN_SCLK 10
#define LCD_PIN_CS   12
#define LCD_PIN_DC   13
#define LCD_PIN_RST  14

// The schematic lists no backlight GPIO, so it is presumed tied on. -1 means
// "no software control": the panel lights up and the brightness slider becomes
// a no-op. If your schematic does show one, put its number here and the slider
// starts working again.
#define LCD_PIN_BL   -1
#define LCD_BL_ACTIVE_LEVEL 1

#define LCD_SPI_FREQ 27000000

// ---- microSD: plain SPI, on its own host ---------------------------------
// Four wires only. There is no CMD line and no DAT1/DAT2/DAT3, so the SDMMC
// driver cannot drive this card at all - see nomad_sd.h. Confirmed by the
// board spec and by USBArmyKnife, which supports this board.
#define NOMAD_SD_BUS  NOMAD_SD_BUS_SPI
#define SD_SCLK_PIN   17
#define SD_MOSI_PIN   18
#define SD_MISO_PIN   16
#define SD_CS_PIN     47
#define SD_SPI_FREQ   20000000   // starting point; NomadSD_Mount steps down

// ---- RGB LED -------------------------------------------------------------
// Not present in the pin list the seller gave. Set to APA102/WS2812 with the
// right pins if your board does have one; the /led endpoints are no-ops until
// then.
#define NOMAD_LED_TYPE NOMAD_LED_NONE
#define LED_PIN_DATA   -1
#define LED_PIN_CLOCK  -1

// ---- controls ------------------------------------------------------------
#define BOOT_BUTTON_PIN 0

// ---- UI ------------------------------------------------------------------
#define NOMAD_UI_LAYOUT   NOMAD_UI_LANDSCAPE_MINI
#define LVGL_BUF_DIVISOR  4
#define LVGL_FULL_REFRESH 0

// =========================================================================
#elif NOMAD_BOARD == NOMAD_BOARD_TDONGLE_S3
// =========================================================================
#define NOMAD_BOARD_NAME "LilyGO T-Dongle-S3"

// LilyGO's reference wiring, cross-checked against their esp_lcd config and
// Adafruit_ST7735's INITR_MINI160x80 rotation 1.
#define NOMAD_LCD_CONTROLLER NOMAD_LCD_ST7735
#define LCD_WIDTH  160
#define LCD_HEIGHT 80

#define LCD_OFFSET_X 1
#define LCD_OFFSET_Y 26
#define LCD_MADCTL   0xA8  // MY | MV | BGR
#define LCD_INVERT_COLORS 1

#define LCD_PIN_MISO -1
#define LCD_PIN_MOSI 3
#define LCD_PIN_SCLK 5
#define LCD_PIN_CS   4
#define LCD_PIN_DC   2
#define LCD_PIN_RST  1
#define LCD_PIN_BL   38

#define LCD_SPI_FREQ 27000000
#define LCD_BL_ACTIVE_LEVEL 0   // backlight is driven through an inverter here

#define NOMAD_SD_BUS NOMAD_SD_BUS_SDMMC
#define SD_CLK_PIN 12
#define SD_CMD_PIN 16
#define SD_D0_PIN  14
#define SD_D1_PIN  17
#define SD_D2_PIN  21
#define SD_D3_PIN  18

#define NOMAD_LED_TYPE   NOMAD_LED_APA102
#define LED_PIN_DATA     40
#define LED_PIN_CLOCK    39
#define LED_APA102_LEVEL 12  // APA102 global-current field, 0..31

#define BOOT_BUTTON_PIN 0

#define NOMAD_UI_LAYOUT   NOMAD_UI_LANDSCAPE_MINI
#define LVGL_BUF_DIVISOR  4
#define LVGL_FULL_REFRESH 0

// =========================================================================
#elif NOMAD_BOARD == NOMAD_BOARD_WAVESHARE_LCD147
// =========================================================================
#define NOMAD_BOARD_NAME "Waveshare ESP32-S3-LCD-1.47"

#define NOMAD_LCD_CONTROLLER NOMAD_LCD_ST7789
#define LCD_WIDTH  172
#define LCD_HEIGHT 320

#define LCD_OFFSET_X 34
#define LCD_OFFSET_Y 0
#define LCD_MADCTL   0x00
#define LCD_INVERT_COLORS 1

#define LCD_PIN_MISO -1
#define LCD_PIN_MOSI 45
#define LCD_PIN_SCLK 40
#define LCD_PIN_CS   42
#define LCD_PIN_DC   41
#define LCD_PIN_RST  39
#define LCD_PIN_BL   48

#define LCD_SPI_FREQ 80000000
#define LCD_BL_ACTIVE_LEVEL 1

#define NOMAD_SD_BUS NOMAD_SD_BUS_SDMMC
#define SD_CLK_PIN 14
#define SD_CMD_PIN 15
#define SD_D0_PIN  16
#define SD_D1_PIN  18
#define SD_D2_PIN  17
#define SD_D3_PIN  21

#define NOMAD_LED_TYPE NOMAD_LED_WS2812
#define LED_PIN_DATA   38
#define LED_PIN_CLOCK  -1

#define BOOT_BUTTON_PIN 0

#define NOMAD_UI_LAYOUT   NOMAD_UI_PORTRAIT_TALL
#define LVGL_BUF_DIVISOR  20
#define LVGL_FULL_REFRESH 0   // upstream moved to partial refresh; far less SPI traffic

// =========================================================================
#elif NOMAD_BOARD == NOMAD_BOARD_P4_DEV
// Guition JC-ESP32P4-M3-DEV. RISC-V, 32 MB PSRAM, 16 MB flash.
//
// Two things make this board unlike the other three:
//
//   No panel. There is a MIPI-DSI connector but nothing fitted, so this is the
//   headless profile - LVGL and the display driver are compiled out entirely
//   and status goes to serial and the web UI. That is most of what the screen
//   ever showed anyway: SSID, IP, client count.
//
//   No radio. Wi-Fi comes from the on-board ESP32-C6 over ESP-Hosted. Nothing
//   in this file configures that - it is a core/sdkconfig matter - but it is
//   why the C6's slave firmware version has to match the Arduino core's.
//
// Everything below is read off the manufacturer schematic, sheets 3 and 4 of
// github.com/p1ngb4ck/unofficial_guition_esp32p4_repo -> JC-ESP32P4-M3-Dev.
// Nothing here is inferred from the reference design any more.
//
// The card is wired to slot 0's IOMUX pins, so the board follows the reference
// design exactly: sheet 4 shows SD_CLK on GPIO43, SD_CMD on GPIO44 and
// SD_DATA0..3 on GPIO39..42.
//
// Power: sheet 3 runs the slot from ESP_LDO_VO4 (module pin 58) through an
// AO3401 P-FET whose gate is held low by R13 (10K). GPIO45 reaches that gate
// only through R10, which is marked NC - not fitted. So on this board the card
// is powered whenever LDO VO4 is up, and driving GPIO45 does nothing. What
// does matter is the LDO: GPIO39-48 sit behind VO4 at 3300 mV and are dead
// until it is enabled, and every SD data pin is in that range. The stock
// esp32p4 variant brings it up automatically (BOARD_PERIMAN_IO_LDO_AUTO); a
// custom variant would have to carry that over or the card never appears,
// which looks exactly like bad wiring.
#define NOMAD_BOARD_NAME "Guition JC-ESP32P4-M3-DEV"

// ---- display: none -------------------------------------------------------
#define NOMAD_HAS_DISPLAY 0
#define NOMAD_UI_LAYOUT   NOMAD_UI_HEADLESS

// ---- no USB mass-storage mode --------------------------------------------
// The dongle's party trick is being a USB-A plug you can hold a button on to
// turn into a thumb drive. This board has a card slot on its edge and builds
// with USBMode=hwcdc rather than the TinyUSB device stack USBMSC needs, so the
// mode is compiled out. Pull the card, or use the web UI.
#define NOMAD_HAS_USB_MSC 0

// ---- microSD: 4-bit SDIO, confirmed against the schematic ----------------
#define NOMAD_SD_BUS NOMAD_SD_BUS_SDMMC
#define NOMAD_SD_USE_DEFAULT_PINS 0   // we know them; say so rather than infer
#define SD_CLK_PIN 43
#define SD_CMD_PIN 44
#define SD_D0_PIN  39
#define SD_D1_PIN  40
#define SD_D2_PIN  41
#define SD_D3_PIN  42

// ---- no addressable LED --------------------------------------------------
#define NOMAD_LED_TYPE NOMAD_LED_NONE
#define LED_PIN_DATA  -1
#define LED_PIN_CLOCK -1

// Sheet 4: SW1 pulls GPIO35 (BOOTMODE) to ground, with R34 10K to VCC3V3. So
// active-low with a pull-up, which is what NomadButton_Init already assumes.
//
// Two cautions from the same sheet. GPIO35 is also RMII_TXD1, so this button
// and the Ethernet PHY cannot both be live - whichever is added second has to
// move. And the board does have a real reset button: SW2 sits on CHIP_PU, so
// unlike the S3 dongle there is no unplug-and-hold dance to enter download
// mode.
//
// Without a screen the short-press page cycle does nothing; the long-press USB
// mass-storage mode still matters.
#define BOOT_BUTTON_PIN 35

#else
#error "Unknown NOMAD_BOARD - see board_config.h for the supported profiles"
#endif

// ------------------------------------------------- shared derived settings
// Every board with a panel gets the full LVGL UI. Only a profile that has no
// display says so explicitly, so adding a board cannot accidentally opt out.
#ifndef NOMAD_HAS_DISPLAY
#define NOMAD_HAS_DISPLAY 1
#endif

// USB mass-storage mode: hold the button and the board becomes a thumb drive.
// That is the headline feature on a board shaped like a USB-A plug and close to
// pointless on a dev board with a card slot on the edge, and it needs the
// TinyUSB device stack, which is not what the P4 profile builds. On by default,
// so a new stick-shaped board gets it without asking.
#ifndef NOMAD_HAS_USB_MSC
#define NOMAD_HAS_USB_MSC 1
#endif

// SDMMC boards normally name their pins; the P4 profile leaves them to the
// core's own defaults until the probe reports the real ones.
#ifndef NOMAD_SD_USE_DEFAULT_PINS
#define NOMAD_SD_USE_DEFAULT_PINS 0
#endif

// Backlight PWM. 10-bit resolution gives 0..1023 duty steps.
#define LCD_BL_PWM_FREQ_HZ 1000
#define LCD_BL_PWM_BITS    10
#define LCD_BL_PWM_MAX     ((1 << LCD_BL_PWM_BITS) - 1)

// Boot button: hold this long to fall into USB mass-storage mode. A shorter
// press just cycles the on-screen page.
#define NOMAD_BTN_LONGPRESS_MS 1200
#define NOMAD_BTN_DEBOUNCE_MS  40

#endif  // NOMAD_BOARD_CONFIG_H
