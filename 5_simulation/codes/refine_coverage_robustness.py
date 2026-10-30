"""Cross-check competing coverage minima before publishing structural sensitivity.

Propagates the two independently established main-search basins to every
configuration (scaled by the net budget), refines improvements, and resolves the
associated retention constraints. Phase-one results remain unchanged on disk.
"""
import os
for k in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS'):os.environ[k]='1'
import json,time
from pathlib import Path
import numpy as np
import pandas as pd
import pyomo.environ as pyo
from scipy.optimize import minimize_scalar,brentq
import common as cm
import policy_model as pm
import micro_simulation as ms

def main():
    start=time.time();out=cm.OUT
    source=out/'diagnostics/pmt_coverage_robustness.json'
    prior=json.loads(source.read_text(encoding='utf-8'))
    assert prior['status']=='complete' and prior['completed_case_count']==20
    current=out/'diagnostics/pmt_coverage_robustness_refined.json'
    source_sha=cm.sha(source);code_sha=cm.sha(Path(__file__))
    checkpoint=json.loads(current.read_text(encoding='utf-8')) if current.exists() else {}
    if checkpoint:assert checkpoint['prior_sha256']==source_sha and checkpoint['code_sha256']==code_sha
    cases=checkpoint.get('cases',{})
    curvepath=out/'tables/PMT_coverage_robustness_refined_curves.csv'
    rows=pd.read_csv(curvepath if curvepath.exists() else out/'tables/PMT_coverage_robustness_curves.csv').to_dict('records')
    base0=pm.build(cm.configurations()['main']);cm.cge.solve_model(base0)
    olddump=ms.dump;ms.dump=lambda *a:None
    micro,h,f=ms.prepare_micro(base0);_,pred,_,_=ms.fit_pmt(micro,h,f);ms.dump=olddump
    pop=float(micro['pw'].sum());poor=micro['income']/micro['equiv']<micro['poverty_line'];poorpop=micro['pw'][poor].sum()
    star=json.loads((out/'diagnostics/pmt_coverage_optimization_final.json').read_text(encoding='utf-8'))['optimum']['coverage_pct']/100
    for name,original in prior['cases'].items():
        if name in cases:continue
        cfg=original['configuration'];seed=original['seed'];print('Refining',name,flush=True)
        base=base0 if cfg==cm.configurations()['main'] else pm.build(cfg)
        if base is not base0:cm.cge.solve_model(base)
        shock=pm.shock_model(base,cfg);budget=pm.gdp(base)*cfg['budget']
        if seed==cm.SEED:scores=pred
        else:
            oldseed=ms.SEED;olddump=ms.dump
            try:ms.SEED=seed;ms.dump=lambda *a:None;_,scores,_,_=ms.fit_pmt(micro,h,f)
            finally:ms.SEED=oldseed;ms.dump=olddump
        order=np.argsort(scores,kind='stable');checks=[]
        cache={round(r['coverage_pct']/100,12):r for r in rows if r['configuration']==name}
        def evaluate(q,stage='competing_minimum',force=False):
            q=float(q);key=round(q,12)
            if key in cache and not force:return cache[key]
            mask=ms.exact_mask(micro['pw'],order,q*pop);shares=ms.group_shares(micro,mask)
            m,d=pm.policy_model(shock,cfg,'cash',shares,budget);d['sam_gap_trillion_tl']=pm.check_policy_sam(m)
            state=pm.snapshot(m,base,shares=shares,cash_saving=cfg['cash_saving'],reference_sg=pyo.value(shock.Sg))
            vals,_,_=ms.household_outcomes(state,micro,mask);e=ms.errors(micro,mask)
            row=dict(configuration=name,seed=seed,stage=stage,coverage_pct=100*q,recipients_million=q*pop/1e6,
                target_reached_pct=100*(1-e['exclusion']),initial_poor_reached_pct=100*np.dot(micro['pw'][poor],mask[poor])/poorpop,
                annual_cash_per_recipient_sam_tl=state['net_cash']*1e12/(q*pop),
                net_fiscal_cost_billion_tl=state['macro']['net_fiscal_cost_trillion_tl']*1000,**vals)
            cache[key]=row;checks.append(dict(coverage_pct=100*q,**d))
            # Replace a repeated point rather than creating duplicate workbook rows.
            found=[i for i,r in enumerate(rows) if r['configuration']==name and round(r['coverage_pct']/100,12)==key]
            if found:rows[found[0]]=row
            else:rows.append(row)
            return row
        scale=cfg['budget']/.005
        for q in [star*scale,.03954934*scale]:evaluate(min(.999,max(.001,q)))
        best=min(cache.values(),key=lambda r:r['fgt1_pct'])
        if best['fgt1_pct']<original['numerical_minimum']['fgt1_pct']-1e-8 and name!='main':
            q=best['coverage_pct']/100
            lo=max(.001,q-.001);hi=min(1,q+.001)
            result=minimize_scalar(lambda x:evaluate(x,'competing_refinement')['fgt1_pct'],bounds=(lo,hi),method='bounded',options={'xatol':2e-7,'maxiter':22})
            evaluate(result.x,'competing_refinement');best=min(cache.values(),key=lambda r:r['fgt1_pct'])
        gain=original['shock_fgt1_pct']-best['fgt1_pct']
        selected=[dict(choice='minimum_gap',retention_pct=100.,**best)]
        for retention in [.75,.5]:
            limit=best['fgt1_pct']+(1-retention)*gain
            lo=max(q for q,r in cache.items() if r['fgt1_pct']<=limit+1e-10)
            if lo>=1-1e-10:q=1.
            else:
                hi=min(q for q in cache if q>lo)
                residual=lambda q:evaluate(q,'retention_refinement')['fgt1_pct']-limit
                q=lo if abs(residual(lo))<1e-8 else brentq(residual,lo,hi,xtol=2e-9,rtol=1e-12)
                probe=evaluate(min(1,q+1e-5),'retention_probe')['fgt1_pct'];assert probe>limit-1e-8
            r=evaluate(q,'retention_choice');assert r['fgt1_pct']<=limit+1e-7
            selected.append(dict(choice=f'retain_{int(100*retention)}',retention_pct=100*retention,epsilon_pp=limit-best['fgt1_pct'],fgt1_limit_pct=limit,**r))
        cases[name]=dict(configuration=cfg,seed=seed,shock_fgt1_pct=original['shock_fgt1_pct'],numerical_minimum=best,
            maximum_reduction_pp=gain,selected=selected,additional_policy_solves=len(checks),checks=checks,
            phase_one_minimum_fgt1_pct=original['numerical_minimum']['fgt1_pct'])
        cm.dump(current,dict(status='running',cases=cases,prior_sha256=source_sha,code_sha256=code_sha,elapsed_seconds=time.time()-start))
        pd.DataFrame(rows).to_csv(curvepath,index=False,float_format='%.12g')
        pd.DataFrame([r for c in cases.values() for r in c['selected']]).to_csv(out/'tables/PMT_coverage_robustness_refined_summary.csv',index=False,float_format='%.12g')
        print(f"  {best['coverage_pct']:.5f}% / {best['fgt1_pct']:.8f}; {len(checks)} new solves",flush=True)
    # Identical cash-policy specifications must have matching achievable minima.
    assert abs(cases['main']['numerical_minimum']['fgt1_pct']-cases['energy_support_only']['numerical_minimum']['fgt1_pct'])<1e-6
    audit=json.loads(current.read_text(encoding='utf-8'));audit['status']='complete';audit['completed_case_count']=len(cases)
    audit['elapsed_seconds']=time.time()-start;cm.dump(current,audit)
    for rel,expected in prior['protected_hashes'].items():assert cm.sha(cm.ROOT/rel)==expected
    print('COMPLETE competing-minimum check',len(cases),flush=True)

if __name__=='__main__':main()
