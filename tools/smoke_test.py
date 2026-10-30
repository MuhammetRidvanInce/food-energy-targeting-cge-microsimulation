"""Re-solve the macro benchmark and, optionally, all four main household policies."""
from pathlib import Path
import argparse,json,os,sys
for key in ['OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS']:os.environ.setdefault(key,'1')
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'5_simulation/codes'))
import numpy as np
import pandas as pd
import pyomo.environ as pyo
from common import configurations,cge
from policy_model import build,shock_model,policy_model,gdp,snapshot,check_policy_sam
from micro_simulation import prepare_micro,fit_pmt,group_shares,household_outcomes

def main(with_microdata=False):
    cfg=configurations()['main'];base=build(cfg);check=cge.solve_model(base)
    report={'baseline_passed':True,'baseline_diagnostics':check}
    if with_microdata:
        micro,h,f=prepare_micro(base);mask,*_=fit_pmt(micro,h,f)
        ones=np.ones(len(mask));shock=shock_model(base,cfg)
        saved=pd.read_csv(ROOT/'5_simulation/outputs/tables/main/Table1_main_policy_results.csv').set_index('policy')
        out={}
        for name,receipt in {'perfect_targeting':(micro['group']<2).astype(float),'pmt':mask,'universal_cash':ones,'price_support':ones}.items():
            shares=group_shares(micro,receipt)
            model,diag=policy_model(shock,cfg,'price' if name=='price_support' else 'cash',shares,gdp(base)*cfg['budget'])
            state=snapshot(model,base,shares=shares,cash_saving=cfg['cash_saving'],reference_sg=pyo.value(shock.Sg))
            values,_,_=household_outcomes(state,micro,receipt)
            gap=max(abs(float(values[k])-saved.loc[name,k]) for k in ['fgt0_pct','fgt1_pct','fgt2_pct'])
            assert gap<1e-7,(name,gap)
            out[name]={'fgt1_pct':values['fgt1_pct'],'max_fgt_difference_pp':gap,'sam_gap_trillion_tl':check_policy_sam(model)}
        report['main_policy_replication']=out
    print(json.dumps(report,indent=2,default=float));return report
if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--with-microdata',action='store_true');a=ap.parse_args();main(a.with_microdata)
