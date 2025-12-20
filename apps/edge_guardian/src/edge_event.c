#include "edge_event.h"
#include "edge_guardian.h"
#include "tal_api.h"
#include "tal_sw_timer.h"

static void demo_timer_cb(void *arg)
{
    PR_WARN("Demo Event: simulated intrusion");
    edge_guardian_on_threat_detected("demo timer");
}

void edge_event_init(void)
{
    PR_NOTICE("EdgeEvent initialized");
}

void edge_event_start(void)
{
    PR_NOTICE("EdgeEvent demo started");

    tal_sw_timer_start(
        NULL,
        demo_timer_cb,
        NULL,
        10 * 1000,   // 10 seconds
        TAL_TIMER_ONCE
    );
}

