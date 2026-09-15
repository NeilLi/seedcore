class_name RouteTrail3D
extends MeshInstance3D

@export var route_height := 0.08

func show_waypoints(world_points: PackedVector3Array) -> void:
	if world_points.size() < 2:
		mesh = null
		return
	var line := ImmediateMesh.new()
	line.surface_begin(Mesh.PRIMITIVE_LINE_STRIP)
	for point in world_points:
		line.surface_add_vertex(to_local(point + Vector3.UP * route_height))
	line.surface_end()
	mesh = line
