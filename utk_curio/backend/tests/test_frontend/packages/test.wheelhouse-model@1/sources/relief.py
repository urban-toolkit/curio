import numpy as np

import curio_wheelhouse_model

model = curio_load_model("test.wheelhouse-model")
relief = model.run({"height": np.arange(64, dtype=np.float32).reshape(1, 1, 8, 8)})[0]

print(curio_wheelhouse_model.MESSAGE)
print("relief", tuple(relief.shape))
return [curio_wheelhouse_model.MESSAGE, float(np.abs(relief).sum())]
