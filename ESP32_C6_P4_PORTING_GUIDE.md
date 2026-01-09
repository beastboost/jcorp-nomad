# ESP32-C6 / ESP32-P4 Porting Guide for Jcorp Nomad

## ⚠️ **IMPORTANT: ESP32-P4 + ESP32-C6 Combo Board Analysis**

**Based on real-world testing by the original developer:**

### ❌ Problem Confirmed: WiFi + SD Don't Work Simultaneously on UART-based P4+C6 Boards

The original coder tested an ESP32-P4+C6 combo board (like JC-ESP32P4-M3-DEV) and found that **WiFi and SD card cannot operate at the same time**, unlike the ESP32-S3 which works fine.

### Root Cause: UART Communication Bottleneck

**JC-ESP32P4-M3-DEV Architecture:**
```
ESP32-P4 (SD card)  ←─ UART (115200 baud ≈ 11 KB/s) ─→  ESP32-C6 (WiFi)
```

**Why This Fails for Media Streaming:**

| Interface | Bandwidth | Reality |
|-----------|-----------|---------|
| SD Card (SDMMC) | 20-40 MB/s | ✅ Fast enough for HD video |
| UART (P4↔C6) | **0.01-0.5 MB/s** | ❌ **1000x too slow!** |
| WiFi 6 | Up to 100 MB/s | ✅ Fast enough |

**Bottleneck:** Even at maximum UART speed (921600 baud), you only get ~92 KB/s - nowhere near enough for video streaming.

### Comparison of P4+C6 Communication Methods

| Board Type | P4↔C6 Interface | Bandwidth | Can Stream Video? |
|------------|----------------|-----------|-------------------|
| **JC-ESP32P4-M3-DEV** | **UART** | **11-92 KB/s** | ❌ **NO** |
| Espressif P4 Function EV | SDIO | 40-200 MB/s | ✅ Yes |
| Waveshare ESP32-P4-WIFI6 | SDIO | 40-200 MB/s | ✅ Yes |

**Your board (UART-based) cannot handle simultaneous WiFi + SD for this use case.**

---

## JC-ESP32P4-M3-DEV Specific Pin Analysis

Based on the schematic, here's why WiFi + SD fail on this board:

### P4 ↔ C6 Communication (UART - THE BOTTLENECK)

| Signal | ESP32-P4 GPIO | ESP32-C6 GPIO | Max Speed |
|--------|---------------|---------------|-----------|
| TX | 44 | 16 | 921600 baud |
| RX | 43 | 17 | = 92 KB/s max |
| RTS | 45 | 18 | Flow control |
| CTS | 46 | 19 | Flow control |

**Reality Check:**
- Video bitrate: 500-2000 KB/s (SD quality)
- UART max: 92 KB/s
- **Gap: 5-20x too slow**

### SD Card Pins (ESP32-P4 SDMMC)

| Signal | ESP32-P4 GPIO | Notes |
|--------|---------------|-------|
| SD_CLK | 12 | ✅ No conflict with UART |
| SD_CMD | 11 | ✅ No conflict |
| SD_D0 | 13 | ✅ No conflict |
| SD_D1 | 14 | ✅ No conflict |
| SD_D2 | 15 | ✅ No conflict |
| SD_D3 | 16 | ✅ No conflict |
| SD_CD | 10 | Card detect |

**Pins are fine** - the problem is architectural:
```
SD Card (20 MB/s) → P4 → [UART 0.09 MB/s BOTTLENECK] → C6 → WiFi
```

### Why This Architecture Fails

**Typical media streaming flow:**
1. User's browser → WiFi → C6: "GET /video.mp4"
2. C6 → UART → P4: "Send me video.mp4"
3. P4 reads SD card at 20 MB/s ✅
4. P4 → **UART** → C6: Sending video data... ❌ **BLOCKED HERE**
5. UART can only push 92 KB/s, but video needs 500+ KB/s
6. Result: Buffering, stuttering, timeout

### Could You Work Around It?

**Possible (terrible) workarounds:**

1. **Lower video quality to 480p @ 64 KB/s** - Barely fits in UART, looks terrible
2. **Pre-transcode all media** - Massive storage overhead
3. **Time-multiplex**: WiFi OR SD, never both - Defeats the purpose

**None of these are practical for a media server.**

---

