import pandas as pd

dataset_path = curio_data_path("data.utk.milan-era5-weather")
sensor = pd.read_csv(dataset_path)

return sensor
