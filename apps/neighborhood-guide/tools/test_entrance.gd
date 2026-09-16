extends SceneTree

var failures := 0

func _initialize() -> void:
	call_deferred("run_checks")

func check(condition: bool, description: String) -> void:
	if not condition:
		failures += 1
		push_error(description)

func run_checks() -> void:
	check(ProjectSettings.get_setting("application/run/main_scene") == "res://scenes/Landing.tscn", "Application must launch into the entrance")
	change_scene_to_file("res://scenes/Landing.tscn")
	await scene_changed
	for index in range(4):
		var entrance = current_scene
		check(entrance.destination_buttons.size() == 4 and entrance.hotspot_buttons.size() == 4, "Each destination must have a card and scene hotspot")
		entrance.open_destination("unknown")
		check(not root.has_meta("neighborhood_entry"), "Unknown destinations must not create navigation state")
		# Exercise a scene hotspot and cards, using keyboard activation for guide.
		var button: Button = entrance.hotspot_buttons[index] if index == 0 else entrance.destination_buttons[index]
		if index == 3:
			button.grab_focus()
			var key := InputEventAction.new()
			key.action = "ui_accept"
			key.pressed = true
			Input.parse_input_event(key)
			key = InputEventAction.new()
			key.action = "ui_accept"
			key.pressed = false
			Input.parse_input_event(key)
		else:
			button.pressed.emit()
		await scene_changed
		await process_frame
		var city = current_scene
		check(city is Node3D, "Destination must enter the actual 3D district")
		check(not root.has_meta("neighborhood_entry"), "Navigation handoff must be consumed once")
		check(not city.walking, "Navigation must not automatically start a walk")
		if index in [1, 2]:
			check(city.selected.poi.id == ("textile" if index == 1 else "wood"), "Maker and craft entries must select their corresponding POI")
			check(not city.path.is_empty(), "Workshop entry must preview a walk")
		elif index == 3:
			check(city.search.has_focus(), "Guide entry must focus the searchable local guide")
		else:
			check(city.path.is_empty(), "Exploration should begin without a preselected route")
		city.go_home()
		await scene_changed
		check(current_scene is Control, "Home must return to the entrance")
	print("ENTRANCE_CHECKS: ", "PASS" if failures == 0 else "FAIL", " (", failures, " failures)")
	quit(0 if failures == 0 else 1)
