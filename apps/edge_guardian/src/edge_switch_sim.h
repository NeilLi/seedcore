/**
 * @file edge_switch_sim.h
 * @brief CLI-triggered switch and relay simulation
 *
 * This module simulates button press/release and relay control
 * without requiring actual hardware. It can be triggered via CLI
 * commands or timer-driven events.
 *
 * Copyright (c) 2025 SeedCore
 */

#ifndef EDGE_SWITCH_SIM_H
#define EDGE_SWITCH_SIM_H

#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* =========================================================
 * Event Types
 * ========================================================= */

typedef enum {
    EDGE_EVENT_BUTTON_PRESS = 0,
    EDGE_EVENT_BUTTON_RELEASE,
    EDGE_EVENT_BUTTON_LONG_PRESS,
    EDGE_EVENT_RELAY_ON,
    EDGE_EVENT_RELAY_OFF,
} edge_switch_event_t;

/* =========================================================
 * API
 * ========================================================= */

/**
 * @brief Initialize switch simulation
 */
void edge_switch_sim_init(void);

/**
 * @brief Simulate button press
 */
void edge_switch_sim_press(void);

/**
 * @brief Simulate button release
 */
void edge_switch_sim_release(void);

/**
 * @brief Simulate button long press
 */
void edge_switch_sim_long_press(void);

/**
 * @brief Simulate relay ON
 */
void edge_switch_sim_relay_on(void);

/**
 * @brief Simulate relay OFF
 */
void edge_switch_sim_relay_off(void);

/**
 * @brief Get current relay state
 *
 * @return true if relay is ON, false if OFF
 */
bool edge_switch_sim_get_relay_state(void);

/**
 * @brief Start timer-driven event simulation
 *
 * @param interval_ms Interval between simulated events (milliseconds)
 */
void edge_switch_sim_start_timer(uint32_t interval_ms);

/**
 * @brief Stop timer-driven simulation
 */
void edge_switch_sim_stop_timer(void);

#ifdef __cplusplus
}
#endif

#endif /* EDGE_SWITCH_SIM_H */

