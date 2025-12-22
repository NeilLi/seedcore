/**
 * @file edge_cam_sim.h
 * @brief Synthetic camera frame generator for Edge Guardian simulation
 *
 * This module generates fake camera frames in RAM to simulate DVP camera
 * input without requiring actual hardware. It triggers events like:
 * - Motion detected
 * - Person detected
 * - Anomaly score spike
 *
 * Copyright (c) 2025 SeedCore
 */

#ifndef EDGE_CAM_SIM_H
#define EDGE_CAM_SIM_H

#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* =========================================================
 * Types
 * ========================================================= */

/**
 * @brief Synthetic camera frame structure
 */
typedef struct {
    uint8_t *data;      // Frame buffer (grayscale or RGB)
    uint16_t width;     // Frame width
    uint16_t height;    // Frame height
    uint8_t format;     // 0=grayscale, 1=RGB565, 2=RGB888
    uint32_t timestamp; // Frame timestamp
} edge_camera_frame_t;

/**
 * @brief Detection event types
 */
typedef enum {
    EDGE_CAM_EVENT_NONE = 0,
    EDGE_CAM_EVENT_MOTION,
    EDGE_CAM_EVENT_PERSON,
    EDGE_CAM_EVENT_ANOMALY,
} edge_cam_event_type_t;

/**
 * @brief Frame callback function type
 */
typedef void (*edge_cam_frame_cb_t)(edge_camera_frame_t *frame, edge_cam_event_type_t event);

/* =========================================================
 * API
 * ========================================================= */

/**
 * @brief Initialize synthetic camera generator
 */
void edge_cam_sim_init(void);

/**
 * @brief Start generating synthetic frames
 *
 * @param width Frame width (default: 640)
 * @param height Frame height (default: 480)
 * @param interval_ms Frame generation interval in milliseconds
 */
void edge_cam_sim_start(uint16_t width, uint16_t height, uint32_t interval_ms);

/**
 * @brief Stop frame generation
 */
void edge_cam_sim_stop(void);

/**
 * @brief Register callback for generated frames
 *
 * @param cb Callback function
 */
void edge_cam_sim_register_callback(edge_cam_frame_cb_t cb);

/**
 * @brief Generate a single synthetic frame
 *
 * @param frame Output frame structure (data buffer must be pre-allocated)
 * @param event_type Event type to simulate (motion, person, anomaly)
 */
void edge_cam_sim_generate(edge_camera_frame_t *frame, edge_cam_event_type_t event_type);

/**
 * @brief Trigger a specific event manually (for testing)
 *
 * @param event_type Event type to trigger
 */
void edge_cam_sim_trigger_event(edge_cam_event_type_t event_type);

#ifdef __cplusplus
}
#endif

#endif /* EDGE_CAM_SIM_H */

