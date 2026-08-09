/*
 * NomadP4Probe - can this board run Jcorp Nomad at all?
 *
 * The ESP32-P4 has no radio. Wi-Fi comes from the on-board ESP32-C6 over
 * ESP-Hosted, and Nomad is nothing but a SoftAP captive portal: softAP(),
 * DNSServer, AsyncWebServer, softAPgetStationNum(). If that path does not work
 * on this board then no amount of porting saves it, so this sketch exercises
 * exactly that stack and nothing else, before any effort goes into the port.
 *
 * It answers, in order:
 *   1. Chip, flash, PSRAM        - is the 32 MB PSRAM actually visible?
 *   2. Host <-> C6 hosted link   - is the co-processor talking, at what version?
 *   3. SoftAP                    - does an AP come up, with an IP?
 *   4. DNS + async web server    - the real captive-portal stack, on port 80
 *   5. microSD                   - SDMMC 4-bit, sweeping candidate pin sets
 *   6. Live client count         - connect a phone and watch it register
 *
 * Steps 3-4 are the ones that decide the port. 5 is a pin-map hunt: this board's
 * SD wiring is not published anywhere I could verify, so the sketch sweeps
 * candidates and prints what worked rather than shipping a guessed pin map.
 *
 * Build: nomad-setup flash --board p4-dev --sketch firmware/NomadP4Probe
 * Then open the serial monitor at 115200.
 */

#include <Arduino.h>
#include <WiFi.h>
#include <DNSServer.h>
#include <SD_MMC.h>
#include <ESPAsyncWebServer.h>

#ifndef CONFIG_IDF_TARGET_ESP32P4
#warning "This probe is for the ESP32-P4. On other targets it still runs, but the hosted-link section is meaningless."
#endif

static const char *AP_SSID = "NomadP4Probe";
static const char *AP_PASS = "";          // open, like Nomad's default
static const uint8_t AP_CHANNEL = 1;
static const uint8_t AP_MAX_CLIENTS = 8;  // matches Nomad's MAX_CLIENTS
static const byte DNS_PORT = 53;

DNSServer dnsServer;
AsyncWebServer server(80);

static bool apUp = false;
static bool webUp = false;
static bool sdUp = false;
static String sdHow = "not mounted";

// ------------------------------------------------------------------ 1. chip --

static void reportChip() {
  Serial.println("\n--- 1. Chip ---");
  Serial.printf("  target        : %s\n", ESP.getChipModel());
  Serial.printf("  revision      : %d\n", ESP.getChipRevision());
  Serial.printf("  cores         : %d\n", ESP.getChipCores());
  Serial.printf("  cpu freq      : %lu MHz\n", (unsigned long)getCpuFrequencyMhz());
  Serial.printf("  flash         : %.1f MB\n", ESP.getFlashChipSize() / (1024.0 * 1024.0));
  Serial.printf("  free heap     : %lu bytes\n", (unsigned long)ESP.getFreeHeap());

  size_t psram = ESP.getPsramSize();
  Serial.printf("  PSRAM         : %.1f MB\n", psram / (1024.0 * 1024.0));
  if (psram == 0) {
    Serial.println("    *** No PSRAM. Enable it in the board menu (PSRAM: Enabled).");
    Serial.println("    *** Nomad needs it; the module has 32 MB.");
  } else if (psram < 16 * 1024 * 1024) {
    Serial.printf("    note: expected ~32 MB on this module, saw %.1f MB.\n",
                  psram / (1024.0 * 1024.0));
  }
}

// ------------------------------------------------------ 2. the C6 hosted link --

