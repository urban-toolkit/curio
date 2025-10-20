import pandas as pd
import io

df = pd.read_csv(io.StringIO([!! Load CSV$FILE$ !!]), sep=",")

return df