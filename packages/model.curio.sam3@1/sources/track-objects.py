from sam3_tracking import track_objects

# The Widgets tab sets what to look for, in plain words (SAM 3 takes any short
# noun phrase), the gap between two frames SAM 3 looks at, where the part of
# each video to track starts, in seconds from its start, the most frames of a
# video one run looks at, and the widest frames are read and drawn at. These
# two may be None, which no widget holds, so they are set here:
FORGET_SECONDS = 10  # SAM 3 lets go of an object unseen this long; None keeps every object
TO_SECONDS = None  # where the part of each video ends; None is the video's end

return track_objects(
    input_0, curio_load_model("model.curio.sam3"), curio_derived_file,
    labels=[!! labels !!], every_seconds=float([!! every_seconds !!]), forget_seconds=FORGET_SECONDS,
    from_seconds=float([!! from_seconds !!]), to_seconds=TO_SECONDS,
    max_frames=int([!! max_frames !!]), width=int([!! width !!]),
)
