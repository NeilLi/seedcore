extends Node3D

const Routes = preload("res://scripts/city_routes.gd")
const START := Vector3(0, 0.18, 6)
const INK := Color("183b32")
const CREAM := Color("faf6eb")
const MUTED := Color("a7bfb2")
const GOLD := Color("f6c667")

var routes := Routes.new()
var anchors: Array[POIAnchor3D] = []
var selected: POIAnchor3D
var planned_stops: Array[POIAnchor3D] = []
var path := PackedVector3Array()
var path_index := 0
var walking := false
var walker := Node3D.new()
var trail := MeshInstance3D.new()
var highlight := MeshInstance3D.new()
var search: LineEdit
var title_label: Label
var story_label: Label
var category_label: Label
var route_label: Label
var route_detail: Label
var status_label: Label
var walk_button: Button
var detour_toggle: CheckButton
var inspect_button: Button
var poi_buttons: Array[Button] = []
var cafe_roof: Node3D
var cafe_controls: HBoxContainer
var roof_button: Button
var place_labels: Array[Label3D] = []

func _ready() -> void:
	cafe_roof = $CafeBuilding.find_child("CafeRoof", true, false) as Node3D
	if cafe_roof == null:
		push_error("Café GLB is missing the CafeRoof group; rebuild it with tools/build_cafe.py.")
	for child in $POIAnchors.get_children():
		anchors.append(child as POIAnchor3D)
	_build_lighting()
	_build_markers()
	_build_walker()
	add_child(trail)
	trail.material_override = _material(GOLD, true)
	_build_interface()
	select_place(anchors[0])
	status_label.text = "Explore the district or ask for a place to begin."

func _build_lighting() -> void:
	var environment := Environment.new()
	environment.background_mode = Environment.BG_COLOR
	environment.background_color = Color("c8d9ce")
	environment.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	environment.ambient_light_color = Color("e4eedb")
	environment.ambient_light_energy = 0.3
	environment.tonemap_mode = Environment.TONE_MAPPER_LINEAR
	var world := WorldEnvironment.new()
	world.environment = environment
	add_child(world)
	var sun := DirectionalLight3D.new()
	sun.rotation_degrees = Vector3(-58, -25, 0)
	sun.light_color = Color("fff0d2")
	sun.light_energy = 0.65
	sun.shadow_enabled = true
	sun.directional_shadow_max_distance = 80
	add_child(sun)

func _build_markers() -> void:
	for anchor in anchors:
		var label := Label3D.new()
		label.text = anchor.poi.display_name.to_upper()
		label.font_size = 64
		label.pixel_size = 0.010
		label.modulate = CREAM
		label.outline_modulate = INK
		label.outline_size = 14
		label.billboard = BaseMaterial3D.BILLBOARD_ENABLED
		label.no_depth_test = false
		add_child(label)
		place_labels.append(label)
		label.position = Vector3(anchor.position.x, 4.5, -4)
		if anchor.poi.id == "textile":
			label.position.y = 7.7
		if anchor.poi.id == "garden":
			label.position = Vector3(-15, 4.7, -3)
		if anchor.poi.id == "cafe":
			label.position = Vector3(-8, 4.8, -5)
		# A dedicated selection volume is independent of asset mesh names.
		var body := StaticBody3D.new()
		body.collision_layer = 2
		body.collision_mask = 0
		body.set_meta("poi", anchor)
		var shape := CollisionShape3D.new()
		var bounds := BoxShape3D.new()
		bounds.size = Vector3(4.6, 4, 5.6)
		if anchor.poi.id == "textile":
			bounds.size.y = 7
		if anchor.poi.id == "cafe":
			bounds.size = Vector3(6.4, 4.2, 6.4)
		shape.shape = bounds
		body.add_child(shape)
		add_child(body)
		body.position = Vector3(anchor.position.x, bounds.size.y * 0.5, -3)
		if anchor.poi.id == "garden":
			body.position.x = -15
		if anchor.poi.id == "cafe":
			body.position.z = -5
	var circle := CylinderMesh.new()
	circle.top_radius = 0.65
	circle.bottom_radius = 0.65
	circle.height = 0.04
	highlight.mesh = circle
	highlight.material_override = _material(GOLD, true)
	add_child(highlight)

