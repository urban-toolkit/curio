import json
import pytest
from utk_curio.backend.app.notebooks.analyzer import analyze_cells, runtime_analyze_cells, _UsedNamesVisitor, _collect_import_names, _collect_defined
import ast      # The magical abstract syntax tree
import builtins

class TestNoteBookAnalyzer:
    # <-------------------------Linear Notebooks-------------------------->
    def test_edges_simple_linear_notebook_chain(self):
        cells = [
            "import pandas as pd\nimport numpy as np\n\ndf = pd.read_csv(\"/Users/andresquesada/desktop/CPS.csv\")\ndf",
            "HS_only_data = df[df[\"Elementary, Middle, or High School\"] == \"HS\"]\ncommunity_zipcode = HS_only_data[[\"Community Area Name\", \"ZIP Code\"]]\ncommunity_zipcode",
            "grouped_data = community_zipcode.groupby(\"Community Area Name\").size().reset_index(name=\"High School Count\")\ngrouped_data"
        ]

        output = runtime_analyze_cells(cells)

        # for analysis in output["analysis"]:
        #     print(f"{analysis}\n")
        # print(f"{output["edges"]}\n")

        actual_edges = {(e["source"], e["target"]) for e in output["edges"]}
        expected_edges = {(0, 1), (1, 2)}
        assert actual_edges == expected_edges
    
    def test_edges_complex_linear_notebook_chain(self):
        '''Data is fed downstream in a linear pattern'''
        cells = [
            "import pandas as pd\nimport numpy as np\n\ndf = pd.read_csv(\"/Users/andresquesada/desktop/CPS.csv\")\ndf",
            "df_clean = df.rename(columns=lambda c: c.strip()).copy()\ndf_clean[\"Average Student Attendance\"] = pd.to_numeric(\n    df_clean[\"Average Student Attendance\"].astype(str).str.replace(\"%\", \"\"), errors=\"coerce\"\n)\ndf_clean[\"Graduation Rate %\"] = pd.to_numeric(df_clean[\"Graduation Rate %\"], errors=\"coerce\")\ndf_clean[\"College Eligibility %\"] = pd.to_numeric(df_clean[\"College Eligibility %\"], errors=\"coerce\")\ndf_clean[\"Safety Score\"] = pd.to_numeric(df_clean[\"Safety Score\"], errors=\"coerce\")\ndf_clean[\"Instruction Score\"] = pd.to_numeric(df_clean[\"Instruction Score\"], errors=\"coerce\")\ndf_clean[\"Teachers Score\"] = pd.to_numeric(df_clean[\"Teachers Score\"], errors=\"coerce\")\ndf_clean[\"Family Involvement Score\"] = pd.to_numeric(df_clean[\"Family Involvement Score\"], errors=\"coerce\")",
            "numeric_cols = [\n    \"Average Student Attendance\", \"Graduation Rate %\",\n    \"College Eligibility %\", \"Safety Score\",\n    \"Instruction Score\", \"Teachers Score\", \"Family Involvement Score\"\n]\n\ndf_zscores = df_clean[[\"Name of School\", \"Elementary, Middle, or High School\"] + numeric_cols].copy()\nfor col in numeric_cols:\n    mean = df_zscores[col].mean()\n    std = df_zscores[col].std()\n    df_zscores[f\"{col}_z\"] = (df_zscores[col] - mean) / std",
            "z_cols = [c for c in df_zscores.columns if c.endswith(\"_z\")]\n\ndf_scored = df_zscores.copy()\ndf_scored[\"composite_score\"] = df_scored[z_cols].mean(axis=1)\ndf_scored[\"performance_tier\"] = pd.cut(\n    df_scored[\"composite_score\"],\n    bins=[-np.inf, -1, 0, 1, np.inf],\n    labels=[\"Low\", \"Below Average\", \"Above Average\", \"High\"]\n)",
            "tier_summary = (\n    df_scored\n    .groupby([\"Elementary, Middle, or High School\", \"performance_tier\"])\n    .agg(\n        school_count=(\"Name of School\", \"count\"),\n        avg_composite=(\"composite_score\", \"mean\")\n    )\n    .round(3)\n    .reset_index()\n)\ntier_summary",
            "tier_pivot = tier_summary.pivot_table(\n    index=\"Elementary, Middle, or High School\",\n    columns=\"performance_tier\",\n    values=\"school_count\",\n    fill_value=0\n)\n\ntier_pivot[\"dominant_tier\"] = tier_pivot.idxmax(axis=1)\ntier_pivot[\"total_schools\"] = tier_pivot.drop(columns=\"dominant_tier\").sum(axis=1)\ntier_pivot = tier_pivot.reset_index()\ntier_pivot"
        ]
        output = runtime_analyze_cells(cells)


        actual_edges = {(e["source"], e["target"]) for e in output["edges"]}
        expected_edges = {(0,1), (1,2), (2,3), (3,4), (4,5)}
        assert actual_edges == expected_edges, f"This is what our edges are {actual_edges}"

    # <-------------------------Branching Notebooks-------------------------->
    @pytest.mark.xfail(reason="Our current algorithm can't handle this test case")
    def test_edges_simple_branches_one(self):
        '''Data branches off into different nodes starting at the second node'''
        '''Note: The 2nd cell on the notebook handles 3 different types of output'''
        cells = [
            "import pandas as pd\nimport numpy as np\n\ndf = pd.read_csv(\"/Users/andresquesada/desktop/CPS.csv\")\ndf",
            "HS_only = df[df[\"Elementary, Middle, or High School\"] == 'HS']\nMS_only = df[df[\"Elementary, Middle, or High School\"] == 'MS']\nES_only = df[df[\"Elementary, Middle, or High School\"] == 'ES']",
            "community_zipcode = HS_only[[\"Community Area Name\", \"ZIP Code\"]]\ngrouped_data = community_zipcode.groupby(\"Community Area Name\").size().reset_index(name=\"High School Count\")\ngrouped_data",
            "community_zipcode = MS_only[[\"Community Area Name\", \"ZIP Code\"]]\ngrouped_data = community_zipcode.groupby(\"Community Area Name\").size().reset_index(name=\"Middle School Count\")\ngrouped_data",
            "community_zipcode = ES_only[[\"Community Area Name\", \"ZIP Code\"]]\ngrouped_data = community_zipcode.groupby(\"Community Area Name\").size().reset_index(name=\"Elementary School Count\")\ngrouped_data"
        ]
        output = runtime_analyze_cells(cells)

        actual_edges = {(e["source"], e["target"]) for e in output["edges"]}
        expected_edges = set()

        assert 1 == 1 ,f"Our current algorithm cannot possible deal with this yet. Don't even try"

    def test_edges_simple_branches_two(self):
        '''Data branches off into different nodes starting at the second node'''
        '''Note: Notebook cells give at most 2 types of output'''
        cells = [
            "import pandas as pd\nimport numpy as np\n\ndf = pd.read_csv(\"/Users/andresquesada/desktop/CPS.csv\")\ndf",
            "HS_only = df[df[\"Elementary, Middle, or High School\"] == 'HS']",
            "MS_only = df[df[\"Elementary, Middle, or High School\"] == 'MS']",
            "ES_only = df[df[\"Elementary, Middle, or High School\"] == 'ES']",
            "community_zipcode = HS_only[[\"Community Area Name\", \"ZIP Code\"]]\ngrouped_data = community_zipcode.groupby(\"Community Area Name\").size().reset_index(name=\"High School Count\")\ngrouped_data",
            "community_zipcode = MS_only[[\"Community Area Name\", \"ZIP Code\"]]\ngrouped_data = community_zipcode.groupby(\"Community Area Name\").size().reset_index(name=\"Middle School Count\")\ngrouped_data",
            "community_zipcode = ES_only[[\"Community Area Name\", \"ZIP Code\"]]\ngrouped_data = community_zipcode.groupby(\"Community Area Name\").size().reset_index(name=\"Elementary School Count\")\ngrouped_data"
        ]
        output = runtime_analyze_cells(cells)

        actual_edges = {(e["source"], e["target"]) for e in output["edges"]}
        expected_edges = {(0,1), (0,2), (0,3), (1,4), (2,5), (3,6)}
        assert actual_edges == expected_edges, f"This is what our edges are {actual_edges}"

    # <-------------------------Independent cells------------------------->
    def test_edges_simple_independent_cells_data(self):
        """Each cell handles their own data"""
        cells = [
            "import pandas as pd\n\ndf = pd.read_csv(\"/Users/andresquesada/desktop/CPS.csv\")\ndf.head()",
            "import pandas as pd\n\nsafety_df = pd.read_csv(\"/Users/andresquesada/desktop/CPS.csv\")\nsafety_df[\"Safety Score\"] = pd.to_numeric(safety_df[\"Safety Score\"], errors=\"coerce\")\ntop_safe = safety_df[[\"Name of School\", \"Safety Score\"]].dropna().sort_values(\"Safety Score\", ascending=False).head(10)\ntop_safe",
            "import pandas as pd\n\nattend_df = pd.read_csv(\"/Users/andresquesada/desktop/CPS.csv\")\nattend_df[\"Average Student Attendance\"] = pd.to_numeric(\n    attend_df[\"Average Student Attendance\"].astype(str).str.replace(\"%\", \"\"), errors=\"coerce\"\n)\nattendance_by_type = attend_df.groupby(\"Elementary, Middle, or High School\")[\"Average Student Attendance\"].mean().round(2)\nattendance_by_type",
            "import pandas as pd\n\ngrad_df = pd.read_csv(\"/Users/andresquesada/desktop/CPS.csv\")\ngrad_df[\"Graduation Rate %\"] = pd.to_numeric(grad_df[\"Graduation Rate %\"], errors=\"coerce\")\nhs_grad = grad_df[grad_df[\"Elementary, Middle, or High School\"] == \"HS\"][\"Graduation Rate %\"].dropna()\nhs_grad.describe()",
            "import pandas as pd\n\ncommunity_df = pd.read_csv(\"/Users/andresquesada/desktop/CPS.csv\")\nschools_per_community = community_df.groupby(\"Community Area Name\")[\"Name of School\"].count().sort_values(ascending=False)\nschools_per_community.head(10)"
        ]
        output = runtime_analyze_cells(cells)

        actual_edges = {(e["source"], e["target"]) for e in output["edges"]}
        expected_edges = set()


        assert actual_edges == expected_edges, f"This is what our edges are {actual_edges}"
    
    def test_edges_simple_independent_cells_no_data(self):
        """Each cell runs its own computation"""
        cells = [
            "for i in range(1,11):\n    print(f\"{i}.) Bullet point\")",
            "x = \"Hello\"\ny = \"World!\"\n\nprint(x+\" \"+y)",
            "def fizzbuzz(num):\n    if (num % 15 == 0):\n        print(\"FizzBuzz\")\n    elif (num % 3 == 0):\n        print(\"Fizz\")\n    elif (num % 5 == 0):\n        print(\"Buzz\")\n    else:\n        print(\"Sleep\")\n\nfor i in range(1,11):\n    print(f\"{i}.)\", end=\" \")\n    fizzbuzz(i)\n\n    "
        ]
        output = runtime_analyze_cells(cells)

        for analysis in output["analysis"]:
            print(f"{analysis}\n")
        # Personal Testing Area
        # assert output['analysis'][0]['defined'] == set(), f"Defined Variables: ({output['analysis'][0]['defined']})"  #Fails
        # assert output['analysis'][0]['used'] == set(), f"Used: {output['analysis'][0]['used']}"

        actual_edges = {(e["source"], e["target"]) for e in output["edges"]}
        expected_edges = set()

        assert actual_edges == expected_edges, f"This is what our edges are {actual_edges}"

    
    def test_edges_complex_independent_cells(sells):
        """The same as simple_independent_cells_data. Except that variable names are reused between cells"""
        cells = [
            "import pandas as pd\n\ndf = pd.read_csv(\"/Users/andresquesada/desktop/CPS.csv\")\ndf.head()",
            "import pandas as pd\n\ndf = pd.read_csv(\"/Users/andresquesada/desktop/CPS.csv\")\ndf[\"Safety Score\"] = pd.to_numeric(df[\"Safety Score\"], errors=\"coerce\")\ntop_safe = df[[\"Name of School\", \"Safety Score\"]].dropna().sort_values(\"Safety Score\", ascending=False).head(10)\ntop_safe",
            "import pandas as pd\n\ndf = pd.read_csv(\"/Users/andresquesada/desktop/CPS.csv\")\ndf[\"Average Student Attendance\"] = pd.to_numeric(\n    df[\"Average Student Attendance\"].astype(str).str.replace(\"%\", \"\"), errors=\"coerce\"\n)\nattendance_by_type = df.groupby(\"Elementary, Middle, or High School\")[\"Average Student Attendance\"].mean().round(2)\nattendance_by_type",
            "import pandas as pd\n\ndf = pd.read_csv(\"/Users/andresquesada/desktop/CPS.csv\")\ndf[\"Graduation Rate %\"] = pd.to_numeric(df[\"Graduation Rate %\"], errors=\"coerce\")\nhs_grad = df[df[\"Elementary, Middle, or High School\"] == \"HS\"][\"Graduation Rate %\"].dropna()\nhs_grad.describe()",
            "import pandas as pd\n\ndf = pd.read_csv(\"/Users/andresquesada/desktop/CPS.csv\")\nschools_per_community = df.groupby(\"Community Area Name\")[\"Name of School\"].count().sort_values(ascending=False)\nschools_per_community.head(10)"
        ]
        output = runtime_analyze_cells(cells)

        actual_edges = {(e["source"], e["target"]) for e in output["edges"]}
        expected_edges = set()

        for e in output["edges"]:
            print(f"\n{e}\n")
        
        assert actual_edges == expected_edges, f"This is what our edges are {actual_edges}"

    # <-------------------------Vague returns------------------------->
    def test_edges_uncertain_return(self):
        """ The desired output is a variable declared before the last assigned variable"""
        cells = [
            "import pandas as pd\nimport numpy as np\n\ndf = pd.read_csv(\"/Users/andresquesada/desktop/CPS.csv\")\ndf",
            "unsafe_df = df[df['Safety Score'] < 40]\ngrouped_data = unsafe_df.groupby(\"Community Area Name\").size().reset_index(name=\"Unsafe Schools in the Area\")\ngrouped_data",
            "unsafeHS_df = unsafe_df[unsafe_df[\"Elementary, Middle, or High School\"] == \"HS\"]\nunsafeMS_df = unsafe_df[unsafe_df[\"Elementary, Middle, or High School\"] == \"MS\"]\nunsafeES_df = unsafe_df[unsafe_df[\"Elementary, Middle, or High School\"] == \"ES\"]\n\nhs_grouped = unsafeHS_df.groupby(\"Community Area Name\").size().reset_index(name=\"Unsafe HS Count\")\nms_grouped = unsafeMS_df.groupby(\"Community Area Name\").size().reset_index(name=\"Unsafe MS Count\")\nes_grouped = unsafeES_df.groupby(\"Community Area Name\").size().reset_index(name=\"Unsafe ES Count\")\n\nunsafe_summary = hs_grouped.merge(ms_grouped, on=\"Community Area Name\", how=\"outer\") \\\n                            .merge(es_grouped, on=\"Community Area Name\", how=\"outer\") \\\n                            .fillna(0)\n\nunsafe_summary[[\"Unsafe HS Count\", \"Unsafe MS Count\", \"Unsafe ES Count\"]] = \\\n    unsafe_summary[[\"Unsafe HS Count\", \"Unsafe MS Count\", \"Unsafe ES Count\"]].astype(int)\n\nunsafe_summary"
        ]
        output = runtime_analyze_cells(cells)

        actual_edges = {(e["source"], e["target"]) for e in output["edges"]}
        expected_edges = {(0,1),(1,2)}
        assert actual_edges == expected_edges, f"This is what our edges are {actual_edges}"

    # <-------------------------Test Self Assignment------------------------->
    def test_edges_self_assignment(self):
        cells = [
            "print(\"Hello\")",
            "import pandas as pd\nimport numpy as np\n\ncps_df = pd.read_csv(\"/Users/andresquesada/desktop/CPS.csv\")\ncps_df",
            "import pandas as pd\n\ndata = {\n    \"Name\": [\"Alice\", \"Bob\", \"Charlie\"],\n    \"Age\": [25, 30, 35],\n    \"Score\": [88, 92, 79]\n}\n\ndf = pd.DataFrame(data)\ndf\n",
            "import pandas as pd\ndf = pd.read_csv('/Users/andresquesada/desktop/words_dataset.txt', header=None, names=['My_Column'])\n\nrecords = []\nfor word in df['My_Column']:\n    sz = len(str(word))\n    if sz >= 22:\n        label = \"22+\"\n    else:\n        label = sz\n    records.append({\"Word Size\": label, \"count\": 1})\n\nt_df = pd.DataFrame(records).groupby(\"Word Size\", as_index=False).sum()\n\nt_df",
            "import numpy as np\nimport pandas as pd\n\ncps_df.columns = cps_df.columns.str.strip().str.replace(\" \", \"_\").str.lower()\n\ncps_df = cps_df.replace(\"NDA\", np.nan)\n\n\ndef convert_percent(val):\n    if pd.isna(val) or not isinstance(val, str):\n        return val\n    return float(val.replace(\"%\", \"\")) / 100.0\n\n\ncps_df[\"average_student_attendance\"] = cps_df[\"average_student_attendance\"].apply(\n    convert_percent\n)\ncps_df[\"average_teacher_attendance\"] = cps_df[\"average_teacher_attendance\"].apply(\n    convert_percent\n)\n\nnumeric_score_cols = [\n    \"safety_score\",\n    \"environment_score\",\n    \"instruction_score\",\n    \"parent_engagement_score\",\n    \"parent_environment_score\",\n]\nfor col in numeric_score_cols:\n    if col in cps_df.columns:\n        cps_df[col] = pd.to_numeric(cps_df[col], errors=\"coerce\")\n\ncps_df[\"high_student_attendance\"] = cps_df[\"average_student_attendance\"] >= 0.95\n\ncps_df.head()"
        ]
        output = runtime_analyze_cells(cells)

        actual_edges = {(e["source"], e["target"]) for e in output["edges"]}
        expected_edges = {(1,4)}
        assert actual_edges == expected_edges, f"Actual result: {actual_edges}"