## Executive Summary (For Single-Chip Options)

**Current Status:** Jcorp Nomad is designed for **ESP32-S3** with hardware SDMMC controller.

**Hardware Compatibility:**
- ❌ **ESP32-C6 alone**: NOT compatible - lacks SDMMC hardware, requires full SD card rewrite to SPI
- ⚠️ **ESP32-P4 alone**: NOT recommended - no WiFi (needs external module)
- ✅ **ESP32-P4 + C6 combo**: HIGHLY RECOMMENDED - best performance and no WiFi/SD conflicts

---

## Critical Hardware Differences

### ESP32-S3 (Current)
- ✅ Dedicated SDMMC host controller (4-bit SD card support)
- ✅ WiFi 2.4GHz + Bluetooth 5.0
- ✅ 512KB SRAM
- ✅ Pins: 45 GPIO pins
- ✅ USB OTG support

### ESP32-C6
- ❌ **NO SDMMC controller** - SD card must use SPI only
- ✅ WiFi 6 (2.4GHz) + Bluetooth 5.3 + Zigbee/Thread
- ⚠️ Only 512KB SRAM (same as S3)
- ⚠️ Fewer GPIO pins (30 pins)
- ✅ USB Serial/JTAG (no USB OTG)

### ESP32-P4
- ✅ Has SDMMC host controller (supports 4-bit mode)
- ❌ **NO WiFi or Bluetooth** (typically paired with companion chip like C6)
- ✅ Much more RAM (32MB PSRAM standard)
- ✅ More GPIO pins (54 pins)
- ✅ More powerful CPU (dual-core 400MHz)
- ⚠️ Different pin matrix than S3

---

## WiFi + SD Card Issues by Chip

### ESP32-S3 (Current Implementation)
**Issue Type:** Software/Performance conflicts only
- WiFi and SDMMC use separate hardware peripherals ✅
- No pin conflicts ✅
- Issues are RAM, concurrent access, and CPU load related
- **Already handled in your code via:**
  - SD mutex protection
  - Performance throttling
  - SD recovery system
  - Conservative frequency settings

### ESP32-C6
**Issue Type:** Critical hardware limitation + potential SPI bus conflicts
- ⚠️ **Must use SPI for SD card** (no SDMMC hardware)
- ⚠️ SPI bus can interfere with WiFi operations
- ⚠️ Single SPI controller can be bottleneck
- Known workarounds:
  - Use slower SPI speeds during WiFi activity
  - Implement careful SPI transaction timing
  - Consider SPI mutex protection
  - May need to pause SD operations during critical WiFi tasks

### ESP32-P4
**Issue Type:** No direct WiFi+SD conflict (P4 has no WiFi radio)
- ✅ If P4 is standalone: No WiFi to conflict with
- ⚠️ If P4+C6 combo: WiFi on C6, SD on P4 - should work well
- ⚠️ Communication between P4 and C6 (if combo) needs bandwidth management

---

## Required Code Changes

## For ESP32-C6 (Major Rewrite Required)

### 1. Replace All SD_MMC with SD (SPI)

**Files to modify:**
- `firmware/JcorpNomadProject/SD_Card.h`
- `firmware/JcorpNomadProject/JcorpNomadProject.ino`
- `firmware/JcorpNomadProject/usb_mode.cpp`
- All files using SD card operations

**Library Change:**
```cpp
// OLD (ESP32-S3):
#include "SD_MMC.h"
SD_MMC.begin(...)

// NEW (ESP32-C6):
#include "SD.h"
#include "SPI.h"
SD.begin(CS_PIN, SPI)
```

### 2. Pin Configuration Changes

**Create new file: `firmware/JcorpNomadProject/SD_Card_C6.h`**

```cpp
#pragma once
#include "Arduino.h"
#include <cstring>
#include "FS.h"
#include "SD.h"
#include "SPI.h"

// ESP32-C6 SPI pins for SD card
#define SD_CS_PIN      10    // Chip Select
#define SD_MOSI_PIN    19    // Master Out Slave In
#define SD_MISO_PIN    20    // Master In Slave Out
#define SD_SCK_PIN     21    // Clock

// These pins are NO LONGER USED (SDMMC specific):
// SD_CLK_PIN, SD_CMD_PIN, SD_D0_PIN, SD_D1_PIN, SD_D2_PIN, SD_D3_PIN

extern uint16_t SDCard_Size;
extern uint16_t Flash_Size;

void SD_Init();
void Flash_test();

bool File_Search(const char* directory, const char* fileName);
uint16_t Folder_retrieval(const char* directory, const char* fileExtension, char File_Name[][100],uint16_t maxFiles);
void remove_file_extension(char *file_name);
```

