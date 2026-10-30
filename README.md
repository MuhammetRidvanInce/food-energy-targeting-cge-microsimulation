# Food–energy targeting: CGE–microsimulation and coverage design

Analysis companion for **The Poverty–Coverage Trade-off under Food and Energy Shocks: Targeting and Pareto-Efficient Policy Design through CGE–Microsimulation**, by Muhammet Rıdvan İnce (Kocaeli University; ORCID [0000-0003-2050-2545](https://orcid.org/0000-0003-2050-2545)).

The model links a 64-sector Turkish social accounting matrix with five income groups to household microsimulation. Equal-net-cost comparisons of perfect targeting, out-of-fold PMT, universal cash, and price support are followed by coverage optimisation and epsilon-constraint Pareto analysis. Monetary equilibrium calculations use trillion TRY internally; the macro-model public API uses thousand TRY. Survey income retains its annual survey-year units. See the code and supplementary variable descriptions for the conversion bridge.

## Contents

| Directory | Analysis |
|---|---|
| `1_input_output` | Supply/use transformation to industry input–output accounts; public statistical inputs and notebook |
| `2_social_accounting_matrix` | Construction of the 73-account SAM and institutional direct-tax bridge |
| `3_household_groups` | Five-group household split; code and aggregate outputs only |
| `4_cge_model` | Calibrated 78-account, 64-sector, five-household-group CGE engine and selected elasticities |
| `5_simulation` | Policy comparisons, targeting errors, PMT-score degradation, robustness, coverage search, and aggregate results |
| `publication_tables` | Plain English main tables 1–5 and supplementary tables S1–S18; each workbook includes variable descriptions |
| `tools` | Portable notebook execution, aggregate-figure regeneration, public-file checks and model smoke tests |

**No household, person, or consumption microdata are included.** No individual predicted scores, recipient masks, record-level outcomes, executed notebook cell outputs, manuscripts, or cover letters are distributed. Public figure inputs are binned/aggregated statistics. The macro SAM contains five representative household groups rather than individual records.

## Installation

Use a recent Python environment and install `requirements.txt`. The numerical results were obtained with Python 3.14.3, NumPy 2.4.3, pandas 3.0.1, SciPy 1.17.1, scikit-learn 1.8.0, Pyomo 6.10.0, and IPOPT 3.14.19. Exact replication is best attempted with these versions. Workbook export in the public notebooks uses XlsxWriter; this changes workbook packaging and cached formulas, while keeping the scientific calculations and values.

Install the [IPOPT solver](https://coin-or.github.io/Ipopt/) separately and make its executable available on `PATH`. On conda-forge it is available as `ipopt`. The model also accepts `--solver-executable` when invoked directly. The figure and stored-result checks do not require a solver or confidential data.

```bash
python -m pip install -r requirements.txt
python tools/validate_public_release.py
python tools/render_public_figures.py
python tools/smoke_test.py
```

## Reconstructing the accounts

```bash
python tools/run_preparation.py 1
python tools/run_preparation.py 2
```

Repository documentation, notebooks, code comments and public workbook labels are in English. Original HBS field identifiers and source filenames remain unchanged for authorised-data compatibility. The public Excel exporter uses the Python-computed formula values as caches; Excel can recalculate the formulas when opened. Raw public inputs are checked by hashes, while regenerated intermediate workbooks are checked by accounting identities and numerical comparisons. Historical calibrated macro inputs in stages 4 and 5 are retained as the fixed publication benchmark.

The household split requires authorised 2024 TurkStat HBS data, including the item dictionary. Set `HBS_DATA_DIR` to an external directory containing the filenames listed in `3_household_groups/datas/RESTRICTED_DATA.md`. Do not commit that directory or any record-level derivative. Then run:

```bash
python tools/run_preparation.py 3
python tools/smoke_test.py --with-microdata
```

The first command writes aggregate five-group accounts. The smoke test compares the four main policy FGT measures against the stored publication results. It reads confidential records into memory but writes only aggregate calibration diagnostics.

## Full simulation and coverage extension

With IPOPT and authorised microdata available, run the following in sequence from the repository root. These commands overwrite generated aggregate outputs, so use a fresh checkout if you want to retain an untouched reference release.

```bash
python 5_simulation/codes/run_simulations.py
python 5_simulation/codes/figure_profiles.py
python 5_simulation/codes/pmt_coverage_sensitivity.py
python 5_simulation/codes/pmt_coverage_optimization.py
python 5_simulation/codes/pmt_coverage_competing_minima.py
python 5_simulation/codes/summarize_pmt_coverage_optimization.py
python 5_simulation/codes/pmt_coverage_tradeoff.py
python 5_simulation/codes/pmt_epsilon_constraint.py
python 5_simulation/codes/pmt_coverage_robustness.py
python 5_simulation/codes/refine_coverage_robustness.py
python 5_simulation/codes/coverage_publication_outputs.py
python tools/render_public_figures.py
```

Coverage optimisation searches the original fixed PMT ranking and constant per-person payment policies. The finite evaluated Pareto set and the numerically refined optimum are distinguished in the tables. Conditional intervals hold estimated scores, selected policies, and macro calibration fixed. The original four-policy comparison uses target-population coverage close to 40%; the coverage extension applies exact population-weighted coverage thresholds.

## Access, attribution and funding

See `DATA_SOURCES.md` for public-data provenance and restricted-input access. The code/documentation license is MIT; third-party statistical inputs retain their originating terms. Please cite the dataset providers and the associated article when using the analysis. Repository citation metadata are in `CITATION.cff`.

This research was funded by the Kocaeli University Scientific Research Projects Coordination Unit (KOÜ BAP), project ID **5665**. The funder had no role in research design, data analysis, interpretation, writing, or publication decisions.
