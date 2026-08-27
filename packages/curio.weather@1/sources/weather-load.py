import pandas as pd

dataset_path = curio_dataset_path("data.urbanlab.milan-era5-weather")
sensor = pd.read_csv(dataset_path)

return sensor
