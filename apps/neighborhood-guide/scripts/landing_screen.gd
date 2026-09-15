extends Control

## The initial Digital City scene is a responsive presentation surface. It uses
## fictional labels and routes visitors to the local 3D prototype only; it does
## not query or mutate SeedCore authority, custody, evidence, or policy state.

const BASE_WIDTH := 866.0
const BACKGROUND := Color("17352d")
const PRIMARY_TEXT := Color("f5f0e8")
const MUTED_TEXT := Color("bcc8c3")
const MINT_TEXT := Color("9cdccc")
const ACCENT := Color("ffad98")
const PANEL := Color("283f35")

var _scale := 1.0
var _experience_open := false
var _experience_rect := Rect2()
var _scene_link_rect := Rect2()
var _body_font: Font
var _display_font: Font

func _ready() -> void:
	mouse_filter = Control.MOUSE_FILTER_STOP
	_body_font = _system_font(PackedStringArray(["Avenir Next", "Helvetica Neue", "Arial"]))
	_display_font = _system_font(PackedStringArray(["Iowan Old Style", "Baskerville", "Georgia", "Times New Roman"]))
	resized.connect(queue_redraw)
	queue_redraw()

func _draw() -> void:
	_scale = size.x / BASE_WIDTH
	draw_rect(Rect2(Vector2.ZERO, size), BACKGROUND)
	_draw_hero_illustration()
	_draw_copy()

func _draw_hero_illustration() -> void:
	var margin := 59.0 * _scale
	var hero := Rect2(margin, 25.0 * _scale, 725.0 * _scale, 388.0 * _scale)
	draw_style_box(_rounded_box(Color("e5eff0"), 42.0 * _scale), hero)

	# Soft street and planted-route bands make the illustration legible before
	# the Blender street kit exists. The actual 3D scene remains a separate route.
	var road_y := hero.position.y + hero.size.y * 0.84
	draw_set_transform(Vector2.ZERO, 0.0, Vector2.ONE)
	draw_circle(Vector2(hero.get_center().x, road_y + 175.0 * _scale), 250.0 * _scale, Color(0.41, 0.59, 0.55, 0.23))
	draw_circle(Vector2(hero.get_center().x, road_y + 203.0 * _scale), 260.0 * _scale, Color(0.9, 0.86, 0.56, 0.25))

	var building_base := hero.position.y + hero.size.y * 0.84
	_draw_building(Rect2(hero.position.x + 79.0 * _scale, building_base - 148.0 * _scale, 167.0 * _scale, 164.0 * _scale), Color("fffaf2"), Color("f3b85d"))
	_draw_building(Rect2(hero.position.x + 283.0 * _scale, building_base - 215.0 * _scale, 167.0 * _scale, 231.0 * _scale), Color("f38267"), Color("ffc160"))
	_draw_building(Rect2(hero.position.x + 486.0 * _scale, building_base - 120.0 * _scale, 167.0 * _scale, 136.0 * _scale), Color("fff6d8"), Color("f3b85d"))

	var pin_center := Vector2(hero.get_center().x, hero.position.y + 77.0 * _scale)
	draw_circle(pin_center, 26.0 * _scale, Color(1.0, 1.0, 1.0, 0.95))
	draw_circle(pin_center, 12.0 * _scale, Color("ee715b"))
	draw_colored_polygon(PackedVector2Array([
		pin_center + Vector2(-10.0, 7.0) * _scale,
		pin_center + Vector2(10.0, 7.0) * _scale,
		pin_center + Vector2(0.0, 27.0) * _scale,
	]), Color(1.0, 1.0, 1.0, 0.95))

	var tag_y := hero.end.y - 64.0 * _scale
	_draw_pill(Rect2(hero.position.x + 20.0 * _scale, tag_y, 160.0 * _scale, 50.0 * _scale), Color("173d35"), "Local café", PRIMARY_TEXT, 18)
	_draw_pill(Rect2(hero.position.x + 192.0 * _scale, tag_y, 190.0 * _scale, 50.0 * _scale), Color("fbfaf8"), "Textile studio", Color("18372f"), 18)
	_draw_pill(Rect2(hero.position.x + 394.0 * _scale, tag_y, 216.0 * _scale, 50.0 * _scale), Color("fbfaf8"), "Wood workshop", Color("18372f"), 18)

func _draw_building(rect: Rect2, fill: Color, window_color: Color) -> void:
	draw_style_box(_rounded_box(fill, 17.0 * _scale), rect)
	var window_size := Vector2(20.0, 28.0) * _scale
	var left_window := Rect2(rect.position + Vector2(28.0, 36.0) * _scale, window_size)
	var right_window := Rect2(rect.position + Vector2(rect.size.x - 48.0 * _scale, 36.0 * _scale), window_size)
	draw_style_box(_rounded_box(window_color, 6.0 * _scale), left_window)
	draw_style_box(_rounded_box(window_color, 6.0 * _scale), right_window)

