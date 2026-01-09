# ESP32-C6 / ESP32-P4 Porting Guide for Jcorp Nomad

## Executive Summary

**Current Status:** Jcorp Nomad is designed for **ESP32-S3** with hardware SDMMC controller.

**Hardware Compatibility:**
- ❌ **ESP32-C6**: NOT compatible - lacks SDMMC hardware, requires full SD card rewrite to SPI
- ⚠️ **ESP32-P4**: Partially compatible - has SDMMC but requires pin remapping and testing

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

## Questions for Original Coder

1. **Why ESP32-C6/P4?** What specific feature drove this hardware change?
   - WiFi 6? (C6) - probably not needed for local AP
   - More RAM? (P4) - could help with indexing
   - Cost? (C6 is cheaper)
   - Availability?

2. **Which exact dev board model?** Need specific part number for pin mappings

3. **Is it a combo board?** (e.g., P4 with C6 WiFi module integrated)

4. **Can we reconsider ESP32-S3?** It's genuinely the best fit for this use case

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

**Document Version:** 1.0
**Date:** 2026-01-09
**Based on:** Jcorp Nomad main branch (commit c4d4b30)
