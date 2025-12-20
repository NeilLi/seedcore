#ifndef EDGE_CAM_H
#define EDGE_CAM_H

#include <stdbool.h>

typedef void (*edge_cam_frame_cb_t)(void *frame, int len);

void edge_cam_init(void);
void edge_cam_start(void);
void edge_cam_stop(void);

/* Register callback for captured frames */
void edge_cam_register_callback(edge_cam_frame_cb_t cb);

#endif

