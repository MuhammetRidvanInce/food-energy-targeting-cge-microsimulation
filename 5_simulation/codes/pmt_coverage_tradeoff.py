"""Quantify the poverty-gap opportunity cost of expanding PMT coverage.

Post-processes the previously solved equal-net-cost equilibria. No new model
approximation or CGE solve is used. Main manuscript and analysis are unchanged.
"""
from datetime import datetime, timezone
from pathlib import Path
import json
import numpy as np
import pandas as pd
import common as cm


def main():
    paths={
        "optimum_audit":cm.OUT/"diagnostics/pmt_coverage_optimization_final.json",
        "solved_curve":cm.OUT/"tables/PMT_coverage_optimization_final_curve.csv",
        "main_results":cm.OUT/"tables/main/Table1_main_policy_results.csv",
        "first_search_audit":cm.OUT/"diagnostics/pmt_coverage_optimization.json",
        "secondary_search_audit":cm.OUT/"diagnostics/pmt_coverage_competing_minima.json",
    }
    input_hashes={str(p.relative_to(cm.ROOT)):cm.sha(p) for p in paths.values()}
    audit=json.loads(paths["optimum_audit"].read_text(encoding="utf-8"))
    first=json.loads(paths["first_search_audit"].read_text(encoding="utf-8"))
    assert audit["status"]==first["status"]=="complete"
    for relative,expected in first["protected_output_hashes"].items():
        assert cm.sha(cm.ROOT/relative)==expected,relative
    for relative,expected in first["source_hashes"].items():
        assert cm.sha(cm.PROJECT/relative)==expected,relative
    source=pd.read_csv(paths["solved_curve"])
    main_results=pd.read_csv(paths["main_results"]).set_index("policy")
    best=audit["optimum"]
    cstar=float(best["coverage_pct"])
    gstar=float(best["fgt1_pct"])
    population_million=best["recipients_million"]*100/cstar
    shock=float(main_results.loc["shock","fgt1_pct"])
    max_reduction=shock-gstar
    assert max_reduction>0

    # Use the unrounded audit value for the reference point. CSV values retain
    # twelve significant digits and are adequate for the remaining comparisons.
    curve=source.loc[source.coverage_pct>cstar+1e-8].copy()
    curve=pd.concat([pd.DataFrame([best]),curve],ignore_index=True).sort_values("coverage_pct")

    def enrich(frame):
        f=frame.copy()
        f["additional_coverage_pp"]=f.coverage_pct-cstar
        f["additional_recipients_million"]=population_million*f.additional_coverage_pp/100
        f["fgt1_cost_pp"]=f.fgt1_pct-gstar
        f["relative_gap_increase_pct"]=100*f.fgt1_cost_pp/gstar
        f["poverty_reduction_vs_shock_pp"]=shock-f.fgt1_pct
        f["maximum_poverty_reduction_forgone_pct"]=100*f.fgt1_cost_pp/max_reduction
        f["maximum_poverty_reduction_retained_pct"]=100*f.poverty_reduction_vs_shock_pp/max_reduction
        f["average_cost_pp_per_extra_million"]=np.divide(
            f.fgt1_cost_pp.to_numpy(),f.additional_recipients_million.to_numpy(),
            out=np.full(len(f),np.nan),where=f.additional_recipients_million.to_numpy()>1e-8)
        assert f.fgt1_cost_pp.min()>-1e-9
        assert np.allclose(f.maximum_poverty_reduction_forgone_pct+f.maximum_poverty_reduction_retained_pct,100,atol=1e-9)
        assert np.allclose(f.recipients_million-best["recipients_million"],f.additional_recipients_million,atol=1e-8)
        return f

    curve=enrich(curve)
    selected=[best]
    for coverage in [5,10,20,30,40,50,60,80,100]:
        row=source.iloc[(source.coverage_pct-coverage).abs().argmin()]
        assert abs(row.coverage_pct-coverage)<1e-8
        selected.append(row.to_dict())
    table=enrich(pd.DataFrame(selected)).sort_values("coverage_pct").reset_index(drop=True)
    intervals=[]
    for i in range(1,len(table)):
        a,b=table.iloc[i-1],table.iloc[i]
        dg=b.fgt1_pct-a.fgt1_pct
        dc=b.coverage_pct-a.coverage_pct
        dn=population_million*dc/100
        intervals.append(dict(from_coverage_pct=a.coverage_pct,to_coverage_pct=b.coverage_pct,
                              additional_coverage_pp=dc,additional_recipients_million=dn,
                              incremental_fgt1_cost_pp=dg,
                              fgt1_pp_per_coverage_pp=dg/dc,
                              fgt1_pp_per_additional_million=dg/dn))
    marginal=pd.DataFrame(intervals)
    assert np.isclose(marginal.incremental_fgt1_cost_pp.sum(),table.iloc[-1].fgt1_cost_pp,atol=1e-10)
    assert np.isclose(marginal.additional_recipients_million.sum(),table.iloc[-1].additional_recipients_million,atol=1e-8)
    assert np.allclose(marginal.fgt1_pp_per_additional_million,
                       marginal.fgt1_pp_per_coverage_pp*100/population_million,atol=1e-12)
    assert np.ptp(table.net_fiscal_cost_billion_tl)<1e-6
    conditional=[]
    for row in audit["paired_intervals"]:
        if row["policy_b"] in ("pmt_20","pmt_40","universal_cash"):
            conditional.append(dict(coverage_pct={"pmt_20":20,"pmt_40":40,"universal_cash":100}[row["policy_b"]],
                                    fgt1_cost_pp=-row["difference_pp"],lower95_pp=-row["upper95_pp"],upper95_pp=-row["lower95_pp"]))
    for row in conditional:
        r=table.loc[np.isclose(table.coverage_pct,row["coverage_pct"])].iloc[0]
        assert abs(r.fgt1_cost_pp-row["fgt1_cost_pp"])<1e-8

    columns=["coverage_pct","recipients_million","additional_coverage_pp","additional_recipients_million",
             "fgt1_pct","fgt1_cost_pp","relative_gap_increase_pct","poverty_reduction_vs_shock_pp",
             "maximum_poverty_reduction_forgone_pct","maximum_poverty_reduction_retained_pct",
             "average_cost_pp_per_extra_million","annual_cash_per_recipient_sam_tl","target_reached_pct",
             "net_fiscal_cost_billion_tl"]
    table[columns].to_csv(cm.OUT/"tables/PMT_coverage_tradeoff.csv",index=False,encoding="utf-8-sig",float_format="%.12g")
    curve[columns].to_csv(cm.OUT/"tables/PMT_coverage_tradeoff_curve.csv",index=False,encoding="utf-8-sig",float_format="%.12g")
    marginal.to_csv(cm.OUT/"tables/PMT_coverage_tradeoff_intervals.csv",index=False,encoding="utf-8-sig",float_format="%.12g")

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import MultipleLocator
    plt.rcParams.update({"font.family":"DejaVu Sans","font.size":10,"axes.spines.top":False,
                         "axes.spines.right":False,"axes.labelcolor":"#252b33","text.color":"#252b33",
                         "xtick.color":"#58616b","ytick.color":"#58616b","svg.fonttype":"none"})
    blue="#1b6b93";red="#bc4557"
    fig,(a,b)=plt.subplots(1,2,figsize=(12.2,4.65),gridspec_kw={"width_ratios":[1.08,1]},layout="constrained")
    a.plot(curve.coverage_pct,curve.fgt1_cost_pp,color=blue,lw=2.2,zorder=3)
    marks=table.loc[table.coverage_pct.isin([20,40,60,100])]
    a.scatter(marks.coverage_pct,marks.fgt1_cost_pp,s=25,color=blue,zorder=4)
    for _,r in marks.iterrows():
        last=r.coverage_pct==100
        a.annotate(f"{r.fgt1_cost_pp:.3f} pp",(r.coverage_pct,r.fgt1_cost_pp),
                   xytext=(-8 if last else 6,8),textcoords="offset points",ha="right" if last else "left",fontsize=9,
                   bbox=dict(facecolor="white",edgecolor="none",alpha=.88,pad=.7))
    a.scatter([cstar],[0],s=42,color=red,zorder=5)
    a.annotate(f"Reference: {cstar:.2f}% coverage",(cstar,0),xytext=(10,13),textcoords="offset points",fontsize=9,color=red)
    a.set(xlim=(0,103),ylim=(-.045,1.17),xlabel="Population receiving cash (%)",
          ylabel="Increase in FGT1 from the minimum (pp)",title="a   Total poverty-gap cost of wider coverage")
    a.yaxis.set_major_locator(MultipleLocator(.2))
    a.grid(axis="y",color="#e3e7eb",lw=.7)
    a.set_axisbelow(True)
    right=a.secondary_yaxis("right",functions=(lambda z:100*z/max_reduction,lambda z:z*max_reduction/100))
    right.set_ylabel("Maximum poverty reduction forgone (%)",fontsize=9,labelpad=6)
    right.tick_params(labelsize=8)
    right.spines["right"].set_visible(False)
    labels=[f"{r.from_coverage_pct:.2f}" if i==0 else f"{r.from_coverage_pct:.0f}" for i,r in marginal.iterrows()]
    labels=[f"{low}\u2013{r.to_coverage_pct:.0f}" for low,(_,r) in zip(labels,marginal.iterrows())]
    x=np.arange(len(marginal))
    values=marginal.fgt1_pp_per_additional_million.to_numpy()
    b.bar(x,values,width=.68,color=blue,zorder=3)
    for xx,yy in zip(x,values):b.text(xx,yy+.001,f"{yy:.3f}",ha="center",va="bottom",fontsize=8)
    b.set(xticks=x,xticklabels=labels,ylim=(0,values.max()*1.22),xlabel="Coverage expansion interval (%)",
          ylabel="FGT1 increase per additional million people (pp)",
          title="b   Incremental cost per million recipients")
    b.tick_params(axis="x",rotation=40,labelsize=8)
    b.grid(axis="y",color="#e3e7eb",lw=.7);b.set_axisbelow(True)
    for ext in ("png","svg"):
        fig.savefig(cm.OUT/f"figures/PMT_coverage_tradeoff.{ext}",dpi=300,bbox_inches="tight")
    plt.close(fig)

    lines=["# Poverty-gap opportunity cost of expanding PMT coverage","",
           f"Reference: coverage c* = {cstar:.8f}% of population, FGT1 G* = {gstar:.8f}%, and {best['recipients_million']:.6f} million recipients. Population N = {population_million:.8f} million. All policies retain the main shock, fitted PMT ranking, equal per-recipient payment rule and the same net fiscal cost of {best['net_fiscal_cost_billion_tl']:.6f} billion TL.","",
           "Let c denote coverage in percentage points of total population and G(c) denote the FGT1 index expressed in percent. The cumulative opportunity cost of wider coverage is:","",
           r"$$L(c)=G(c)-G(c^*).$$","",
           "L is measured in FGT1 percentage points. The corresponding increase in recipients, in millions, is:","",
           r"$$\Delta N_m(c)=N_m\frac{c-c^*}{100}.$ $".replace("$ $","$$"),"",
           "The average cost from the reference and the incremental cost between two solved policies are different quantities:","",
           r"$$A(c)=\frac{L(c)}{\Delta N_m(c)},\qquad M(c_1,c_2)=\frac{G(c_2)-G(c_1)}{N_m(c_2-c_1)/100}.$ $".replace("$ $","$$"),"",
           "Both are measured in FGT1 percentage points per additional million recipients. M is a finite-interval slope. Household-entry kinks make these explicit finite differences preferable to assigning a smooth derivative to the entire empirical curve.","",
           f"The no-policy shock has FGT1 G_shock = {shock:.8f}%. The largest attained reduction relative to that shock is G_shock - G* = {max_reduction:.8f} percentage points. The share of this reduction forgone at coverage c is:","",
           r"$$S(c)=100\frac{G(c)-G(c^*)}{G_{\mathrm{shock}}-G(c^*)}.$ $".replace("$ $","$$"),"",
           "A separate quantity, 100 L(c)/G*, measures the percentage increase in the remaining poverty gap itself. These denominators answer different questions; the table below reports S(c), the share of the maximum shock-to-policy reduction forgone.","",
           "| Coverage (%) | Additional recipients (million) | FGT1 (%) | Cumulative FGT1 cost (pp) | Maximum reduction forgone (%) |",
           "|---:|---:|---:|---:|---:|"]
    for r in table.to_dict(orient="records"):
        lines.append(f"| {r['coverage_pct']:.2f} | {r['additional_recipients_million']:.3f} | {r['fgt1_pct']:.6f} | {r['fgt1_cost_pp']:.6f} | {r['maximum_poverty_reduction_forgone_pct']:.2f} |")
    lines += ["","For example, expanding coverage from the reference to 20% reaches 13.204 million additional people and increases FGT1 by 0.372155 percentage points, giving up 26.626% of the largest attained reduction relative to the no-policy shock. Expanding coverage to 40% reaches 30.029 million additional people, with a 0.662680-point cost and 47.411% of the reduction forgone.","",
              "| Coverage expansion (%) | Additional recipients (million) | Incremental FGT1 cost (pp) | FGT1 cost per coverage percentage point | FGT1 cost per additional million |",
              "|---|---:|---:|---:|---:|"]
    for i,r in marginal.iterrows():
        lines.append(f"| {r.from_coverage_pct:.2f} to {r.to_coverage_pct:.0f} | {r.additional_recipients_million:.3f} | {r.incremental_fgt1_cost_pp:.6f} | {r.fgt1_pp_per_coverage_pp:.6f} | {r.fgt1_pp_per_additional_million:.6f} |")
    lines += ["","The cumulative cost increases across the selected wider-coverage policies, while the finite-interval cost per additional million decreases across the displayed intervals. This distinction matters: later expansion has a lower additional poverty-gap cost even though its cumulative cost from the optimum is larger. Small reversals remain in the fully resolved household-level curve near the optimum; they are retained in the figure and data rather than removed by smoothing.","",
              "Selected conditional 95% intervals, obtained by reversing the signs and endpoints of the previously calculated paired optimum-minus-policy differences:",""]
    for r in conditional:
        lines.append(f"- Coverage {r['coverage_pct']}%: cost {r['fgt1_cost_pp']:.6f} pp; conditional interval [{r['lower95_pp']:.6f}, {r['upper95_pp']:.6f}].")
    lines += ["","Figure: panel (a) reports point estimates of cumulative FGT1 cost; its right axis expresses the same cost as a share of the largest attained poverty reduction. Panel (b) reports finite differences over the labelled coverage intervals. Both use previously solved equilibria. These are poverty-outcome trade-offs at an unchanged net fiscal budget; their units are FGT1 percentage points, not additional public expenditure.","",
              "![Poverty-gap cost of wider PMT coverage](../figures/PMT_coverage_tradeoff.png)",""]
    (cm.OUT/"reports/PMT_coverage_tradeoff.md").write_text("\n".join(lines),encoding="utf-8")
    for relative,expected in input_hashes.items():assert cm.sha(cm.ROOT/relative)==expected,relative
    cm.dump(cm.OUT/"diagnostics/pmt_coverage_tradeoff.json",dict(
        status="complete",utc_time=datetime.now(timezone.utc).isoformat(),model_rerun=False,
        reference_coverage_pct=cstar,reference_fgt1_pct=gstar,population_million=population_million,
        shock_fgt1_pct=shock,maximum_shock_to_policy_reduction_pp=max_reduction,
        net_fiscal_cost_billion_tl=best["net_fiscal_cost_billion_tl"],
        selected_policy_count=len(table),evaluated_curve_points=len(curve),finite_difference_intervals=len(marginal),
        conditional_intervals=conditional,input_hashes=input_hashes,source_sha256=cm.sha(Path(__file__)),
        original_outputs_unchanged=True,
        checks=["All original source/output hash contracts hold","Same net fiscal budget across selected policies",
                "Population increments match stored recipient counts","Incremental costs telescope to total cost",
                "Coverage and per-million slope conversions agree","Forgone and retained benefit shares sum to 100",
                "Conditional intervals agree with previous paired results"]
    ))
    print(table[["coverage_pct","additional_recipients_million","fgt1_pct","fgt1_cost_pp","maximum_poverty_reduction_forgone_pct"]].to_string(index=False))
    print(marginal.to_string(index=False))
    print("COMPLETE: arithmetic, source hashes and fiscal consistency verified.")


if __name__=="__main__":main()
