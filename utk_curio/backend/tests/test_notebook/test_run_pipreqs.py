import json
import pytest
import re
import textwrap
from utk_curio.backend.app.notebooks.run_pipreqs import run_pipreqs

class TestRunPipReqs:
    def test_single_cell_import(self):
        code = textwrap.dedent("""\
            import numpy as np
            import pandas as pd
            df = pd.DataFrame({"price": [100, 250, 50], "qty": [3, 2, 10]})
        """)

        expctdVals = {'numpy', 'pandas'}
        result = run_pipreqs(code)

        for rawImprt in result:
            imprt = re.sub(r'\b=.*', '', rawImprt)
            assert imprt in expctdVals
    
    def test_double_cell_import(self):
        cell_one = textwrap.dedent("""\
            import numpy as np
            arr = np.array([1, 2, 3])
        """)

        cell_two = textwrap.dedent("""\
            import matplotlib.pyplot as plt
            plt.plot(arr)
        """)

        code = "\n".join([cell_one, cell_two])

        expected_imports = {"numpy", "matplotlib"}
        result = run_pipreqs(code)

        for raw_import in result:
            import_name = re.sub(r"\b=.*", "", raw_import)
            assert import_name in expected_imports

    def test_import_diversity(self):
        code = textwrap.dedent("""\
            import os
            import sys
            import numpy as np
            import pandas as pd
            import matplotlib.pyplot as plt
            from sklearn.model_selection import train_test_split
            from collections import OrderedDict, defaultdict
            import requests
            import scipy.stats as stats
        """)

        expected_imports = {"numpy", "pandas", "matplotlib", "scikit_learn", "Requests", "scipy"}
        result = run_pipreqs(code)

        for imprt in result:
            assert imprt in expected_imports

# pytest utk_curio/backend/tests/test_notebook/test_run_pipreqs.py
# pytest utk_curio/backend/tests/test_packages/test_libraries.py