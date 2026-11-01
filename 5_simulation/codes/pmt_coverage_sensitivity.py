"""Re-solve PMT policies at 20, 30, 40, 50 and 60 percent population coverage.

Run: python -B codes/pmt_coverage_sensitivity.py
Uses the existing main shock, net fiscal budget, PMT score and micro bridge.
The existing bottom-two-quintile eligibility definition is held fixed when
reporting exclusion and leakage. No manuscript or original analysis is changed.
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

import common as cm
import micro_simulation as ms
import policy_model as pm
from validate_results import verify_source


def main():
    started = time.time()
    historical = json.loads((cm.OUT / "diagnostics/run_manifest.json").read_text(encoding="utf-8"))
    assert historical["status"] == "complete"
    for relative, expected in historical["source_hashes"].items():
        verify_source(cm.PROJECT / relative, expected)

    source_paths = [cm.PROJECT / relative for relative in historical["source_hashes"]]
    source_paths += [Path(__file__).resolve(), cm.ROOT / "codes/supplementary_catalog.py"]
    source_hashes = {str(path.relative_to(cm.PROJECT)): cm.sha(path) for path in source_paths}
    protected = [
        cm.OUT / "diagnostics/run_manifest.json",
        cm.OUT / "diagnostics/micro_calibration.json",
        cm.OUT / "diagnostics/pmt_design.json",
        cm.OUT / "diagnostics/equilibrium_checks.json",
        cm.OUT / "equilibria/main_equilibria.json",
        *sorted(p for p in (cm.OUT / "tables/main").glob("*.csv") if p.name.lower()!='table5.csv'),
        *sorted(p for p in (cm.OUT / "tables/supplementary").glob("S*.xlsx") if int(p.stem.split('_')[0][1:])<=13),
    ]
    protected_hashes = {str(p.relative_to(cm.ROOT)): cm.sha(p) for p in protected}
    published = pd.read_csv(cm.OUT / "tables/main/Table1_main_policy_results.csv").set_index("policy")
    cfg = cm.configurations()["main"]

    print("Solving benchmark and rebuilding the unchanged survey bridge", flush=True)
    base = pm.build(cfg)
    base_check = cm.cge.solve_model(base)
    checks = [dict(label="baseline", **base_check, max_sam_account_gap_trillion_tl=pm.check_policy_sam(base))]
    captured = {}
    original_dump = ms.dump
    try:
        # Existing preparation functions ordinarily write their main diagnostics.
        # Capture these diagnostics in memory for this separate experiment instead.
        ms.dump = lambda path, obj: captured.update({path.name: obj})
        micro, households, persons = ms.prepare_micro(base)
        original_mask, scores, _, pmt_report = ms.fit_pmt(micro, households, persons)
    finally:
        ms.dump = original_dump
    del households, persons

    population = float(micro["pw"].sum())
    target = micro["group"] < 2
    target_population = float(micro["pw"][target].sum())
    order = np.argsort(scores, kind="stable")
    baseline_state = pm.snapshot(base, base)
    baseline, _, _ = ms.household_outcomes(baseline_state, micro, np.zeros(len(scores)))
    shock = pm.shock_model(base, cfg)
    checks.append(dict(label="shock", **cm.cge.diagnostics(shock), max_sam_account_gap_trillion_tl=pm.check_policy_sam(shock)))
    shock_state = pm.snapshot(shock, base)
    shock_metrics, _, _ = ms.household_outcomes(shock_state, micro, np.zeros(len(scores)))
    for label, values in (("baseline", baseline), ("shock", shock_metrics)):
        for metric in ("fgt0_pct", "fgt1_pct", "fgt2_pct"):
            assert abs(values[metric] - published.loc[label, metric]) < 1e-8, (label, metric)

    budget = pm.gdp(base) * cfg["budget"]
    states, contributions, group_rows, rows = {}, {}, [], []

    def solve(label, mask):
        shares = ms.group_shares(micro, mask)
        model, diagnostics = pm.policy_model(shock, cfg, "cash", shares, budget)
        diagnostics["max_sam_account_gap_trillion_tl"] = pm.check_policy_sam(model)
        checks.append(dict(label=label, **diagnostics))
        state = pm.snapshot(model, base, shares=shares, cash_saving=cfg["cash_saving"], reference_sg=pyo.value(shock.Sg))
        values, groups, fgt1 = ms.household_outcomes(state, micro, mask)
        assert abs(state["macro"]["net_fiscal_cost_trillion_tl"] - budget) / budget < 1e-8
        assert values["negative_income_households"] == 0
        states[label] = state
        contributions[label] = fgt1
        group_rows.extend(dict(policy=label, **row) for row in groups)
        print(f"  {label}: FGT0={values['fgt0_pct']:.6f}; FGT1={values['fgt1_pct']:.6f}; FGT2={values['fgt2_pct']:.6f}", flush=True)
        return state, values

    print("Reproducing original PMT and universal-cash reference results", flush=True)
    _, original_metrics = solve("original_pmt", original_mask)
    universal_state, universal_metrics = solve("universal_cash", np.ones(len(scores)))
    for key, values in (("pmt", original_metrics), ("universal_cash", universal_metrics)):
        for metric in ("fgt0_pct", "fgt1_pct", "fgt2_pct", "bottom40_ev_pct"):
            assert abs(values[metric] - published.loc[key, metric]) < 1e-8, (key, metric)

    previous = np.zeros(len(scores))
    for coverage in (.2, .3, .4, .5, .6):
        label = f"pmt_{int(coverage * 100)}"
        mask = ms.exact_mask(micro["pw"], order, coverage * population)
        assert (mask >= previous - 1e-12).all()
        previous = mask
        state, values = solve(label, mask)
        errors = ms.errors(micro, mask)
        recipients = float(np.dot(micro["pw"], mask))
        reached_target = float(np.dot(micro["pw"][target], mask[target]))
        assert abs(errors["coverage"] - coverage) < 1e-12
        # At variable coverage exclusion and leakage have different denominators.
        assert abs((1 - errors["exclusion"]) * target_population - (1 - errors["leakage"]) * recipients) < 1e-6
        cash_per_person = state["net_cash"] * 1e12 / recipients
        rows.append(dict(
            policy=label, coverage_pct=100 * coverage, recipients_million=recipients / 1e6,
            target_reached_pct=100 * (1 - errors["exclusion"]),
            exclusion_pct=100 * errors["exclusion"], leakage_pct=100 * errors["leakage"],
            target_cash_share_pct=100 * reached_target / recipients,
            annual_cash_per_recipient_sam_tl=cash_per_person,
            annual_cash_per_recipient_hbs_tl=state["net_cash"] / recipients / micro["income_scale"],
            net_cash_billion_tl=state["net_cash"] * 1000,
            admin_billion_tl=state["macro"]["admin_cost_trillion_tl"] * 1000,
            net_fiscal_cost_billion_tl=state["macro"]["net_fiscal_cost_trillion_tl"] * 1000,
            net_cost_gdp_pct=state["macro"]["net_cost_gdp_pct"],
            investment_baseprice_pct=state["macro"]["investment_baseprice_pct"],
            fgt1_vs_universal_pp=values["fgt1_pct"] - universal_metrics["fgt1_pct"],
            fgt1_shock_compensation_pct=100 * (shock_metrics["fgt1_pct"] - values["fgt1_pct"]) / (shock_metrics["fgt1_pct"] - baseline["fgt1_pct"]),
            **values,
        ))

    pairs = [(row["policy"], "universal_cash") for row in rows]
    pairs += [(row["policy"], "pmt_40") for row in rows if row["policy"] != "pmt_40"]
    pairs += [(rows[i]["policy"], rows[i + 1]["policy"]) for i in range(len(rows) - 1)]
    intervals = ms.paired_intervals(contributions, micro, pairs, reps=1000)
    frame = pd.DataFrame(rows)
    reference = frame.loc[frame.policy == "pmt_40"].iloc[0]
    frame["cash_per_recipient_index_pmt40_100"] = 100 * frame.annual_cash_per_recipient_sam_tl / reference.annual_cash_per_recipient_sam_tl
    frame["fgt1_vs_pmt40_pp"] = frame.fgt1_pct - reference.fgt1_pct
    for interval in intervals:
        if interval["policy_b"] == "universal_cash":
            idx = frame.policy == interval["policy_a"]
            frame.loc[idx, "vs_universal_lower95_pp"] = interval["lower95_pp"]
            frame.loc[idx, "vs_universal_upper95_pp"] = interval["upper95_pp"]
    assert np.isfinite(frame.select_dtypes("number").to_numpy()).all()
    for relative, before in protected_hashes.items():
        assert cm.sha(cm.ROOT / relative) == before, f"Original output changed: {relative}"
    for relative, before in source_hashes.items():
        assert cm.sha(cm.PROJECT / relative) == before, f"Source changed during run: {relative}"

    out = cm.OUT / "tables"
    frame.to_csv(out / "PMT_coverage_sensitivity.csv", index=False, encoding="utf-8-sig", float_format="%.12g")
    pd.DataFrame(group_rows).to_csv(out / "PMT_coverage_quintiles.csv", index=False, encoding="utf-8-sig", float_format="%.12g")
    pd.DataFrame(intervals).to_csv(out / "PMT_coverage_intervals.csv", index=False, encoding="utf-8-sig", float_format="%.12g")
    cm.dump(cm.OUT / "equilibria/pmt_coverage_equilibria.json", states)
    report = dict(
        status="complete", utc_time=datetime.now(timezone.utc).isoformat(), elapsed_seconds=time.time() - started,
        configuration=cfg, population=population, target_population=target_population,
        existing_target_population_pct=100 * target_population / population,
        coverage_definition="Exact person-weighted population fractions: 20, 30, 40, 50, 60 percent. PMT score is unchanged.",
        eligibility_definition="Original bottom two income quintiles, held fixed for all coverage scenarios.",
        boundary_convention="Fractional survey weight receives full payment; remaining fraction receives zero.",
        fiscal_definition="Same net cost: decline in government savings from the same-shock no-policy equilibrium, equal to 0.5 percent of benchmark GDP.",
        administrative_cost="3 percent of gross cash program spending, as in the main configuration.",
        money_units="Annual per-recipient cash in SAM-calibrated nominal TL; separate HBS-scale TL column follows the existing micro income conversion.",
        exact_40_vs_original_fgt1_pp=float(reference.fgt1_pct - original_metrics["fgt1_pct"]),
        interval_definition="1000 paired household exponential multipliers, conditional on fitted PMT, solved equilibria, poverty line and payment amounts.",
        baseline=baseline, shock=shock_metrics, original_pmt=original_metrics, universal_cash=universal_metrics,
        pmt_design=pmt_report, micro_calibration=captured["micro_calibration.json"],
        results=frame.to_dict(orient="records"), intervals=intervals, checks=checks,
        source_hashes=source_hashes, protected_output_hashes=protected_hashes,
        original_outputs_unchanged=True,
    )
    cm.dump(cm.OUT / "diagnostics/pmt_coverage_sensitivity.json", report)

    lines = [
        "# PMT coverage sensitivity", "",
        "The original out-of-fold PMT ranking is retained. Each coverage level is solved as a new CGE equilibrium at the same net fiscal cost (0.5% of benchmark GDP), followed by the existing household microsimulation. The external shock remains food import prices +20% and energy import prices +40%, with a 3% administrative share of gross cash spending.", "",
        "Exclusion and leakage are measured against the original bottom-two-quintile target population, held fixed across scenarios. Coverage refers to the entire population. Payments are equal per recipient person. Increasing coverage changes the recipient composition, group cash shares and endogenous total cash transfer.", "",
        "| Population coverage (%) | FGT0 (%) | FGT1 (%) | FGT2 (%) | Target reached (%) | Exclusion (%) | Leakage (%) | Annual cash per recipient (SAM TL) | FGT1 vs universal (pp) |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in frame.to_dict(orient="records"):
        lines.append(f"| {r['coverage_pct']:.0f} | {r['fgt0_pct']:.3f} | {r['fgt1_pct']:.3f} | {r['fgt2_pct']:.3f} | {r['target_reached_pct']:.2f} | {r['exclusion_pct']:.2f} | {r['leakage_pct']:.2f} | {r['annual_cash_per_recipient_sam_tl']:.2f} | {r['fgt1_vs_universal_pp']:.3f} |")
    lines += ["", f"Universal cash reference: FGT0 = {universal_metrics['fgt0_pct']:.6f}%, FGT1 = {universal_metrics['fgt1_pct']:.6f}%, FGT2 = {universal_metrics['fgt2_pct']:.6f}%.", "",
        f"The original nominal 40% target contains {100 * target_population / population:.8f}% of population because complete households define the quintiles. This experiment uses exactly 40% for its middle scenario. Its FGT1 differs from the reproduced original PMT by {reference.fgt1_pct - original_metrics['fgt1_pct']:+.8f} percentage points.", "",
        "The lowest FGT1 among these five tested coverage levels is attained at " + str(int(frame.loc[frame.fgt1_pct.idxmin(), "coverage_pct"])) + "%. This is a comparison on the stated coverage grid, not an optimisation over all coverage levels or alternative PMT estimators.", "",
        "All nine benchmark, shock and policy equilibria pass the existing model diagnostics and SAM-account checks. Baseline, shock, original PMT and universal-cash outcomes reproduce the published results to within 1e-8 percentage points. Original analysis files and the manuscript are preserved.", "",
        "Additional machine-readable outputs contain quintile results, paired conditional 95% intervals, macro equilibrium snapshots and a run audit. The intervals hold the PMT model, equilibrium and transfer amounts fixed; they summarise household reweighting uncertainty.", "",
    ]
    (cm.OUT / "reports/PMT_coverage_sensitivity.md").write_text("\n".join(lines), encoding="utf-8")
    columns = ["coverage_pct", "fgt0_pct", "fgt1_pct", "fgt2_pct", "target_reached_pct", "exclusion_pct", "leakage_pct", "annual_cash_per_recipient_sam_tl", "bottom40_ev_pct"]
    print(frame[columns].to_string(index=False), flush=True)
    print(f"COMPLETE: {len(checks)} equilibria; {time.time() - started:.1f} seconds", flush=True)


if __name__ == "__main__":
    main()
