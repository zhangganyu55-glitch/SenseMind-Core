/*
 * SenseMind H3-05 product UI for the 1.54" 240x240 ST7789V panel.
 *
 * Rendering uses one 240x16 band buffer (7.5 KB), not a full frame buffer.
 * A page switch redraws all bands; normal 1 Hz updates redraw only the bands
 * that contain changed values.  BLE callbacks, the sensor loop and the button
 * ISR only update a small mutex-protected snapshot / event queue; all SPI
 * drawing stays in the low-priority UI thread.
 *
 * HR and SpO2 are deliberately shown as "--": no verified algorithm runs on
 * the device.  The motion card shows a real accelerometer vector magnitude and
 * "MONITORING"; it does not invent an activity classification.
 */
#include <errno.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include <zephyr/device.h>
#include <zephyr/drivers/display.h>
#include <zephyr/kernel.h>
#include <zephyr/sys/byteorder.h>
#include <zephyr/sys/printk.h>
#include <zephyr/sys/util.h>

#include "buttons.h"
#include "display_ui.h"
#include "font_1016.h"
#include "font_1524.h"
#include "font_2032.h"
#include "sm_logo_120.h"
#include "sm_logo_32.h"

#define UI_W 240
#define UI_H 240
#define UI_BAND 16
#define UI_BANDS (UI_H / UI_BAND)
#define PPG_N 120

#define RGB565(r, g, b) \
	((uint16_t)((((r) & 0xF8) << 8) | (((g) & 0xFC) << 3) | ((b) >> 3)))

/* Product palette, H3-05 section 2. */
#define C_BG      RGB565(0x08, 0x0D, 0x16)
#define C_CARD    RGB565(0x17, 0x21, 0x30)
#define C_CARD_HI RGB565(0x20, 0x2C, 0x3E)
#define C_LINE    RGB565(0x2A, 0x36, 0x48)
#define C_DOT     RGB565(0x3E, 0x4C, 0x5E)
#define C_PLOT_BG RGB565(0x0C, 0x13, 0x1E)
#define C_BRAND   RGB565(0x42, 0xE8, 0xD2)
#define C_TEXT    RGB565(0xF5, 0xF7, 0xFA)
#define C_MUTED   RGB565(0x98, 0xA5, 0xB5)
#define C_OK      RGB565(0x43, 0xD9, 0xA3)
#define C_WARN    RGB565(0xF2, 0xB9, 0x5C)
#define C_ERR     RGB565(0xF3, 0x6B, 0x75)

enum ui_page {
	PAGE_HEALTH = 0,
	PAGE_HEALTH_DETAIL,
	PAGE_MOTION,
	PAGE_DEVICE,
	PAGE_MOTION_DETAIL,
	PAGE_DEVICE_DEBUG,
	PAGE_MENU,
};

enum data_state {
	DATA_LIVE = 0,
	DATA_STALE,
	DATA_OFF,
};

struct ui_snapshot {
	bool ble_connected;
	bool ble_subscribed;
	bool imu_ok;
	bool ppg_ok;
	int16_t imu[6];
	uint32_t red;
	uint32_t ir;
	uint32_t seq;
	uint32_t overruns;
	uint32_t ppg[PPG_N];
	uint16_t head;
	uint16_t count;
	uint32_t ppg_total;
	int64_t ppg_last_ms;
	int64_t imu_last_ms;
	char device_id[40];
	char boot_id[40];
	char fw[16];
};

struct ui_font {
	const uint8_t *data;
	uint8_t w;
	uint8_t bytes_per_col;
};

static struct ui_snapshot ui;
static struct ui_snapshot last_snap;
static K_MUTEX_DEFINE(ui_lock);

static const struct ui_font font_small = {
	.data = &sm_font_1016[0][0], .w = 10, .bytes_per_col = 2,
};
static const struct ui_font font_med = {
	.data = &sm_font_1524[0][0], .w = 15, .bytes_per_col = 3,
};
static const struct ui_font font_big = {
	.data = &sm_font_2032[0][0], .w = 20, .bytes_per_col = 4,
};

static uint16_t band_buf[UI_W * UI_BAND];
static int band_y;

static enum ui_page current_page = PAGE_HEALTH;
static enum ui_page menu_return = PAGE_HEALTH;
static uint8_t menu_index;
static uint32_t button_event_count;
static uint32_t last_refresh_ms;
static uint32_t max_refresh_ms;
static uint32_t dirty_mask;
static uint32_t ui_stack_unused;
static int64_t accent_until;
static bool accent_drawn;
static enum data_state last_ppg_state;
static enum data_state last_imu_state;

static inline uint16_t be16(uint16_t c)
{
	return sys_cpu_to_be16(c);
}

static inline int iabs(int v)
{
	return v < 0 ? -v : v;
}

static uint32_t isqrt32(uint32_t n)
{
	if (n == 0) {
		return 0;
	}

	uint32_t x = n;
	uint32_t y = (x + 1) / 2;

	while (y < x) {
		x = y;
		y = (x + n / x) / 2;
	}

	return x;
}

static void band_clear(uint16_t c)
{
	uint16_t v = be16(c);

	for (int i = 0; i < UI_W * UI_BAND; i++) {
		band_buf[i] = v;
	}
}

static void cpx(int x, int y, uint16_t c)
{
	if ((unsigned)x < UI_W && y >= band_y && y < band_y + UI_BAND) {
		band_buf[(y - band_y) * UI_W + x] = be16(c);
	}
}

static void canvas_fill_rect(int x, int y, int w, int h, uint16_t c)
{
	if (w <= 0 || h <= 0) {
		return;
	}

	int x0 = MAX(0, x);
	int x1 = MIN(UI_W, x + w);
	int y0 = MAX(band_y, y);
	int y1 = MIN(band_y + UI_BAND, y + h);
	uint16_t v = be16(c);

	for (int yy = y0; yy < y1; yy++) {
		for (int xx = x0; xx < x1; xx++) {
			band_buf[(yy - band_y) * UI_W + xx] = v;
		}
	}
}

