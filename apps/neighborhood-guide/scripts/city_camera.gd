extends Camera3D

var target := Vector3(0, 0, 0)
var azimuth := 0.32
var elevation := 0.72

func _ready() -> void:
	projection = Camera3D.PROJECTION_ORTHOGONAL
	h_offset = 3.5
	size = 43
	update_view()

func reset_view() -> void:
	h_offset = 3.5
	target = Vector3.ZERO
	azimuth = 0.32
	elevation = 0.72
	size = 43
	update_view()

func focus_cafe(interior: bool = false) -> void:
	target = Vector3(-8, 1.4, -5)
	h_offset = 1.1
	azimuth = 0.56
	elevation = 0.85 if interior else 0.38
	size = 12
	update_view()

func update_view() -> void:
	position = target + Vector3(sin(azimuth) * cos(elevation), sin(elevation), cos(azimuth) * cos(elevation)) * 55
	look_at(target)

func _unhandled_input(event: InputEvent) -> void:
	if event is InputEventMouseButton and event.pressed:
		if event.button_index == MOUSE_BUTTON_WHEEL_UP:
			size = clampf(size - 1, 7, 58)
		elif event.button_index == MOUSE_BUTTON_WHEEL_DOWN:
			size = clampf(size + 1, 7, 58)
	if event is InputEventMouseMotion:
		if event.button_mask & MOUSE_BUTTON_MASK_RIGHT:
			azimuth -= event.relative.x * 0.006
			elevation = clampf(elevation + event.relative.y * 0.004, 0.35, 1.25)
			update_view()
		elif event.button_mask & MOUSE_BUTTON_MASK_MIDDLE:
			var forward := Vector3(basis.z.x, 0, basis.z.z).normalized()
			target += (-basis.x * event.relative.x - forward * event.relative.y) * size * 0.001
			target.x = clampf(target.x, -10, 10)
			target.z = clampf(target.z, -8, 8)
			update_view()
