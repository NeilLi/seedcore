extends Node3D

const RouteMatcherScript = preload("res://scripts/route_matcher.gd")

@onready var _anchors: Array[POIAnchor3D] = _collect_anchors()
@onready var _route_trail: RouteTrail3D = $RouteTrail
@onready var _start_marker: Marker3D = $WalkerStart
@onready var _prompt_input: LineEdit = %PromptInput
@onready var _route_summary: Label = %RouteSummary

var _matcher := RouteMatcherScript.new()

func _ready() -> void:
	$CameraRig/Camera3D.look_at(Vector3(0.0, 0.0, 0.0))
	%FindWalkButton.pressed.connect(_on_find_walk_pressed)
	_prompt_input.text_submitted.connect(func(_submitted: String) -> void: _on_find_walk_pressed())
	_on_find_walk_pressed()

func _on_find_walk_pressed() -> void:
	var plan: Dictionary = _matcher.make_plan(_prompt_input.text, _anchors, _start_marker.global_position)
	if plan.is_empty():
		_route_summary.text = "Add a POIAnchor3D with a POIResource to create a route."
		_route_trail.show_waypoints(PackedVector3Array())
		return
	var waypoints: PackedVector3Array = plan["waypoints"]
	var destination: POIAnchor3D = plan["destination"]
	var detour: POIAnchor3D = plan["detour"]
	_route_trail.show_waypoints(waypoints)
	var detour_text: String = ""
	if detour != null:
		detour_text = " via %s" % detour.poi.display_name
	_route_summary.text = "%s%s\n%s" % [destination.poi.display_name, detour_text, destination.poi.story_snippet]

func _collect_anchors() -> Array[POIAnchor3D]:
	var anchors: Array[POIAnchor3D] = []
	for child in $POIAnchors.get_children():
		if child is POIAnchor3D:
			anchors.append(child)
	return anchors