static void canvas_hline(int x, int y, int w, uint16_t c)
{
	for (int xx = x; xx < x + w; xx++) {
		cpx(xx, y, c);
	}
}

static void canvas_vline(int x, int y, int h, uint16_t c)
{
	for (int yy = y; yy < y + h; yy++) {
		cpx(x, yy, c);
	}
}

static void canvas_rect(int x, int y, int w, int h, uint16_t c)
{
	if (w <= 0 || h <= 0) {
		return;
	}

	canvas_hline(x, y, w, c);
	canvas_hline(x, y + h - 1, w, c);
	canvas_vline(x, y, h, c);
	canvas_vline(x + w - 1, y, h, c);
}

static void canvas_line(int x0, int y0, int x1, int y1, uint16_t c)
{
	int dx = iabs(x1 - x0);
	int sx = x0 < x1 ? 1 : -1;
	int dy = -iabs(y1 - y0);
	int sy = y0 < y1 ? 1 : -1;
	int err = dx + dy;

	while (1) {
		cpx(x0, y0, c);
		if (x0 == x1 && y0 == y1) {
			break;
		}
		int e2 = 2 * err;
		if (e2 >= dy) {
			err += dy;
			x0 += sx;
		}
		if (e2 <= dx) {
			err += dx;
			y0 += sy;
		}
	}
}

static void canvas_fill_circle(int cx, int cy, int r, uint16_t c)
{
	if (r < 0) {
		return;
	}

	for (int dy = -r; dy <= r; dy++) {
		int dx = (int)isqrt32((uint32_t)(r * r - dy * dy));

		canvas_hline(cx - dx, cy + dy, 2 * dx + 1, c);
	}
}

static void canvas_circle(int cx, int cy, int r, uint16_t c)
{
	if (r <= 0) {
		cpx(cx, cy, c);
		return;
	}

	int x = r;
	int y = 0;
	int err = 1 - r;

	while (x >= y) {
		cpx(cx + x, cy + y, c);
		cpx(cx + y, cy + x, c);
		cpx(cx - y, cy + x, c);
		cpx(cx - x, cy + y, c);
		cpx(cx - x, cy - y, c);
		cpx(cx - y, cy - x, c);
		cpx(cx + y, cy - x, c);
		cpx(cx + x, cy - y, c);

		y++;
		if (err < 0) {
			err += 2 * y + 1;
		} else {
			x--;
			err += 2 * (y - x) + 1;
		}
	}
}

static void canvas_fill_round_rect(int x, int y, int w, int h, int r, uint16_t c)
{
	if (w <= 0 || h <= 0) {
		return;
	}

	r = MIN(r, MIN(w / 2, h / 2));

	canvas_fill_rect(x + r, y, w - 2 * r, h, c);
	canvas_fill_rect(x, y + r, w, h - 2 * r, c);

	for (int dy = 0; dy < r; dy++) {
		int yy = r - dy;
		int dx = r - (int)isqrt32((uint32_t)(r * r - yy * yy));

		canvas_hline(x + dx, y + dy, w - 2 * dx, c);
		canvas_hline(x + dx, y + h - 1 - dy, w - 2 * dx, c);
	}
}

static void canvas_glyph(int x, int y, char ch, uint16_t c,
			 const struct ui_font *f, int scale)
{
	if (ch < 32 || ch > 126) {
		ch = ' ';
	}

	const uint8_t *g = f->data +
		((uint8_t)ch - 32) * f->w * f->bytes_per_col;
	int h = f->bytes_per_col * 8;

	for (int gx = 0; gx < f->w; gx++) {
		for (int gy = 0; gy < h; gy++) {
			uint8_t b = g[gx * f->bytes_per_col + (gy >> 3)];

			if (b & (1U << (gy & 7))) {
				canvas_fill_rect(x + gx * scale, y + gy * scale,
						 scale, scale, c);
			}
		}
	}
}

static void canvas_text(int x, int y, const char *s, uint16_t c,
			const struct ui_font *f, int scale)
{
	for (; *s; s++) {
		canvas_glyph(x, y, *s, c, f, scale);
		x += f->w * scale;
	}
}

static int text_width(const char *s, const struct ui_font *f, int scale)
{
	return (int)strlen(s) * f->w * scale;
}

static void text_small(int x, int y, const char *s, uint16_t c)
{
	canvas_text(x, y, s, c, &font_small, 1);
}

static void text_med(int x, int y, const char *s, uint16_t c)
{
	canvas_text(x, y, s, c, &font_med, 1);
}

static void text_big(int x, int y, const char *s, uint16_t c)
{
	canvas_text(x, y, s, c, &font_big, 1);
}

static void text_center(int y, const char *s, uint16_t c)
{
	text_small((UI_W - text_width(s, &font_small, 1)) / 2, y, s, c);
}

static void text_right(int x_right, int y, const char *s, uint16_t c)
{
	text_small(x_right - text_width(s, &font_small, 1), y, s, c);
}

static void canvas_logo32(int x, int y)
{
	int y0 = MAX(y, band_y);
	int y1 = MIN(y + 32, band_y + UI_BAND);

	for (int yy = y0; yy < y1; yy++) {
		for (int xx = x; xx < x + 32; xx++) {
			if ((unsigned)xx < UI_W) {
				band_buf[(yy - band_y) * UI_W + xx] =
					sm_logo_32[(yy - y) * 32 + (xx - x)];
			}
		}
	}
}

static void canvas_logo120(int x, int y)
{
	int y0 = MAX(y, band_y);
	int y1 = MIN(y + 120, band_y + UI_BAND);

	for (int yy = y0; yy < y1; yy++) {
		for (int xx = x; xx < x + 120; xx++) {
			if ((unsigned)xx < UI_W) {
				band_buf[(yy - band_y) * UI_W + xx] =
					sm_logo_120[(yy - y) * 120 + (xx - x)];
			}
		}
	}
}

