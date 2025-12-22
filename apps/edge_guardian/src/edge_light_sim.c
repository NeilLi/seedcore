/**
 * @file edge_light_sim.c
 * @brief Software PWM light simulation implementation
 */

#include "edge_light_sim.h"
#include "tal_api.h"
#include "tuya_iot.h"
#include <stdio.h>
#include <string.h>

/* =========================================================
 * Internal State
 * ========================================================= */

static bool g_light_on = false;
static uint8_t g_brightness = 50; // Default 50%
static uint8_t g_rgb_r = 255;
static uint8_t g_rgb_g = 255;
static uint8_t g_rgb_b = 255; // Default white

/* =========================================================
 * Internal Helpers
 * ========================================================= */

/**
 * @brief Report light on/off DP to Tuya Cloud
 * DP ID 5: "light_on"
 */
static void report_light_on_dp(bool on)
{
    char dp_json[128];
    snprintf(dp_json, sizeof(dp_json), "{\"5\":%s}", on ? "true" : "false");
    PR_INFO("EdgeLight: report light_on=%d", on);
    tuya_iot_dp_report_json(tuya_iot_client_get(), dp_json);
}

/**
 * @brief Report brightness DP to Tuya Cloud
 * DP ID 6: "brightness"
 */
static void report_brightness_dp(uint8_t brightness)
{
    char dp_json[128];
    snprintf(dp_json, sizeof(dp_json), "{\"6\":%d}", brightness);
    PR_INFO("EdgeLight: report brightness=%d", brightness);
    tuya_iot_dp_report_json(tuya_iot_client_get(), dp_json);
}

/**
 * @brief Report RGB color DP to Tuya Cloud
 * DP ID 7: "rgb_color" (format: "r,g,b" as string)
 */
static void report_rgb_dp(uint8_t r, uint8_t g, uint8_t b)
{
    char dp_json[256];
    char rgb_str[32];
    snprintf(rgb_str, sizeof(rgb_str), "%d,%d,%d", r, g, b);
    snprintf(dp_json, sizeof(dp_json), "{\"7\":\"%s\"}", rgb_str);
    PR_INFO("EdgeLight: report rgb_color=%s", rgb_str);
    tuya_iot_dp_report_json(tuya_iot_client_get(), dp_json);
}

/* =========================================================
 * Public API
 * ========================================================= */

void edge_light_sim_init(void)
{
    g_light_on = false;
    g_brightness = 50;
    g_rgb_r = 255;
    g_rgb_g = 255;
    g_rgb_b = 255;
    PR_NOTICE("EdgeLightSim initialized");
}

void edge_light_sim_set_on(bool on)
{
    if (g_light_on == on) {
        return;
    }

    g_light_on = on;
    report_light_on_dp(on);
    
    if (on) {
        PR_NOTICE("EdgeLight: Virtual light ON (brightness=%d%%, RGB=%d,%d,%d)", 
                  g_brightness, g_rgb_r, g_rgb_g, g_rgb_b);
    } else {
        PR_NOTICE("EdgeLight: Virtual light OFF");
    }
}

bool edge_light_sim_get_on(void)
{
    return g_light_on;
}

void edge_light_sim_set_brightness(uint8_t brightness)
{
    if (brightness > 100) {
        brightness = 100;
    }

    if (g_brightness == brightness) {
        return;
    }

    g_brightness = brightness;
    report_brightness_dp(brightness);
    
    PR_NOTICE("EdgeLight: Virtual brightness set to %d%%", brightness);
}

uint8_t edge_light_sim_get_brightness(void)
{
    return g_brightness;
}

void edge_light_sim_set_rgb(uint8_t r, uint8_t g, uint8_t b)
{
    if (g_rgb_r == r && g_rgb_g == g && g_rgb_b == b) {
        return;
    }

    g_rgb_r = r;
    g_rgb_g = g;
    g_rgb_b = b;
    report_rgb_dp(r, g, b);
    
    PR_NOTICE("EdgeLight: Virtual RGB set to (%d,%d,%d)", r, g, b);
}

void edge_light_sim_get_rgb(uint8_t *r, uint8_t *g, uint8_t *b)
{
    if (r) *r = g_rgb_r;
    if (g) *g = g_rgb_g;
    if (b) *b = g_rgb_b;
}

void edge_light_sim_report_state(void)
{
    report_light_on_dp(g_light_on);
    report_brightness_dp(g_brightness);
    report_rgb_dp(g_rgb_r, g_rgb_g, g_rgb_b);
    PR_NOTICE("EdgeLight: State reported (on=%d, brightness=%d%%, RGB=%d,%d,%d)",
              g_light_on, g_brightness, g_rgb_r, g_rgb_g, g_rgb_b);
}

