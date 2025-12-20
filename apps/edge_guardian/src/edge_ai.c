#include "edge_ai.h"
#include "edge_guardian.h"
#include "tal_api.h"

void edge_ai_init(void)
{
    PR_NOTICE("EdgeAI initialized (TinyML placeholder)");
}

void edge_ai_process_frame(void *frame, int len)
{
    PR_DEBUG("EdgeAI processing frame len=%d", len);

    /* v1.0 demo logic */
    bool threat_detected = true;

    if (threat_detected) {
        edge_guardian_on_threat_detected("simulated vision trigger");
    }
}

