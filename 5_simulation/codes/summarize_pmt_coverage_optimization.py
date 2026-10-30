"""Consolidate the broad search and independent competing-minimum validation."""
from pathlib import Path
import json
import numpy as np
import pandas as pd
import common as cm


def main():
    first=json.loads((cm.OUT/"diagnostics/pmt_coverage_optimization.json").read_text(encoding="utf-8"))
    second=json.loads((cm.OUT/"diagnostics/pmt_coverage_competing_minima.json").read_text(encoding="utf-8"))
    assert first["status"]==second["status"]=="complete"
    for rel,expected in first["protected_output_hashes"].items():
        assert cm.sha(cm.ROOT/rel)==expected,rel
    for rel,expected in first["source_hashes"].items():
        assert cm.sha(cm.PROJECT/rel)==expected,rel
    assert cm.sha(cm.ROOT/"codes/pmt_coverage_competing_minima.py")==second["source_sha256"]
    winner=second if second["optimum"]["fgt1_pct"]<first["optimum"]["fgt1_pct"] else first
    best=winner["optimum"]
    parts=[pd.read_csv(cm.OUT/"tables/PMT_coverage_optimization_curve.csv"),pd.read_csv(cm.OUT/"tables/PMT_coverage_competing_minima.csv")]
    common_cols=[x for x in parts[0].columns if x in parts[1].columns]
    curve=pd.concat([x[common_cols] for x in parts],ignore_index=True).sort_values("coverage_pct")
    curve=curve.drop_duplicates("coverage_pct").reset_index(drop=True)
    curve["fgt1_regret_pp"]=curve.fgt1_pct-best["fgt1_pct"]
    assert curve.fgt1_regret_pp.min()>-1e-9
    curve.to_csv(cm.OUT/"tables/PMT_coverage_optimization_final_curve.csv",index=False,encoding="utf-8-sig",float_format="%.12g")
    choices=[best]
    for q in [2,4,5,10,20,30,40,50,60,100]:
        r=curve.loc[(curve.coverage_pct-q).abs().idxmin()]
        assert abs(r.coverage_pct-q)<1e-7
        choices.append(r.to_dict())
    cols=["coverage_pct","recipients_million","annual_cash_per_recipient_sam_tl","fgt0_pct","fgt1_pct","fgt2_pct", "target_reached_pct","exclusion_pct","leakage_pct","bottom40_loser_pct"]
    comparison=pd.DataFrame(choices)[cols].sort_values("coverage_pct")
    comparison.to_csv(cm.OUT/"tables/PMT_coverage_optimization_final_comparison.csv",index=False,encoding="utf-8-sig",float_format="%.12g")
    intervals=winner["paired_intervals"]
    checks=first["checks"]+second["checks"]
    check_keys=["max_scaled_equation_residual","max_relative_goods_gap","household_budget_relative_gap", "gdp_identity_relative_gap","max_sam_account_gap_trillion_tl"]
    maxima={k:max(r[k] for r in checks) for k in check_keys}
    assert max(maxima.values())<1e-8
    max_fiscal=max(r.get("equal_net_cost_relative_gap",0) for r in checks)
    assert max_fiscal<1e-8
    near=curve[curve.fgt1_regret_pp<=.01]
    state_path=cm.OUT/("equilibria/pmt_coverage_validated_optimum.json" if winner is second else "equilibria/pmt_coverage_optimum.json")
    state=json.loads(state_path.read_text(encoding="utf-8"))
    cm.dump(cm.OUT/"equilibria/pmt_coverage_optimum_final.json",state)
    final=dict(status="complete",optimum=best,objective=first["objective"],config=first["config"],
               evaluated_policy_count=len(first["checks"])-2+len(second["checks"]),checked_equilibria=len(checks),
               unique_evaluated_coverages=len(curve),max_checks=maxima,max_fiscal_relative_gap=max_fiscal,
               paired_intervals=intervals,near_optimal_evaluated_range_pct=[float(near.coverage_pct.min()),float(near.coverage_pct.max())],
               near_optimal_tolerance_fgt1_pp=.01,original_outputs_unchanged=True,
               initial_candidate=first["optimum"],secondary_refinement=second["method"],
               source_audits=["pmt_coverage_optimization.json","pmt_coverage_competing_minima.json"],
               summarizer_sha256=cm.sha(Path(__file__)),
               interpretation="Numerically located minimum for the existing PMT score and equal per-person transfer, conditional on the stated shock, budget, model and microdata. Original target coverage is an additional policy outcome. No mathematical global certificate or external validation is claimed.")
    cm.dump(cm.OUT/"diagnostics/pmt_coverage_optimization_final.json",final)

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.family":"DejaVu Sans","font.size":9,"axes.spines.top":False,"axes.spines.right":False})
    fig,(a,b)=plt.subplots(1,2,figsize=(10,3.5),layout="constrained")
    qbest=best["coverage_pct"];ybest=best["fgt1_pct"]
    a.plot(curve.coverage_pct,curve.fgt1_pct,color="#2476a8",lw=1.5)
    a.scatter([qbest],[ybest],color="#c34855",zorder=5)
    ref40=float(comparison.loc[np.isclose(comparison.coverage_pct,40),"fgt1_pct"].iloc[0])
    a.axhline(ref40,color="#777777",ls="--",lw=.8,label="40% coverage reference")
    a.set(xlabel="Population receiving cash (%)",ylabel="Poverty gap, FGT1 (%)",title="a   Equal-net-cost coverage frontier")
    a.legend(frameon=False,fontsize=8)
    zoom=curve[(curve.coverage_pct>=3)&(curve.coverage_pct<=6)]
    b.plot(zoom.coverage_pct,zoom.fgt1_pct,color="#2476a8",lw=1.1)
    b.scatter([qbest],[ybest],color="#c34855",zorder=5,label=f"Minimum: {qbest:.2f}% coverage")
    b.axvline(qbest,color="#c34855",ls=":",lw=.8)
    b.set(xlabel="Population receiving cash (%)",ylabel="Poverty gap, FGT1 (%)",title="b   Household-boundary refinement")
    b.legend(frameon=False,fontsize=8)
    for ax in (a,b):ax.grid(alpha=.18)
    for ext in ("png","pdf"):
        fig.savefig(cm.OUT/f"figures/PMT_coverage_optimization_final.{ext}",dpi=300,bbox_inches="tight")
    plt.close(fig)
    lines=["# PMT coverage optimisation: validated result","",
           f"The numerical FGT1 minimum occurs at **{qbest:.4f}% population coverage** (approximately **{qbest:.1f}%**), with a poverty gap of **{ybest:.6f}%**. The main shock, out-of-fold PMT ranking, equal per-person transfers, fixed real poverty line, 3% administrative share and net fiscal budget of 0.5% of benchmark GDP are held constant. Each evaluated policy is solved as a new CGE equilibrium before microsimulation.","",
           f"The policy reaches {best['recipients_million']:.4f} million persons. Annual cash per recipient is {best['annual_cash_per_recipient_sam_tl']:.2f} TL in the SAM macro calibration scale. Net fiscal cost is {best['net_fiscal_cost_billion_tl']:.6f} billion TL.","",
           "| Population coverage (%) | Annual cash per person (SAM TL) | FGT0 (%) | FGT1 (%) | FGT2 (%) | Original target reached (%) | Exclusion (%) | Leakage (%) |",
           "|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for r in comparison.to_dict(orient="records"):
        lines.append(f"| {r['coverage_pct']:.4f} | {r['annual_cash_per_recipient_sam_tl']:.2f} | {r['fgt0_pct']:.4f} | {r['fgt1_pct']:.6f} | {r['fgt2_pct']:.4f} | {r['target_reached_pct']:.2f} | {r['exclusion_pct']:.2f} | {r['leakage_pct']:.2f} |")
    lines += ["",f"The original target remains the bottom two income quintiles. At the optimum, {best['target_reached_pct']:.2f}% of this target receives cash and {best['exclusion_pct']:.2f}% is excluded. Leakage among recipients is {best['leakage_pct']:.2f}%. The result expresses the trade-off between payment size and population coverage under the FGT1 objective. A minimum target-coverage constraint or an alternative objective such as FGT0 changes the policy problem.","",
              "At very narrow coverage, large payments can exceed recipients' poverty gaps while many other poor households receive no payment. Expanding coverage initially improves FGT1. Beyond the numerical minimum, the reduction in payment per recipient and changes in recipient composition outweigh the additional reach in the evaluated configurations.","",
              f"The initial refined candidate was {first['optimum']['coverage_pct']:.6f}%. An independent examination of competitive secondary fine-grid minima located the final result above. The two stages checked {len(checks)} equilibria and {len(curve)} distinct positive coverage values, using a broad 1-100% scan, lower-edge checks, fine grids, actual household-entry boundaries, interval midpoints and bounded local refinements. All model and fiscal checks pass. Original analyses and manuscripts are unchanged.","",
              f"Evaluated policies within 0.01 FGT1 percentage points of the minimum range from {near.coverage_pct.min():.4f}% to {near.coverage_pct.max():.4f}% coverage. This describes the envelope of evaluated near-optimal candidates; individual points inside the envelope may have larger regret. The reported decimal places locate the sample-model minimum and do not establish a precise population-optimal threshold.","",
              "Paired conditional differences in FGT1 (percentage points):",""]
    for r in intervals:
        lines.append(f"- Minimum minus {r['policy_b']}: {r['difference_pp']:+.6f}; conditional 95% interval [{r['lower95_pp']:+.6f}, {r['upper95_pp']:+.6f}].")
    lines += ["","Intervals use 1,000 paired household exponential-multiplier draws and hold the fitted PMT, equilibria, payment amounts and poverty line fixed. They are conditional comparisons of the selected policies. Policy thresholds were selected using the same survey; external or nested validation would assess their portability. The numerical search does not provide an analytic global-optimality certificate over all continuous thresholds or all targeting methods.","",
              "![Validated coverage frontier](../figures/PMT_coverage_optimization_final.png)",""]
    (cm.OUT/"reports/PMT_coverage_optimization_final.md").write_text("\n".join(lines),encoding="utf-8")
    print(json.dumps(final,ensure_ascii=False,indent=2))


if __name__=="__main__":main()