func _build_walker() -> void:
	walker.name = "Visitor"
	add_child(walker)
	walker.position = START
	var body := MeshInstance3D.new()
	var capsule := CapsuleMesh.new()
	capsule.radius = 0.24
	capsule.height = 0.95
	body.mesh = capsule
	body.material_override = _material(Color("f18a68"))
	body.position.y = 0.58
	walker.add_child(body)
	var head := MeshInstance3D.new()
	var sphere := SphereMesh.new()
	sphere.radius = 0.21
	sphere.height = 0.42
	head.mesh = sphere
	head.position.y = 1.24
	head.material_override = _material(CREAM)
	walker.add_child(head)
	var label := Label3D.new()
	label.text = "YOU"
	label.position.y = 2
	label.font_size = 42
	label.pixel_size = 0.006
	label.billboard = BaseMaterial3D.BILLBOARD_ENABLED
	label.outline_modulate = INK
	walker.add_child(label)

func _build_interface() -> void:
	var canvas := CanvasLayer.new()
	add_child(canvas)
	var ui := Control.new()
	canvas.add_child(ui)
	ui.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	ui.mouse_filter = Control.MOUSE_FILTER_IGNORE
	var theme := Theme.new()
	theme.default_font_size = 16
	theme.set_color("font_color", "Label", CREAM)
	theme.set_color("font_color", "Button", INK)
	theme.set_color("font_hover_color", "Button", INK)
	theme.set_stylebox("normal", "Button", _style(Color("e8ecdf"), 8))
	theme.set_stylebox("hover", "Button", _style(Color("f6c667"), 8))
	theme.set_stylebox("pressed", "Button", _style(Color("d8b258"), 8))
	theme.set_stylebox("focus", "Button", _style(Color(0, 0, 0, 0), 8, GOLD))
	theme.set_stylebox("normal", "LineEdit", _style(CREAM, 8))
	theme.set_color("font_color", "LineEdit", INK)
	theme.set_color("font_placeholder_color", "LineEdit", Color("64786c"))
	theme.set_color("caret_color", "LineEdit", INK)
	ui.theme = theme
	var header := _panel(ui, Vector2(24, 24), Vector2(-24, 94), Control.PRESET_TOP_WIDE)
	var header_row := HBoxContainer.new()
	header.add_child(header_row)
	header_row.add_theme_constant_override("separation", 22)
	var brand := _label(header_row, "SEEDCORE  /  DIGITAL CITY", 22)
	brand.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_label(header_row, "FOUNDRY LANE     •     Fictional district", 16, MUTED)
	_button(header_row, "District view", show_district)
	var query_panel := _panel(ui, Vector2(24, 108), Vector2(760, 216))
	var query_box := VBoxContainer.new()
	query_panel.add_child(query_box)
	_label(query_box, "A CITY YOU CAN ASK", 13, GOLD)
	var query_row := HBoxContainer.new()
	query_box.add_child(query_row)
	search = LineEdit.new()
	search.name = "Question"
	search.placeholder_text = "Coffee, handmade textiles, a quiet garden…"
	search.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	search.custom_minimum_size.y = 38
	query_row.add_child(search)
	search.text_submitted.connect(find_walk)
	_button(query_row, "Find a walk  →", func() -> void: find_walk(search.text))
	status_label = _label(query_box, "", 14, MUTED)
	var side := _panel(ui, Vector2(-322, 180), Vector2(-24, 645), Control.PRESET_TOP_RIGHT)
	var details := VBoxContainer.new()
	details.add_theme_constant_override("separation", 11)
	side.add_child(details)
	_label(details, "NEIGHBORHOOD PLACES", 13, GOLD)
	for anchor in anchors:
		var button := _button(details, anchor.poi.display_name, func() -> void: select_place(anchor))
		button.alignment = HORIZONTAL_ALIGNMENT_LEFT
		poi_buttons.append(button)
	details.add_child(HSeparator.new())
	category_label = _label(details, "", 12, GOLD)
	title_label = _label(details, "", 22)
	story_label = _label(details, "", 15, Color("d6e1d5"))
	story_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	story_label.custom_minimum_size = Vector2(254, 98)
	inspect_button = _button(details, "Walk here  →", func() -> void: plan_walk(selected))
	cafe_controls = HBoxContainer.new()
	details.add_child(cafe_controls)
	_button(cafe_controls, "View café", focus_cafe)
	roof_button = _button(cafe_controls, "Roof off", toggle_cafe_roof)
	var footer := _panel(ui, Vector2(24, -152), Vector2(-24, -24), Control.PRESET_BOTTOM_WIDE)
	var footer_box := VBoxContainer.new()
	footer_box.add_theme_constant_override("separation", 10)
	footer.add_child(footer_box)
	var route_row := HBoxContainer.new()
	footer_box.add_child(route_row)
	var route_copy := VBoxContainer.new()
	route_copy.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	route_row.add_child(route_copy)
	route_label = _label(route_copy, "Your neighborhood, at walking pace.", 20)
	route_detail = _label(route_copy, "Select a building or search above to preview a route.", 14, MUTED)
	detour_toggle = CheckButton.new()
	detour_toggle.text = "Garden detour"
	detour_toggle.button_pressed = true
	route_row.add_child(detour_toggle)
	# Toggling changes the next plan; it never silently reroutes an active walk.
	detour_toggle.tooltip_text = "Include the garden when planning your next walk."
	walk_button = _button(route_row, "Start walk", toggle_walk)
	walk_button.disabled = true
	_button(route_row, "Reset walk", reset_walk)
	_label(footer_box, "Click a building to inspect   ·   Right-drag to orbit   ·   Middle-drag to pan   ·   Scroll to zoom", 13, MUTED)

