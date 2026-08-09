// nomad_ui.cpp - implementation of the board independent UI API.

#include <Arduino.h>
#include <string.h>
#include "nomad_ui.h"
#include "board_config.h"

#if NOMAD_HAS_DISPLAY

#include "Display_Driver.h"
#include "LVGL_Driver.h"
#include "ui.h"
#include "ui_screen_mini.h"

static bool s_uiReady = false;
static int  s_page = 0;

// Scope guard around the LVGL lock. Every public setter below runs from a
// different task than the one calling lv_timer_handler(), so none of them may
// touch a widget unlocked.
namespace {
struct LvglGuard {
  bool held;
  explicit LvglGuard(uint32_t timeoutMs = 60) : held(Lvgl_Lock(timeoutMs)) {}
  ~LvglGuard() { if (held) Lvgl_Unlock(); }
  explicit operator bool() const { return held; }
};
}  // namespace

#define COLOUR_OK  lv_color_hex(0x3DDC84)
#define COLOUR_OFF lv_color_hex(0x4A5468)

static void fmt_bytes(uint64_t bytes, char *out, size_t outLen) {
  if (bytes >= (1024ULL * 1024ULL * 1024ULL)) {
    snprintf(out, outLen, "%.1f GB", (double)bytes / (1024.0 * 1024.0 * 1024.0));
  } else if (bytes >= (1024ULL * 1024ULL)) {
    snprintf(out, outLen, "%.0f MB", (double)bytes / (1024.0 * 1024.0));
  } else {
    snprintf(out, outLen, "%llu KB", (unsigned long long)(bytes / 1024ULL));
  }
}

void NomadUI_Init(void) {
  if (s_uiReady) return;
  LCD_Init();
  Lvgl_Init();
  ui_init();
  s_uiReady = true;
  NomadUI_Flush();
}

void NomadUI_Flush(void) {
  for (int i = 0; i < 4; ++i) {
    if (Lvgl_Lock(200)) {
      lv_timer_handler();
      Lvgl_Unlock();
    }
    delay(6);
  }
}

void NomadUI_Tick(void) {
  LvglGuard g(20);
  if (!g) return;               // UI task mid-update; catch it next pass
  lv_timer_handler();
}

// Recursive mutex, so the setters can be called inside a held lock.
bool NomadUI_Lock(uint32_t timeoutMs) { return Lvgl_Lock(timeoutMs); }
void NomadUI_Unlock(void) { Lvgl_Unlock(); }

void NomadUI_SetRotation(bool flip180) {
  LvglGuard g(200);
  if (!g) return;
  LCD_SetRotation180(flip180);
  // MADCTL only changes how panel RAM is scanned out, so whatever was already
  // drawn stays mirrored until it is painted again.
  lv_obj_invalidate(lv_scr_act());
  lv_timer_handler();
}

void NomadUI_BootComplete(void) {
  LvglGuard g(200);
  if (!g) return;
  if (ui_MediaGen) {
    lv_textarea_set_text(ui_MediaGen, "");
    lv_obj_add_flag(ui_MediaGen, LV_OBJ_FLAG_HIDDEN);
  }
  // The boot spinner animates forever if it is left visible, which on a
  // partial-refresh panel means never-ending SPI traffic.
  if (ui_Spinner1) lv_obj_add_flag(ui_Spinner1, LV_OBJ_FLAG_HIDDEN);
  lv_timer_handler();
}

void NomadUI_Message(const char *text) {
  if (!ui_MediaGen) return;
  LvglGuard g;
  if (!g) return;
  lv_textarea_set_text(ui_MediaGen, text ? text : "");
  lv_obj_clear_flag(ui_MediaGen, LV_OBJ_FLAG_HIDDEN);
}

void NomadUI_ClearMessage(void) {
  if (!ui_MediaGen) return;
  LvglGuard g;
  if (!g) return;
  lv_textarea_set_text(ui_MediaGen, "");
  lv_obj_add_flag(ui_MediaGen, LV_OBJ_FLAG_HIDDEN);
}

// lv_label_set_text() always invalidates the label, so these setters - which
// are polled several times a second - only touch LVGL when the value actually
// moved. Otherwise the panel would be redrawing text that never changes.
void NomadUI_SetSSID(const char *ssid) {
  static char last[40] = "";
  if (!ui_ssidlabel || !ssid) return;
  if (strncmp(last, ssid, sizeof(last) - 1) == 0) return;
  snprintf(last, sizeof(last), "%s", ssid);

  LvglGuard g;
  if (!g) return;
  lv_label_set_text(ui_ssidlabel, ssid);
}

void NomadUI_SetUsers(int count) {
  static int last = -1;
  if (!ui_userlabel || count == last) return;
  last = count;

  LvglGuard g;
  if (!g) return;
  char buf[12];
  snprintf(buf, sizeof(buf), "%d", count);
  lv_label_set_text(ui_userlabel, buf);
}

// ==========================================================================
#if NOMAD_UI_LAYOUT == NOMAD_UI_LANDSCAPE_MINI
// ==========================================================================

