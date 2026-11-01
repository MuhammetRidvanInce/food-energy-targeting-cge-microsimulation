"""Coverage design checks: structural scenarios, PMT partitions and feedbacks.

Numerical minima are conditional on the PMT ordering and equal per-person cash.
Structural searches use a common coarse grid, local grids and bounded refinements.
No record-level survey data are exported. Historical analysis outputs are read-only.
"""
import os
for key in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS'):
    os.environ[key]='1'
import argparse, copy, json, time
from pathlib import Path
import numpy as np
import pandas as pd
import pyomo.environ as pyo
from scipy.optimize import minimize_scalar, brentq
import common as cm
import micro_simulation as ms
import policy_model as pm

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--only',default='all');args=ap.parse_args()
    if args.only=='all':
        from parallel_coverage_robustness import main as parallel_main
        return parallel_main()
    start=time.time(); out=cm.OUT
    audit_path=out/'diagnostics/pmt_coverage_robustness.json'
    protected={str(p.relative_to(cm.ROOT)):cm.sha(p) for p in [
        out/'diagnostics/pmt_design.json',out/'diagnostics/micro_calibration.json',
        out/'diagnostics/pmt_epsilon_constraint.json',out/'tables/main/Table1_main_policy_results.csv']}
    source={str(p.relative_to(cm.PROJECT)):cm.sha(p) for p in [
        Path(__file__),Path(ms.__file__),Path(pm.__file__),Path(cm.__file__),cm.SAM,cm.ELASTICITIES]}
    saved_dump=ms.dump;ms.dump=lambda *a,**k:None
    cfg0=cm.configurations()['main'];base0=pm.build(cfg0);cm.cge.solve_model(base0)
    micro,h,f=ms.prepare_micro(base0)
    _,pred,_,design=ms.fit_pmt(micro,h,f)
    ms.dump=saved_dump
    pop=float(micro['pw'].sum());target=float(micro['pw'][micro['group']<2].sum())
    original_poor=micro['income']/micro['equiv']<micro['poverty_line']
    poor_pop=float(micro['pw'][original_poor].sum())
    cases=[(k,v,cm.SEED) for k,v in cm.configurations().items()]
    cases += [(f'pmt_partition_{s}',cfg0,s) for s in (20261026,20261027,20261028)]
    if args.only!='all':cases=[x for x in cases if x[0] in args.only.split(',')]
    previous=json.loads(audit_path.read_text(encoding='utf-8')) if audit_path.exists() else {}
    if previous:assert previous['source_hashes']==source,'Source changed since checkpoint'
    done=previous.get('cases',{}); all_rows=[]; checks=[]; feedback=[]
    curves_path=out/'tables/PMT_coverage_robustness_curves.csv'
    if curves_path.exists():all_rows=pd.read_csv(curves_path).to_dict(orient='records')
    for name,cfg,seed in cases:
        if name in done:
            print('Already complete:',name,flush=True);continue
        print('Starting',name,flush=True)
        base=base0 if cfg==cfg0 else pm.build(cfg)
        if base is not base0:cm.cge.solve_model(base)
        shock=pm.shock_model(base,cfg);budget=pm.gdp(base)*cfg['budget']
        if seed==cm.SEED:scores=pred
        else:
            old_seed=ms.SEED;old_dump=ms.dump
            try:
                ms.SEED=seed;ms.dump=lambda *a,**k:None
                _,scores,_,_=ms.fit_pmt(micro,h,f)
            finally:ms.SEED=old_seed;ms.dump=old_dump
        order=np.argsort(scores,kind='stable');cache={};case_checks=[]
        shock_state=pm.snapshot(shock,base)
        shock_metrics,_,_=ms.household_outcomes(shock_state,micro,np.zeros(len(scores)))
        def evaluate(q,stage='search'):
            q=float(q);key=round(q,13)
            if key in cache:return cache[key]
            mask=ms.exact_mask(micro['pw'],order,q*pop);shares=ms.group_shares(micro,mask)
            m,d=pm.policy_model(shock,cfg,'cash',shares,budget)
            d['sam_gap_trillion_tl']=pm.check_policy_sam(m)
            state=pm.snapshot(m,base,shares=shares,cash_saving=cfg['cash_saving'],reference_sg=pyo.value(shock.Sg))
            vals,_,_=ms.household_outcomes(state,micro,mask)
            e=ms.errors(micro,mask)
            row=dict(configuration=name,seed=seed,stage=stage,coverage_pct=100*q,
                recipients_million=q*pop/1e6,target_reached_pct=100*(1-e['exclusion']),
                initial_poor_reached_pct=100*np.dot(micro['pw'][original_poor],mask[original_poor])/poor_pop,
                annual_cash_per_recipient_sam_tl=state['net_cash']*1e12/(q*pop),
                net_fiscal_cost_billion_tl=state['macro']['net_fiscal_cost_trillion_tl']*1000,**vals)
            cache[key]=dict(row=row,state=state,mask=mask)
            case_checks.append(dict(coverage_pct=100*q,**d));all_rows.append(row)
            return cache[key]
        grid=np.unique(np.r_[.001,.005,np.arange(.01,.101,.01),.12,.15,.2,.3,.4,.5,.6,.8,1.])
        for q in grid:evaluate(q,'coarse')
        # Refine every coarse local minimum within 0.03 pp of the best one.
        gv=np.array([evaluate(q)['row']['fgt1_pct'] for q in grid])
        centres=[i for i in range(1,len(grid)-1) if gv[i]<=gv[i-1] and gv[i]<=gv[i+1] and gv[i]<gv.min()+.03]
        if not centres:centres=[int(np.argmin(gv))]
        for i in centres:
            lo=grid[max(i-1,0)];hi=grid[min(i+1,len(grid)-1)]
            fine=np.linspace(lo,hi,11)
            for q in fine:evaluate(q,'local_grid')
            fg=np.array([evaluate(q)['row']['fgt1_pct'] for q in fine]);j=int(np.argmin(fg))
            a=fine[max(j-1,0)];b=fine[min(j+1,len(fine)-1)]
            if b>a:
                sol=minimize_scalar(lambda q:evaluate(q,'local_refinement')['row']['fgt1_pct'],bounds=(a,b),method='bounded',options={'xatol':1e-6,'maxiter':24})
                evaluate(sol.x,'local_refinement')
        # Main case retains the denser verified 525-policy search and exact minimum.
        if name=='main':
            final=json.loads((out/'diagnostics/pmt_coverage_optimization_final.json').read_text(encoding='utf-8'))
            evaluate(final['optimum']['coverage_pct']/100,'dense_search_reference')
        best=min(cache.values(),key=lambda a:a['row']['fgt1_pct']);gstar=best['row']['fgt1_pct']
        gain=shock_metrics['fgt1_pct']-gstar
        selected=[dict(choice='minimum_gap',retention_pct=100.,**best['row'])]
        for retention in (.75,.5):
            limit=gstar+(1-retention)*gain
            feasible=[q for q,x in cache.items() if x['row']['fgt1_pct']<=limit+1e-10]
            lo=max(feasible)
            if lo>=1-1e-10:q=1.
            else:
                hi=min(q for q in cache if q>lo)
                for t in np.linspace(lo,hi,5)[1:-1]:evaluate(t,'epsilon_bracket')
                lo=max(q for q,x in cache.items() if x['row']['fgt1_pct']<=limit+1e-10)
                hi=min(q for q in cache if q>lo)
                q=brentq(lambda q:evaluate(q,'epsilon_root')['row']['fgt1_pct']-limit,lo,hi,xtol=2e-9,rtol=1e-12)
                probe=evaluate(min(1,q+1e-5),'epsilon_probe')['row']['fgt1_pct']
                assert probe>limit-1e-8
            r=evaluate(q,'epsilon_choice')['row']
            assert r['fgt1_pct']<=limit+1e-7
            selected.append(dict(choice=f'retain_{int(100*retention)}',retention_pct=100*retention,
                epsilon_pp=limit-gstar,fgt1_limit_pct=limit,**r))
        if name=='main':
            # Hold each GE cash envelope and allocation fixed, and freeze all
            # prices and regular incomes at the unsupported-shock equilibrium.
            # This is a channel decomposition, not an alternative equal-cost GE.
            for q in [best['row']['coverage_pct']/100,.10,.20,.40,.60,1.]:
                item=evaluate(q,'feedback_decomposition');state=item['state'];mask=item['mask']
                frozen=copy.deepcopy(shock_state)
                frozen['net_cash']=state['net_cash'];frozen['shares']=state['shares'];frozen['cash_saving']=cfg['cash_saving']
                frozen['group_budget']=np.asarray(shock_state['group_budget'])+(1-cfg['cash_saving'])*state['net_cash']*np.asarray(state['shares'])
                frozen['consumption_expenditure']=np.asarray(frozen['group_beta'])*frozen['group_budget'][None,:]
                fm,_,_=ms.household_outcomes(frozen,micro,mask)
                feedback.append(dict(coverage_pct=100*q,general_equilibrium_fgt1_pct=item['row']['fgt1_pct'],
                    frozen_feedback_fgt1_pct=fm['fgt1_pct'],feedback_difference_pp=item['row']['fgt1_pct']-fm['fgt1_pct'],
                    net_cash_billion_tl=1000*state['net_cash']))
            pd.DataFrame(feedback).to_csv(out/'tables/PMT_coverage_feedback.csv',index=False,float_format='%.12g')
        done[name]=dict(configuration=cfg,seed=seed,shock_fgt1_pct=shock_metrics['fgt1_pct'],
            numerical_minimum=best['row'],maximum_reduction_pp=gain,selected=selected,
            policy_solves=len(case_checks),max_sam_gap=max(x['sam_gap_trillion_tl'] for x in case_checks),
            max_fiscal_gap=max(x['equal_net_cost_relative_gap'] for x in case_checks),
            checks=case_checks)
        for rel,expected in protected.items():assert cm.sha(cm.ROOT/rel)==expected,rel
        cm.dump(audit_path,dict(status='running',elapsed_seconds=time.time()-start,source_hashes=source,
            protected_hashes=protected,cases=done,population=pop,target_population=target,
            initial_poor_population=poor_pop,search='Coarse grid, local grids and bounded refinement; rightmost evaluated feasible epsilon crossing. Main minimum additionally uses the existing dense search.'))
        pd.DataFrame(all_rows).to_csv(curves_path,index=False,float_format='%.12g')
        pd.DataFrame([r for d in done.values() for r in d['selected']]).to_csv(out/'tables/PMT_coverage_robustness_summary.csv',index=False,float_format='%.12g')
        print(f"Completed {name}: min {best['row']['coverage_pct']:.4f}%; retain75 {selected[1]['coverage_pct']:.4f}%; retain50 {selected[2]['coverage_pct']:.4f}%; {len(case_checks)} solves",flush=True)
    audit=json.loads(audit_path.read_text(encoding='utf-8'));audit['status']='complete';audit['elapsed_seconds']=time.time()-start
    audit['completed_case_count']=len(done);cm.dump(audit_path,audit)
    print('COMPLETE',len(done),'cases',flush=True)

if __name__=='__main__':main()