func select_place(anchor: POIAnchor3D) -> void:
	selected = anchor
	cafe_controls.visible = anchor.poi.id == "cafe"
	title_label.text = anchor.poi.display_name
	category_label.text = ("COURTYARD" if anchor.poi.category == "green_spot" else anchor.poi.category.to_upper()) + "  /  DEMO PLACE"
	story_label.text = anchor.poi.story_snippet
	highlight.position = anchor.position + Vector3(0, 0.035, 0)
	for index in poi_buttons.size():
		poi_buttons[index].add_theme_stylebox_override("normal", _style(GOLD if anchors[index] == selected else Color("e8ecdf"), 8))

func focus_cafe() -> void:
	$Camera.focus_cafe(cafe_roof != null and not cafe_roof.visible)
	for label in place_labels:
		label.visible = false
	status_label.text = "Komorebi café • Drag to orbit; switch the roof off to look inside."

func toggle_cafe_roof() -> void:
	if cafe_roof == null:
		return
	cafe_roof.visible = not cafe_roof.visible
	roof_button.text = "Roof off" if cafe_roof.visible else "Roof on"
	focus_cafe()

func show_district() -> void:
	$Camera.reset_view()
	for label in place_labels:
		label.visible = true
	if cafe_roof != null:
		cafe_roof.visible = true
		roof_button.text = "Roof off"

func match_place(query: String) -> POIAnchor3D:
	var regex := RegEx.new()
	regex.compile("[\\p{L}\\p{N}-]+")
	var terms: Array[String] = []
	for result in regex.search_all(query.to_lower()):
		terms.append(result.get_string())
	var best: POIAnchor3D = null
	var best_score := 0
	for anchor in anchors:
		var score := 0
		for tag in anchor.poi.mood_tags:
			if terms.has(tag):
				score += 1
		if score > best_score:
			best = anchor
			best_score = score
	return best

func find_walk(query: String) -> void:
	var match_anchor := match_place(query)
	if match_anchor == null:
		reset_walk()
		status_label.text = "No match yet. Try coffee, textiles, wood, or garden."
		return
	select_place(match_anchor)
	plan_walk(match_anchor)
	status_label.text = "Matched your interests to " + match_anchor.poi.display_name + "."

func plan_walk(destination: POIAnchor3D) -> void:
	if destination == null:
		return
	walking = false
	walker.position = START
	planned_stops.clear()
	if detour_toggle.button_pressed and destination.poi.id != "garden":
		planned_stops.append(anchors[3])
	planned_stops.append(destination)
	var stops: Array[Vector3] = []
	var names := PackedStringArray()
	for stop in planned_stops:
		stops.append(stop.position)
		names.append(stop.poi.display_name)
	path = routes.plan(START, stops)
	path_index = 1
	_draw_trail()
	walk_button.disabled = path.size() < 2
	walk_button.text = "Start walk"
	if path.size() < 2:
		route_label.text = "No pedestrian route available."
		route_detail.text = "Choose a connected place in this district."
		return
	route_label.text = " → ".join(names)
	var meters: float = routes.length_meters(path)
	route_detail.text = "%d m  ·  ~%d sec at walking pace  ·  Uses marked crossings" % [roundi(meters), ceili(meters / 1.4)]
	status_label.text = "Route ready. Start your walk when you’re ready."

