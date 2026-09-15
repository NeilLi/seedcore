class_name RouteMatcher
extends RefCounted

## Small deterministic matcher for the greybox. A future discovery adapter may
## provide reviewed read-only POI projections, but must not turn this into an
## action or authority path.

const MAX_DETOUR_DISTANCE_METERS := 150.0

func make_plan(prompt: String, anchors: Array[POIAnchor3D], start: Vector3) -> Dictionary:
	var candidates: Array[POIAnchor3D] = []
	for anchor in anchors:
		if anchor.is_usable():
			candidates.append(anchor)

	if candidates.is_empty():
		return {}

	var terms: PackedStringArray = _terms(prompt)
	candidates.sort_custom(func(a: POIAnchor3D, b: POIAnchor3D) -> bool:
		var score_delta := _score(b.poi, terms) - _score(a.poi, terms)
		if score_delta != 0:
			return score_delta < 0
		return a.poi.id.naturalnocasecmp_to(b.poi.id) < 0
	)

	var destination: POIAnchor3D = candidates[0]
	var detour: POIAnchor3D = _best_detour(destination, candidates, terms)
	var waypoints: PackedVector3Array = PackedVector3Array([start])
	if detour != null:
		waypoints.append(detour.global_position)
	waypoints.append(destination.global_position)
	return {
		"destination": destination,
		"detour": detour,
		"waypoints": waypoints,
	}

func _best_detour(destination: POIAnchor3D, candidates: Array[POIAnchor3D], terms: PackedStringArray) -> POIAnchor3D:
	var best: POIAnchor3D
	var best_score := -1
	for candidate in candidates:
		if candidate == destination:
			continue
		if candidate.global_position.distance_to(destination.global_position) > MAX_DETOUR_DISTANCE_METERS:
			continue
		var score := _score(candidate.poi, terms)
		if candidate.poi.category == "detour_view" or candidate.poi.category == "green_spot":
			score += 2
		if score > best_score:
			best = candidate
			best_score = score
	return best

func _score(poi: POIResource, terms: PackedStringArray) -> int:
	var score := 0
	for tag in poi.mood_tags:
		if terms.has(tag.to_lower()):
			score += 3
	for term in terms:
		if poi.category.to_lower().contains(term):
			score += 1
	return score

func _terms(prompt: String) -> PackedStringArray:
	var normalized := prompt.to_lower().replace(",", " ").replace(".", " ")
	var output := PackedStringArray()
	for token in normalized.split(" ", false):
		if token.length() > 1 and not output.has(token):
			output.append(token)
	return output