void NomadUI_SetIP(const char *ip) {
  static char last[24] = "";
  if (!ui_iplabel || !ip) return;
  if (strncmp(last, ip, sizeof(last) - 1) == 0) return;
  snprintf(last, sizeof(last), "%s", ip);

  LvglGuard g;
  if (!g) return;
  lv_label_set_text(ui_iplabel, ip);
}

void NomadUI_SetWifiOk(bool ok) {
  LvglGuard g;
  if (!g) return;
  if (ui_wifi) {
    lv_obj_set_style_text_color(ui_wifi, ok ? COLOUR_OK : COLOUR_OFF,
                                LV_PART_MAIN | LV_STATE_DEFAULT);
  }
}

void NomadUI_SetSdOk(bool ok) {
  LvglGuard g;
  if (!g) return;
  if (ui_SDcard) {
    lv_obj_set_style_text_color(ui_SDcard, ok ? COLOUR_OK : COLOUR_OFF,
                                LV_PART_MAIN | LV_STATE_DEFAULT);
  }
}

void NomadUI_SetSdUsage(int percent, uint64_t usedBytes, uint64_t totalBytes) {
  if (percent < 0) percent = 0;
  if (percent > 100) percent = 100;

  LvglGuard g;
  if (!g) return;

  if (ui_sdbar) lv_bar_set_value(ui_sdbar, percent, LV_ANIM_OFF);

  char buf[24];
  if (ui_Label2) {
    snprintf(buf, sizeof(buf), "SD %d%%", percent);
    lv_label_set_text(ui_Label2, buf);
  }

  if (totalBytes == 0) return;

  if (ui_storeUsed) {
    fmt_bytes(usedBytes, buf, sizeof(buf));
    lv_label_set_text(ui_storeUsed, buf);
  }
  if (ui_storeFree) {
    fmt_bytes(totalBytes > usedBytes ? totalBytes - usedBytes : 0, buf, sizeof(buf));
    lv_label_set_text(ui_storeFree, buf);
  }
  if (ui_storeTotal) {
    fmt_bytes(totalBytes, buf, sizeof(buf));
    lv_label_set_text(ui_storeTotal, buf);
  }
}

void NomadUI_SetSysStats(uint32_t freeHeapKB, uint32_t freePsramKB, float tempC, uint32_t uptimeSec) {
  LvglGuard g;
  if (!g) return;
  char buf[24];

  if (ui_heaplabel) {
    snprintf(buf, sizeof(buf), "%lu KB", (unsigned long)freeHeapKB);
    lv_label_set_text(ui_heaplabel, buf);
  }
  if (ui_psramlabel) {
    if (freePsramKB == 0) {
      lv_label_set_text(ui_psramlabel, "none");
    } else {
      snprintf(buf, sizeof(buf), "%lu KB", (unsigned long)freePsramKB);
      lv_label_set_text(ui_psramlabel, buf);
    }
  }
  if (ui_templabel) {
    snprintf(buf, sizeof(buf), "%.1f C", (double)tempC);
    lv_label_set_text(ui_templabel, buf);
  }
  if (ui_uptimelabel) {
    uint32_t h = uptimeSec / 3600;
    uint32_t m = (uptimeSec % 3600) / 60;
    uint32_t s = uptimeSec % 60;
    if (h) snprintf(buf, sizeof(buf), "%luh %lum", (unsigned long)h, (unsigned long)m);
    else   snprintf(buf, sizeof(buf), "%lum %lus", (unsigned long)m, (unsigned long)s);
    lv_label_set_text(ui_uptimelabel, buf);
  }
}

int NomadUI_PageCount(void) {
  return NOMAD_MINI_PAGE_COUNT;
}

int NomadUI_GetPage(void) {
  return s_page;
}

void NomadUI_NextPage(void) {
  if (!ui_mini_page[0]) return;
  LvglGuard g;
  if (!g) return;

  s_page = (s_page + 1) % NOMAD_MINI_PAGE_COUNT;
  for (int i = 0; i < NOMAD_MINI_PAGE_COUNT; ++i) {
    if (!ui_mini_page[i]) continue;
    if (i == s_page) lv_obj_clear_flag(ui_mini_page[i], LV_OBJ_FLAG_HIDDEN);
    else             lv_obj_add_flag(ui_mini_page[i], LV_OBJ_FLAG_HIDDEN);
  }

  for (int i = 0; i < NOMAD_MINI_PAGE_COUNT; ++i) {
    if (!ui_pagedot[i]) continue;
    lv_obj_set_style_bg_color(ui_pagedot[i],
                              (i == s_page) ? lv_color_hex(0xA5E0F9) : COLOUR_OFF,
                              LV_PART_MAIN | LV_STATE_DEFAULT);
  }
}

// ==========================================================================
#else  // NOMAD_UI_PORTRAIT_TALL - the original 172x320 SquareLine layout
// ==========================================================================

void NomadUI_SetIP(const char *ip) {
  (void)ip;  // the tall layout shows the SSID only
}

