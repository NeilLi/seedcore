extends SceneTree

var failures := 0

func _initialize() -> void:
	call_deferred("run_checks")

func check(condition: bool, description: String) -> void:
	if not condition:
		failures += 1
		push_error(description)

func run_checks() -> void:
	var city = load("res://scenes/City.tscn").instantiate()
	root.add_child(city)
	await process_frame
	await physics_frame
	check(city.get_node("District").get_child_count() > 20, "Blender district must be instantiated")
	check(city.anchors.size() == 4, "All four place resources must load")
	check(city.match_place("a coffee, please!").poi.id == "cafe", "Coffee query should match cafe")
	check(city.match_place("handmade textile").poi.id == "textile", "Textile query should match studio")
	check(city.match_place("wood carving").poi.id == "wood", "Wood query should match workshop")
	check(city.match_place("hospital") == null, "Unknown requests must not fabricate matches")
	check(city.match_place("") == null, "Empty requests must not fabricate matches")
	# Every route from the south-side entrance to a place must stay on the
	# sidewalk or the two crossings, even when the destination is opposite us.
	for anchor in city.anchors:
		var route: PackedVector3Array = city.routes.path_between(city.START, anchor.position)
		check(route.size() >= 3, "Every POI must have a connected pedestrian route")
		for index in range(1, route.size()):
			var a := route[index - 1]
			var b := route[index]
			if not is_equal_approx(a.z, b.z):
				check(is_equal_approx(a.x, b.x) and is_equal_approx(absf(a.x), 12), "Road crossing must use a marked crossing")
	check(city.routes.path_between(city.START, Vector3(0, 5, -4)).is_empty(), "Roof request must be rejected")
	check(city.routes.path_between(Vector3(INF, 0, 0), city.START).is_empty(), "Non-finite position must be rejected")
	city.find_walk("coffee")
	check(city.planned_stops.size() == 2, "Garden detour must be present when enabled")
	check(city.path[-1].is_equal_approx(city.anchors[0].position), "Route must end at cafe entrance")
	check(is_equal_approx(city.routes.length_meters(city.path), 22.0), "Cafe route must be 22 m via the west crossing")
	city.walk_button.pressed.emit()
	city.advance_walk(0.5)
	check(city.walker.position.distance_to(city.START) > 0.1, "Start button must move the visitor")
	city.walk_button.pressed.emit()
	var paused: Vector3 = city.walker.position
	city.advance_walk(1)
	check(city.walker.position.is_equal_approx(paused), "Pause button must stop movement")
	city.walk_button.pressed.emit()
	for step in range(500):
		city.advance_walk(0.1)
	check(not city.walking and city.selected.poi.id == "cafe", "Walk must complete at destination and reveal its card")
	city.detour_toggle.button_pressed = false
	city.plan_walk(city.anchors[2])
	check(city.planned_stops.size() == 1, "Detour switch must omit garden on next plan")
	city.poi_buttons[1].pressed.emit()
	check(city.selected.poi.id == "textile", "Place button must open textile card")
	city.find_walk("unknown")
	check(city.path.is_empty() and not city.walking and city.walk_button.disabled, "No-match query must clear stale walk")
	city.reset_walk()
	check(city.walker.position.is_equal_approx(city.START), "Reset must restore start position")
	# Ray selection volumes should be present independently of GLB suffixes.
	var query := PhysicsRayQueryParameters3D.create(Vector3(0, 10, -4), Vector3(0, 0, -4), 2)
	var hit: Dictionary = city.get_world_3d().direct_space_state.intersect_ray(query)
	check(not hit.is_empty(), "Textile building must be selectable by a 3D ray")
	if not hit.is_empty():
		check(hit.collider.get_meta("poi").poi.id == "textile", "Building ray must resolve the correct POI")
	print("CITY_CHECKS: ", "PASS" if failures == 0 else "FAIL", " (", failures, " failures)")
	city.queue_free()
	await process_frame
	quit(0 if failures == 0 else 1)