static void draw_card(int x, int y, int w, int h, int r, bool selected)
{
	uint16_t fill = selected ? C_CARD_HI : C_CARD;
	uint16_t border = selected ? C_BRAND : C_LINE;

	canvas_fill_round_rect(x, y, w, h, r, border);
	canvas_fill_round_rect(x + 1, y + 1, w - 2, h - 2, r - 1, fill);
}

static void draw_dashes(int cx, int y, int bar_w, int bar_h, int gap, uint16_t c)
{
	int total = bar_w * 2 + gap;
	int x = cx - total / 2;

	canvas_fill_round_rect(x, y, bar_w, bar_h, bar_h / 2, c);
	canvas_fill_round_rect(x + bar_w + gap, y, bar_w, bar_h, bar_h / 2, c);
}

static void format_accel(char *out, size_t n, int16_t raw, bool two_decimals)
{
	int32_t mg = (int32_t)raw * 1000 / 16384;
	bool neg = mg < 0;
	uint32_t a = (uint32_t)(neg ? -mg : mg);

	if (two_decimals) {
		uint32_t h = (a + 5) / 10;

		snprintf(out, n, "%s%lu.%02lu", neg ? "-" : "",
			 (unsigned long)(h / 100), (unsigned long)(h % 100));
	} else {
		uint32_t t = (a + 50) / 100;

		snprintf(out, n, "%s%lu.%lu", neg ? "-" : "",
			 (unsigned long)(t / 10), (unsigned long)(t % 10));
	}
}

static void format_dps(char *out, size_t n, int16_t raw)
{
	int32_t dps10 = (int32_t)raw * 10 / 131;
	bool neg = dps10 < 0;
	uint32_t a = (uint32_t)(neg ? -dps10 : dps10);

	snprintf(out, n, "%s%lu.%lu", neg ? "-" : "",
		 (unsigned long)(a / 10), (unsigned long)(a % 10));
}

static void format_g1(char *out, size_t n, uint32_t mg)
{
	uint32_t t = (mg + 50) / 100;

	snprintf(out, n, "%lu.%lu", (unsigned long)(t / 10),
		 (unsigned long)(t % 10));
}

static void format_age(char *out, size_t n, int64_t age_ms)
{
	if (age_ms < 0) {
		age_ms = 0;
	}

	if (age_ms < 1000) {
		snprintf(out, n, "%llums", (long long)age_ms);
	} else if (age_ms < 60000) {
		snprintf(out, n, "%llds", (long long)(age_ms / 1000));
	} else {
		snprintf(out, n, "%lldm", (long long)(age_ms / 60000));
	}
}

static void format_uptime(char *out, size_t n, int64_t now_ms)
{
	uint32_t sec = (uint32_t)(now_ms / 1000);

	snprintf(out, n, "%02u:%02u:%02u",
		 (unsigned)((sec / 3600U) % 100U),
		 (unsigned)((sec / 60U) % 60U),
		 (unsigned)(sec % 60U));
}

static uint32_t accel_mg(int16_t raw)
{
	int32_t mg = (int32_t)raw * 1000 / 16384;

	return (uint32_t)(mg < 0 ? -mg : mg);
}

static uint32_t vector_mg(const struct ui_snapshot *s)
{
	uint32_t x = accel_mg(s->imu[0]);
	uint32_t y = accel_mg(s->imu[1]);
	uint32_t z = accel_mg(s->imu[2]);

	return isqrt32(x * x + y * y + z * z);
}

static uint32_t gyro_dps10(const struct ui_snapshot *s)
{
	uint32_t x = (uint32_t)(iabs(s->imu[3]) * 10 / 131);
	uint32_t y = (uint32_t)(iabs(s->imu[4]) * 10 / 131);
	uint32_t z = (uint32_t)(iabs(s->imu[5]) * 10 / 131);

	return isqrt32(x * x + y * y + z * z);
}

static enum data_state ppg_data_state(const struct ui_snapshot *s, int64_t now)
{
	if (!s->ppg_ok || s->count == 0) {
		return DATA_OFF;
	}

	int64_t age = now - s->ppg_last_ms;

	if (age > 5000) {
		return DATA_OFF;
	}
	if (age > 1200) {
		return DATA_STALE;
	}
	return DATA_LIVE;
}

static enum data_state imu_data_state(const struct ui_snapshot *s, int64_t now)
{
	if (!s->imu_ok) {
		return DATA_OFF;
	}

	int64_t age = now - s->imu_last_ms;

	if (age > 5000) {
		return DATA_OFF;
	}
	if (age > 1000) {
		return DATA_STALE;
	}
	return DATA_LIVE;
}

static uint16_t state_color(enum data_state s)
{
	switch (s) {
	case DATA_LIVE:
		return C_OK;
	case DATA_STALE:
		return C_WARN;
	default:
		return C_MUTED;
	}
}

static const char *ble_text(const struct ui_snapshot *s)
{
	if (s->ble_subscribed) {
		return "ON";
	}
	if (s->ble_connected) {
		return "LINK";
	}
	return "OFF";
}

static const char *ble_detail(const struct ui_snapshot *s)
{
	if (s->ble_subscribed) {
		return "SUB";
	}
	if (s->ble_connected) {
		return "LINK";
	}
	return "OFF";
}

static uint16_t ble_color(const struct ui_snapshot *s)
{
	if (s->ble_subscribed) {
		return C_OK;
	}
	if (s->ble_connected) {
		return C_WARN;
	}
	return C_MUTED;
}

static void short_id(const char *id, char *out, size_t n)
{
	size_t len = strlen(id);

	if (len == 0) {
		snprintf(out, n, "ID --");
		return;
	}

	const char *p = len > 12 ? id + len - 12 : id;

	snprintf(out, n, "ID %s", p);
}

static void take_snapshot(struct ui_snapshot *s)
{
	k_mutex_lock(&ui_lock, K_FOREVER);
	*s = ui;
	k_mutex_unlock(&ui_lock);
}

