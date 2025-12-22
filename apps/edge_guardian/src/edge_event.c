#include "edge_event.h"
#include "edge_guardian.h"
#include "tal_api.h"
#include "tal_sw_timer.h"

static TIMER_ID demo_timer_id = NULL;

static void demo_timer_cb(TIMER_ID timer_id, void *arg)
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

    // Create timer with callback and argument
    tal_sw_timer_create(demo_timer_cb, NULL, &demo_timer_id);

    // Start timer with timing parameters
    tal_sw_timer_start(demo_timer_id, 10 * 1000, TAL_TIMER_ONCE);
}

