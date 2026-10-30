"""Pareto filtering and epsilon-constraint PMT coverage optimisation.

Maximise coverage subject to FGT1 <= numerical minimum + epsilon and the same
net fiscal cost. Reuses the broad solved grid, then solves new CGE equilibria to
refine the rightmost observed feasible crossing for each tolerance.
"""
import os
for key in ("OPENBLAS_NUM_THREADS","OMP_NUM_THREADS","MKL_NUM_THREADS"):
    os.environ.setdefault(key,"1")
import json
import time
from datetime import datetime,timezone
from pathlib import Path
import numpy as np
import pandas as pd
import pyomo.environ as pyo
from scipy.optimize import brentq
import common as cm
import micro_simulation as ms
import policy_model as pm


def main():
    started=time.time()
    initial_path=cm.OUT/"diagnostics/pmt_coverage_optimization.json"
    final_path=cm.OUT/"diagnostics/pmt_coverage_optimization_final.json"
    curve_path=cm.OUT/"tables/PMT_coverage_optimization_final_curve.csv"
    initial=json.loads(initial_path.read_text(encoding="utf-8"))
    final=json.loads(final_path.read_text(encoding="utf-8"))
    assert initial["status"]==final["status"]=="complete"
    for rel,expected in initial["source_hashes"].items():assert cm.sha(cm.PROJECT/rel)==expected,rel
    for rel,expected in initial["protected_output_hashes"].items():assert cm.sha(cm.ROOT/rel)==expected,rel
    protected=[initial_path,final_path,curve_path,cm.OUT/"diagnostics/pmt_coverage_tradeoff.json"]
    protected_hashes={str(p.relative_to(cm.ROOT)):cm.sha(p) for p in protected}
    original=pd.read_csv(cm.OUT/"tables/main/Table1_main_policy_results.csv").set_index("policy")
    known=pd.read_csv(curve_path)
    star=final["optimum"]
    qstar=star["coverage_pct"]/100
    gstar=star["fgt1_pct"]
    shock_gap=float(original.loc["shock","fgt1_pct"])
    gain=shock_gap-gstar
    universal_gap=float(original.loc["universal_cash","fgt1_pct"])
    cap_epsilon=universal_gap-gstar
    cfg=cm.configurations()["main"]
    print("Preparing benchmark, unchanged PMT and common-shock equilibrium",flush=True)
    base=pm.build(cfg);base_diag=cm.cge.solve_model(base)
    saved_dump=ms.dump
    try:
        ms.dump=lambda *args:None
        micro,h,f=ms.prepare_micro(base)
        original_mask,scores,_,pmt_design=ms.fit_pmt(micro,h,f)
    finally:ms.dump=saved_dump
    del h,f
    pop=float(micro["pw"].sum());order=np.argsort(scores,kind="stable")
    shock=pm.shock_model(base,cfg);budget=pm.gdp(base)*cfg["budget"]
    checks=[dict(label="baseline",**base_diag,max_sam_account_gap_trillion_tl=pm.check_policy_sam(base)),
            dict(label="shock",**cm.cge.diagnostics(shock),max_sam_account_gap_trillion_tl=pm.check_policy_sam(shock))]
    cache={float(r["coverage_pct"])/100:dict(row=r) for r in known.to_dict(orient="records")}
    fresh={};new_rows=[];root_audits=[]

    def evaluate(q,stage="refinement",force=False):
        q=float(q)
        if q in fresh:return fresh[q]
        if q in cache and not force:return cache[q]
        mask=ms.exact_mask(micro["pw"],order,q*pop)
        shares=ms.group_shares(micro,mask)
        model,d=pm.policy_model(shock,cfg,"cash",shares,budget)
        d["max_sam_account_gap_trillion_tl"]=pm.check_policy_sam(model)
        checks.append(dict(coverage_pct=100*q,stage=stage,**d))
        state=pm.snapshot(model,base,shares=shares,cash_saving=cfg["cash_saving"],reference_sg=pyo.value(shock.Sg))
        values,groups,contribution=ms.household_outcomes(state,micro,mask)
        er=ms.errors(micro,mask)
        assert values["negative_income_households"]==0
        assert d["equal_net_cost_relative_gap"]<1e-8
        row=dict(coverage_pct=100*q,recipients_million=q*pop/1e6,
                 additional_recipients_million=(q-qstar)*pop/1e6,
                 annual_cash_per_recipient_sam_tl=state["net_cash"]*1e12/(q*pop),
                 target_reached_pct=100*(1-er["exclusion"]),exclusion_pct=100*er["exclusion"],
                 leakage_pct=100*er["leakage"],net_fiscal_cost_billion_tl=state["macro"]["net_fiscal_cost_trillion_tl"]*1000,
                 net_cash_billion_tl=1000*state["net_cash"],**values)
        item=dict(row=row,state=state,contribution=contribution,groups=groups)
        fresh[q]=item;cache[q]=item;new_rows.append(dict(stage=stage,**row))
        if len(new_rows)%10==0:
            pd.DataFrame(new_rows).to_csv(cm.OUT/"tables/PMT_epsilon_new_evaluations.csv",index=False,encoding="utf-8-sig",float_format="%.12g")
            print(f"  {len(new_rows)} new policy equilibria; elapsed {time.time()-started:.0f}s",flush=True)
        return item

    reference=evaluate(qstar,"replication",True)
    assert abs(reference["row"]["fgt1_pct"]-gstar)<1e-8
    reference=evaluate(1.,"replication",True)
    assert abs(reference["row"]["fgt1_pct"]-universal_gap)<1e-8
    target_share=float(np.dot(micro["pw"],original_mask)/pop)
    reference=evaluate(target_share,"replication",True)
    assert abs(reference["row"]["fgt1_pct"]-float(original.loc["pmt","fgt1_pct"]))<1e-8

    def rightmost_bracket(limit):
        feasible=[q for q,item in cache.items() if item["row"]["fgt1_pct"]<=limit+1e-10]
        assert feasible
        low=max(feasible)
        if low>=1-1e-12:return 1.,1.
        high=min(q for q in cache if q>low)
        assert cache[high]["row"]["fgt1_pct"]>limit
        return low,high

    def solve_epsilon(epsilon):
        limit=gstar+epsilon
        if epsilon==0:
            return qstar,dict(method="Replicated numerical FGT1 minimum",coverage=qstar,slack_pp=limit-evaluate(qstar)["row"]["fgt1_pct"])
        if limit>=evaluate(1.)["row"]["fgt1_pct"]-1e-9:
            return 1.,dict(method="Universal-coverage upper bound",coverage=1.,slack_pp=limit-evaluate(1.)["row"]["fgt1_pct"])
        lo,hi=rightmost_bracket(limit)
        initial_bracket=[lo,hi]
        # Sample the full candidate interval before choosing its rightmost
        # feasible crossing. This retains non-monotone household-entry effects.
        for q in np.linspace(lo,hi,6)[1:-1]:evaluate(float(q),"bracket_scan")
        lo,hi=rightmost_bracket(limit)
        # Re-solve endpoints so the root uses unrounded model values.
        evaluate(lo,"root_endpoint",True);evaluate(hi,"root_endpoint",True)
        lo,hi=rightmost_bracket(limit)
        def residual(q):return evaluate(float(q),"epsilon_root")["row"]["fgt1_pct"]-limit
        if abs(residual(lo))<1e-10:q=lo
        else:q=float(brentq(residual,lo,hi,xtol=2e-10,rtol=1e-12,maxiter=50))
        actual=evaluate(q,"selected",True)["row"]["fgt1_pct"]
        # Choose the feasible side if solver round-off is slightly positive.
        for _ in range(5):
            if actual<=limit+2e-10:break
            q=max(lo,q-2e-10)
            actual=evaluate(q,"feasible_roundoff")["row"]["fgt1_pct"]
        assert actual<=limit+1e-8
        # A 0.001 coverage-percentage-point expansion must violate this cap.
        probe=min(1.,q+1e-5)
        probe_gap=evaluate(probe,"right_probe")["row"]["fgt1_pct"]
        assert probe_gap>limit+1e-9,(epsilon,q,probe_gap,limit)
        larger=[item["row"]["fgt1_pct"] for z,item in cache.items() if z>q+1e-8]
        assert all(g>limit-1e-8 for g in larger)
        return q,dict(method="Rightmost evaluated feasible crossing, bracket scan and CGE root refinement",
                       initial_bracket=initial_bracket,refined_bracket=[lo,hi],coverage=q,
                       slack_pp=limit-actual,right_probe_coverage=probe,right_probe_excess_pp=probe_gap-limit)

    absolute=[0.,.01,.05,.10,.20,.25,.50,.75,1.,cap_epsilon]
    retention=[.75,.50,.25]
    specs=[dict(kind="absolute_tolerance",epsilon=e) for e in absolute]
    specs += [dict(kind="retention_target",epsilon=(1-r)*gain,minimum_reduction_retained_pct=100*r) for r in retention]
    solutions={};rows=[]
    for epsilon in sorted(set(s["epsilon"] for s in specs)):
        print(f"Solving epsilon = {epsilon:.9f} FGT1 percentage points",flush=True)
        q,info=solve_epsilon(epsilon)
        solutions[epsilon]=q
        root_audits.append(dict(epsilon_pp=epsilon,**info))
        print(f"  maximum coverage {100*q:.6f}%; FGT1 {evaluate(q)['row']['fgt1_pct']:.9f}",flush=True)
    for spec in specs:
        epsilon=spec["epsilon"];q=solutions[epsilon];r=evaluate(q)["row"]
        rows.append(dict(scenario_kind=spec["kind"],epsilon_pp=epsilon,fgt1_upper_bound_pct=gstar+epsilon,
                         reduction_retention_requirement_pct=spec.get("minimum_reduction_retained_pct",np.nan),
                         actual_fgt1_cost_pp=r["fgt1_pct"]-gstar,
                         maximum_reduction_retained_pct=100*(shock_gap-r["fgt1_pct"])/gain,
                         epsilon_slack_pp=gstar+epsilon-r["fgt1_pct"],**r))
    result=pd.DataFrame(rows).sort_values(["epsilon_pp","scenario_kind"]).reset_index(drop=True)
    assert result.epsilon_slack_pp.min()>-1e-8
    assert np.ptp(result.net_fiscal_cost_billion_tl)<1e-6
    assert np.diff(result.coverage_pct).min()>-1e-8

    # Pareto dominance: maximise coverage and minimise FGT1. At equal coverage
    # retain the lower gap; filter numerically indistinguishable duplicates.
    all_rows=pd.DataFrame([item["row"] for item in cache.values()])
    all_rows["coverage_key"]=all_rows.coverage_pct.round(8)
    all_rows=all_rows.sort_values(["coverage_key","fgt1_pct"],ascending=[False,True]).drop_duplicates("coverage_key").reset_index(drop=True)
    running=float("inf");flags=[]
    for g in all_rows.fgt1_pct:
        keep=g<running-1e-10
        flags.append(keep)
        running=min(running,g)
    all_rows["pareto_efficient_evaluated"]=flags
    all_rows=all_rows.sort_values("coverage_pct").drop(columns="coverage_key")
    front=all_rows[all_rows.pareto_efficient_evaluated].copy()
    for r in result.to_dict(orient="records"):
        assert not ((all_rows.coverage_pct>r["coverage_pct"]+1e-6)&(all_rows.fgt1_pct<=r["fgt1_pct"]-1e-8)).any()
    result.to_csv(cm.OUT/"tables/PMT_epsilon_solutions.csv",index=False,encoding="utf-8-sig",float_format="%.12g")
    all_rows.to_csv(cm.OUT/"tables/PMT_pareto_evaluated_policies.csv",index=False,encoding="utf-8-sig",float_format="%.12g")
    front.to_csv(cm.OUT/"tables/PMT_pareto_frontier.csv",index=False,encoding="utf-8-sig",float_format="%.12g")
    pd.DataFrame(new_rows).to_csv(cm.OUT/"tables/PMT_epsilon_new_evaluations.csv",index=False,encoding="utf-8-sig",float_format="%.12g")
    selected_states={f"epsilon_{e:.12g}":dict(coverage=q,**evaluate(q)["state"]) for e,q in solutions.items()}
    cm.dump(cm.OUT/"equilibria/pmt_epsilon_solutions.json",selected_states)
    group_rows=[dict(epsilon_pp=e,coverage_pct=100*q,**g) for e,q in solutions.items() for g in evaluate(q)["groups"]]
    pd.DataFrame(group_rows).to_csv(cm.OUT/"tables/PMT_epsilon_quintiles.csv",index=False,encoding="utf-8-sig",float_format="%.12g")
    for rel,expected in protected_hashes.items():assert cm.sha(cm.ROOT/rel)==expected,rel
    for rel,expected in initial["protected_output_hashes"].items():assert cm.sha(cm.ROOT/rel)==expected,rel
    for rel,expected in initial["source_hashes"].items():assert cm.sha(cm.PROJECT/rel)==expected,rel
    clean=result.astype(object).where(pd.notna(result),None).to_dict(orient="records")
    run=dict(status="complete",utc_time=datetime.now(timezone.utc).isoformat(),elapsed_seconds=time.time()-started,
             problem="Maximise population coverage subject to FGT1 <= G_min + epsilon, unchanged PMT ranking and equal per-person transfers, and common net fiscal cost.",
             g_min_pct=gstar,minimum_coverage_pct=100*qstar,no_policy_shock_fgt1_pct=shock_gap,
             maximum_poverty_reduction_pp=gain,universal_coverage_epsilon_pp=cap_epsilon,
             population=pop,config=cfg,results=clean,root_refinements=root_audits,
             evaluated_policy_count=len(all_rows),pareto_point_count=len(front),new_policy_equilibria=len(new_rows),
             checked_equilibria=len(checks),checks=checks,pmt_design=pmt_design,
             source_sha256=cm.sha(Path(__file__)),protected_hashes=protected_hashes,original_outputs_unchanged=True,
             search_interpretation="Maximum feasible coverage found from the prior global evaluated grid, additional bracket sampling and exact-model root refinement. Right-side probes and dominance checks are numerical validations, not a formal global certificate between every unevaluated pair of policies.")
    cm.dump(cm.OUT/"diagnostics/pmt_epsilon_constraint.json",run)

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.family":"DejaVu Sans","font.size":9,"axes.spines.top":False,"axes.spines.right":False,"svg.fonttype":"none"})
    fig,(a,b)=plt.subplots(1,2,figsize=(11.3,4.2),layout="constrained")
    blue="#216b92";red="#bd4659"
    dominated=all_rows[~all_rows.pareto_efficient_evaluated]
    a.scatter(dominated.coverage_pct,dominated.fgt1_pct,s=10,color="#b3b7bb",alpha=.65,label="Dominated evaluated policies")
    a.plot(front.coverage_pct,front.fgt1_pct,lw=1.8,color=blue,label="Evaluated Pareto frontier")
    absolute_rows=result[result.scenario_kind=="absolute_tolerance"]
    a.scatter(absolute_rows.coverage_pct,absolute_rows.fgt1_pct,s=22,color=red,zorder=4,label="Epsilon-constraint solutions")
    example=result[(result.scenario_kind=="absolute_tolerance")&np.isclose(result.epsilon_pp,.5)].iloc[0]
    a.hlines(example.fgt1_pct,0,example.coverage_pct,color=red,ls="--",lw=.9)
    a.vlines(example.coverage_pct,gstar-.05,example.fgt1_pct,color=red,ls="--",lw=.9)
    a.annotate(r"$\epsilon=0.50$ pp",(example.coverage_pct,example.fgt1_pct),xytext=(8,-15),textcoords="offset points",color=red,fontsize=9)
    a.set(xlim=(0,103),ylim=(gstar-.05,8.15),xlabel="Population receiving cash (%)",ylabel="Poverty gap, FGT1 (%)",title="a   Poverty-gap and coverage Pareto frontier")
    a.legend(frameon=False,fontsize=7.6,loc="upper center")
    # The staircase uses evaluated policies; exact root-refined choices are marked.
    b.step(front.fgt1_pct-gstar,front.coverage_pct,where="post",color=blue,lw=1.5,label="Evaluated feasible-coverage envelope")
    b.scatter(absolute_rows.epsilon_pp,absolute_rows.coverage_pct,s=27,color=red,zorder=4,label="Refined constraint-boundary solutions")
    for e in [.1,.25,.5,.75,1.]:
        r=absolute_rows[np.isclose(absolute_rows.epsilon_pp,e)].iloc[0]
        b.annotate(f"{r.coverage_pct:.1f}%",(e,r.coverage_pct),xytext=(-5,7),textcoords="offset points",ha="right",fontsize=8)
    b.set(xlim=(-.025,cap_epsilon+.045),ylim=(0,104),xlabel="Allowed FGT1 increase above the minimum (pp)",ylabel="Maximum population coverage (%)",title="b   Epsilon tolerance and attainable coverage")
    b.legend(frameon=False,fontsize=7.6,loc="upper left")
    for ax in (a,b):ax.grid(alpha=.17);ax.set_axisbelow(True)
    for ext in ("png","svg"):
        fig.savefig(cm.OUT/f"figures/PMT_epsilon_pareto.{ext}",dpi=300,bbox_inches="tight")
    plt.close(fig)

    lines=["# Epsilon-constraint analysis of poverty reduction and PMT coverage","",
           "The two objectives are to minimise FGT1 and maximise the number of persons receiving cash. Population is fixed, so maximising recipients is equivalent to maximising the population coverage rate. The PMT ranking, equal per-person payment rule, common shock and net fiscal budget remain those of the main configuration.","",
           r"$$\max_{0<c\leq100}c\quad\text{subject to}\quad G(c)\leq G^*+\epsilon,\qquad F(c)=B.$ $".replace("$ $","$$"),"",
           f"Here c is total population coverage in percent, G(c) is FGT1 in percent, G* = {gstar:.9f}%, epsilon is measured in FGT1 percentage points, and B = {1000*budget:.6f} billion TL. Each boundary solution is re-evaluated through the CGE and microsimulation. No objective weights are imposed.","",
           "| Allowed FGT1 increase (pp) | Maximum coverage (%) | Recipients (million) | FGT1 (%) | Annual cash per person (SAM TL) | Original target reached (%) | Maximum poverty reduction retained (%) |",
           "|---:|---:|---:|---:|---:|---:|---:|"]
    for r in absolute_rows.to_dict(orient="records"):
        lines.append(f"| {r['epsilon_pp']:.6f} | {r['coverage_pct']:.4f} | {r['recipients_million']:.4f} | {r['fgt1_pct']:.6f} | {r['annual_cash_per_recipient_sam_tl']:.2f} | {r['target_reached_pct']:.2f} | {r['maximum_reduction_retained_pct']:.2f} |")
    lines += ["","The original target used in the reach column is the bottom two income quintiles. The optimised second objective is the total number of cash recipients, including recipients outside that original target. The poverty-gap cap and common net budget hold for every row.","",
              "An equivalent way to express the cap is to retain at least a specified share of the largest attained poverty reduction relative to the no-policy shock:","",
              r"$$\epsilon=(1-r)\left(G_{\mathrm{shock}}-G^*\right),$$","",
              "where r is the retained fraction. These additional constraints give:","",
              "| Required reduction retained (%) | Epsilon (pp) | Maximum coverage (%) | Recipients (million) | FGT1 (%) | Original target reached (%) |",
              "|---:|---:|---:|---:|---:|---:|"]
    for r in result[result.scenario_kind=="retention_target"].sort_values("reduction_retention_requirement_pct",ascending=False).to_dict(orient="records"):
        lines.append(f"| {r['reduction_retention_requirement_pct']:.0f} | {r['epsilon_pp']:.6f} | {r['coverage_pct']:.4f} | {r['recipients_million']:.4f} | {r['fgt1_pct']:.6f} | {r['target_reached_pct']:.2f} |")
    lines += ["",f"Across {len(all_rows)} distinct evaluated policies, {len(front)} are retained by Pareto dominance filtering: a policy is removed if another evaluated policy provides at least as much coverage and at most as much FGT1, with a strict improvement in one dimension. The additional root search solved {len(new_rows)} policy equilibria. All {len(checks)} newly checked benchmark, shock and policy equilibria pass the existing model and fiscal diagnostics.","",
              "The search identifies the rightmost feasible region in the existing global grid, samples its bracket, and refines its boundary using new CGE solutions. For each interior tolerance, a coverage expansion of 0.001 percentage points beyond the selected solution violates the FGT1 cap; all evaluated higher-coverage policies are also checked. This is a numerical frontier for the existing PMT policy family, conditional on the model and survey. External uncertainty and alternative targeting rules can be investigated separately.","",
              "The epsilon method supplies efficient policy alternatives for explicit poverty-gap tolerances. Selecting one alternative requires a substantive tolerance or coverage preference. The equations alone do not assign that policy preference.","",
              "![Pareto frontier and epsilon-constraint solutions](../figures/PMT_epsilon_pareto.png)","",
              "Method reference: Mavrotas, G. (2009). Effective implementation of the epsilon-constraint method in Multi-Objective Mathematical Programming problems. Applied Mathematics and Computation, 213(2), 455-465. https://doi.org/10.1016/j.amc.2009.03.037",""]
    (cm.OUT/"reports/PMT_epsilon_constraint.md").write_text("\n".join(lines),encoding="utf-8")
    print(result[["scenario_kind","epsilon_pp","coverage_pct","recipients_million","fgt1_pct","annual_cash_per_recipient_sam_tl","target_reached_pct","maximum_reduction_retained_pct"]].to_string(index=False),flush=True)
    print(f"COMPLETE: {len(new_rows)} policy equilibria; {time.time()-started:.1f}s",flush=True)


if __name__=="__main__":main()
