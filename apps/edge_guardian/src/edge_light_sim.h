/**
 * @file edge_light_sim.h
 * @brief Software PWM model for AI Light simulation
 *
 * This module simulates PWM/RGB lighting control without requiring
 * actual hardware. It maintains internal state for brightness and RGB
 * values and reports them via Tuya DPs.
 *
 * Copyright (c) 2025 SeedCore
 */

#ifndef EDGE_LIGHT_SIM_H
#define EDGE_LIGHT_SIM_H

#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* =========================================================
 * API
 * ========================================================= */

/**
 * @brief Initialize light simulation
 */
void edge_light_sim_init(void);

/**
 * @brief Set light on/off state
 *
 * @param on true = ON, false = OFF
 */
void edge_light_sim_set_on(bool on);

/**
 * @brief Get light on/off state
 *
 * @return true if ON, false if OFF
 */
bool edge_light_sim_get_on(void);

/**
 * @brief Set brightness (0-100)
 *
 * @param brightness Brightness level (0-100)
 */
void edge_light_sim_set_brightness(uint8_t brightness);

/**
 * @brief Get current brightness
 *
 * @return Brightness level (0-100)
 */
uint8_t edge_light_sim_get_brightness(void);

/**
 * @brief Set RGB color
 *
 * @param r Red component (0-255)
 * @param g Green component (0-255)
 * @param b Blue component (0-255)
 */
void edge_light_sim_set_rgb(uint8_t r, uint8_t g, uint8_t b);

/**
 * @brief Get RGB color
 *
 * @param r Output red component (0-255)
 * @param g Output green component (0-255)
 * @param b Output blue component (0-255)
 */
void edge_light_sim_get_rgb(uint8_t *r, uint8_t *g, uint8_t *b);

/**
 * @brief Report all light state to Tuya Cloud
 */
void edge_light_sim_report_state(void);

#ifdef __cplusplus
}
#endif

#endif /* EDGE_LIGHT_SIM_H */