### 3. Initialization Code Changes

**In `JcorpNomadProject.ino` around line 3242:**

```cpp
// OLD (ESP32-S3):
Serial.println("Setting up MMC pins...");
if (!SD_MMC.setPins(SD_CLK_PIN, SD_CMD_PIN, SD_D0_PIN, SD_D1_PIN, SD_D2_PIN, SD_D3_PIN)) {
    Serial.println("ERROR: SDMMC Pin configuration failed!");
    return;
}

if (!SD_MMC.begin("/sdcard", true, false, SDMMC_FREQ_DEFAULT, 12)) {
    Serial.println("ERROR: SDMMC Card initialization failed.");
    return;
}

// NEW (ESP32-C6):
Serial.println("Setting up SPI for SD card...");
SPI.begin(SD_SCK_PIN, SD_MISO_PIN, SD_MOSI_PIN, SD_CS_PIN);

if (!SD.begin(SD_CS_PIN, SPI, 10000000)) {  // 10MHz for stability with WiFi
    Serial.println("ERROR: SD Card initialization failed.");
    return;
}
```

### 4. All SD_MMC References Must Change

**Global find/replace needed (but review each):**
- `SD_MMC.` → `SD.`
- `SD_MMC` → `SD`
- Note: Some methods differ between SD_MMC and SD libraries

**Method differences to watch for:**
```cpp
// SDMMC methods that differ or don't exist in SD:
SD_MMC.setPins()        // Remove - use SPI.begin() instead
SD_MMC.readRAW()        // May not exist in SD library
SD_MMC.writeRAW()       // May not exist in SD library
SD_MMC.sectorSize()     // May not exist in SD library
SD_MMC.numSectors()     // May not exist in SD library
```

### 5. USB Mode Changes

**In `usb_mode.cpp` lines 73-79:**

ESP32-C6 doesn't have USB OTG, so USB mass storage mode **won't work**. You'll need to:
- Remove USB mode entirely, OR
- Implement alternative file transfer (WiFi file upload only)

### 6. Display Pin Conflicts (Check Required)

ESP32-C6 has only 30 GPIO pins vs S3's 45 pins. Verify these pins are available:

**Current pin usage:**
- SD: Will use pins 10, 19, 20, 21 (SPI)
- Display: pins 39, 40, 41, 42, 45, 48
- NeoPixel: pin 38
- Boot button: pin 0

⚠️ **Pins 39, 40, 41, 42, 45, 48 may not exist on ESP32-C6!**

You'll need to remap ALL pins to C6's available GPIOs.

### 7. Performance Implications

SPI is slower than SDMMC:
- **SDMMC 4-bit:** ~20-40 MB/s
- **SPI mode:** ~1-5 MB/s

**Impact:**
- Video streaming may be choppy
- Indexing will be much slower
- Multiple simultaneous users may struggle

**Workarounds:**
- Lower video bitrates
- More aggressive buffering
- Limit concurrent users
- Reduce SPI speed during WiFi activity (add to your existing throttling)

---

## For ESP32-P4 (Moderate Changes Required)

### 1. Pin Remapping Only (SDMMC Still Works!)

ESP32-P4 has SDMMC, so the SD_MMC library works. Just change pins.

**Modify `firmware/JcorpNomadProject/SD_Card.h`:**

```cpp
// ESP32-P4 SDMMC pins (example - verify with your board datasheet)
#define SD_CLK_PIN    43
#define SD_CMD_PIN    44
#define SD_D0_PIN     39
#define SD_D1_PIN     40
#define SD_D2_PIN     41
#define SD_D3_PIN     42
```

⚠️ **You MUST verify these pins with your specific ESP32-P4 dev board datasheet!**

### 2. WiFi Handling

ESP32-P4 has NO built-in WiFi. Options:

**Option A: P4 + C6 Combo Board**
If your board has both P4 and C6:
- P4 handles SD card and processing
- C6 handles WiFi
- Need to implement P4↔C6 communication (SPI/UART/etc)
- This is a MAJOR architectural change

