async def adjust(controller, energy_slope):
    import logging
    old_tau = controller.tau
    if energy_slope < 0:
        controller.tau = max(controller.tau * 0.9, 0.05)
    elif energy_slope > 0:
        controller.tau = min(controller.tau * 1.1, 0.9)
    logging.info(f"Meta-controller adjusted tau: {old_tau:.4f} -> {controller.tau:.4f} (slope={energy_slope:.4f})") 