static int page_index(enum ui_page p)
{
	switch (p) {
	case PAGE_HEALTH:
		return 0;
	case PAGE_HEALTH_DETAIL:
		return 1;
	case PAGE_MOTION:
	case PAGE_MOTION_DETAIL:
		return 2;
	case PAGE_DEVICE:
	case PAGE_DEVICE_DEBUG:
		return 3;
	default:
		return -1;
	}
}

static void draw_topbar(const struct ui_snapshot *s, int64_t now)
{
	canvas_fill_rect(0, 0, UI_W, 40, C_BG);
	canvas_logo32(8, 4);
	text_small(48, 6, "SenseMind", C_TEXT);
	text_small(48, 24, "BAND", C_MUTED);

	canvas_fill_round_rect(178, 9, 52, 22, 11, C_LINE);
	canvas_fill_round_rect(179, 10, 50, 20, 10, C_CARD);
	canvas_fill_circle(189, 20, 4, ble_color(s));
	text_small(197, 13, s->ble_connected ? "ON" : "OFF",
		   s->ble_connected ? C_TEXT : C_MUTED);
	canvas_hline(0, 40, UI_W, (now < accent_until) ? C_BRAND : C_LINE);
}

static void draw_title(const char *title, const char *meta)
{
	text_med(12, 46, title, C_TEXT);

	if (meta != NULL) {
		text_right(228, 50, meta, C_MUTED);
	}
}

static void draw_ppg_wave(const struct ui_snapshot *s, int x0, int y0,
			  int w, int h, enum data_state state)
{
	canvas_fill_rect(x0, y0, w, h, C_PLOT_BG);

	for (int x = x0 + 40; x < x0 + w; x += 40) {
		canvas_vline(x, y0, h, C_LINE);
	}
	for (int y = y0 + 14; y < y0 + h; y += 14) {
		canvas_hline(x0, y, w, C_LINE);
	}
	canvas_rect(x0 - 1, y0 - 1, w + 2, h + 2, C_LINE);

	if (state == DATA_OFF || s->count < 2) {
		int tx = x0 + (w - text_width("NO DATA", &font_small, 1)) / 2;

		text_small(tx, y0 + h / 2 - 8, "NO DATA", C_MUTED);
		return;
	}

	uint32_t vmin = UINT32_MAX;
	uint32_t vmax = 0;

	for (uint16_t i = 0; i < s->count; i++) {
		uint16_t idx = (s->head + PPG_N - s->count + i) % PPG_N;
		uint32_t v = s->ppg[idx];

		vmin = MIN(vmin, v);
		vmax = MAX(vmax, v);
	}

	if (vmax <= vmin) {
		vmax = vmin + 1;
	}
	if (vmax - vmin < 40) {
		uint32_t mid = (vmin + vmax) / 2;

		vmin = mid > 20 ? mid - 20 : 0;
		vmax = vmin + 40;
	}

	uint16_t color = state == DATA_LIVE ? C_BRAND : C_MUTED;
	uint16_t start = (s->head + PPG_N - s->count) % PPG_N;
	int prev_x = 0;
	int prev_y = 0;

	for (uint16_t i = 0; i < s->count; i++) {
		uint16_t idx = (start + i) % PPG_N;
		uint32_t v = s->ppg[idx];
		int x = x0 + (int)((uint32_t)i * (w - 1) / (s->count - 1));
		int y = y0 + h - 1 -
			(int)((uint64_t)(v - vmin) * (h - 1) / (vmax - vmin));

		y = CLAMP(y, y0, y0 + h - 1);
		if (i == 0) {
			cpx(x, y, color);
		} else {
			canvas_line(prev_x, prev_y, x, y, color);
		}
		prev_x = x;
		prev_y = y;
	}

	canvas_fill_circle(prev_x - 2, prev_y, 2, color);
}

static void draw_posture(const struct ui_snapshot *s, int cx, int cy, int r)
{
	canvas_circle(cx, cy, r, C_LINE);
	canvas_circle(cx, cy, r / 2, C_LINE);
	canvas_hline(cx - r, cy, 2 * r + 1, C_LINE);
	canvas_vline(cx, cy - r, 2 * r + 1, C_LINE);

	if (!s->imu_ok) {
		canvas_fill_circle(cx, cy, 4, C_MUTED);
		return;
	}

	int dx = (int)((int32_t)s->imu[0] * r / 16384);
	int dy = (int)((int32_t)s->imu[1] * r / 16384);

	dx = CLAMP(dx, -(r - 8), r - 8);
	dy = CLAMP(dy, -(r - 8), r - 8);
	canvas_fill_circle(cx + dx, cy - dy, 5, C_BRAND);
	canvas_circle(cx + dx, cy - dy, 8, C_BRAND);
}

static void draw_health(const struct ui_snapshot *s, int64_t now)
{
	char b[8];
	enum data_state ps = ppg_data_state(s, now);

	draw_card(12, 50, 216, 94, 14, false);
	text_small(26, 62, "HEART RATE", C_MUTED);

	uint16_t pc = state_color(ps);

	canvas_fill_round_rect(146, 59, 68, 20, 10, C_LINE);
	canvas_fill_round_rect(147, 60, 66, 18, 9, C_CARD_HI);
	canvas_fill_circle(161, 69, 4, pc);
	text_small(170, 63, "PPG", pc);

	draw_dashes(120, 88, 30, 8, 10, C_TEXT);
	text_center(104, "BPM", C_MUTED);
	text_center(122, "RAW PPG ONLY", C_MUTED);

	draw_card(12, 150, 104, 58, 12, false);
	text_small(20, 156, "SPO2", C_MUTED);
	draw_dashes(64, 174, 18, 7, 8, C_TEXT);
	text_small(88, 168, "%", C_MUTED);

	draw_card(124, 150, 104, 58, 12, false);
	text_small(132, 154, "MOTION", C_MUTED);

	if (s->imu_ok) {
		uint32_t mg = vector_mg(s);

		if (mg >= 9950) {
			snprintf(b, sizeof(b), "%lu",
				 (unsigned long)((mg + 500) / 1000));
		} else {
			format_g1(b, sizeof(b), mg);
		}
		text_big(132, 170, b, C_TEXT);
		text_small(196, 186, "g", C_MUTED);
		canvas_fill_circle(216, 158, 3, state_color(imu_data_state(s, now)));
	} else {
		draw_dashes(176, 184, 18, 7, 8, C_MUTED);
		canvas_fill_circle(216, 158, 3, C_MUTED);
	}
}