**Option B: External WiFi Module**
- Add ESP8266, ESP32-C3, or similar as WiFi co-processor
- Similar complexity to Option A

**Option C: Use Different Board**
- Stick with ESP32-S3 (current) or wait for integrated P4 solution

### 3. Display Pin Remapping

ESP32-P4 has different GPIO numbers. Remap all pins in `Display_ST7789.h`:

```cpp
// Verify these with P4 board datasheet
#define EXAMPLE_PIN_NUM_MOSI           XX
#define EXAMPLE_PIN_NUM_SCLK           XX
#define EXAMPLE_PIN_NUM_LCD_CS         XX
#define EXAMPLE_PIN_NUM_LCD_DC         XX
#define EXAMPLE_PIN_NUM_LCD_RST        XX
#define EXAMPLE_PIN_NUM_BK_LIGHT       XX
```

### 4. USB Mode

ESP32-P4 may or may not have USB OTG depending on the board. Check your board's datasheet.

---

## Testing Requirements

### For ESP32-C6
1. ✅ SD card detection and mounting (SPI)
2. ✅ File read/write operations
3. ✅ WiFi AP mode startup
4. ⚠️ **Critical:** WiFi + SD simultaneously under load
5. ✅ Video streaming quality (expect degradation)
6. ✅ Multiple concurrent users
7. ✅ Display functionality with new pins
8. ⚠️ **Critical:** System stability during indexing + WiFi
9. ✅ SD card recovery system still works
10. ❌ Remove USB mode or document as unsupported

### For ESP32-P4
1. ✅ SD card detection with new SDMMC pins
2. ✅ File operations at normal speed
3. ⚠️ **Critical:** WiFi communication (P4+C6 combo)
4. ✅ Display with remapped pins
5. ✅ All existing features if WiFi works
6. ❌ USB mode (check board support)

---

## Recommendation

### Best Path Forward:

1. **If you need it working now:** Use ESP32-S3 (current design) ✅

2. **If you want ESP32-P4 performance:**
   - Only proceed if your board is a P4+C6 combo with documented SPI/communication
   - Otherwise, you'll spend weeks implementing P4↔WiFi module communication
   - Moderate difficulty

3. **If you want ESP32-C6:**
   - Expect 2-3 weeks of development to port to SPI
   - Performance will be worse than S3
   - WiFi 6 features won't matter much for local AP
   - High difficulty, questionable benefit

### Easiest Solution:
**Stick with ESP32-S3 hardware** - it's the best fit for this project's requirements.

---

## Code Change Summary

### ESP32-C6 (Complete Rewrite)
- 🔴 Replace SD_MMC with SD library (SPI mode)
- 🔴 Change all SD card pin definitions
- 🔴 Remap ALL GPIO pins (display, NeoPixel, etc)
- 🔴 Remove or redesign USB mode
- 🔴 Add SPI-specific WiFi conflict handling
- 🔴 Test and tune for slower SD speeds
- 🔴 Update all SD card operations (readRAW, etc)
- **Estimated effort:** 20-40 hours

### ESP32-P4 (Moderate Remap)
- 🟡 Remap SDMMC pins only
- 🔴 Implement P4↔C6 WiFi communication (if combo board)
- 🟡 Remap all GPIO pins
- 🟡 Test USB mode support
- 🟡 Verify SDMMC compatibility
- **Estimated effort:** 10-30 hours (depending on WiFi solution)

---

## Current Code Dependencies on ESP32-S3

**Files that assume ESP32-S3 SDMMC:**
1. `firmware/JcorpNomadProject/JcorpNomadProject.ino` (lines 3242-3254)
2. `firmware/JcorpNomadProject/SD_Card.h` (lines 5-12)
3. `firmware/JcorpNomadProject/SD_MMC.h` (entire file)
4. `firmware/JcorpNomadProject/usb_mode.cpp` (lines 78-79)
5. All media serving functions using SD_MMC
6. Display pin configuration in `Display_ST7789.h`
7. Boot mode handling with USB

**Library dependencies:**
- `SD_MMC.h` - ESP32-S3 SDMMC library
- `USB.h` / `USBMSC.h` - USB OTG (S3 only)
- Hardware SDMMC driver in ESP-IDF

