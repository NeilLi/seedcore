/**
 * @file edge_cam_sim.c
 * @brief Synthetic camera frame generator implementation
 */

#include "edge_cam_sim.h"
#include "edge_guardian.h"
#include "tal_api.h"
#include "tal_sw_timer.h"
#include "tuya_iot.h"
#include <stdlib.h>
#include <string.h>

/* =========================================================
 * Internal State
 * ========================================================= */

static edge_cam_frame_cb_t g_frame_cb = NULL;
static TIMER_ID g_frame_timer_id = NULL;
static uint16_t g_frame_width = 640;
static uint16_t g_frame_height = 480;
static uint32_t g_frame_interval_ms = 1000; // 1 FPS default
static uint32_t g_frame_counter = 0;
static edge_cam_event_type_t g_next_event = EDGE_CAM_EVENT_NONE;

/* Static frame buffer (reused to avoid malloc/free per frame) */
#define MAX_FRAME_SIZE (640 * 480)  // Grayscale: 640x480 = 307200 bytes
static uint8_t g_frame_buffer[MAX_FRAME_SIZE] = {0};
static bool g_frame_buffer_allocated = false;

/* =========================================================
 * Internal Helpers
 * ========================================================= */

/**
 * @brief Report motion detection DP to Tuya Cloud
 */
static void report_motion_dp(bool detected)
{
    char dp_json[128];
    snprintf(dp_json, sizeof(dp_json), "{\"2\":%s}", detected ? "true" : "false");
    PR_INFO("EdgeCam: report motion_detected=%d", detected);
    tuya_iot_dp_report_json(tuya_iot_client_get(), dp_json);
}

/**
 * @brief Report person detection DP to Tuya Cloud
 */
static void report_person_dp(bool detected)
{
    char dp_json[128];
    snprintf(dp_json, sizeof(dp_json), "{\"3\":%s}", detected ? "true" : "false");
    PR_INFO("EdgeCam: report person_detected=%d", detected);
    tuya_iot_dp_report_json(tuya_iot_client_get(), dp_json);
}

/**
 * @brief Report anomaly score DP to Tuya Cloud
 */
static void report_anomaly_dp(uint8_t score)
{
    char dp_json[128];
    snprintf(dp_json, sizeof(dp_json), "{\"4\":%d}", score);
    PR_INFO("EdgeCam: report anomaly_score=%d", score);
    tuya_iot_dp_report_json(tuya_iot_client_get(), dp_json);
}

/**
 * @brief Generate synthetic frame data
 */
static void generate_frame_data(edge_camera_frame_t *frame, edge_cam_event_type_t event_type)
{
    if (!frame || !frame->data) {
        return;
    }

    size_t pixel_count = frame->width * frame->height;
    size_t bytes_per_pixel = (frame->format == 0) ? 1 : ((frame->format == 1) ? 2 : 3);
    size_t frame_size = pixel_count * bytes_per_pixel;

    // Generate base pattern (checkerboard or gradient)
    uint32_t seed = g_frame_counter + (uint32_t)tal_time_get_posix();
    
    // Simulate different patterns based on event type
    switch (event_type) {
    case EDGE_CAM_EVENT_MOTION:
        // Add moving pattern (bright region moving)
        for (size_t i = 0; i < frame_size; i++) {
            uint32_t pos = (i + seed) % frame_size;
            frame->data[i] = (uint8_t)(128 + (pos % 64));
        }
        break;
    
    case EDGE_CAM_EVENT_PERSON:
        // Add person-like pattern (vertical blob)
        for (size_t i = 0; i < frame_size; i++) {
            uint32_t x = (i / bytes_per_pixel) % frame->width;
            // Create vertical blob (person-like shape)
            if (x > frame->width / 3 && x < 2 * frame->width / 3) {
                frame->data[i] = 200; // Bright vertical region
            } else {
                frame->data[i] = 50;  // Dark background
            }
        }
        break;
    
    case EDGE_CAM_EVENT_ANOMALY:
        // Add high-contrast anomaly pattern
        for (size_t i = 0; i < frame_size; i++) {
            frame->data[i] = (uint8_t)((i % 2) ? 255 : 0); // High contrast
        }
        break;
    
    default:
        // Normal frame (gradient)
        for (size_t i = 0; i < frame_size; i++) {
            frame->data[i] = (uint8_t)((i * 255) / frame_size);
        }
        break;
    }
}

/**
 * @brief Timer callback for frame generation
 */