static void draw_health_detail(const struct ui_snapshot *s, int64_t now)
{
	enum data_state ps = ppg_data_state(s, now);

	draw_title("HEALTH", "DETAIL");

	draw_card(12, 76, 104, 52, 12, false);
	text_small(20, 82, "HR", C_MUTED);
	draw_dashes(58, 98, 12, 5, 4, C_TEXT);
	text_small(76, 94, "BPM", C_MUTED);

	draw_card(124, 76, 104, 52, 12, false);
	text_small(132, 82, "SPO2", C_MUTED);
	draw_dashes(170, 98, 12, 5, 4, C_TEXT);
	text_small(190, 94, "%", C_MUTED);

	draw_card(12, 136, 216, 68, 14, false);
	text_small(24, 144, "PPG  IR", C_MUTED);
	text_right(216, 144,
		   ps == DATA_LIVE ? "VALID" : (ps == DATA_STALE ? "STALE" : "NO DATA"),
		   state_color(ps));
	draw_ppg_wave(s, 24, 164, 192, 34, ps);
}

static void draw_motion(const struct ui_snapshot *s, int64_t now)
{
	char b[12];
	enum data_state is = imu_data_state(s, now);

	draw_title("MOTION", NULL);

	draw_card(12, 76, 216, 84, 14, false);
	text_small(24, 86, "MOTION", C_MUTED);
	text_right(216, 86, is == DATA_OFF ? "UNAVAILABLE" : "MONITORING",
		   state_color(is));

	draw_posture(s, 58, 126, 22);

	text_small(104, 104, "|A|", C_MUTED);
	if (s->imu_ok) {
		uint32_t mg = vector_mg(s);

		if (mg >= 9950) {
			snprintf(b, sizeof(b), "%lu",
				 (unsigned long)((mg + 500) / 1000));
		} else {
			format_g1(b, sizeof(b), mg);
		}
		text_big(104, 122, b, C_TEXT);
		text_small(168, 138, "g", C_MUTED);
	} else {
		draw_dashes(160, 138, 16, 6, 6, C_MUTED);
	}

	draw_card(12, 168, 104, 40, 10, false);
	text_small(20, 172, "IMU", C_MUTED);
	text_small(20, 190, is == DATA_OFF ? "OFFLINE" : "ONLINE",
		   state_color(is));

	draw_card(124, 168, 104, 40, 10, false);
	text_small(132, 172, "GYRO", C_MUTED);
	if (s->imu_ok) {
		uint32_t dps = gyro_dps10(s);

		snprintf(b, sizeof(b), "%lu.%ludps",
			 (unsigned long)(dps / 10), (unsigned long)(dps % 10));
		text_small(132, 190, b, C_TEXT);
	} else {
		text_small(132, 190, "--", C_MUTED);
	}
}

static void draw_motion_detail(const struct ui_snapshot *s, int64_t now)
{
	char ax[12], ay[12], az[12];
	char gx[12], gy[12], gz[12];
	char b[24];
	const char *axv = "--", *ayv = "--", *azv = "--";
	const char *gxv = "--", *gyv = "--", *gzv = "--";

	draw_title("MOTION DATA", NULL);
	draw_card(12, 76, 216, 132, 14, false);

	text_small(24, 84, "ACCEL (g)", C_MUTED);
	text_small(136, 84, "GYRO dps", C_MUTED);
	canvas_hline(24, 102, 192, C_LINE);

	if (s->imu_ok) {
		format_accel(ax, sizeof(ax), s->imu[0], true);
		format_accel(ay, sizeof(ay), s->imu[1], true);
		format_accel(az, sizeof(az), s->imu[2], true);
		format_dps(gx, sizeof(gx), s->imu[3]);
		format_dps(gy, sizeof(gy), s->imu[4]);
		format_dps(gz, sizeof(gz), s->imu[5]);
		axv = ax;
		ayv = ay;
		azv = az;
		gxv = gx;
		gyv = gy;
		gzv = gz;
	}

	text_small(24, 108, "X", C_MUTED);
	text_small(48, 108, axv, C_TEXT);
	text_small(24, 126, "Y", C_MUTED);
	text_small(48, 126, ayv, C_TEXT);
	text_small(24, 144, "Z", C_MUTED);
	text_small(48, 144, azv, C_TEXT);

	text_small(128, 108, "X", C_MUTED);
	text_small(152, 108, gxv, C_TEXT);
	text_small(128, 126, "Y", C_MUTED);
	text_small(152, 126, gyv, C_TEXT);
	text_small(128, 144, "Z", C_MUTED);
	text_small(152, 144, gzv, C_TEXT);

	canvas_hline(24, 162, 192, C_LINE);

	text_small(24, 170, "|A|", C_MUTED);
	if (s->imu_ok) {
		format_g1(b, sizeof(b), vector_mg(s));
		text_small(58, 170, b, C_TEXT);
	} else {
		text_small(58, 170, "--", C_MUTED);
	}

	text_small(128, 170, "AGE", C_MUTED);
	format_age(b, sizeof(b), now - s->imu_last_ms);
	text_small(164, 170, b, C_MUTED);

	text_small(24, 190, "SEQ", C_MUTED);
	snprintf(b, sizeof(b), "%lu", (unsigned long)s->seq);
	text_small(58, 190, b, C_TEXT);
	text_small(128, 190, "OVR", C_MUTED);
	snprintf(b, sizeof(b), "%lu", (unsigned long)s->overruns);
	text_small(162, 190, b, C_TEXT);
}

