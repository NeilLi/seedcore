/**
 * @file edge_guardian.c
 * @brief SeedCore Edge Guardian core implementation
 */

#include "edge_guardian.h"

#include "tal_api.h"
#include "tuya_iot.h"
#include <string.h>

/* =========================================================
 * Internal State
 * ========================================================= */

static edge_guardian_state_t g_edge_state = EDGE_GUARDIAN_IDLE;

/* =========================================================
 * Internal Helpers
 * ========================================================= */

/**
 * @brief Report switch DP to Tuya Cloud
 *
 * DP ID 1: "switch"
 */
static void report_switch_dp(bool on)
{
    char dp_json[64];

    snprintf(
        dp_json,
        sizeof(dp_json),
        "{\"1\":%s}",
        on ? "true" : "false"
    );

    PR_INFO("EdgeGuardian: report switch=%d", on);
    tuya_iot_dp_report_json(tuya_iot_client_get(), dp_json);
}

/* =========================================================
 * Lifecycle
 * ========================================================= */

void edge_guardian_init(void)
{
    g_edge_state = EDGE_GUARDIAN_IDLE;
    PR_NOTICE("EdgeGuardian initialized");
}

void edge_guardian_start(void)
{
    PR_NOTICE("EdgeGuardian started");
}

void edge_guardian_stop(void)
{
    PR_NOTICE("EdgeGuardian stopped");
}

/* =========================================================
 * State Management
 * ========================================================= */

edge_guardian_state_t edge_guardian_get_state(void)
{
    return g_edge_state;
}

void edge_guardian_set_state(edge_guardian_state_t state)
{
    if (g_edge_state == state) {
        return;
    }

    PR_NOTICE("EdgeGuardian state %d -> %d", g_edge_state, state);
    g_edge_state = state;
}

/* =========================================================
 * Control
 * ========================================================= */

void edge_guardian_set_switch(bool on)
{
    report_switch_dp(on);
}

/* =========================================================
 * Event Handling (AI / Vision)
 * ========================================================= */

void edge_guardian_on_threat_detected(const char *reason)
{
    PR_WARN("Threat detected: %s", reason ? reason : "unknown");

    edge_guardian_set_state(EDGE_GUARDIAN_ALERT);

    /* Local autonomous response (v1.0) */
    edge_guardian_set_switch(true);

    /*
     * v2.0 ideas:
     *  - Strobe AI light
     *  - Capture image
     *  - Push event to SeedCore Cloud Cortex
     */
}

