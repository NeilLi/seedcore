extends SceneTree

## Render the application's own viewport to a review artifact with real GPU
## rendering. This does not capture other applications or the desktop.
func _initialize() -> void:
	call_deferred("render")

func render() -> void:
	var city = load("res://scenes/City.tscn").instantiate()
	root.add_child(city)
	await process_frame
	city.search.text = "coffee"
	city.find_walk("coffee")
	var args := OS.get_cmdline_user_args()
	if args.has("--cafe"):
		city.focus_cafe()
	if args.has("--roof-off"):
		city.toggle_cafe_roof()
	for frame in range(15):
		await process_frame
	await RenderingServer.frame_post_draw
	var output := args[0] if not args.is_empty() else "/tmp/seedcore-digital-city.png"
	var result := root.get_texture().get_image().save_png(output)
	print("CITY_RENDER: ", output, " result=", result)
	quit(0 if result == OK else 1)