static void draw_device(const struct ui_snapshot *s, int64_t now)
{
	char buf[32];
	char idbuf[24];

	draw_title("DEVICE", NULL);
	draw_card(12, 76, 216, 132, 14, false);

	text_small(24, 84, "SenseMind Band", C_TEXT);
	canvas_fill_circle(204, 92, 4, C_BRAND);
	short_id(s->device_id, idbuf, sizeof(idbuf));
	text_small(24, 104, idbuf, C_MUTED);
	canvas_hline(24, 126, 192, C_LINE);

	text_small(24, 130, "BLE", C_MUTED);
	text_right(216, 130, ble_text(s), ble_color(s));

	text_small(24, 150, "IMU", C_MUTED);
	text_small(68, 150, s->imu_ok ? "OK" : "ERR",
		   s->imu_ok ? C_OK : C_ERR);
	text_small(128, 150, "PPG", C_MUTED);
	text_small(172, 150, s->ppg_ok ? "OK" : "ERR",
		   s->ppg_ok ? C_OK : C_ERR);

	text_small(24, 170, "FW", C_MUTED);
	text_right(216, 170, s->fw[0] ? s->fw : "--", C_TEXT);

	text_small(24, 190, "UP", C_MUTED);
	format_uptime(buf, sizeof(buf), now);
	text_right(216, 190, buf, C_TEXT);
}

static void draw_debug(const struct ui_snapshot *s, int64_t now)
{
	char b[32];
	size_t len;
	const char *id;

	(void)now;
	draw_title("DEBUG", NULL);
	draw_card(12, 76, 216, 132, 14, false);

	text_small(24, 82, "BLE", C_MUTED);
	text_right(216, 82, ble_detail(s), ble_color(s));

	text_small(24, 100, "SEQ", C_MUTED);
	snprintf(b, sizeof(b), "%lu", (unsigned long)s->seq);
	text_small(58, 100, b, C_TEXT);
	text_small(128, 100, "OVR", C_MUTED);
	snprintf(b, sizeof(b), "%lu", (unsigned long)s->overruns);
	text_small(162, 100, b, C_TEXT);

	text_small(24, 118, "RED", C_MUTED);
	snprintf(b, sizeof(b), "%lu", (unsigned long)s->red);
	text_small(58, 118, b, C_TEXT);
	text_small(128, 118, "IR", C_MUTED);
	snprintf(b, sizeof(b), "%lu", (unsigned long)s->ir);
	text_small(152, 118, b, C_TEXT);

	text_small(24, 136, "BTN", C_MUTED);
	snprintf(b, sizeof(b), "%lu", (unsigned long)button_event_count);
	text_small(58, 136, b, C_TEXT);
	text_small(128, 136, "DRP", C_MUTED);
	snprintf(b, sizeof(b), "%lu",
		 (unsigned long)buttons_dropped_events());
	text_small(162, 136, b, C_TEXT);

	text_small(24, 154, "DRAW", C_MUTED);
	snprintf(b, sizeof(b), "%lums", (unsigned long)max_refresh_ms);
	text_small(68, 154, b, C_TEXT);
	text_small(132, 154, "STK", C_MUTED);
	snprintf(b, sizeof(b), "%luB", (unsigned long)ui_stack_unused);
	text_small(166, 154, b, C_TEXT);

	text_small(24, 172, "BOT", C_MUTED);
	text_small(56, 172, s->boot_id[0] ? s->boot_id : "--", C_MUTED);

	len = strlen(s->device_id);
	id = (len > 16) ? s->device_id + len - 16 : s->device_id;
	text_small(24, 190, "ID", C_MUTED);
	text_small(56, 190, id[0] ? id : "--", C_MUTED);
}

static void draw_menu(void)
{
	static const char *const items[] = {
		"Back to main",
		"Health detail",
		"Device info",
	};

	draw_title("QUICK MENU", NULL);

	for (int i = 0; i < 3; i++) {
		int y = 86 + i * 46;

		draw_card(12, y, 216, 38, 12, i == menu_index);
		if (i == menu_index) {
			canvas_fill_round_rect(18, y + 9, 4, 20, 2, C_BRAND);
		}
		text_small(32, y + 11, items[i],
			   i == menu_index ? C_TEXT : C_MUTED);
	}
}

static void draw_footer(enum ui_page p)
{
	if (p == PAGE_MENU) {
		text_center(220, "A MOVE    B OPEN", C_MUTED);
		return;
	}
	if (p == PAGE_MOTION_DETAIL || p == PAGE_DEVICE_DEBUG) {
		text_center(220, "B BACK", C_MUTED);
		return;
	}

	int active = page_index(p);

	if (active < 0) {
		return;
	}

	static const int xs[4] = {99, 113, 127, 141};
	const int cy = 222;

	for (int i = 0; i < 4; i++) {
		if (i == active) {
			canvas_fill_round_rect(xs[i] - 6, cy - 3, 12, 6, 3, C_BRAND);
		} else {
			canvas_fill_circle(xs[i], cy, 3, C_DOT);
		}
	}
}

static void render_band(const struct ui_snapshot *s, int64_t now, int y)
{
	band_y = y;
	band_clear(C_BG);

	/* The top bar and its divider live in bands 0..2. */
	if (y < 48) {
		draw_topbar(s, now);
	}

	switch (current_page) {
	case PAGE_HEALTH:
		draw_health(s, now);
		break;
	case PAGE_HEALTH_DETAIL:
		draw_health_detail(s, now);
		break;
	case PAGE_MOTION:
		draw_motion(s, now);
		break;
	case PAGE_MOTION_DETAIL:
		draw_motion_detail(s, now);
		break;
	case PAGE_DEVICE:
		draw_device(s, now);
		break;
	case PAGE_DEVICE_DEBUG:
		draw_debug(s, now);
		break;
	case PAGE_MENU:
		draw_menu();
		break;
	default:
		break;
	}

	draw_footer(current_page);
}

