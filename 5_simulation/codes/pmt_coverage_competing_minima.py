"""Independently refine competitive secondary minima of the PMT coverage curve.

The initial search refines the best coarse basin. This additional check inspects
all competitive fine-grid minima outside its household-boundary window.
"""
import os
for key in ("OPENBLAS_NUM_THREADS","OMP_NUM_THREADS","MKL_NUM_THREADS"):
    os.environ.setdefault(key,"1")
import json
import time
from pathlib import Path
import numpy as np
import pandas as pd
import pyomo.environ as pyo
from scipy.optimize import minimize_scalar
import common as cm
import micro_simulation as ms
import policy_model as pm


def main():
    started=time.time()
    prior=pd.read_csv(cm.OUT/"tables/PMT_coverage_optimization_curve.csv")
    fine=prior[prior.stage.isin(["fine_0.1pp","global_1pp"])].sort_values("coverage_pct")
    x=fine.coverage_pct.to_numpy()/100
    y=fine.fgt1_pct.to_numpy()
    current_best=float(prior.loc[prior.fgt1_pct.idxmin(),"coverage_pct"])/100
    candidate_windows=[]
    for i in range(1,len(x)-1):
        if y[i]<=y[i-1] and y[i]<=y[i+1] and y[i]<=prior.fgt1_pct.min()+.02 and abs(x[i]-current_best)>.003:
            candidate_windows.append((float(x[i-1]),float(x[i+1])))
    # An empty set is valid: re-solve the primary optimum and comparators.
    print("Secondary search windows:",candidate_windows,flush=True)
    cfg=cm.configurations()["main"]
    base=pm.build(cfg);cm.cge.solve_model(base)
    saved=ms.dump
    try:
        ms.dump=lambda *args:None
        micro,h,f=ms.prepare_micro(base)
        _,scores,_,_=ms.fit_pmt(micro,h,f)
    finally:ms.dump=saved
    del h,f
    shock=pm.shock_model(base,cfg)
    budget=pm.gdp(base)*cfg["budget"]
    pop=float(micro["pw"].sum())
    order=np.argsort(scores,kind="stable")
    boundaries=np.cumsum(micro["pw"][order])/pop
    cache={};rows=[];checks=[]
    def evaluate(q):
        q=float(q)
        if q in cache:return cache[q]
        mask=ms.exact_mask(micro["pw"],order,q*pop)
        shares=ms.group_shares(micro,mask)
        model,d=pm.policy_model(shock,cfg,"cash",shares,budget)
        d["max_sam_account_gap_trillion_tl"]=pm.check_policy_sam(model)
        checks.append(dict(coverage_pct=100*q,**d))
        state=pm.snapshot(model,base,shares=shares,cash_saving=cfg["cash_saving"],reference_sg=pyo.value(shock.Sg))
        v,groups,contribution=ms.household_outcomes(state,micro,mask)
        e=ms.errors(micro,mask)
        row=dict(coverage_pct=100*q,recipients_million=q*pop/1e6,
                 annual_cash_per_recipient_sam_tl=state["net_cash"]*1e12/(q*pop),
                 target_reached_pct=100*(1-e["exclusion"]),exclusion_pct=100*e["exclusion"],leakage_pct=100*e["leakage"],
                 net_fiscal_cost_billion_tl=state["macro"]["net_fiscal_cost_trillion_tl"]*1000,**v)
        rows.append(row);cache[q]=dict(row=row,state=state,contribution=contribution)
        if len(rows)%10==0:
            b=min(rows,key=lambda r:r["fgt1_pct"])
            print(f"Secondary check {len(rows)}: best {b['coverage_pct']:.6f}% -> {b['fgt1_pct']:.8f}; {time.time()-started:.0f}s",flush=True)
        return cache[q]
    all_intervals=[]
    for lo,hi in candidate_windows:
        qset=sorted(set([lo,hi,*[float(q) for q in boundaries if lo<q<hi]]))
        for q in qset:evaluate(q)
        for a,b in zip(qset[:-1],qset[1:]):
            mid=evaluate((a+b)/2)
            merit=min(cache[a]["row"]["fgt1_pct"],cache[b]["row"]["fgt1_pct"],mid["row"]["fgt1_pct"])
            all_intervals.append((merit,a,b))
    optimisations=[]
    for _,a,b in sorted(all_intervals)[:4]:
        res=minimize_scalar(lambda q:evaluate(q)["row"]["fgt1_pct"],bounds=(a,b),method="bounded",options={"xatol":1e-7,"maxiter":50})
        assert res.success
        optimisations.append(dict(lower=a,upper=b,x=float(res.x),fun=float(res.fun)))
    evaluate(current_best)
    evaluate(.2);evaluate(.4);evaluate(1.)
    best_q=min(cache,key=lambda q:cache[q]["row"]["fgt1_pct"])
    best=cache[best_q]
    contributions={"validated_optimum":best["contribution"],"initial_optimum":cache[current_best]["contribution"],
                   "pmt_20":cache[.2]["contribution"],"pmt_40":cache[.4]["contribution"],"universal_cash":cache[1.]["contribution"]}
    intervals=ms.paired_intervals(contributions,micro,[("validated_optimum",key) for key in ("initial_optimum","pmt_20","pmt_40","universal_cash")])
    pd.DataFrame(rows).sort_values("coverage_pct").to_csv(cm.OUT/"tables/PMT_coverage_competing_minima.csv",index=False,encoding="utf-8-sig",float_format="%.12g")
    cm.dump(cm.OUT/"equilibria/pmt_coverage_validated_optimum.json",dict(coverage=best_q,**best["state"]))
    audit=dict(status="complete",windows=candidate_windows,initial_best_coverage_pct=100*current_best,
               optimum=best["row"],checked_equilibria=len(checks),checks=checks,bounded_optimisations=optimisations,
               paired_intervals=intervals,elapsed_seconds=time.time()-started,source_sha256=cm.sha(Path(__file__)),
               method="Refine all secondary fine-grid local minima within 0.02 FGT1 percentage points of the preliminary best, outside its +/-0.3 percentage-point window; all household boundaries, midpoints and bounded optimisation of four best intervals.")
    cm.dump(cm.OUT/"diagnostics/pmt_coverage_competing_minima.json",audit)
    print("VALIDATED OPTIMUM",json.dumps(best["row"]),flush=True)
    print("PAIRED",json.dumps(intervals),flush=True)


if __name__=="__main__":main()