static void frame_timer_cb(TIMER_ID timer_id, void *arg)
{
    edge_camera_frame_t frame;
    size_t frame_size;
    edge_cam_event_type_t event_type = EDGE_CAM_EVENT_NONE;

    // Determine event type (simulate periodic events)
    g_frame_counter++;
    
    // Simulate events: motion every 5 frames, person every 10, anomaly every 20
    if (g_frame_counter % 20 == 0) {
        event_type = EDGE_CAM_EVENT_ANOMALY;
        g_next_event = EDGE_CAM_EVENT_NONE;
    } else if (g_frame_counter % 10 == 0) {
        event_type = EDGE_CAM_EVENT_PERSON;
        g_next_event = EDGE_CAM_EVENT_NONE;
    } else if (g_frame_counter % 5 == 0) {
        event_type = EDGE_CAM_EVENT_MOTION;
        g_next_event = EDGE_CAM_EVENT_NONE;
    } else if (g_next_event != EDGE_CAM_EVENT_NONE) {
        event_type = g_next_event;
        g_next_event = EDGE_CAM_EVENT_NONE;
    }

    // Use static frame buffer (reused to avoid malloc/free per frame)
    frame_size = g_frame_width * g_frame_height;
    if (frame_size > MAX_FRAME_SIZE) {
        PR_ERR("EdgeCam: frame size %zu exceeds buffer %d", frame_size, MAX_FRAME_SIZE);
        return;
    }

    frame.data = g_frame_buffer;
    frame.width = g_frame_width;
    frame.height = g_frame_height;
    frame.format = 0; // Grayscale
    frame.timestamp = (uint32_t)tal_time_get_posix();

    // Generate synthetic frame
    generate_frame_data(&frame, event_type);

    // Report DPs based on event type
    switch (event_type) {
    case EDGE_CAM_EVENT_MOTION:
        report_motion_dp(true);
        edge_guardian_on_threat_detected("simulated motion");
        break;
    
    case EDGE_CAM_EVENT_PERSON:
        report_person_dp(true);
        edge_guardian_on_threat_detected("simulated person");
        break;
    
    case EDGE_CAM_EVENT_ANOMALY:
        report_anomaly_dp(85); // High anomaly score
        edge_guardian_on_threat_detected("simulated anomaly");
        break;
    
    default:
        // Normal frame - no events
        break;
    }

    // Call registered callback if available
    if (g_frame_cb) {
        g_frame_cb(&frame, event_type);
    }

    // Note: frame buffer is static, no free needed
}

/* =========================================================
 * Public API
 * ========================================================= */

void edge_cam_sim_init(void)
{
    g_frame_cb = NULL;
    g_frame_timer_id = NULL;
    g_frame_counter = 0;
    g_next_event = EDGE_CAM_EVENT_NONE;
    g_frame_buffer_allocated = false;
    PR_NOTICE("EdgeCamSim initialized (static buffer: %d bytes)", MAX_FRAME_SIZE);
}

void edge_cam_sim_start(uint16_t width, uint16_t height, uint32_t interval_ms)
{
    if (g_frame_timer_id) {
        PR_WARN("EdgeCamSim: already started");
        return;
    }

    g_frame_width = width ? width : 640;
    g_frame_height = height ? height : 480;
    g_frame_interval_ms = interval_ms ? interval_ms : 1000;

    // Create timer for frame generation
    tal_sw_timer_create(frame_timer_cb, NULL, &g_frame_timer_id);
    tal_sw_timer_start(g_frame_timer_id, g_frame_interval_ms, TAL_TIMER_CYCLE);

    PR_NOTICE("EdgeCamSim started: %dx%d @ %dms", g_frame_width, g_frame_height, g_frame_interval_ms);
}

void edge_cam_sim_stop(void)
{
    if (g_frame_timer_id) {
        tal_sw_timer_stop(g_frame_timer_id);
        tal_sw_timer_delete(g_frame_timer_id);
        g_frame_timer_id = NULL;
    }
    PR_NOTICE("EdgeCamSim stopped");
}

void edge_cam_sim_register_callback(edge_cam_frame_cb_t cb)
{
    g_frame_cb = cb;
}

void edge_cam_sim_generate(edge_camera_frame_t *frame, edge_cam_event_type_t event_type)
{
    if (!frame) {
        return;
    }

    if (!frame->data) {
        // Allocate buffer if not provided
        size_t frame_size = frame->width * frame->height;
        frame->data = (uint8_t *)tal_malloc(frame_size);
        if (!frame->data) {
            PR_ERR("EdgeCamSim: failed to allocate frame buffer");
            return;
        }
    }

    generate_frame_data(frame, event_type);
    frame->timestamp = (uint32_t)tal_time_get_posix();
}

void edge_cam_sim_trigger_event(edge_cam_event_type_t event_type)
{
    g_next_event = event_type;
    PR_NOTICE("EdgeCamSim: event %d queued for next frame", event_type);
}

