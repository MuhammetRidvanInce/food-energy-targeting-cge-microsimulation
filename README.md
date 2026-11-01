# Nested-CES food–energy targeting replication package

This repository accompanies **The Poverty–Coverage Trade-off under Food and Energy Shocks: Targeting and Pareto-Efficient Policy Design through CGE–Microsimulation**, by Muhammet Rıdvan İnce (Kocaeli University), updated on 1 November 2026. Version 2.0.0 contains the nested-CES model, current simulations, public aggregate inputs and aggregate results. The earlier CD implementation remains available in [the previous commit](https://github.com/MuhammetRidvanInce/food-energy-targeting-cge-microsimulation/tree/885d68721773897caa0da46bc25f38654db930ba).

## Analytical specification

The 2023 Turkish social accounting matrix has 64 sectors and five household groups. Household consumption uses food, energy and other-goods nests, with upper-nest elasticity 0.25 and within-nest elasticities 0.50, 0.40 and 0.50. The main import-price shock is food +20% and energy +40%. Four support rules have an identical net fiscal cost of 0.5% of benchmark GDP. The simulation covers instrument comparisons, targeting-error and recipient-composition experiments, PMT coverage choice, epsilon-constraint solutions and 23 structural/preference configurations.

## Contents and dependencies

Stages 1–3 provide the unchanged English upstream construction workflow and public aggregate inputs. Stage 4 contains the current nested-CES model and calibration. Stage 5 contains the current analysis and aggregate outputs. These upstream inputs reproduce the same numeric SAM used in the local CES analysis. Analysis uses NumPy, pandas, SciPy, scikit-learn, Pyomo, Matplotlib and openpyxl; see requirements.txt. Install IPOPT separately and make it available on PATH. The study environment used Python 3.14.3 and IPOPT 3.14.19.

The public files permit a macro-model benchmark check:

```sh
python 4_cge_model/codes/cge_model.py --self-check
```

Full household replication additionally requires independently authorised access to the 2024 TurkStat Household Budget Survey. Set the environment variable `HBS_DATA_DIR` to an external authorised data directory containing the original files `hane_cd_2024.csv`, `fert_cd_2024.csv` and `tuketim_cd_2024.csv`; stage 3 also requires `hbs_madde_tanim.csv`. Keep the restricted directory outside this repository. Provider field names remain unchanged for compatibility. The repository contains no such records, household scores, receipt masks, or record-level results. Its `.gitignore` also excludes restricted files and record-level caches.

```sh
python 5_simulation/codes/run_ces_pipeline.py
python 5_simulation/codes/validate_coverage_publication.py
```

The pipeline can take several hours and overwrites generated aggregate outputs. Use a fresh checkout when reproducing results. The retained JSON provenance records describe the original analytical run; translated public inputs have their own hashes in PACKAGE_MANIFEST.json. Re-running generates new provenance for the replication copy. Monetary calculations in stage 5 use trillion TRY; the stand-alone macro-model public API uses thousand TRY. Survey income retains annual survey-year units.

The following checks and figure rendering use only public aggregate inputs:

```sh
python tools/validate_public_release.py
python tools/render_public_figures.py
python tools/smoke_test.py
```

With authorised external microdata, `python tools/smoke_test.py --with-microdata` additionally re-solves the four main policies and compares their FGT measures against stored CES results. The stages 1–3 notebooks can be executed without saving cell outputs using `python tools/run_preparation.py 1` (or 2 or 3); stage 3 requires the external survey directory.

## Results and numbering

At the main coverage rule, FGT1 is 7.220857% for perfect targeting, 7.343969% for PMT, 7.731658% for universal cash and 7.835895% for price support. PMT minus universal cash is −0.387688 percentage points. The minimum is approximately 4.305727% coverage and 6.681388% FGT1. Designs retaining 75% and 50% of the maximum gain reach 18.673048% and 43.164008% coverage, respectively.

The article tables 1–5 are editorial presentations of these underlying results. The `publication_tables` folder provides the main tables and supplementary tables S1–S19 in English, with Data and Variable Descriptions sheets. Internal CSV names retain their computational names; figures 1–7/S1–S7 follow the article's numbering. Source and access information for public statistical inputs is in DATA_SOURCES.md. The consumption-preference calibration and source URLs are also in household_preferences.json and Table S19.

## Funding and contact

Kocaeli University Scientific Research Projects Coordination Unit (KOÜ BAP), project ID 5665, provided financial support. Contact: muhammet.ince@kocaeli.edu.tr. ORCID: https://orcid.org/0000-0003-2050-2545.
