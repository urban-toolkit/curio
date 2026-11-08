import pandas as pd

df = input_0  # The DataFrame on input circle 0

summary = {
    "shape": {"rows": int(df.shape[0]), "columns": int(df.shape[1])},
    "dtypes": df.dtypes.astype(str).to_dict(),
    "missing": df.isnull().sum().to_dict(),
    "describe": df.describe(include="all").fillna("").to_dict(),
}

return summary
