import pandas as pd

df = arg # Getting DataFrame from a previous node

df.dropna(how='all', inplace=True)

df['Age'] = pd.to_numeric(df['Age'], errors='coerce')  # convert to numeric
df['Age'].fillna(df['Age'].mean(), inplace=True)

df['Name'].fillna('Unknown', inplace=True)
df['Email'].fillna('no-email@example.com', inplace=True)

df['Name'] = df['Name'].str.strip().str.title()  # ' alice ' -> 'Alice'

df.drop_duplicates(inplace=True)

return df