func toggle_walk() -> void:
	if path.size() < 2:
		return
	if path_index >= path.size():
		walker.position = START
		path_index = 1
	walking = not walking
	walk_button.text = "Pause" if walking else "Resume"
	status_label.text = "Walking through Foundry Lane…" if walking else "Walk paused."

func reset_walk() -> void:
	walking = false
	path.clear()
	path_index = 0
	planned_stops.clear()
	walker.position = START
	trail.mesh = null
	walk_button.disabled = true
	walk_button.text = "Start walk"
	route_label.text = "Your neighborhood, at walking pace."
	route_detail.text = "Select a building or search above to preview a route."
	status_label.text = "Explore the district or ask for a place to begin."

func _physics_process(delta: float) -> void:
	advance_walk(delta)

func advance_walk(delta: float) -> void:
	if not walking or path_index >= path.size():
		return
	walker.position = walker.position.move_toward(path[path_index], delta * 1.4)
	if walker.position.distance_to(path[path_index]) < 0.01:
		for stop in planned_stops:
			if stop.position.distance_to(walker.position) < 0.2:
				select_place(stop)
				status_label.text = "Arrived at " + stop.poi.display_name + "."
		path_index += 1
		if path_index >= path.size():
			walking = false
			walk_button.text = "Walk again"

func _draw_trail() -> void:
	if path.size() < 2:
		trail.mesh = null
		return
	var mesh := ImmediateMesh.new()
	mesh.surface_begin(Mesh.PRIMITIVE_TRIANGLES)
	for index in range(1, path.size()):
		var a := path[index - 1] + Vector3.UP * 0.035
		var b := path[index] + Vector3.UP * 0.035
		var side := (b - a).normalized().cross(Vector3.UP) * 0.10
		for point in [a - side, b - side, b + side, a - side, b + side, a + side]:
			mesh.surface_add_vertex(point)
	mesh.surface_end()
	trail.mesh = mesh

func _unhandled_input(event: InputEvent) -> void:
	if event is InputEventMouseButton and event.button_index == MOUSE_BUTTON_LEFT and event.pressed:
		var camera: Camera3D = $Camera
		var origin := camera.project_ray_origin(event.position)
		var query := PhysicsRayQueryParameters3D.create(origin, origin + camera.project_ray_normal(event.position) * 200, 2)
		var hit := get_world_3d().direct_space_state.intersect_ray(query)
		if not hit.is_empty():
			select_place(hit.collider.get_meta("poi"))

func _material(color: Color, unshaded: bool = false) -> StandardMaterial3D:
	var material := StandardMaterial3D.new()
	material.albedo_color = color
	material.roughness = 0.9
	material.cull_mode = BaseMaterial3D.CULL_DISABLED
	if unshaded:
		material.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	return material

func _style(color: Color, radius: int, border: Color = Color.TRANSPARENT) -> StyleBoxFlat:
	var style := StyleBoxFlat.new()
	style.bg_color = color
	style.set_corner_radius_all(radius)
	style.content_margin_left = 14
	style.content_margin_right = 14
	style.content_margin_top = 10
	style.content_margin_bottom = 10
	style.border_color = border
	style.set_border_width_all(1)
	return style

func _panel(parent: Control, start: Vector2, end: Vector2, preset: int = Control.PRESET_TOP_LEFT) -> PanelContainer:
	var panel := PanelContainer.new()
	parent.add_child(panel)
	panel.set_anchors_and_offsets_preset(preset)
	panel.offset_left = start.x
	panel.offset_top = start.y
	panel.offset_right = end.x
	panel.offset_bottom = end.y
	panel.add_theme_stylebox_override("panel", _style(Color("183b32f5"), 12))
	return panel

func _label(parent: Node, text: String, font_size: int, color: Color = CREAM) -> Label:
	var label := Label.new()
	label.text = text
	label.add_theme_font_size_override("font_size", font_size)
	label.add_theme_color_override("font_color", color)
	parent.add_child(label)
	return label

func _button(parent: Node, text: String, action: Callable) -> Button:
	var button := Button.new()
	button.text = text
	button.mouse_default_cursor_shape = Control.CURSOR_POINTING_HAND
	button.pressed.connect(action)
	parent.add_child(button)
	return button
