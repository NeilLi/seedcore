class_name POIAnchor3D
extends Marker3D

@export var poi: POIResource

func is_usable() -> bool:
	return poi != null and not poi.id.is_empty() and not poi.display_name.is_empty()
