from sam3_images import find_in_images

# The Widgets tab sets what to look for, in plain words (SAM 3 takes any short
# noun phrase; it starts with the 35 labels of its package, in their seven
# groups), the score SAM 3 needs to keep an object, the widest images are read
# and drawn at, and the most images one run looks at.

return find_in_images(
    input_0, curio_load_model("model.curio.sam3"), curio_derived_file,
    labels=[!! labels !!], threshold=float([!! threshold !!]),
    width=int([!! width !!]), max_images=int([!! max_images !!]),
)
