# Notes

**Week 4: Oct 13 - 19**

**Summary:**

- Downloaded dataset from SF SOCRATA (49,768 curb ramps with 40 attributes)
- Started Exploratory Data Analysis (EDA) in Jupyter notebooks
- Identified common data errors and inconsistencies in the curb ramps dataset
- Analyzed column types and value distributions

**Data Discovery:**

- Successfully loaded the San Francisco Curb Ramps dataset (~50K rows, 40 columns) from CRIS (Curb Ramp Information System)
- Retrieved data dictionary from DPW to understand field definitions
- No completely null rows found in the dataset - good data quality indicator
- Dataset includes both current and historical data with timestamp columns

**Data Analysis:**

- Identified column types across the 40 attributes:
  - **Numerical columns:** conditionScore (0-100 scale), latitude/longitude coordinates
  - **Boolean columns:** curb ramp existence flags, accessibility features (detectableSurf, colorContrast, paintedRed)
  - **Categorical columns:** surface condition (surfCond), vital facilities proximity (vitalFacilities), heavy traffic exposure (heavyTraffic), curb ramp possibility (crPossible)
  - **Temporal columns:** multiple timestamp fields needing standardization
  - **Location columns:** street names, intersection identifiers, curb return data

**Data Quality Issues Identified:**

- Missing data in various columns - need to determine how to handle (treat as zero? flag as unknown?)
- Inconsistent timestamp formats across different temporal columns
- Some columns with NULL values that may represent "not applicable" vs "missing data"
- Need to validate coordinate data for mapping purposes
- Dark data problem: some attributes have incomplete documentation about what missing values mean

**Next Steps:**

1. Complete data cleaning pipeline - handle nulls, standardize timestamps
2. Generate statistical summaries for key numerical columns (conditionScore distribution)
3. Analyze categorical distributions to understand dataset composition
4. Prepare dataset for visualization tool development
5. Identify most interesting attributes for visualization focus based on data patterns

**Key Insights:**

- Dataset is comprehensive but requires careful interpretation of missing values
- Temporal aspect of data (updated daily since 2012) suggests potential for time-series analysis
- Location data quality appears good - suitable for geographic visualization
- The 40 attributes provide rich multi-dimensional analysis opportunities

