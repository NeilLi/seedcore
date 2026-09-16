extends Control

## Local navigation using an original orthographic Blender render.
## Destinations resolve to fictional POIs in the existing district.
const ART := preload("res://assets/illustrations/entrance_render.png")
const LAYOUT := preload("res://scripts/entrance_layout.gd")
const DESIGN_SIZE := Vector2(1440, 900)
const INK := Color("284a40")
const MUTED := Color("7a8176")
const PAPER := Color("fcf5ec")
const DESTINATIONS := [
	["explore", "01", "Explore the neighborhood", "Find a café, a garden, a little detour.", "5e877c"],
	["textile", "02", "Meet the makers", "Step inside the local textile studio.", "c77960"],
	["wood", "03", "Discover local craft", "Visit the neighborhood wood workshop.", "a68a52"],
	["guide", "04", "Ask your guide", "Find a place that feels like you.", "668592"],
]

var canvas := Control.new()
var destination_buttons: Array[Button] = []
var hotspot_buttons: Array[Button] = []
var _opening := false
var _message: Label

func _ready() -> void:
	var background := ColorRect.new()
	background.color = PAPER
	background.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	background.mouse_filter = Control.MOUSE_FILTER_IGNORE
	add_child(background)
	add_child(canvas)
	canvas.size = DESIGN_SIZE
	var font := SystemFont.new()
	font.font_names = PackedStringArray(["Helvetica Neue", "Arial"])
	var theme := Theme.new()
	theme.default_font = font
	theme.default_font_size = 17
	canvas.theme = theme
	_build_entrance()
	resized.connect(_fit)
	_fit()

func _fit() -> void:
	var ratio := minf(size.x / DESIGN_SIZE.x, size.y / DESIGN_SIZE.y)
	canvas.scale = Vector2.ONE * ratio
	canvas.position = (size - DESIGN_SIZE * ratio) * 0.5

func _build_entrance() -> void:
	_label(canvas, "◈", Vector2(48, 29), Vector2(34, 44), 34, INK)
	_label(canvas, "seedcore", Vector2(91, 33), Vector2(170, 34), 25, INK)
	_label(canvas, "D I G I T A L   C I T Y", Vector2(258, 42), Vector2(230, 22), 12, MUTED)
	_nav("The neighborhood", Rect2(828, 33, 180, 42), "explore")
	_nav("Local makers", Rect2(1016, 33, 150, 42), "textile")
	var guide := _button(canvas, "Your guide  ↗", Rect2(1193, 29, 195, 48), INK, Color.WHITE)
	guide.pressed.connect(open_destination.bind("guide"))
	_rule(Vector2(48, 94), Vector2(1344, 1))

	var picture := TextureRect.new()
	picture.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
	picture.texture = ART
	picture.position = Vector2(399, 105)
	picture.size = Vector2(1010, 673.333)
	picture.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT_CENTERED
	picture.mouse_filter = Control.MOUSE_FILTER_IGNORE
	canvas.add_child(picture)

	_label(canvas, "WELCOME TO FOUNDRY LANE", Vector2(57, 163), Vector2(360, 24), 12, Color("a47750"))
	var heading := _label(canvas, "A little curiosity.\nA whole\nneighborhood.", Vector2(53, 211), Vector2(393, 190), 48, INK)
	var display := SystemFont.new()
	display.font_names = PackedStringArray(["Iowan Old Style", "Baskerville", "Georgia"])
	heading.add_theme_font_override("font", display)
	_label(canvas, "Meet the people, places, and small\nstories that make a city feel like home.", Vector2(57, 422), Vector2(352, 62), 18, MUTED)
	var explore := _button(canvas, "Let’s explore   →", Rect2(57, 518, 243, 57), INK, Color.WHITE)
	explore.pressed.connect(open_destination.bind("explore"))
	_label(canvas, "Take a look around. Choose your own way.", Vector2(57, 593), Vector2(352, 44), 13, MUTED)

	# Position pins on the map, textile kiosk, craft display, and guide desk.
	_hotspot("01  Explore", _pin_position(picture, "explore"), "explore", Color("5e877c"))
	_hotspot("02  Makers", _pin_position(picture, "textile"), "textile", Color("c77960"))
	_hotspot("03  Craft", _pin_position(picture, "wood"), "wood", Color("a68a52"))
	_hotspot("04  Your guide", _pin_position(picture, "guide"), "guide", Color("668592"))

	_label(canvas, "WHERE WILL YOU BEGIN?", Vector2(57, 699), Vector2(500, 20), 12, MUTED)
	for index in DESTINATIONS.size():
		var destination: Array = DESTINATIONS[index]
		var tint := Color(destination[4])
		var card := _button(canvas, "", Rect2(56 + index * 336, 733, 320, 108), Color("fffcf7"), INK)
		card.name = "Destination_" + destination[0]
		card.tooltip_text = destination[2] + ". " + destination[3]
		card.pressed.connect(open_destination.bind(destination[0]))
		_label(card, destination[1], Vector2(19, 13), Vector2(42, 22), 12, tint)
		_label(card, "↗", Vector2(278, 13), Vector2(24, 24), 19, tint)
		_label(card, destination[2], Vector2(19, 39), Vector2(290, 29), 18, INK)
		_label(card, destination[3], Vector2(19, 75), Vector2(288, 25), 13, MUTED)
		destination_buttons.append(card)
		card.mouse_entered.connect(_highlight.bind(index, true))
		card.mouse_exited.connect(_highlight.bind(index, false))
		card.focus_entered.connect(_highlight.bind(index, true))
		card.focus_exited.connect(_highlight.bind(index, false))
	_rule(Vector2(57, 864), Vector2(1328, 1))
	_label(canvas, "A fictional neighborhood. Real room for discovery.", Vector2(57, 875), Vector2(610, 22), 11, MUTED)
	_message = _label(canvas, "LOCAL PREVIEW    /    POWERED BY SEEDCORE", Vector2(990, 875), Vector2(396, 22), 11, MUTED)
	_message.horizontal_alignment = HORIZONTAL_ALIGNMENT_RIGHT

