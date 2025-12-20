/**
 * @file edge_guardian.h
 * @brief SeedCore Edge Guardian core interface
 *
 * This module defines the central coordination logic for the
 * SeedCore Edge Guardian edge AI node.
 *
 * Responsibilities:
 *  - Maintain edge state
 *  - React to events (AI / sensor / CLI)
 *  - Drive actuators (relay, light)
 *  - Bridge local decisions to Tuya Cloud
 *
 * v1.0 Scope:
 *  - Switch / relay control
 *  - Status tracking
 *  - Safe extension points for AI & vision
 *
 * Copyright (c) 2025 SeedCore
 */

#ifndef EDGE_GUARDIAN_H
#define EDGE_GUARDIAN_H

#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

/* =========================================================
 * Types
 * ========================================================= */

/**
 * @brief Edge Guardian runtime state
 */
typedef enum {
    EDGE_GUARDIAN_IDLE = 0,
    EDGE_GUARDIAN_ARMED,
    EDGE_GUARDIAN_ALERT,
} edge_guardian_state_t;

/* =========================================================
 * Lifecycle
 * ========================================================= */

/**
 * @brief Initialize Edge Guardian core
 *
 * Called once during application startup.
 */
void edge_guardian_init(void);

/**
 * @brief Start Edge Guardian logic
 *
 * Called after Tuya IoT is ready.
 */
void edge_guardian_start(void);

/**
 * @brief Stop Edge Guardian logic
 */
void edge_guardian_stop(void);

/* =========================================================
 * Control & Actions
 * ========================================================= */

/**
 * @brief Control relay / AI switch
 *
 * @param on true = ON, false = OFF
 */
void edge_guardian_set_switch(bool on);

/**
 * @brief Get current Edge Guardian state
 */
edge_guardian_state_t edge_guardian_get_state(void);

/**
 * @brief Set Edge Guardian state (internal use)
 */
void edge_guardian_set_state(edge_guardian_state_t state);

/* =========================================================
 * Event Hooks (Future AI / Vision)
 * ========================================================= */

/**
 * @brief Notify Edge Guardian of a detected threat
 *
 * This will:
 *  - Transition to ALERT state
 *  - Trigger local responses (light, relay)
 */
void edge_guardian_on_threat_detected(const char *reason);

#ifdef __cplusplus
}
#endif

#endif /* EDGE_GUARDIAN_H */