func _draw_copy() -> void:
	var left := 59.0 * _scale
	var content_top := 490.0 * _scale
	_draw_text(_body_font, Vector2(left, content_top), "A CITY YOU CAN ASK", 23, MINT_TEXT)
	_draw_text(_display_font, Vector2(left, 573.0 * _scale), "Digital City", 82, PRIMARY_TEXT)

	var description := [
		"A neighborhood guide that helps visitors find a",
		"local café, meet a maker, or choose a small detour",
		"worth taking. Start with a question and turn it into a",
		"walk.",
	]
	for index in description.size():
		_draw_text(_body_font, Vector2(left, (666.0 + index * 50.0) * _scale), description[index], 29, MUTED_TEXT)

	var quote_rect := Rect2(left, 862.0 * _scale, 725.0 * _scale, 130.0 * _scale)
	draw_style_box(_rounded_box(PANEL, 20.0 * _scale), quote_rect)
	draw_rect(Rect2(quote_rect.position, Vector2(6.0 * _scale, quote_rect.size.y)), Color("f7ce68"))
	_draw_text(_display_font, quote_rect.position + Vector2(37.0, 52.0) * _scale, "The best stop might be the workshop you nearly", 28, PRIMARY_TEXT)
	_draw_text(_display_font, quote_rect.position + Vector2(37.0, 93.0) * _scale, "walked past.", 28, PRIMARY_TEXT)

	_draw_pill(Rect2(left, 1029.0 * _scale, 180.0 * _scale, 43.0 * _scale), Color("29463d"), "Local makers", PRIMARY_TEXT, 17)
	_draw_pill(Rect2(left + 191.0 * _scale, 1029.0 * _scale, 258.0 * _scale, 43.0 * _scale), Color("29463d"), "Neighborhood walks", PRIMARY_TEXT, 17)
	_draw_pill(Rect2(left + 461.0 * _scale, 1029.0 * _scale, 262.0 * _scale, 43.0 * _scale), Color("29463d"), "Ask in your language", PRIMARY_TEXT, 17)

	draw_line(Vector2(left, 1120.0 * _scale), Vector2(left + 725.0 * _scale, 1120.0 * _scale), Color("385149"), 1.0)
	_draw_text(_body_font, Vector2(left, 1180.0 * _scale), "FOR", 21, MUTED_TEXT)
	_draw_text(_body_font, Vector2(left + 200.0 * _scale, 1184.0 * _scale), "Visitors, residents and local producers", 25, PRIMARY_TEXT)
	_draw_text(_body_font, Vector2(left, 1242.0 * _scale), "THE MOMENT", 21, MUTED_TEXT)
	_draw_text(_body_font, Vector2(left + 200.0 * _scale, 1246.0 * _scale), "“What’s nearby that we’d love to discover?”", 24, PRIMARY_TEXT)

	_experience_rect = Rect2(left, 1370.0 * _scale, 725.0 * _scale, 60.0 * _scale)
	_draw_text(_body_font, Vector2(left, 1412.0 * _scale), "What the experience feels like", 26, ACCENT)
	_draw_text(_body_font, Vector2(left + 706.0 * _scale, 1414.0 * _scale), "−" if _experience_open else "+", 32, ACCENT)
	if _experience_open:
		_draw_text(_body_font, Vector2(left, 1458.0 * _scale), "Warm, source-aware suggestions with small, optional detours.", 20, MUTED_TEXT)

	var link_y := 1498.0 if not _experience_open else 1536.0
	_scene_link_rect = Rect2(left, (link_y - 42.0) * _scale, 400.0 * _scale, 58.0 * _scale)
	_draw_text(_body_font, Vector2(left, link_y * _scale), "Read the Digital City scene  →", 26, ACCENT)

func _gui_input(event: InputEvent) -> void:
	if event is InputEventMouseButton and event.button_index == MOUSE_BUTTON_LEFT and not event.pressed:
		if _experience_rect.has_point(event.position):
			_experience_open = not _experience_open
			queue_redraw()
		elif _scene_link_rect.has_point(event.position):
			get_tree().change_scene_to_file("res://scenes/Main.tscn")

func _draw_pill(rect: Rect2, fill: Color, label: String, text_color: Color, font_size: int) -> void:
	draw_style_box(_rounded_box(fill, rect.size.y * 0.5), rect)
	var text_width := _body_font.get_string_size(label, HORIZONTAL_ALIGNMENT_LEFT, -1, font_size * _scale).x
	var text_position := Vector2(rect.get_center().x - text_width * 0.5, rect.position.y + rect.size.y * 0.67)
	draw_string(_body_font, text_position, label, HORIZONTAL_ALIGNMENT_LEFT, -1, font_size * _scale, text_color)

func _draw_text(font: Font, position: Vector2, text: String, font_size: int, color: Color) -> void:
	draw_string(font, position, text, HORIZONTAL_ALIGNMENT_LEFT, -1, font_size * _scale, color)

func _rounded_box(color: Color, radius: float) -> StyleBoxFlat:
	var style := StyleBoxFlat.new()
	style.bg_color = color
	style.corner_radius_top_left = int(radius)
	style.corner_radius_top_right = int(radius)
	style.corner_radius_bottom_left = int(radius)
	style.corner_radius_bottom_right = int(radius)
	return style

func _system_font(names: PackedStringArray) -> Font:
	var font := SystemFont.new()
	font.font_names = names
	return font