static void render_splash_band(int y)
{
	band_y = y;
	band_clear(C_BG);
	canvas_logo120(60, 24);
	canvas_text((UI_W - text_width("SenseMind", &font_big, 1)) / 2, 158,
		    "SenseMind", C_TEXT, &font_big, 1);
	text_center(196, "BAND", C_BRAND);
	canvas_fill_round_rect(100, 220, 40, 3, 1, C_BRAND);
}

static int flush_band(const struct device *display, int y)
{
	struct display_buffer_descriptor desc = {
		.buf_size = sizeof(band_buf),
		.width = UI_W,
		.height = UI_BAND,
		.pitch = UI_W,
	};

	return display_write(display, 0, y, &desc, band_buf);
}

static void mark_all(void)
{
	dirty_mask = (1U << UI_BANDS) - 1U;
}

static void mark_bands(int first, int last)
{
	for (int b = first; b <= last; b++) {
		if (b >= 0 && b < UI_BANDS) {
			dirty_mask |= BIT(b);
		}
	}
}

static void render_dirty(const struct device *display,
			 const struct ui_snapshot *s)
{
	int64_t start = k_uptime_get();
	int64_t now = start;

	for (int b = 0; b < UI_BANDS; b++) {
		if ((dirty_mask & BIT(b)) == 0) {
			continue;
		}

		render_band(s, now, b * UI_BAND);
#if IS_ENABLED(CONFIG_SENSEMIND_BRINGUP_LOG)
		printk("SM UI flush y=%d\n", b * UI_BAND);
#endif
		int rc = flush_band(display, b * UI_BAND);
#if IS_ENABLED(CONFIG_SENSEMIND_BRINGUP_LOG)
		printk("SM UI flush rc=%d y=%d\n", rc, b * UI_BAND);
#endif

		if (rc != 0) {
			printk("SM UI write y=%d rc=%d\n", b * UI_BAND, rc);
			break;
		}
	}

	last_refresh_ms = (uint32_t)(k_uptime_get() - start);
	max_refresh_ms = MAX(max_refresh_ms, last_refresh_ms);
	dirty_mask = 0;
}

static void mark_changes(const struct ui_snapshot *s,
			 const struct ui_snapshot *last, int64_t now)
{
	enum data_state ps = ppg_data_state(s, now);
	enum data_state is = imu_data_state(s, now);
	bool all = s->ble_connected != last->ble_connected ||
		   s->ble_subscribed != last->ble_subscribed ||
		   s->imu_ok != last->imu_ok ||
		   s->ppg_ok != last->ppg_ok;
	bool ppg_new = s->ppg_total != last->ppg_total;
	bool imu_new = memcmp(s->imu, last->imu, sizeof(s->imu)) != 0;
	bool counters_new = s->seq != last->seq ||
			    s->overruns != last->overruns;
	bool raw_new = s->red != last->red || s->ir != last->ir;

	if (all) {
		mark_all();
	} else {
		switch (current_page) {
		case PAGE_HEALTH:
			if (ps != last_ppg_state) {
				mark_bands(3, 4);
			}
			if (imu_new || is != last_imu_state) {
				mark_bands(9, 12);
			}
			break;
		case PAGE_HEALTH_DETAIL:
			if (ppg_new || ps != last_ppg_state) {
				mark_bands(8, 12);
			}
			break;
		case PAGE_MOTION:
			if (imu_new || is != last_imu_state) {
				mark_bands(4, 12);
			}
			break;
		case PAGE_MOTION_DETAIL:
			if (imu_new || is != last_imu_state || counters_new) {
				mark_bands(4, 12);
			}
			break;
		case PAGE_DEVICE:
			if (counters_new) {
				mark_bands(12, 12);
			}
			break;
		case PAGE_DEVICE_DEBUG:
			if (ppg_new || imu_new || counters_new || raw_new ||
			    is != last_imu_state) {
				mark_bands(5, 12);
			}
			break;
		case PAGE_MENU:
			break;
		default:
			break;
		}
	}

	last_ppg_state = ps;
	last_imu_state = is;
}

static enum ui_page next_main_page(enum ui_page p)
{
	static const enum ui_page pages[4] = {
		PAGE_HEALTH, PAGE_HEALTH_DETAIL, PAGE_MOTION, PAGE_DEVICE,
	};
	int i = page_index(p);

	if (i < 0) {
		return PAGE_HEALTH;
	}

	return pages[(i + 1) & 3];
}

static enum ui_page detail_toggle(enum ui_page p)
{
	switch (p) {
	case PAGE_HEALTH:
		return PAGE_HEALTH_DETAIL;
	case PAGE_HEALTH_DETAIL:
		return PAGE_HEALTH;
	case PAGE_MOTION:
		return PAGE_MOTION_DETAIL;
	case PAGE_MOTION_DETAIL:
		return PAGE_MOTION;
	case PAGE_DEVICE:
		return PAGE_DEVICE_DEBUG;
	case PAGE_DEVICE_DEBUG:
		return PAGE_DEVICE;
	default:
		return p;
	}
}

static void handle_button_event(const struct button_event *ev)
{
	button_event_count++;

	if (ev->id == BTN_A) {
		if (ev->type == BTN_SHORT) {
			if (current_page == PAGE_MENU) {
				menu_index = (menu_index + 1) % 3;
			} else {
				current_page = next_main_page(current_page);
			}
		} else {
			if (current_page == PAGE_MENU) {
				current_page = menu_return;
			} else {
				menu_return = current_page;
				current_page = PAGE_MENU;
				menu_index = 0;
			}
		}
	} else {
		if (ev->type == BTN_SHORT) {
			if (current_page == PAGE_MENU) {
				switch (menu_index) {
				case 0:
					current_page = PAGE_HEALTH;
					break;
				case 1:
					current_page = PAGE_HEALTH_DETAIL;
					break;
				default:
					current_page = PAGE_DEVICE;
					break;
				}
			} else {
				current_page = detail_toggle(current_page);
			}
		} else {
			current_page = PAGE_HEALTH;
			menu_index = 0;
		}
	}

	mark_all();
	accent_until = k_uptime_get() + 350;
	accent_drawn = true;
}

