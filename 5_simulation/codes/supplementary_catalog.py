"""Stable analytical keys mapped to the single published supplementary numbering."""
from pathlib import Path
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
FOLDER=ROOT/'outputs/tables/supplementary'
TABLE_FILES={
    'S8_elasticity_assignment':'S1_elasticity_assignment.xlsx',
    'PMT_predictors':'S2_pmt_predictors.xlsx',
    'Quintile_results':'S3_quintile_results.xlsx',
    'S4_error_grid_draws':'S4_error_grid_draws.xlsx',
    'S5_error_grid_summary':'S5_error_grid_summary.xlsx',
    'Score_degradation_summary':'S6_score_degradation_summary.xlsx',
    'S6_score_degradation_draws':'S7_score_degradation_draws.xlsx',
    'S1_configuration_results':'S8_configuration_results.xlsx',
    'S9_policy_rankings':'S9_policy_rankings.xlsx',
    'S2_macro_results':'S10_macro_results.xlsx',
    'S3_sector_results':'S11_sector_results.xlsx',
    'S7_micro_sensitivity':'S12_micro_sensitivity.xlsx',
    'S10_negative_income_diagnostic':'S13_negative_income_diagnostic.xlsx',
}
# Old manuscript labels -> labels in order of first citation in the main text.
MANUSCRIPT_TABLE_NUMBERS={'S6':'S1','S9':'S2','S8':'S3','S4':'S6','S1':'S8',
                          'S2':'S10','S3':'S11','S5':'S12','S7':'S13'}
FIGURE_NUMBERS={'S5':'S1','S1':'S2','S3':'S3','S2':'S4','S4':'S5'}

def load_supplementary(name):
    key=Path(name).stem
    file=TABLE_FILES[key] if key in TABLE_FILES else name
    df=pd.read_excel(FOLDER/file,sheet_name='Data')
    if 'homogeneous_within_quintile' in df and df['homogeneous_within_quintile'].dtype==object:
        df['homogeneous_within_quintile']=df['homogeneous_within_quintile'].map({True:True,False:False,'True':True,'False':False})
    return df

def save_supplementary(name,df):
    from document_supplementary_tables import write_workbook
    return write_workbook(Path(name).stem,df)
