"""Execute calculation cells without storing any notebook outputs."""
from pathlib import Path
import argparse,json,os

ROOT=Path(__file__).resolve().parents[1]
NOTEBOOKS={
 1:'1_input_output/analysis/codes/supply_use_to_input_output.ipynb',
 2:'2_social_accounting_matrix/codes/construct_social_accounting_matrix.ipynb',
 3:'3_household_groups/codes/household_disaggregation.ipynb',
}
def run(stage):
    p=ROOT/NOTEBOOKS[stage]
    if stage==3:
        data=Path(os.environ.get('HBS_DATA_DIR',ROOT/'3_household_groups/datas'))
        required=['hane_cd_2024.csv','fert_cd_2024.csv','tuketim_cd_2024.csv','hbs_madde_tanim.csv']
        if any(not (data/f).exists() for f in required):
            raise FileNotFoundError('Stage 3 requires authorised HBS data. See 3_household_groups/datas/RESTRICTED_DATA.md.')
    nb=json.loads(p.read_text(encoding='utf-8'));scope={'__name__':'__main__'}
    previous=Path.cwd()
    try:
        os.chdir(p.parent)
        for i,c in enumerate(nb['cells']):
            if c['cell_type']=='code':exec(compile(''.join(c['source']),f'{p.name}:cell{i}','exec'),scope)
    finally:os.chdir(previous)

if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('stage',type=int,choices=[1,2,3]);a=ap.parse_args();run(a.stage)
