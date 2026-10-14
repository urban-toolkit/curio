from deep_umbra import accumulated_shadow
model = curio_load_model("model.scout.deep-umbra")
return accumulated_shadow(input_0, season=[!! season !!], model=model, output_file=curio_output_file)