static void reportHostedLink() {
  Serial.println("\n--- 2. Wi-Fi co-processor (ESP32-C6 over ESP-Hosted) ---");
  Serial.println("  The P4 has no radio of its own. Everything below depends on");
  Serial.println("  the C6 answering over SDIO.");

  // The stock esp32p4 Arduino variant is the ESP32-P4 *Function EV Board* -
  // its own header says so - and these pin numbers come from it, not from the
  // Guition board. If Guition wired the C6 anywhere else, the link cannot come
  // up and no amount of Nomad code fixes it; it needs a custom variant. So
  // print what this build actually compiled in, and compare it to the
  // schematic.
#ifdef BOARD_HAS_SDIO_ESP_HOSTED
  Serial.printf("  hosted SDIO pins compiled in: CLK %d CMD %d D0 %d D1 %d D2 %d D3 %d, reset %d\n",
                BOARD_SDIO_ESP_HOSTED_CLK, BOARD_SDIO_ESP_HOSTED_CMD,
                BOARD_SDIO_ESP_HOSTED_D0, BOARD_SDIO_ESP_HOSTED_D1,
                BOARD_SDIO_ESP_HOSTED_D2, BOARD_SDIO_ESP_HOSTED_D3,
                BOARD_SDIO_ESP_HOSTED_RESET);
  Serial.println("    ^ these are the EV-board's pins. Check them against this");
  Serial.println("      board's schematic - a mismatch is the first thing to rule out.");
#else
  Serial.println("  *** This build has no ESP-Hosted SDIO configuration at all.");
  Serial.println("  *** Wi-Fi cannot work. Wrong board selected in the FQBN?");
#endif

  // Bringing the driver up is itself the test: on a broken or version-mismatched
  // hosted link, mode() fails or the MAC comes back all zeroes.
  if (!WiFi.mode(WIFI_AP)) {
    Serial.println("  FAIL: WiFi.mode(WIFI_AP) returned false.");
    Serial.println("    *** The host cannot reach the C6. Usual causes:");
    Serial.println("    *** - the C6's ESP-Hosted slave firmware is older than the");
    Serial.println("    ***   host core expects (boards ship v0.0.6; recent cores");
    Serial.println("    ***   want newer). Reflash the C6 via its own USB port.");
    Serial.println("    *** - SDIO wiring/pull-ups, if this is not the stock board.");
    return;
  }
  Serial.println("  ok  WiFi.mode(WIFI_AP) accepted");

  String mac = WiFi.macAddress();
  Serial.printf("  MAC           : %s\n", mac.c_str());
  if (mac == "00:00:00:00:00:00" || mac.length() < 17) {
    Serial.println("    *** A zero MAC means the link is up but the C6 is not");
    Serial.println("    *** answering properly. Treat Wi-Fi as broken.");
  }
}

// ----------------------------------------------------------------- 3. softAP --

static void bringUpAp() {
  Serial.println("\n--- 3. SoftAP ---");
  Serial.println("  This is the call Nomad makes, with the same arguments.");

  // Exactly Nomad's call: WiFi.softAP(ssid, pass, channel, hidden, max_conn)
  apUp = WiFi.softAP(AP_SSID, strlen(AP_PASS) ? AP_PASS : nullptr,
                     AP_CHANNEL, 0, AP_MAX_CLIENTS);
  if (!apUp) {
    Serial.println("  FAIL: WiFi.softAP() returned false.");
    Serial.println("    *** Nomad cannot run on this board until this works.");
    Serial.println("    *** SoftAP over ESP-Hosted is the least-proven part of");
    Serial.println("    *** the P4 story - report this with the C6 firmware version.");
    return;
  }

  IPAddress ip = WiFi.softAPIP();
  Serial.printf("  ok  AP '%s' up, IP %s\n", AP_SSID, ip.toString().c_str());
  if (ip == IPAddress(0, 0, 0, 0)) {
    Serial.println("    *** softAP() succeeded but the IP is 0.0.0.0, so the DHCP");
    Serial.println("    *** server did not claim its pool. Clients will associate");
    Serial.println("    *** and then fail to get an address.");
    apUp = false;
  }
}

// -------------------------------------------------- 4. DNS + async web server --