static void ui_thread(void *a, void *b, void *c)
{
	ARG_UNUSED(a);
	ARG_UNUSED(b);
	ARG_UNUSED(c);

	const struct device *display = DEVICE_DT_GET(DT_CHOSEN(zephyr_display));
	size_t unused = 0;

	while (!device_is_ready(display)) {
		k_sleep(K_MSEC(100));
	}

	(void)display_blanking_off(display);

	/* Splash. */
	for (int y = 0; y < UI_H; y += UI_BAND) {
		render_splash_band(y);
		(void)flush_band(display, y);
	}
	k_sleep(K_MSEC(1500));

	if (k_thread_stack_space_get(k_current_get(), &unused) == 0) {
		ui_stack_unused = (uint32_t)unused;
	}

	struct ui_snapshot snap;

	take_snapshot(&snap);
	current_page = PAGE_HEALTH;
	mark_all();
	render_dirty(display, &snap);
	last_snap = snap;
	int64_t now = k_uptime_get();

	last_ppg_state = ppg_data_state(&snap, now);
	last_imu_state = imu_data_state(&snap, now);

	int64_t next_data_at = now + 1000;
	int64_t last_log_at = now;
	int64_t last_stack_at = now;

	while (1) {
		struct button_event ev;
		int rc = buttons_get_event(&ev, K_MSEC(1000));

		if (rc == 0) {
			do {
				handle_button_event(&ev);
			} while (buttons_get_event(&ev, K_NO_WAIT) == 0);

			take_snapshot(&snap);
			render_dirty(display, &snap);
			last_snap = snap;
			now = k_uptime_get();
			last_ppg_state = ppg_data_state(&snap, now);
			last_imu_state = imu_data_state(&snap, now);
		}

		now = k_uptime_get();

		if (now >= next_data_at) {
#if IS_ENABLED(CONFIG_SENSEMIND_BRINGUP_LOG)
			printk("SM UI tick page=%d snap\n", current_page);
#endif
			take_snapshot(&snap);
#if IS_ENABLED(CONFIG_SENSEMIND_BRINGUP_LOG)
			printk("SM UI tick mark\n");
#endif
			mark_changes(&snap, &last_snap, now);

			if (accent_drawn && now >= accent_until) {
				mark_bands(2, 2);
				accent_drawn = false;
			}

#if IS_ENABLED(CONFIG_SENSEMIND_BRINGUP_LOG)
			printk("SM UI tick draw dirty=%lx\n",
			       (unsigned long)dirty_mask);
#endif
			render_dirty(display, &snap);
#if IS_ENABLED(CONFIG_SENSEMIND_BRINGUP_LOG)
			printk("SM UI tick done\n");
#endif
			last_snap = snap;
			last_ppg_state = ppg_data_state(&snap, now);
			last_imu_state = imu_data_state(&snap, now);
			next_data_at = now + 1000;
		}

		now = k_uptime_get();

		if (now - last_stack_at >= 30000) {
			last_stack_at = now;
			if (k_thread_stack_space_get(k_current_get(), &unused) == 0) {
				ui_stack_unused = (uint32_t)unused;
			}
		}

#if IS_ENABLED(CONFIG_SENSEMIND_BRINGUP_LOG)
		if (now - last_log_at >= 30000) {
			last_log_at = now;
			printk("SM UI btn=%lu draw=%lu/%lums stack=%luB\n",
			       (unsigned long)button_event_count,
			       (unsigned long)last_refresh_ms,
			       (unsigned long)max_refresh_ms,
			       (unsigned long)ui_stack_unused);
		}
#else
		(void)last_log_at;
#endif
	}
}

K_THREAD_DEFINE(sm_ui_thread_id, 8192, ui_thread,
		NULL, NULL, NULL, 7, 0, 0);

void sm_ui_set_ble(bool connected, bool subscribed)
{
	k_mutex_lock(&ui_lock, K_FOREVER);
	ui.ble_connected = connected;
	ui.ble_subscribed = subscribed;
	k_mutex_unlock(&ui_lock);
}

void sm_ui_set_sensors(bool imu_ok, bool ppg_ok)
{
	k_mutex_lock(&ui_lock, K_FOREVER);
	ui.imu_ok = imu_ok;
	ui.ppg_ok = ppg_ok;
	k_mutex_unlock(&ui_lock);
}

void sm_ui_set_imu(const int16_t raw[6])
{
	k_mutex_lock(&ui_lock, K_FOREVER);
	memcpy(ui.imu, raw, sizeof(ui.imu));
	ui.imu_last_ms = k_uptime_get();
	k_mutex_unlock(&ui_lock);
}

void sm_ui_push_ppg(uint32_t red, uint32_t ir)
{
	k_mutex_lock(&ui_lock, K_FOREVER);
	ui.ppg[ui.head] = ir;
	ui.head = (ui.head + 1) % PPG_N;
	if (ui.count < PPG_N) {
		ui.count++;
	}
	ui.red = red;
	ui.ir = ir;
	ui.ppg_total++;
	ui.ppg_last_ms = k_uptime_get();
	k_mutex_unlock(&ui_lock);
}

void sm_ui_set_counters(uint32_t seq, uint32_t overruns)
{
	k_mutex_lock(&ui_lock, K_FOREVER);
	ui.seq = seq;
	ui.overruns = overruns;
	k_mutex_unlock(&ui_lock);
}

void sm_ui_set_ids(const char *device_id, const char *boot_id, const char *fw)
{
	k_mutex_lock(&ui_lock, K_FOREVER);
	strncpy(ui.device_id, device_id, sizeof(ui.device_id) - 1);
	ui.device_id[sizeof(ui.device_id) - 1] = '\0';
	strncpy(ui.boot_id, boot_id, sizeof(ui.boot_id) - 1);
	ui.boot_id[sizeof(ui.boot_id) - 1] = '\0';
	strncpy(ui.fw, fw, sizeof(ui.fw) - 1);
	ui.fw[sizeof(ui.fw) - 1] = '\0';
	k_mutex_unlock(&ui_lock);
}
