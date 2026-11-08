from sam3_tracking import track_objects

# What to look for, in plain words: SAM 3 takes any short noun phrase.
LABELS = [
    "curb ramp", "curb cut", "tactile paving", "bollard", "pole",
    "construction barrier", "traffic cone", "person",
]
EVERY_SECONDS = 0.5  # the gap between two frames SAM 3 looks at
FROM_SECONDS = 0  # the part of each video to track, in seconds from its start
TO_SECONDS = None  # None is the video's end
MAX_SECONDS = 300  # the most video one run takes
WIDTH = 960  # the widest frames are read and drawn at

return track_objects(
    input_0, curio_load_model("model.curio.sam3"), curio_derived_file,
    labels=LABELS, every_seconds=EVERY_SECONDS, from_seconds=FROM_SECONDS,
    to_seconds=TO_SECONDS, max_seconds=MAX_SECONDS, width=WIDTH,
)