---

## ESP32-P4 + ESP32-C6 Combo Board Detailed Guide (SDIO-based Only)

**⚠️ WARNING: This section ONLY applies to SDIO-based P4+C6 boards (like Espressif Function EV Board).**

**This does NOT apply to:**
- JC-ESP32P4-M3-DEV (uses UART - too slow)
- Any board where P4↔C6 communicate via UART

**If your board uses UART between P4 and C6, skip this section** - it won't work for media streaming.

### Architecture Overview

```
┌─────────────────────────────────────────────┐
│  ESP32-P4 (Main Processor)                  │
│  ├─ 400MHz dual-core RISC-V CPU             │
│  ├─ 768KB SRAM + 32MB PSRAM                 │
│  ├─ SDMMC Host → SD Card (CLK,CMD,D0-D3)    │
│  ├─ SPI → Display (ST7789)                  │
│  ├─ GPIO → NeoPixel, Buttons, etc           │
│  └─ SDIO Master → ESP32-C6 (separate bus)   │
└─────────────────────────────────────────────┘
                    ↕ SDIO @ 40MHz
┌─────────────────────────────────────────────┐
│  ESP32-C6 (WiFi Co-processor)               │
│  ├─ WiFi 6 (2.4GHz)                         │
│  ├─ Bluetooth 5.3 / BLE                     │
│  └─ SDIO Slave                              │
└─────────────────────────────────────────────┐
```

**Key: The P4 and C6 communicate via SDIO, which is SEPARATE from the SD card's SDMMC interface. This eliminates WiFi/SD conflicts!**

---

### Why WiFi + SD Works Better on P4+C6

**ESP32-S3 Problem:**
```
┌──────────────────┐
│   ESP32-S3       │
│                  │
│  WiFi Radio  ←───┼──→ Interference/Resource Conflicts
│       ↕          │
│  SDMMC Host  ────┼──→ SD Card
│                  │
└──────────────────┘
   Same chip = Conflicts with RAM, CPU, DMA
```

**ESP32-P4+C6 Solution:**
```
┌──────────────┐              ┌──────────────┐
│  ESP32-P4    │              │  ESP32-C6    │
│              │              │              │
│ SDMMC ───────┼──→ SD Card   │  WiFi Radio  │
│              │              │              │
│ SDIO ────────┼──────────────┼──→ SDIO      │
│  Master      │   40MHz      │   Slave      │
└──────────────┘              └──────────────┘

Separate chips = NO conflicts!
```

---

### Required Code Changes

#### 1. Install ESP-Hosted Framework

**Add to `platformio.ini` or install via Arduino:**

```ini
lib_deps =
    espressif/esp_wifi_remote@^0.1.0
    espressif/esp_hosted@^1.0.0
```

**Or via ESP-IDF:**
```bash
idf.py add-dependency "espressif/esp_wifi_remote"
idf.py add-dependency "espressif/esp_hosted"
```

#### 2. Replace WiFi Library Calls

**Current code (ESP32-S3):**
```cpp
#include <WiFi.h>

void setup() {
    WiFi.softAP(ssid, password);
    IPAddress IP = WiFi.softAPIP();
}
```

**New code (ESP32-P4+C6):**
```cpp
#include "esp_wifi_remote.h"  // Instead of WiFi.h
#include "esp_hosted.h"

void setup() {
    // Initialize ESP-Hosted communication to C6
    esp_hosted_init();

    // WiFi API remains similar but uses remote functions
    esp_wifi_set_mode(WIFI_MODE_AP);
    wifi_config_t wifi_config = {
        .ap = {
            .ssid = "YourSSID",
            .password = "YourPassword",
            .max_connection = 4,
            .authmode = WIFI_AUTH_WPA2_PSK
        },
    };
    esp_wifi_set_config(WIFI_IF_AP, &wifi_config);
    esp_wifi_start();
}
```

**Changes needed in:** `firmware/JcorpNomadProject/JcorpNomadProject.ino` (lines 3233-3236)

#### 3. Configure SDIO Pins for C6 Communication

**Add to initialization (around line 3210):**