void NomadUI_SetWifiOk(bool ok) {
  if (!ui_wifi) return;
  LvglGuard g;
  if (!g) return;
  if (ok) lv_obj_add_state(ui_wifi, LV_STATE_CHECKED);
  else    lv_obj_clear_state(ui_wifi, LV_STATE_CHECKED);
}

void NomadUI_SetSdOk(bool ok) {
  if (!ui_SDcard) return;
  LvglGuard g;
  if (!g) return;
  if (ok) lv_obj_add_state(ui_SDcard, LV_STATE_CHECKED);
  else    lv_obj_clear_state(ui_SDcard, LV_STATE_CHECKED);
}

void NomadUI_SetSdUsage(int percent, uint64_t usedBytes, uint64_t totalBytes) {
  (void)usedBytes;
  (void)totalBytes;
  if (percent < 0) percent = 0;
  if (percent > 100) percent = 100;
  LvglGuard g;
  if (!g) return;
  if (ui_sdbar) lv_bar_set_value(ui_sdbar, percent, LV_ANIM_OFF);
}

void NomadUI_SetSysStats(uint32_t freeHeapKB, uint32_t freePsramKB, float tempC, uint32_t uptimeSec) {
  (void)freeHeapKB;
  (void)freePsramKB;
  (void)tempC;
  (void)uptimeSec;
}

int NomadUI_PageCount(void) {
  return 1;
}

int NomadUI_GetPage(void) {
  return 0;
}

void NomadUI_NextPage(void) {
}

#endif  // layout

#else  // !NOMAD_HAS_DISPLAY
// =========================================================================
// Headless boards (the ESP32-P4 dev board). No panel is fitted, so LVGL and
// the display driver are not compiled at all - this is the whole reason the
// firmware talks to the screen through NomadUI_* instead of poking widgets.
//
// The status the panel used to carry - SSID, IP, client count, SD state - is
// all in the web UI already. What is genuinely useful without a screen is
// seeing it during boot, before the web server is up, so the values that
// change rarely go to serial once each. The polled setters stay silent; they
// are called several times a second and would drown the log.
// =========================================================================

void NomadUI_Init(void) {
  Serial.println("[UI] headless build - no panel on this board");
}

void NomadUI_Flush(void) {}
void NomadUI_Tick(void) {}
bool NomadUI_Lock(uint32_t timeoutMs) { (void)timeoutMs; return true; }
void NomadUI_Unlock(void) {}
void NomadUI_SetRotation(bool flip180) { (void)flip180; }
void NomadUI_BootComplete(void) {}
void NomadUI_ClearMessage(void) {}

void NomadUI_Message(const char *text) {
  if (text && *text) Serial.printf("[UI] %s\n", text);
}

// Print only on change: these are polled, and an unchanged value every 500 ms
// would make the serial log useless for anything else.
void NomadUI_SetSSID(const char *ssid) {
  static char last[40] = "";
  if (!ssid || !strcmp(last, ssid)) return;
  snprintf(last, sizeof(last), "%s", ssid);
  Serial.printf("[UI] SSID: %s\n", ssid);
}

void NomadUI_SetIP(const char *ip) {
  static char last[24] = "";
  if (!ip || !strcmp(last, ip)) return;
  snprintf(last, sizeof(last), "%s", ip);
  Serial.printf("[UI] IP: %s\n", ip);
}

void NomadUI_SetUsers(int count) {
  static int last = -1;
  if (count == last) return;
  last = count;
  Serial.printf("[UI] clients: %d\n", count);
}

void NomadUI_SetWifiOk(bool ok) {
  static int last = -1;
  if ((int)ok == last) return;
  last = (int)ok;
  Serial.printf("[UI] wifi: %s\n", ok ? "up" : "down");
}

void NomadUI_SetSdOk(bool ok) {
  static int last = -1;
  if ((int)ok == last) return;
  last = (int)ok;
  Serial.printf("[UI] sd: %s\n", ok ? "mounted" : "absent");
}

void NomadUI_SetSdUsage(int percent, uint64_t usedBytes, uint64_t totalBytes) {
  static int last = -1;
  if (percent == last) return;
  last = percent;
  Serial.printf("[UI] sd usage: %d%% (%llu of %llu MB)\n", percent,
                (unsigned long long)(usedBytes / (1024ULL * 1024ULL)),
                (unsigned long long)(totalBytes / (1024ULL * 1024ULL)));
}

void NomadUI_SetSysStats(uint32_t freeHeapKB, uint32_t freePsramKB, float tempC,
                         uint32_t uptimeSec) {
  (void)freeHeapKB; (void)freePsramKB; (void)tempC; (void)uptimeSec;
}

// No screen, so no pages to cycle. A short press on the boot button does
// nothing here; the long press still enters USB mass-storage mode.
void NomadUI_NextPage(void) {}
int  NomadUI_GetPage(void) { return 0; }
int  NomadUI_PageCount(void) { return 0; }

#endif  // NOMAD_HAS_DISPLAY