static void bringUpWeb() {
  Serial.println("\n--- 4. Captive portal stack ---");
  if (!apUp) {
    Serial.println("  skipped - no AP to serve on.");
    return;
  }

  if (!dnsServer.start(DNS_PORT, "*", WiFi.softAPIP())) {
    Serial.println("  FAIL: DNSServer.start() returned false (port 53 in use?).");
  } else {
    Serial.println("  ok  DNS wildcard responder on port 53");
  }

  server.on("/", HTTP_GET, [](AsyncWebServerRequest *req) {
    String body = "<!doctype html><meta name=viewport content='width=device-width'>"
                  "<h1>Nomad P4 probe</h1><p>The async web server works on this board.</p><ul>";
    body += "<li>PSRAM: " + String(ESP.getPsramSize() / (1024 * 1024)) + " MB</li>";
    body += "<li>SD: " + sdHow + "</li>";
    body += "<li>Clients: " + String(WiFi.softAPgetStationNum()) + "</li>";
    body += "</ul>";
    req->send(200, "text/html", body);
  });
  // Captive-portal probes from phones; answering these is what makes the
  // "sign in to network" sheet appear.
  server.onNotFound([](AsyncWebServerRequest *req) {
    req->redirect("http://" + WiFi.softAPIP().toString() + "/");
  });

  server.begin();
  webUp = true;
  Serial.printf("  ok  AsyncWebServer listening on http://%s/\n",
                WiFi.softAPIP().toString().c_str());
}

// --------------------------------------------------------------- 5. microSD --

struct SdPinSet {
  const char *name;
  int clk, cmd, d0, d1, d2, d3;
};

// Slot 0's IOMUX pins, from ESP-IDF soc/esp32p4/include/soc/sdmmc_pins.h. The
// P4 can also route SDMMC through the GPIO matrix (SOC_SDMMC_USE_GPIO_MATRIX),
// so a board is free to wire the card anywhere - but IOMUX is what the Arduino
// variant selects and what a board following the reference design uses.
//
// There is deliberately only one entry. An earlier version of this sketch swept
// "alternative" pin sets that were invented rather than sourced, and two of them
// were actively harmful on this board: {18,19,14,15,16,17} are the SDIO pins
// carrying the ESP32-C6 Wi-Fi link, and {..37,38} are the console UART. Driving
// either as an SD bus breaks the thing you are trying to test. If the card does
// not appear on these pins, read the schematic - do not guess.
static const SdPinSet kCandidates[] = {
  {"slot 0 IOMUX", 43, 44, 39, 40, 41, 42},
};

// The card slot has its own power switch on the Function EV board, and GPIO
// 39-48 sit behind on-chip LDO VO4. Get either wrong and the card never powers
// up, which looks exactly like bad wiring.
#ifndef BOARD_SDMMC_POWER_PIN
#define BOARD_SDMMC_POWER_PIN -1
#endif
#ifndef BOARD_SDMMC_POWER_ON_LEVEL
#define BOARD_SDMMC_POWER_ON_LEVEL LOW
#endif

static void sdPowerOn() {
  if (BOARD_SDMMC_POWER_PIN < 0) {
    Serial.println("  no SD power-enable pin defined for this variant");
    return;
  }
  Serial.printf("  powering the slot: GPIO %d -> %s\n", (int)BOARD_SDMMC_POWER_PIN,
                BOARD_SDMMC_POWER_ON_LEVEL == LOW ? "LOW" : "HIGH");
  pinMode(BOARD_SDMMC_POWER_PIN, OUTPUT);
  digitalWrite(BOARD_SDMMC_POWER_PIN, BOARD_SDMMC_POWER_ON_LEVEL);
  delay(50);
}

static bool trySd(const SdPinSet &p, bool oneBit, int freq) {
  SD_MMC.end();
  delay(20);
  if (!SD_MMC.setPins(p.clk, p.cmd, p.d0, p.d1, p.d2, p.d3)) return false;
  // never format: a card that fails to mount must stay untouched
  if (!SD_MMC.begin("/sdcard", oneBit, false, freq, 5)) return false;
  return SD_MMC.cardType() != CARD_NONE;
}

