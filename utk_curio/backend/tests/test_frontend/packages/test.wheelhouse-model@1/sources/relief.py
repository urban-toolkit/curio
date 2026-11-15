import numpy as np
import onnxruntime as ort

import curio_wheelhouse_model

model = curio_load_model("test.wheelhouse-model")
session = ort.InferenceSession(model.path, providers=["CPUExecutionProvider"])
relief = session.run(None, {"height": np.arange(64, dtype=np.float32).reshape(1, 1, 8, 8)})[0]

print(curio_wheelhouse_model.MESSAGE)
print("relief", tuple(relief.shape))
return [curio_wheelhouse_model.MESSAGE, float(np.abs(relief).sum())]
