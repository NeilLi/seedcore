class_name POIResource
extends Resource

## Presentation data for one curated stop. It contains no authority or evidence
## semantics; real data must come from a reviewed read-only projection.

@export var id: String
@export var display_name: String
@export_enum("cafe", "maker", "detour_view", "history", "green_spot") var category: String
@export var mood_tags: PackedStringArray = PackedStringArray()
@export_multiline var story_snippet: String