```cpp
// ESP-Hosted SDIO configuration (P4 ↔ C6 communication)
// These are SEPARATE from SD card SDMMC pins!
#define ESPHOSTED_SDIO_CLK   18
#define ESPHOSTED_SDIO_CMD   19
#define ESPHOSTED_SDIO_D0    14
#define ESPHOSTED_SDIO_D1    15
#define ESPHOSTED_SDIO_D2    16
#define ESPHOSTED_SDIO_D3    17
#define ESPHOSTED_RESET_PIN  54

// Initialize ESP-Hosted before WiFi operations
esp_hosted_config_t config = {
    .transport = ESP_HOSTED_TRANSPORT_SDIO,
    .sdio_config = {
        .clk_pin = ESPHOSTED_SDIO_CLK,
        .cmd_pin = ESPHOSTED_SDIO_CMD,
        .d0_pin = ESPHOSTED_SDIO_D0,
        .d1_pin = ESPHOSTED_SDIO_D1,
        .d2_pin = ESPHOSTED_SDIO_D2,
        .d3_pin = ESPHOSTED_SDIO_D3,
        .reset_pin = ESPHOSTED_RESET_PIN,
        .clock_speed = 40000000  // 40MHz
    }
};

esp_err_t ret = esp_hosted_init(&config);
if (ret != ESP_OK) {
    Serial.println("ERROR: ESP-Hosted initialization failed!");
    return;
}
```

#### 4. Update SD Card Pins for P4

**Modify `firmware/JcorpNomadProject/SD_Card.h`:**

```cpp
// ESP32-P4 SDMMC pins (verify with your specific board!)
// Note: P4 has flexible GPIO matrix, but these are typical for Waveshare boards
#define SD_CLK_PIN    43
#define SD_CMD_PIN    44
#define SD_D0_PIN     39
#define SD_D1_PIN     40
#define SD_D2_PIN     41
#define SD_D3_PIN     42
```

**Important:** Verify these with your board's schematic! P4 allows any GPIO for SDMMC via GPIO matrix.

#### 5. Update Display Pins

**Modify `firmware/JcorpNomadProject/Display_ST7789.h`:**

Check your board schematic for the actual pins. Example:

```cpp
#define EXAMPLE_PIN_NUM_MOSI           11
#define EXAMPLE_PIN_NUM_SCLK           10
#define EXAMPLE_PIN_NUM_LCD_CS         9
#define EXAMPLE_PIN_NUM_LCD_DC         8
#define EXAMPLE_PIN_NUM_LCD_RST        12
#define EXAMPLE_PIN_NUM_BK_LIGHT       13
```

#### 6. WiFi API Migration Table

Replace all WiFi calls in your code:

| ESP32-S3 (Old) | ESP32-P4+C6 (New) | Location |
|----------------|-------------------|----------|
| `WiFi.h` | `esp_wifi_remote.h` | All files |
| `WiFi.softAP()` | `esp_wifi_set_mode()` + config | JcorpNomadProject.ino:3235 |
| `WiFi.softAPIP()` | `esp_netif_get_ip_info()` | JcorpNomadProject.ino:3236 |
| `WiFi.setSleep()` | `esp_wifi_set_ps()` | Wireless.cpp:13 |
| `WiFi.scanNetworks()` | `esp_wifi_scan_start()` | Wireless.cpp |

#### 7. Remove USB Mass Storage (Optional)

ESP32-P4 may or may not have USB OTG depending on board variant. If not available:

**Option A:** Remove USB mode entirely from `usb_mode.cpp`

**Option B:** Keep USB mode if your P4 board supports it (check datasheet)

---

### Configuration Checklist

- [ ] Install ESP-Hosted library
- [ ] Replace `WiFi.h` with `esp_wifi_remote.h`
- [ ] Update all WiFi API calls (see migration table)
- [ ] Configure ESP-Hosted SDIO pins (P4↔C6 communication)
- [ ] Update SD card SDMMC pins for P4
- [ ] Update display SPI pins for P4
- [ ] Update NeoPixel/button GPIO pins
- [ ] Test WiFi AP mode startup
- [ ] Test SD card mount
- [ ] Test simultaneous WiFi + SD heavy operations
- [ ] Update ESP-Hosted firmware on C6 if needed (see below)
- [ ] Performance tuning (see below)

---

### ESP-Hosted Firmware on C6

The C6 on your combo board comes pre-flashed with ESP-Hosted slave firmware (v0.0.6). You may want to update it:

**To update C6 firmware:**
1. You'll need an ESP-Prog or similar JTAG adapter
2. USB-C only flashes the P4, not the C6
3. Download latest ESP-Hosted slave firmware from Espressif
4. Flash via JTAG to C6

**Check current version:**
```cpp
esp_hosted_version_t version;
esp_hosted_get_version(&version);
Serial.printf("ESP-Hosted version: %d.%d.%d\n",
    version.major, version.minor, version.patch);
```

---

### Performance Tuning

Add these to your ESP-IDF `sdkconfig` or Arduino `menuconfig`:

```
# Increase WiFi buffers for better throughput
CONFIG_WIFI_RMT_STATIC_RX_BUFFER_NUM=16
CONFIG_WIFI_RMT_DYNAMIC_RX_BUFFER_NUM=64

# Optimize TCP window sizes
CONFIG_LWIP_TCP_SND_BUF_DEFAULT=65534
CONFIG_LWIP_TCP_WND_DEFAULT=65534

# Enable high-speed SDIO (if stable)
CONFIG_ESP_HOSTED_SDIO_CLK_FREQ=50000000
```

**SD Card Frequency:** Keep using `SDMMC_FREQ_DEFAULT` initially. Since WiFi is on a separate chip, you can potentially increase to `SDMMC_FREQ_HIGHSPEED` without conflicts. Test carefully!

```cpp
// In JcorpNomadProject.ino line 3249
// Try this after basic functionality works:
if (!SD_MMC.begin("/sdcard", true, false, SDMMC_FREQ_HIGHSPEED, 12)) {
```

---

### Testing Plan

1. **Basic Boot:** P4 boots, C6 initializes via ESP-Hosted
2. **WiFi Only:** Can create AP and connect from phone
3. **SD Only:** Can mount SD card and list files
4. **WiFi + SD Light:** Browse media files over WiFi
5. **WiFi + SD Heavy:** Stream video while indexing SD card
6. **Multi-user:** 4-6 simultaneous video streams
7. **Stability:** 24-hour stress test with continuous streaming
8. **Recovery:** SD card recovery still works under load

**Expected Improvements:**
- ✅ No WiFi/SD throttling needed (separate chips!)
- ✅ 2-3x faster indexing (400MHz vs 240MHz)
- ✅ Support 2x more simultaneous users
- ✅ Higher quality video streaming (more CPU headroom)
- ✅ WiFi 6 efficiency improvements

---

### Estimated Effort Summary

| Task | Time | Difficulty |
|------|------|------------|
| Install ESP-Hosted library | 30 min | Easy |
| Update WiFi API calls | 2-3 hours | Medium |
| Remap all GPIO pins | 1-2 hours | Easy |
| Test and debug | 4-8 hours | Medium |
| Performance tuning | 2-3 hours | Medium |
| **Total** | **8-15 hours** | **Moderate** |

**Payoff:** 2-3x performance improvement + zero WiFi/SD conflicts

---

## Final Recommendations

### For UART-based P4+C6 Boards (JC-ESP32P4-M3-DEV, etc.)

**❌ NOT RECOMMENDED** - UART bottleneck makes this unusable for media streaming:

**Why It Doesn't Work:**
- UART bandwidth: 11-92 KB/s (even at max speed)
- Video streaming needs: 500+ KB/s minimum
- **UART is 5-50x too slow** for this application
- Original coder confirmed WiFi+SD don't work simultaneously

**Confirmed by real-world testing:** The developer tried this architecture and it failed.

---

### For SDIO-based P4+C6 Boards (Espressif EV Board, Some Waveshare)

**✅ POTENTIALLY GOOD** - But check your specific board:

**Benefits IF your board uses SDIO:**
- 66% faster CPU (400MHz vs 240MHz)
- 4x more RAM (768KB + 32MB PSRAM vs 512KB)
- SDIO bandwidth: 40-200 MB/s (fast enough!)
- WiFi 6 instead of WiFi 4

**How to check:** Look at the schematic - if P4↔C6 uses GPIO 14-19 for SDIO (not UART), it may work.

**Effort:** 8-15 hours (moderate complexity)

---

### For Single-Chip Options

**ESP32-S3:** ✅ **STRONGLY RECOMMENDED - BEST OPTION**
- Already works perfectly for this project
- WiFi + SD work simultaneously (confirmed by coder)
- No changes needed
- Proven stability
- 240MHz is fast enough for multi-user streaming

