"""Inspect any negative micro income in no-policy reference shocks; retain full accounting.

The diagnostic reports a zero-floor sensitivity without silently changing incomes
or breaking the benchmark-to-group reconciliation. No household identifiers leave memory.
"""
from common import *
from policy_model import build,shock_model,snapshot
from micro_simulation import prepare_micro,household_outcomes

def main():
    df=load_supplementary('S1_configuration_results')
    flagged=df[df.negative_income_households>0]
    rows=[]
    if len(flagged):
        cfgs=configurations();base=build(cfgs['main']);cge.solve_model(base)
        micro,_,_=prepare_micro(base)
        for _,row in flagged.iterrows():
            assert row.policy=='shock', 'A policy case requires a separate recipient-state audit'
            b=build(cfgs[row['case']]);cge.solve_model(b);sh=shock_model(b,cfgs[row['case']])
            st=snapshot(sh,b);g=micro['group'];w=micro['pw'];ratio=np.asarray(st['price_ratios'])
            cpi=np.ones(len(g))
            for k in range(5):
                ix=g==k;cpi[ix]=np.exp(np.log(ratio[:,k])@micro['beta'][:,ix])
            disp=(1-micro['tax'])*(st['w']*micro['L']+st['r']*micro['K']+micro['R']*st['factor_index'])
            eq=disp/micro['income_scale']/micro['equiv']/cpi
            z=micro['poverty_line'];negative=eq<0
            original=100*np.average(np.maximum(1-eq/z,0),weights=w)
            floored=100*np.average(np.maximum(1-np.maximum(eq,0)/z,0),weights=w)
            assert abs(original-row.fgt1_pct)<1e-8
            vals,_,_=household_outcomes(st,micro,np.zeros(len(g)))
            rows.append(dict(case=row['case'],policy=row.policy,negative_households=int(negative.sum()),
                affected_population_pct=100*w[negative].sum()/w.sum(),
                minimum_real_equivalent_income_hbs_tl=float(eq.min()),
                poverty_line_hbs_tl=z,original_fgt1_pct=original,zero_floor_fgt1_pct=floored,
                zero_floor_difference_pp=floored-original,
                note='Factor-indexed micro reconciliation residual; all policy cases retain nonnegative disposable income'))
    table('S10_negative_income_diagnostic',rows,True)
    dump(OUT/'diagnostics/income_boundary_check.json',dict(flagged_cases=rows,
        policy_cases_with_negative_income=int(((df.policy!='shock')&(df.negative_income_households>0)).sum()),
        interpretation='Zero-floor sensitivity is reported separately; original accounting-consistent incomes remain in the analysis'))
    print(pd.DataFrame(rows).to_string(index=False))

if __name__=='__main__':main()
