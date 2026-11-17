from sam3_images import find_in_images

# What to look for, in plain words: SAM 3 takes any short noun phrase. These are
# the 35 labels of its package, in their seven groups.
LABELS = [
    # surface and crossings
    "sidewalk", "crosswalk", "curb", "driveway", "alley", "tactile paving", "stairs",
    # curb ramp variants
    "curb ramp", "curb cut", "wheelchair ramp", "ramp", "curbramp",
    # crossing control
    "traffic light", "pedestrian signal", "stop sign",
    # obstacles and furniture
    "pole", "fire hydrant", "trash bin", "bench", "bollard", "tree", "planter", "parking meter",
    "bicycle rack", "bus stop",
    # temporary obstructions
    "construction barrier", "traffic cone", "scaffolding",
    # surface condition
    "pothole", "puddle", "manhole cover", "sidewalk crack",
    # context
    "person", "car", "bicycle",
]
THRESHOLD = 0.5  # the score SAM 3 needs to keep an object
WIDTH = 960  # the widest images are read and drawn at
MAX_IMAGES = 300  # the most images one run looks at

return find_in_images(
    input_0, curio_load_model("model.curio.sam3"), curio_derived_file,
    labels=LABELS, threshold=THRESHOLD, width=WIDTH, max_images=MAX_IMAGES,
)