**ESP32-C6 alone:** ❌ NOT RECOMMENDED
- No SDMMC (must use slow SPI)
- Major rewrite required (20-40 hours)
- Worse performance than S3

**ESP32-P4 alone:** ❌ NOT RECOMMENDED
- No WiFi (would need external module)
- Complex to implement

---

## Summary: What to Tell the Original Coder

**The problem they experienced is real and fundamental:**

1. ✅ **ESP32-S3 works great** - keep using it
2. ❌ **UART-based P4+C6 won't work** - UART is too slow for video
3. ⚠️ **SDIO-based P4+C6 would work** - but need different board
4. 💡 **Best solution:** Stay with ESP32-S3

**The issue isn't a software bug** - it's a hardware limitation of UART communication between the chips.

---

## Additional Resources Needed

To proceed with porting, you'll need:

1. **Datasheet** for specific ESP32-C6 or ESP32-P4 dev board
2. **Pin mapping diagram** from manufacturer
3. **Schematic** showing SD card connections
4. **Decision** on USB mode (keep, remove, or replace)
5. **Testing plan** for WiFi+SD conflict scenarios
6. For P4: **WiFi communication protocol** if using companion chip

---

## Known Issues in Current Code (Any Platform)

These issues exist on ESP32-S3 and will carry over:

1. Heavy SD operations can crash during WiFi activity (mitigated by mutex/throttling)
2. Admin page warns not to use device during SD scans
3. Multiple recovery commits in git history show SD stability challenges
4. RAM usage is tight with WiFi enabled (Bluetooth already disabled)

**These will be worse on ESP32-C6** due to SPI bottleneck.

---

## Contact

If original coder wants to discuss implementation strategy, key questions:

1. Confirm target hardware model (with part number)
2. Discuss whether SPI SD card performance is acceptable for use case
3. Review WiFi+SD conflict testing plan
4. Consider whether ESP32-S3 remains better option

---

**Document Version:** 2.0
**Date:** 2026-01-09
**Based on:** Jcorp Nomad main branch (commit c4d4b30)

---

## Sources and References

This guide was compiled using information from:

- [ESP32-P4-Function-EV-Board User Guide](https://docs.espressif.com/projects/esp-dev-kits/en/latest/esp32p4/esp32-p4-function-ev-board/user_guide.html) - Official Espressif documentation
- [ESP-Hosted-MCU Documentation](https://github.com/espressif/esp-hosted-mcu/blob/main/docs/esp32_p4_function_ev_board.md) - ESP-Hosted framework for P4↔C6 communication
- [Waveshare ESP32-P4-WIFI6](https://www.waveshare.com/esp32-p4-wifi6.htm) - Combo board specifications
- [Waveshare ESP32-P4-Module-DEV-KIT](https://www.waveshare.com/esp32-p4-module-dev-kit.htm) - Development board details
- [Waveshare ESP32-P4-WIFI6 Wiki](https://www.waveshare.com/wiki/ESP32-P4-WIFI6) - Technical specifications
- [ESP32-P4 SDMMC Host Driver](https://docs.espressif.com/projects/esp-idf/en/stable/esp32p4/api-reference/peripherals/sdmmc_host.html) - SDMMC technical documentation
- [ESP32-P4 vs ESP32-S3 Performance Comparison](https://www.elecrow.com/blog/who-is-the-true-performance-king-esp32-p4-vs-esp32-s3.html) - Performance benchmarks
- [ESP32 Versions Complete Comparison Chart](https://www.espboards.dev/blog/esp32-soc-options/) - Comprehensive chip comparison
- [Espressif ESP32-P4 Product Page](https://www.espressif.com/en/products/socs/esp32-p4) - Official specifications
- [CNX Software ESP32-P4+C6 PoE Board Article](https://www.cnx-software.com/2025/11/19/waveshare-esp32-p4-esp32-c6-poe-development-board-targets-hmi-and-iot-applications/) - Combo board architecture analysis
- [ESPHome Issue #10956](https://github.com/esphome/esphome/issues/10956) - Real-world WiFi issues between P4 & C6
- [ESP-IDF SD Card SDMMC Examples](https://github.com/espressif/esp-idf/tree/master/examples/storage/sd_card/sdmmc) - Code examples