static void sweepSd() {
  Serial.println("\n--- 5. microSD (SDIO / SDMMC) ---");
  Serial.println("  The P4 board has a 4-bit SDIO slot, so this should be much");
  Serial.println("  faster than the S3 dongle's plain SPI card.");
  sdPowerOn();

  const int freqs[] = {SDMMC_FREQ_HIGHSPEED, SDMMC_FREQ_DEFAULT, SDMMC_FREQ_PROBING};

  // The stock pins first: on a board wired to the reference design, begin()
  // without setPins() just works.
  SD_MMC.end();
  delay(20);
  if (SD_MMC.begin("/sdcard", false, false, SDMMC_FREQ_HIGHSPEED, 5) &&
      SD_MMC.cardType() != CARD_NONE) {
    sdUp = true;
    sdHow = "default pins, 4-bit";
    Serial.println("  MOUNTED on the core's default pins, 4-bit");
  }

  for (size_t i = 0; !sdUp && i < sizeof(kCandidates) / sizeof(kCandidates[0]); ++i) {
    const SdPinSet &p = kCandidates[i];
    for (int bits = 0; !sdUp && bits < 2; ++bits) {
      bool oneBit = (bits == 1);
      for (size_t f = 0; f < sizeof(freqs) / sizeof(freqs[0]); ++f) {
        Serial.printf("  trying %-18s %s @ %d kHz ... ",
                      p.name, oneBit ? "1-bit" : "4-bit", freqs[f]);
        if (trySd(p, oneBit, freqs[f])) {
          sdUp = true;
          sdHow = String(p.name) + (oneBit ? ", 1-bit" : ", 4-bit");
          Serial.println("MOUNTED");
          Serial.printf("    *** CLK %d CMD %d D0 %d D1 %d D2 %d D3 %d\n",
                        p.clk, p.cmd, p.d0, p.d1, p.d2, p.d3);
          Serial.println("    *** Put these in board_config.h.");
          break;
        }
        Serial.println("no");
      }
    }
  }

  if (!sdUp) {
    Serial.println("  No candidate pin set mounted a card.");
    Serial.println("    *** Is a FAT32 card inserted? If so the wiring differs from");
    Serial.println("    *** every guess here - check the board's schematic and add it");
    Serial.println("    *** to kCandidates.");
    return;
  }

  Serial.printf("  card size : %.2f GB\n",
                (double)SD_MMC.cardSize() / (1024.0 * 1024.0 * 1024.0));
  Serial.printf("  used      : %.2f GB of %.2f GB\n",
                (double)SD_MMC.usedBytes() / (1024.0 * 1024.0 * 1024.0),
                (double)SD_MMC.totalBytes() / (1024.0 * 1024.0 * 1024.0));
  Serial.println("  root listing:");
  File root = SD_MMC.open("/");
  if (root) {
    int n = 0;
    for (File e = root.openNextFile(); e && n < 15; e = root.openNextFile(), ++n) {
      Serial.printf("    %-30s %s\n", e.name(), e.isDirectory() ? "<dir>" : "");
      e.close();
    }
    root.close();
  }
}

// ------------------------------------------------------------------ verdict --

static void verdict() {
  Serial.println("\n=== Verdict ===");
  Serial.printf("  PSRAM        : %s\n", ESP.getPsramSize() ? "yes" : "NO - enable it");
  Serial.printf("  SoftAP       : %s\n", apUp ? "yes" : "NO");
  Serial.printf("  Web server   : %s\n", webUp ? "yes" : "NO");
  Serial.printf("  microSD      : %s\n", sdUp ? sdHow.c_str() : "NO");

  if (apUp && webUp) {
    Serial.println("\n  The parts Nomad is built on work. Porting is worth doing.");
    Serial.printf("  Join Wi-Fi '%s' and open http://%s/\n",
                  AP_SSID, WiFi.softAPIP().toString().c_str());
  } else {
    Serial.println("\n  The captive-portal stack does not work on this board yet.");
    Serial.println("  Nomad cannot run until it does - this is the C6 hosted link,");
    Serial.println("  not anything in Nomad. Send this whole log back.");
  }
  Serial.println("\n  Watching for clients. Connect a phone.\n");
}

void setup() {
  Serial.begin(115200);
  uint32_t t0 = millis();
  while (!Serial && millis() - t0 < 3000) delay(10);

  Serial.println("\n\n================================================");
  Serial.println(" Nomad ESP32-P4 capability probe");
  Serial.println("================================================");

  reportChip();
  reportHostedLink();
  bringUpAp();
  bringUpWeb();
  sweepSd();
  verdict();
}

void loop() {
  if (webUp) dnsServer.processNextRequest();

  static uint32_t last = 0;
  static int lastCount = -1;
  if (millis() - last > 1000) {
    last = millis();
    int n = apUp ? WiFi.softAPgetStationNum() : 0;
    if (n != lastCount) {
      lastCount = n;
      Serial.printf("  clients connected: %d\n", n);
    }
  }
  delay(5);
}
