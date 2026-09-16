extends SceneTree

## Save only this application's viewport for layout review.
func _initialize() -> void:
	call_deferred("render")

func render() -> void:
	var landing = load("res://scenes/Landing.tscn").instantiate()
	root.add_child(landing)
	for frame in range(10):
		await process_frame
	await RenderingServer.frame_post_draw
	var args := OS.get_cmdline_user_args()
	var output := args[0] if not args.is_empty() else "/tmp/seedcore-entrance.png"
	var result := root.get_texture().get_image().save_png(output)
	print("ENTRANCE_RENDER: ", output, " result=", result)
	quit(0 if result == OK else 1)