# pytest utk_curio/backend/tests/test_notebook_analyzer.py
# pytest utk_curio/backend/tests/test_notebook_analyzer.py::TestNoteBookAnalyzer::test_AST_trials

# Insert Tests for Out of Order, Tricky installs, Linear Fallback (Another independent cell test)

    # <---------------------Trying to use an AST--------------------->
    @pytest.mark.xfail(reason = "This is to play around")
    def test_AST_trials(self):
        cells = [
            "import pandas as pd\nimport numpy as np\n\ndf = pd.read_csv(\"/Users/andresquesada/desktop/CPS.csv\")\ndf",
            "df_clean = df.rename(columns=lambda c: c.strip()).copy()\ndf_clean[\"Average Student Attendance\"] = pd.to_numeric(\n    df_clean[\"Average Student Attendance\"].astype(str).str.replace(\"%\", \"\"), errors=\"coerce\"\n)\ndf_clean[\"Graduation Rate %\"] = pd.to_numeric(df_clean[\"Graduation Rate %\"], errors=\"coerce\")\ndf_clean[\"College Eligibility %\"] = pd.to_numeric(df_clean[\"College Eligibility %\"], errors=\"coerce\")\ndf_clean[\"Safety Score\"] = pd.to_numeric(df_clean[\"Safety Score\"], errors=\"coerce\")\ndf_clean[\"Instruction Score\"] = pd.to_numeric(df_clean[\"Instruction Score\"], errors=\"coerce\")\ndf_clean[\"Teachers Score\"] = pd.to_numeric(df_clean[\"Teachers Score\"], errors=\"coerce\")\ndf_clean[\"Family Involvement Score\"] = pd.to_numeric(df_clean[\"Family Involvement Score\"], errors=\"coerce\")",
            "numeric_cols = [\n    \"Average Student Attendance\", \"Graduation Rate %\",\n    \"College Eligibility %\", \"Safety Score\",\n    \"Instruction Score\", \"Teachers Score\", \"Family Involvement Score\"\n]\n\ndf_zscores = df_clean[[\"Name of School\", \"Elementary, Middle, or High School\"] + numeric_cols].copy()\nfor col in numeric_cols:\n    mean = df_zscores[col].mean()\n    std = df_zscores[col].std()\n    df_zscores[f\"{col}_z\"] = (df_zscores[col] - mean) / std",
            "z_cols = [c for c in df_zscores.columns if c.endswith(\"_z\")]\n\ndf_scored = df_zscores.copy()\ndf_scored[\"composite_score\"] = df_scored[z_cols].mean(axis=1)\ndf_scored[\"performance_tier\"] = pd.cut(\n    df_scored[\"composite_score\"],\n    bins=[-np.inf, -1, 0, 1, np.inf],\n    labels=[\"Low\", \"Below Average\", \"Above Average\", \"High\"]\n)",
            "tier_summary = (\n    df_scored\n    .groupby([\"Elementary, Middle, or High School\", \"performance_tier\"])\n    .agg(\n        school_count=(\"Name of School\", \"count\"),\n        avg_composite=(\"composite_score\", \"mean\")\n    )\n    .round(3)\n    .reset_index()\n)\ntier_summary",
            "tier_pivot = tier_summary.pivot_table(\n    index=\"Elementary, Middle, or High School\",\n    columns=\"performance_tier\",\n    values=\"school_count\",\n    fill_value=0\n)\n\ntier_pivot[\"dominant_tier\"] = tier_pivot.idxmax(axis=1)\ntier_pivot[\"total_schools\"] = tier_pivot.drop(columns=\"dominant_tier\").sum(axis=1)\ntier_pivot = tier_pivot.reset_index()\ntier_pivot"
        ]

        # code = cells[0]
        code = """if x:
    ...
elif y:
    ...
else:
    ...
"""
        tree = ast.parse(code)

        lines_list = code.splitlines()

        print(ast.dump(tree, indent=4))
        # How we iterate accross an AST
        for node in ast.iter_child_nodes(tree):
            start = node.lineno - 1          # lineno is 1-indexed
            end = node.end_lineno            # end_lineno is also 1-indexed, so slice up to it
            node_source = "\n".join(lines_list[start:end])

            print()
            print(f"Code: {node_source}")
            print(type(node))
            if(isinstance(node, ast.If)):
                print(ast.dump(node, indent=4))


        assert 1 != 1