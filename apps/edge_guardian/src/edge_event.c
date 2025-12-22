#include "edge_event.h"
#include "edge_guardian.h"
#include "tal_api.h"
#include "tal_sw_timer.h"

/* Compile-time guard for simulation mode */
#ifdef EDGE_SIM_MODE
#include "edge_cam_sim.h"
#include "edge_light_sim.h"
#include "edge_switch_sim.h"
#endif

/* =========================================================
 * Camera Frame Callback
 * ========================================================= */

#ifdef EDGE_SIM_MODE
static void camera_frame_cb(edge_camera_frame_t *frame, edge_cam_event_type_t event)
{
    if (!frame) {
        return;
    }

    switch (event) {
    case EDGE_CAM_EVENT_MOTION:
        PR_INFO("EdgeEvent: Camera frame - MOTION detected (size: %dx%d)", 
                frame->width, frame->height);
        break;
    case EDGE_CAM_EVENT_PERSON:
        PR_INFO("EdgeEvent: Camera frame - PERSON detected (size: %dx%d)", 
                frame->width, frame->height);
        break;
    case EDGE_CAM_EVENT_ANOMALY:
        PR_INFO("EdgeEvent: Camera frame - ANOMALY detected (size: %dx%d)", 
                frame->width, frame->height);
        break;
    default:
        PR_DEBUG("EdgeEvent: Camera frame - normal (size: %dx%d)", 
                 frame->width, frame->height);
        break;
    }
}
#endif /* EDGE_SIM_MODE */

/* =========================================================
 * Lifecycle
 * ========================================================= */

void edge_event_init(void)
{
#ifdef EDGE_SIM_MODE
    // Initialize all simulation modules
    edge_cam_sim_init();
    edge_light_sim_init();
    edge_switch_sim_init();
    
    PR_NOTICE("EdgeEvent initialized (all simulators ready)");
#else
    PR_NOTICE("EdgeEvent initialized (hardware mode)");
#endif
}

void edge_event_start(void)
{
#ifdef EDGE_SIM_MODE
    PR_NOTICE("========================================");
    PR_NOTICE("[EdgeGuardian] Simulation mode enabled");
    PR_NOTICE("  - Camera: synthetic frame generator");
    PR_NOTICE("  - Light: software PWM model");
    PR_NOTICE("  - Switch: CLI-triggered events");
    PR_NOTICE("========================================");

    // Start camera simulation (640x480 @ 2 FPS = 500ms interval)
    edge_cam_sim_register_callback(camera_frame_cb);
    edge_cam_sim_start(640, 480, 500);

    // Report initial light state
    edge_light_sim_report_state();

    // Start switch simulation timer (optional - can also use CLI)
    // Uncomment to enable automatic timer-driven switch events:
    // edge_switch_sim_start_timer(10000); // Every 10 seconds

    PR_NOTICE("EdgeEvent: All simulators active");
    PR_NOTICE("EdgeEvent: Use CLI commands for manual control:");
    PR_NOTICE("  - edge switch press/release");
    PR_NOTICE("  - edge relay on/off");
    PR_NOTICE("  - edge help (for full command list)");
#else
    PR_NOTICE("EdgeEvent: Hardware mode - no simulators");
#endif
}

