/**
 * @file edge_switch_sim.c
 * @brief Switch and relay simulation implementation
 */

#include "edge_switch_sim.h"
#include "edge_guardian.h"
#include "tal_api.h"
#include "tal_sw_timer.h"
#include "tuya_iot.h"
#include <stdio.h>
#include <string.h>

/* =========================================================
 * Internal State
 * ========================================================= */

static bool g_relay_state = false;
static TIMER_ID g_timer_id = NULL;
static uint32_t g_event_counter = 0;

/* =========================================================
 * Internal Helpers
 * ========================================================= */

/**
 * @brief Report relay/switch DP to Tuya Cloud
 * DP ID 1: "switch"
 */
static void report_switch_dp(bool on)
{
    char dp_json[128];
    snprintf(dp_json, sizeof(dp_json), "{\"1\":%s}", on ? "true" : "false");
    PR_INFO("EdgeSwitch: report switch=%d", on);
    tuya_iot_dp_report_json(tuya_iot_client_get(), dp_json);
}

/**
 * @brief Emit an event (for future event system integration)
 */
static void emit_event(edge_switch_event_t event)
{
    switch (event) {
    case EDGE_EVENT_BUTTON_PRESS:
        PR_NOTICE("EdgeSwitch: Event emitted - BUTTON_PRESS");
        break;
    case EDGE_EVENT_BUTTON_RELEASE:
        PR_NOTICE("EdgeSwitch: Event emitted - BUTTON_RELEASE");
        break;
    case EDGE_EVENT_BUTTON_LONG_PRESS:
        PR_NOTICE("EdgeSwitch: Event emitted - BUTTON_LONG_PRESS");
        break;
    case EDGE_EVENT_RELAY_ON:
        PR_NOTICE("EdgeSwitch: Event emitted - RELAY_ON");
        break;
    case EDGE_EVENT_RELAY_OFF:
        PR_NOTICE("EdgeSwitch: Event emitted - RELAY_OFF");
        break;
    }
}

/**
 * @brief Timer callback for automatic event simulation
 */
static void switch_timer_cb(TIMER_ID timer_id, void *arg)
{
    g_event_counter++;
    
    // Simulate different events periodically
    switch (g_event_counter % 4) {
    case 0:
        edge_switch_sim_press();
        break;
    case 1:
        edge_switch_sim_release();
        break;
    case 2:
        edge_switch_sim_relay_on();
        break;
    case 3:
        edge_switch_sim_relay_off();
        break;
    }
}

/* =========================================================
 * Public API
 * ========================================================= */

void edge_switch_sim_init(void)
{
    g_relay_state = false;
    g_timer_id = NULL;
    g_event_counter = 0;
    PR_NOTICE("EdgeSwitchSim initialized");
}

void edge_switch_sim_press(void)
{
    PR_NOTICE("EdgeSwitch: Simulated button PRESS");
    emit_event(EDGE_EVENT_BUTTON_PRESS);
    
    // Button press typically doesn't change relay state immediately
    // but could trigger other logic
}

void edge_switch_sim_release(void)
{
    PR_NOTICE("EdgeSwitch: Simulated button RELEASE");
    emit_event(EDGE_EVENT_BUTTON_RELEASE);
}

void edge_switch_sim_long_press(void)
{
    PR_NOTICE("EdgeSwitch: Simulated button LONG_PRESS");
    emit_event(EDGE_EVENT_BUTTON_LONG_PRESS);
    
    // Long press might toggle relay
    edge_switch_sim_relay_on();
}

void edge_switch_sim_relay_on(void)
{
    if (g_relay_state) {
        return; // Already ON
    }

    g_relay_state = true;
    report_switch_dp(true);
    emit_event(EDGE_EVENT_RELAY_ON);
    
    PR_NOTICE("EdgeSwitch: Virtual relay ON");
}

void edge_switch_sim_relay_off(void)
{
    if (!g_relay_state) {
        return; // Already OFF
    }

    g_relay_state = false;
    report_switch_dp(false);
    emit_event(EDGE_EVENT_RELAY_OFF);
    
    PR_NOTICE("EdgeSwitch: Virtual relay OFF");
}

bool edge_switch_sim_get_relay_state(void)
{
    return g_relay_state;
}

void edge_switch_sim_start_timer(uint32_t interval_ms)
{
    if (g_timer_id) {
        PR_WARN("EdgeSwitchSim: timer already started");
        return;
    }

    if (interval_ms == 0) {
        interval_ms = 5000; // Default 5 seconds
    }

    tal_sw_timer_create(switch_timer_cb, NULL, &g_timer_id);
    tal_sw_timer_start(g_timer_id, interval_ms, TAL_TIMER_CYCLE);
    
    PR_NOTICE("EdgeSwitchSim: Timer-driven simulation started (%dms interval)", interval_ms);
}

void edge_switch_sim_stop_timer(void)
{
    if (g_timer_id) {
        tal_sw_timer_stop(g_timer_id);
        tal_sw_timer_delete(g_timer_id);
        g_timer_id = NULL;
        PR_NOTICE("EdgeSwitchSim: Timer-driven simulation stopped");
    }
}