func _pin_position(picture: TextureRect, destination: String) -> Vector2:
	return picture.position + picture.size * LAYOUT.POINTS[destination] - Vector2(77.5, 21.5)

func _highlight(index: int, active: bool) -> void:
	hotspot_buttons[index].modulate = Color("ffe7c6") if active else Color.WHITE

func _hotspot(title: String, position: Vector2, destination: String, tint: Color) -> void:
	var pin := _button(canvas, title + "  ↗", Rect2(position, Vector2(155, 43)), Color("fffcf6"), INK)
	pin.add_theme_font_size_override("font_size", 14)
	pin.add_theme_stylebox_override("normal", _style(Color("fffcf6"), tint, 21))
	pin.tooltip_text = "Open " + title.substr(4)
	pin.pressed.connect(open_destination.bind(destination))
	hotspot_buttons.append(pin)

func _nav(title: String, rect: Rect2, destination: String) -> void:
	var button := _button(canvas, title, rect, PAPER, INK)
	button.add_theme_stylebox_override("normal", _style(PAPER, PAPER))
	button.pressed.connect(open_destination.bind(destination))

func open_destination(destination: String) -> void:
	if _opening or destination not in ["explore", "textile", "wood", "guide"]:
		return
	_opening = true
	get_tree().root.set_meta("neighborhood_entry", destination)
	var result := get_tree().change_scene_to_file("res://scenes/City.tscn")
	if result != OK:
		get_tree().root.remove_meta("neighborhood_entry")
		_opening = false
		_message.text = "Couldn’t open the district. Please try again."

func _button(parent: Control, title: String, rect: Rect2, fill: Color, ink: Color) -> Button:
	var button := Button.new()
	button.text = title
	button.position = rect.position
	button.size = rect.size
	button.mouse_default_cursor_shape = Control.CURSOR_POINTING_HAND
	button.add_theme_color_override("font_color", ink)
	button.add_theme_color_override("font_hover_color", ink)
	button.add_theme_color_override("font_pressed_color", ink)
	button.add_theme_color_override("font_focus_color", ink)
	button.add_theme_stylebox_override("normal", _style(fill, Color("e6e0d4")))
	button.add_theme_stylebox_override("hover", _style(fill.lightened(0.035), Color("bbab8c")))
	button.add_theme_stylebox_override("pressed", _style(fill.darkened(0.06), Color("b79869")))
	var focus := _style(Color.TRANSPARENT, Color("b37c3e"))
	focus.set_border_width_all(3)
	button.add_theme_stylebox_override("focus", focus)
	parent.add_child(button)
	return button

func _label(parent: Control, text: String, position: Vector2, dimensions: Vector2, font_size: int, color: Color) -> Label:
	var label := Label.new()
	label.text = text
	label.position = position
	label.size = dimensions
	label.add_theme_font_size_override("font_size", font_size)
	label.add_theme_color_override("font_color", color)
	label.mouse_filter = Control.MOUSE_FILTER_IGNORE
	parent.add_child(label)
	return label

func _rule(position: Vector2, dimensions: Vector2) -> void:
	var line := ColorRect.new()
	line.position = position
	line.size = dimensions
	line.color = Color("e7dfd1")
	line.mouse_filter = Control.MOUSE_FILTER_IGNORE
	canvas.add_child(line)

func _style(fill: Color, border: Color, radius: int = 12) -> StyleBoxFlat:
	var style := StyleBoxFlat.new()
	style.bg_color = fill
	style.border_color = border
	style.set_border_width_all(1)
	style.set_corner_radius_all(radius)
	return style
