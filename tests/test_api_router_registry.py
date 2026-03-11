from seedcore.api.routers import ACTIVE_ROUTER_NAMES, ACTIVE_ROUTER_SPECS, LEGACY_ROUTER_NAMES


def test_active_router_names_match_registry_specs():
    assert ACTIVE_ROUTER_NAMES == tuple(name for _, name in ACTIVE_ROUTER_SPECS)


def test_active_router_specs_preserve_mount_order():
    assert ACTIVE_ROUTER_SPECS == (
        ("Tasks", "tasks_router"),
        ("Source Registrations", "source_registrations_router"),
        ("Tracking Events", "tracking_events_router"),
        ("Control", "control_router"),
        ("Advisory", "advisory_router"),
        ("PKG", "pkg_router"),
        ("Capabilities", "capabilities_router"),
    )


def test_legacy_router_names_are_archived_not_mounted():
    assert set(LEGACY_ROUTER_NAMES).isdisjoint(ACTIVE_ROUTER_NAMES)
