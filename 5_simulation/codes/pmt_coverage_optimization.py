"""Numerical search for the FGT1-minimising PMT coverage at equal net cost.

Keeps the existing PMT ranking, poverty line, shock and fiscal assumptions.
Every evaluated coverage receives a newly solved CGE equilibrium. Original
analysis outputs and manuscripts are preserved. Run with Python 3.14.
"""
import os
for key in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(key, "1")

import json
import time
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import pandas as pd
import pyomo.environ as pyo
from scipy.optimize import minimize_scalar
import common as cm
import micro_simulation as ms
import policy_model as pm
from validate_results import verify_source


def main():
    start = time.time()
    historical = json.loads((cm.OUT / "diagnostics/run_manifest.json").read_text(encoding="utf-8"))
    for rel, expected in historical["source_hashes"].items():
        verify_source(cm.PROJECT / rel, expected)
    sources = {rel: cm.sha(cm.PROJECT / rel) for rel in historical["source_hashes"]}
    sources[str(Path(__file__).resolve().relative_to(cm.PROJECT))] = cm.sha(Path(__file__))
    protected = [
        cm.OUT / "diagnostics/run_manifest.json", cm.OUT / "diagnostics/micro_calibration.json",
        cm.OUT / "diagnostics/pmt_design.json", cm.OUT / "diagnostics/equilibrium_checks.json",
        cm.OUT / "equilibria/main_equilibria.json",
        cm.OUT / "diagnostics/pmt_coverage_sensitivity.json",
        cm.OUT / "tables/PMT_coverage_sensitivity.csv",
        *sorted((cm.OUT / "tables/main").glob("*.csv")),
        *sorted((cm.OUT / "tables/supplementary").glob("*.xlsx")),
    ]
    protected_hashes = {str(p.relative_to(cm.ROOT)): cm.sha(p) for p in protected}
    cfg = cm.configurations()["main"]
    print("Preparing unchanged benchmark, microdata bridge and out-of-fold PMT", flush=True)
    base = pm.build(cfg)
    base_diag = cm.cge.solve_model(base)
    captured = {}
    original_dump = ms.dump
    try:
        ms.dump = lambda path, obj: captured.update({path.name: obj})
        micro, h, f = ms.prepare_micro(base)
        original_mask, scores, _, pmt_report = ms.fit_pmt(micro, h, f)
    finally:
        ms.dump = original_dump
    del h, f
    shock = pm.shock_model(base, cfg)
    budget = pm.gdp(base) * cfg["budget"]
    pop = float(micro["pw"].sum())
    order = np.argsort(scores, kind="stable")
    boundaries = np.cumsum(micro["pw"][order]) / pop
    target = micro["group"] < 2
    target_share = float(micro["pw"][target].sum() / pop)
    originals = pd.read_csv(cm.OUT / "tables/main/Table1_main_policy_results.csv").set_index("policy")
    cache, records, checks, group_rows = {}, [], [], []
    checks.append(dict(label="baseline", **base_diag, max_sam_account_gap_trillion_tl=pm.check_policy_sam(base)))
    checks.append(dict(label="shock", **cm.cge.diagnostics(shock), max_sam_account_gap_trillion_tl=pm.check_policy_sam(shock)))
    shock_values, _, _ = ms.household_outcomes(pm.snapshot(shock, base), micro, np.zeros(len(scores)))
    assert abs(shock_values["fgt1_pct"] - originals.loc["shock", "fgt1_pct"]) < 1e-8
    curve_path = cm.OUT / "tables/PMT_coverage_optimization_curve.csv"

    def evaluate(q, stage="search"):
        q = float(q)
        if q in cache:
            return cache[q]
        assert 0 < q <= 1
        mask = ms.exact_mask(micro["pw"], order, q * pop)
        shares = ms.group_shares(micro, mask)
        model, diagnostics = pm.policy_model(shock, cfg, "cash", shares, budget)
        diagnostics["max_sam_account_gap_trillion_tl"] = pm.check_policy_sam(model)
        checks.append(dict(coverage_pct=100*q, stage=stage, **diagnostics))
        state = pm.snapshot(model, base, shares=shares, cash_saving=cfg["cash_saving"], reference_sg=pyo.value(shock.Sg))
        values, groups, contribution = ms.household_outcomes(state, micro, mask)
        errors = ms.errors(micro, mask)
        assert values["negative_income_households"] == 0
        assert abs(errors["coverage"]-q) < 1e-12
        assert diagnostics["equal_net_cost_relative_gap"] < 1e-8
        row = dict(coverage_pct=100*q, stage=stage, recipients_million=q*pop/1e6,
                   target_reached_pct=100*(1-errors["exclusion"]),
                   exclusion_pct=100*errors["exclusion"], leakage_pct=100*errors["leakage"],
                   annual_cash_per_recipient_sam_tl=state["net_cash"]*1e12/(q*pop),
                   net_cash_billion_tl=state["net_cash"]*1000,
                   net_fiscal_cost_billion_tl=state["macro"]["net_fiscal_cost_trillion_tl"]*1000,
                   net_cost_gdp_pct=state["macro"]["net_cost_gdp_pct"], **values)
        records.append(row)
        group_rows.extend(dict(coverage_pct=100*q, **x) for x in groups)
        cache[q] = dict(row=row, state=state, contribution=contribution)
        if len(records) % 10 == 0:
            frame = pd.DataFrame(records).sort_values("coverage_pct")
            frame.to_csv(curve_path, index=False, encoding="utf-8-sig", float_format="%.12g")
            best = frame.loc[frame.fgt1_pct.idxmin()]
            print(f"{stage}: {len(records)} policies solved; current best {best.coverage_pct:.6f}% -> FGT1 {best.fgt1_pct:.8f}; elapsed {time.time()-start:.0f}s", flush=True)
        return cache[q]

    # Original PMT uses complete-household quintiles, approximately 39.99028%.
    check = evaluate(target_share, "replication")["row"]
    for metric in ("fgt0_pct", "fgt1_pct", "fgt2_pct", "bottom40_ev_pct"):
        assert abs(check[metric] - originals.loc["pmt", metric]) < 1e-8
    check = evaluate(1., "replication")["row"]
    assert abs(check["fgt1_pct"]-originals.loc["universal_cash", "fgt1_pct"]) < 1e-8

    print("Global coarse scan: 1-100% in one-percentage-point steps, plus lower-edge checks", flush=True)
    coarse = sorted(set([1e-6, .0001, .001, .002, .005] + [i/100 for i in range(1, 101)]))
    for q in coarse:
        evaluate(q, "global_1pp")
    coarse_y = np.array([cache[q]["row"]["fgt1_pct"] for q in coarse])
    minima = [i for i in range(1, len(coarse)-1) if coarse_y[i] <= coarse_y[i-1] and coarse_y[i] <= coarse_y[i+1]]
    assert minima, "No interior coarse-grid minimum; extend the boundary investigation."
    # Refine every local coarse minimum, including any distant alternatives.
    fine_windows = [(coarse[i-1], coarse[i+1]) for i in minima]
    print(f"Refining {len(fine_windows)} coarse local minima at 0.1-percentage-point resolution", flush=True)
    for lo, hi in fine_windows:
        for q in np.linspace(lo, hi, max(3, int(np.ceil((hi-lo)/.001))+1)):
            evaluate(float(q), "fine_0.1pp")

    # Inspect all actual PMT-ranked household boundaries near the best result.
    # This addresses the kinks caused by discrete households and split weights.
    best_q = min(cache, key=lambda q: cache[q]["row"]["fgt1_pct"])
    lo, hi = max(1e-6, best_q-.003), min(1., best_q+.003)
    near = [float(q) for q in boundaries if lo <= q <= hi]
    near = sorted(set([lo, hi, best_q, *near]))
    print(f"Checking {len(near)} household boundaries in {100*lo:.4f}-{100*hi:.4f}% coverage", flush=True)
    for q in near:
        evaluate(q, "household_boundaries")
    # Check all interval midpoints, then optimise the six most promising intervals.
    intervals = []
    for a, b in zip(near[:-1], near[1:]):
        mid = (a+b)/2
        ev = evaluate(mid, "boundary_midpoints")
        intervals.append((min(cache[a]["row"]["fgt1_pct"], cache[b]["row"]["fgt1_pct"], ev["row"]["fgt1_pct"]), a, b))
    optimisation = []
    for _, a, b in sorted(intervals)[:6]:
        res = minimize_scalar(lambda q: evaluate(float(q), "bounded_refinement")["row"]["fgt1_pct"],
                              bounds=(a, b), method="bounded", options={"xatol":1e-7, "maxiter":50})
        optimisation.append(dict(lower=a, upper=b, x=float(res.x), fun=float(res.fun), success=bool(res.success)))
        assert res.success
    best_q = min(cache, key=lambda q: cache[q]["row"]["fgt1_pct"])
    # Useful interpretable reference policies, all re-solved in this run.
    comparisons = [best_q, .05, .1, .15, .2, .3, .4, .5, .6, 1.]
    for q in comparisons:
        evaluate(q, "comparison")
    best_q = min(cache, key=lambda q: cache[q]["row"]["fgt1_pct"])
    best = cache[best_q]
    selected = {"optimum":best["contribution"], "pmt_20":cache[.2]["contribution"],
                "pmt_40":cache[.4]["contribution"], "universal_cash":cache[1.]["contribution"]}
    paired = ms.paired_intervals(selected, micro, [("optimum", "pmt_20"), ("optimum", "pmt_40"), ("optimum", "universal_cash")])
    frame = pd.DataFrame(records).sort_values("coverage_pct").reset_index(drop=True)
    frame["fgt1_regret_pp"] = frame.fgt1_pct - best["row"]["fgt1_pct"]
    assert np.isfinite(frame.select_dtypes("number").to_numpy()).all()
    frame.to_csv(curve_path, index=False, encoding="utf-8-sig", float_format="%.12g")

    print("Conditional re-optimisation across evaluated policies: 1,000 household multiplier draws", flush=True)
    ordered_q = sorted(cache)
    contributions = np.stack([cache[q]["contribution"] for q in ordered_q], axis=1)
    rng = np.random.default_rng(cm.SEED)
    boot_q, boot_y = [], []
    for _ in range(10):
        weights = rng.exponential(size=(100,len(scores)))*micro["pw"]
        draws = (weights@contributions)/weights.sum(axis=1)[:,None]
        best_index = np.argmin(draws, axis=1)
        boot_q.extend(np.array(ordered_q)[best_index]*100)
        boot_y.extend(draws[np.arange(100),best_index])
    bootstrap = dict(replications=1000, lower_coverage_pct=float(np.quantile(boot_q,.025)),
                     median_coverage_pct=float(np.median(boot_q)), upper_coverage_pct=float(np.quantile(boot_q,.975)),
                     description="Conditional re-optimisation over all evaluated coverages; fitted PMT, equilibria, payments and poverty line are fixed. No PMT re-fitting or design-based population inference.")
    band = frame[frame.fgt1_regret_pp <= .01]
    near_optimal = dict(tolerance_fgt1_pp=.01, evaluated_coverage_min_pct=float(band.coverage_pct.min()),
                        evaluated_coverage_max_pct=float(band.coverage_pct.max()))
    comparison_frame = pd.DataFrame([dict(label="FGT1 optimum" if q==best_q else f"PMT {100*q:g}%", **cache[q]["row"]) for q in sorted(set([best_q,*comparisons]))])
    comparison_frame.to_csv(cm.OUT/"tables/PMT_coverage_optimization_comparison.csv",index=False,encoding="utf-8-sig",float_format="%.12g")
    pd.DataFrame(paired).to_csv(cm.OUT/"tables/PMT_coverage_optimization_intervals.csv",index=False,encoding="utf-8-sig",float_format="%.12g")
    pd.DataFrame(group_rows).to_csv(cm.OUT/"tables/PMT_coverage_optimization_quintiles.csv",index=False,encoding="utf-8-sig",float_format="%.12g")
    cm.dump(cm.OUT/"equilibria/pmt_coverage_optimum.json",dict(coverage=best_q,**best["state"]))

    for rel, before in protected_hashes.items():
        assert cm.sha(cm.ROOT/rel)==before, rel
    for rel, before in sources.items():
        assert cm.sha(cm.PROJECT/rel)==before, rel
    audit = dict(status="complete",utc_time=datetime.now(timezone.utc).isoformat(),elapsed_seconds=time.time()-start,
                 objective="Minimise population FGT1 over a threshold in the existing out-of-fold PMT ranking, at the main equal-net-cost fiscal constraint.",
                 config=cfg,original_target_share=target_share,net_budget_billion_tl=1000*budget,
                 optimum=best["row"],evaluated_policies=len(records),checked_equilibria=len(checks),
                 coarse_local_minima_pct=[100*coarse[i] for i in minima],fine_windows=fine_windows,
                 bounded_optimisation=optimisation,near_optimal_evaluated_band=near_optimal,
                 bootstrap=bootstrap,paired_intervals=paired,checks=checks,pmt_design=pmt_report,
                 original_outputs_unchanged=True,protected_output_hashes=protected_hashes,source_hashes=sources,
                 interpretation="A numerically refined minimum from the stated global-grid and household-boundary search, conditional on the survey and model. The search is not a mathematical certificate over every possible continuous coverage or every targeting method.")
    cm.dump(cm.OUT/"diagnostics/pmt_coverage_optimization.json",audit)

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.family":"DejaVu Sans","font.size":9,"axes.spines.top":False,"axes.spines.right":False})
    fig,(a,b)=plt.subplots(1,2,figsize=(10,3.6),layout="constrained")
    global_frame=frame[frame.stage.isin(["global_1pp","replication","comparison"])]
    a.plot(global_frame.coverage_pct,global_frame.fgt1_pct,color="#2476a8",lw=1.8)
    a.scatter([100*best_q],[best["row"]["fgt1_pct"]],color="#c34855",zorder=5)
    a.axhline(cache[.4]["row"]["fgt1_pct"],color="#777777",ls="--",lw=.8,label="40% coverage reference")
    a.set(xlabel="Population receiving cash (%)",ylabel="Poverty gap, FGT1 (%)",title="a   Equal-net-cost coverage frontier")
    a.legend(frameon=False,fontsize=8)
    zoom=frame[(frame.coverage_pct>=100*lo)&(frame.coverage_pct<=100*hi)]
    b.plot(zoom.coverage_pct,zoom.fgt1_pct,color="#2476a8",lw=1.2,marker=".",ms=3)
    b.scatter([100*best_q],[best["row"]["fgt1_pct"]],color="#c34855",zorder=5,label=f"Minimum: {100*best_q:.2f}% coverage")
    b.set(xlabel="Population receiving cash (%)",ylabel="Poverty gap, FGT1 (%)",title="b   Refined search near the minimum")
    b.legend(frameon=False,fontsize=8)
    for ax in (a,b):ax.grid(alpha=.18)
    for ext in ("png","pdf"):
        fig.savefig(cm.OUT/f"figures/PMT_coverage_optimization.{ext}",dpi=300,bbox_inches="tight")
    plt.close(fig)

    lines=["# PMT coverage optimisation","",
           "The objective is to minimise the population poverty gap (FGT1) by varying the PMT eligibility threshold. The fitted out-of-fold PMT ranking, fixed real poverty line, food and energy import-price shock, 3% administrative share and 0.5%-of-GDP net fiscal cost are retained. Each evaluated policy is solved as a new general equilibrium, followed by household microsimulation.","",
           f"The numerically refined minimum occurs at **{100*best_q:.4f}% population coverage**, with **FGT1 = {best['row']['fgt1_pct']:.6f}%**. Annual cash is **{best['row']['annual_cash_per_recipient_sam_tl']:.2f} TL per recipient**, in the SAM macro calibration scale. The net fiscal cost is {1000*budget:.6f} billion TL.","",
           "| Population coverage (%) | FGT0 (%) | FGT1 (%) | FGT2 (%) | Target reached (%) | Exclusion (%) | Leakage (%) | Annual cash per recipient (SAM TL) |",
           "|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for r in comparison_frame.to_dict(orient="records"):
        lines.append(f"| {r['coverage_pct']:.4f} | {r['fgt0_pct']:.4f} | {r['fgt1_pct']:.6f} | {r['fgt2_pct']:.4f} | {r['target_reached_pct']:.2f} | {r['exclusion_pct']:.2f} | {r['leakage_pct']:.2f} | {r['annual_cash_per_recipient_sam_tl']:.2f} |")
    lines += ["", "The target used for error rates remains the original bottom two income quintiles. Consequently, exclusion rises as coverage narrows; minimising FGT1 and maximising target coverage are distinct objectives. All transfers are equal per recipient person and fractional boundary weights retain the existing full-payment convention.","",
              f"The search evaluated {len(records)} policies: a 1-percentage-point scan across 1-100%, lower-edge checks, refinement of every coarse local minimum at 0.1-percentage-point resolution, all household boundaries and interval midpoints near the best candidate, and bounded within-interval optimisation. The reported point is a numerical optimum conditional on this model and search; its decimal precision describes numerical localisation, not empirical certainty.","",
              f"Among evaluated coverages, FGT1 within 0.01 percentage points of the minimum occurs between {near_optimal['evaluated_coverage_min_pct']:.4f}% and {near_optimal['evaluated_coverage_max_pct']:.4f}%. These endpoints describe evaluated candidates rather than exact continuous level-set boundaries.","",
              f"Conditional re-optimisation over evaluated policies using 1,000 household multiplier draws gives a central 95% coverage range of [{bootstrap['lower_coverage_pct']:.4f}%, {bootstrap['upper_coverage_pct']:.4f}%]. PMT parameters, equilibrium responses, policy amounts and the poverty line remain fixed. This range excludes model and parameter uncertainty and external validation.","",
              "Paired conditional FGT1 differences (percentage points):",""]
    for r in paired:
        lines.append(f"- Optimum minus {r['policy_b']}: {r['difference_pp']:+.6f}, 95% interval [{r['lower95_pp']:+.6f}, {r['upper95_pp']:+.6f}].")
    lines += ["",f"All {len(checks)} equilibrium solutions pass the existing optimal-termination, accounting, market, household-budget, fiscal-cost and SAM checks. Original PMT and universal-cash outcomes reproduce the main analysis. Original manuscripts and outputs are unchanged.","",
              "![Coverage frontier](../figures/PMT_coverage_optimization.png)",""]
    (cm.OUT/"reports/PMT_coverage_optimization.md").write_text("\n".join(lines),encoding="utf-8")
    print("OPTIMUM",json.dumps(best["row"],ensure_ascii=False),flush=True)
    print("CONDITIONAL COVERAGE RANGE",bootstrap,flush=True)
    print(f"COMPLETE: {len(records)} policy equilibria, {time.time()-start:.1f}s",flush=True)


if __name__=="__main__":
    main()
