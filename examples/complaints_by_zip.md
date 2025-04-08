# Example: Complaints By Zip Code
In this example, we will explore how Curio can perform simple operations to gather the total number of flooding complaints ordered by Zip Code using Pandas. Here is the overview of the dataflow pipeline:

![enter image description here](https://media-hosting.imagekit.io/63740a353f0b416d/c_by_zip_3.PNG?Expires=1838679694&Key-Pair-Id=K2ZIVPTIP2VGHC&Signature=K3tmZAAoWdp8EYOfeYUTlrLGCeBLqLtHbdeI2nn1DiGc7jPfQmRq5~K-L~hkqN99anyJ-PCRdKVd1UeQT73Ma239sKSFPGF5hUK5BXWycX7lLZq9F4vSdyPDTxMuvqMc9xBWTd-lYUoyegSusZR7Ojq95kl3AWfkJEjlmXjXsIye2rFiDlSiYTiy6N-NNbs6REV0Of3rBRf7XkmmAaGsGqM0TvLKxiEf2LUqPgCj9GqBKss93HhA3gEkO9OlvkHJ6zA3HwhayFeUXYlMFrDH4FedwM4mOo2K7BqaHIM8kGzFl0l5WXGAcrSrY7iNxTrIciXDgJ~NFlw-unBM40Nlaw__)

Before you begin, please familiarize yourself with Curio’s main concepts and functionalities by reading our [usage guide](https://github.com/urban-toolkit/curio/blob/main/docs/USAGE.md).

For completeness, we also include the template code in each dataflow step.

## Step 1: Load in Flooding Complaints Dataset

To get started with performing data analysis on the dataset, it needs to be imported into Curio. The best way to do that is to use a **Data Loading Node** to do so. The following code will complete this step:
```
import pandas as pd

sensor = pd.read_csv('Flooding_Complaints_to_311_20250402.csv')

return sensor
```

![enter image description here](https://media-hosting.imagekit.io/5e9b1aa6a8d8482d/c_by_zip_1.PNG?Expires=1838679608&Key-Pair-Id=K2ZIVPTIP2VGHC&Signature=WNF5oVGMxHi18xsCWKTsT2Ppk~gvF1MrL7EUjCMKKU63kJyLWzoGUgapj6UnjkWb6ZjpowRUJnYcL6Y9jTNHmoKGWSvshauXJbfPTGhNW-~UKstRzH05mLPsUvr9A5dUAvSEyI0TRQNRSPWMiTfZT9iOriVDOzXDvbbcIXrUruUC70AQk~EXDBBqlVS6OjJ8~E3gHeX9ZAAxiehksjuTYRU3Q~NaGFHuGX0zhQUhbtcsqtmaN-AKer4JjllOGNq-5Pwiwdcfit1u7fl69PiUIzRup8pAtSl5WFoLi7Jamxlcho3HIEhu3VSvgt33RB1LeXuFm2ypjnLK4benxXcrXA__)
## Step 2: Performing Computational Analysis to Find Complaints Per Zip Code
Now that we loaded in the dataset using the **Data Loading Node**, we can now perform simple computational analysis using Curio's **Computational Analysis Node** to find the total number of complaints per zip code. Here is the code to do so:

```
def complaints_by_zip(df):

grouped = df["ZIP_CODE"].fillna("UNKNOWN").value_counts().reset_index()

grouped.columns = ["ZIP_CODE",  "Complaint_Count"]

return grouped

return complaints_by_zip(arg)
```

![enter image description here](https://media-hosting.imagekit.io/411e3263f537412a/c_by_zip_2.PNG?Expires=1838679694&Key-Pair-Id=K2ZIVPTIP2VGHC&Signature=xtugJO-plpeEYT~iTlSBXIkovyOIb0sUxg2S9XpWdkWXvSbfKEnTZha5RjaMqWdt-6iuoV36ooOOUSUNSr726TqKWms8JmbZOJSA8qzCe4qq7zUMH~hH9-HAO-ABOKOT94KQt8HH0j4s30mKYx5BUmLui51u3bzYfwAupx1t4GaNsrPvf1k-viouCpZCIhH99-xj1ygBbD3XOaheNW6T6MtacVnflFH~sK2V8LxMJoEFc5m4tmpHXMhOoslMDLxcRAb3C8prTP6fRylkgsWz-O8k6TopmtpAEHFESS64IzDi~D130BzElSDLeeCdf3Bjeew2I2y7H8l0yKf7VCrggQ__)

## Step 3: Display Results Using a Table
In the last step, we performed computational analysis to get the total number of complaints per zip code. One of the best ways to see these types of results is using a table. We will connect the **Computational Analysis Node** with a **Table Node** to display our results in Table format. You do not need to include any code in the **Table Node**.

![enter image description here](https://media-hosting.imagekit.io/63740a353f0b416d/c_by_zip_3.PNG?Expires=1838679694&Key-Pair-Id=K2ZIVPTIP2VGHC&Signature=K3tmZAAoWdp8EYOfeYUTlrLGCeBLqLtHbdeI2nn1DiGc7jPfQmRq5~K-L~hkqN99anyJ-PCRdKVd1UeQT73Ma239sKSFPGF5hUK5BXWycX7lLZq9F4vSdyPDTxMuvqMc9xBWTd-lYUoyegSusZR7Ojq95kl3AWfkJEjlmXjXsIye2rFiDlSiYTiy6N-NNbs6REV0Of3rBRf7XkmmAaGsGqM0TvLKxiEf2LUqPgCj9GqBKss93HhA3gEkO9OlvkHJ6zA3HwhayFeUXYlMFrDH4FedwM4mOo2K7BqaHIM8kGzFl0l5WXGAcrSrY7iNxTrIciXDgJ~NFlw-unBM40Nlaw__)
