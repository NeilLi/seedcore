extends RefCounted

## Fixture sidewalk graph: pedestrians cross the road only at the two crossings.
## Replaces unconstrained straight lines until the district needs a baked navmesh.
var graph := AStar3D.new()

func _init() -> void:
	for row in range(2):
		for col in range(7):
			var id := row * 7 + col
			graph.add_point(id, Vector3(-12 + col * 4, 0.18, row * 6))
			if col > 0:
				graph.connect_points(id - 1, id)
	graph.connect_points(0, 7)
	graph.connect_points(6, 13)

func path_between(start: Vector3, target: Vector3) -> PackedVector3Array:
	if not start.is_finite() or not target.is_finite():
		return PackedVector3Array()
	var a := graph.get_closest_point(start)
	var b := graph.get_closest_point(target)
	# Reject off-network requests, including clicks on roofs or the street.
	if graph.get_point_position(a).distance_to(start) > 0.5 or graph.get_point_position(b).distance_to(target) > 0.5:
		return PackedVector3Array()
	return graph.get_point_path(a, b)

func plan(start: Vector3, stops: Array[Vector3]) -> PackedVector3Array:
	var result := PackedVector3Array()
	var previous := start
	for stop in stops:
		var segment := path_between(previous, stop)
		if segment.is_empty():
			return PackedVector3Array()
		for point in segment:
			if result.is_empty() or not point.is_equal_approx(result[-1]):
				result.append(point)
		previous = stop
	return result

func length_meters(points: PackedVector3Array) -> float:
	var distance := 0.0
	for index in range(1, points.size()):
		distance += points[index - 1].distance_to(points[index])
	return distance
