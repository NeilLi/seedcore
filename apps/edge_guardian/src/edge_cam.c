#include "edge_cam.h"
#include "tal_api.h"

static edge_cam_frame_cb_t g_frame_cb = NULL;

void edge_cam_init(void)
{
    PR_NOTICE("EdgeCam initialized");
}

void edge_cam_start(void)
{
    PR_NOTICE("EdgeCam started (DVP placeholder)");
}

void edge_cam_stop(void)
{
    PR_NOTICE("EdgeCam stopped");
}

void edge_cam_register_callback(edge_cam_frame_cb_t cb)
{
    g_frame_cb = cb;
}

