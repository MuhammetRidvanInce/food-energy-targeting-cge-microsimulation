"""Aggregated household profiles for the publication figure set.

Rebuilds the stage-5 microsimulation bridge, refits the out-of-fold PMT and
re-evaluates every main policy against the stored equilibrium states in
outputs/equilibria/main_equilibria.json. No CGE model is solved and no file
outside outputs/figures/data is written. Only aggregated profiles (income
bins, weighted 2-D histograms) are exported; no HBS record leaves memory.

Adapted from the user-supplied claude_figures design, with input validation and
explicit reconciliation of household-implied subsidy totals to the CGE outlay.
Run: python -B codes/figure_profiles.py
"""
import os
for key in ['OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS']:
    os.environ.setdefault(key, '1')
import sys, json
from pathlib import Path

HERE = Path(__file__).resolve().parent
STAGE5 = HERE.parent
sys.path.insert(0, str(STAGE5/'codes'))

import numpy as np
import pandas as pd
import micro_simulation as ms
from common import OUT, PROJECT, FOOD, ENERGY, SECTORS, configurations, sha
from policy_model import build

DATA = OUT/'figures/data'
POLICIES = ['baseline', 'shock', 'perfect_targeting', 'pmt', 'universal_cash', 'price_support']
BINS = 20


def household_detail(state, micro, mask):
    """Same arithmetic as micro_simulation.household_outcomes, kept per household."""
    g = micro['group']; pw = micro['pw']; beta = micro['beta']
    ratio = np.asarray(state['price_ratios'])
    cpi,current_shares = ms.consumption_system(state,micro)
    contrib = ms.ces_log_price_contributions(state,micro)
    yf = state['w']*micro['L']+state['r']*micro['K']+micro['R']*state['factor_index']
    disp = (1-micro['tax'])*yf
    budget0 = disp-micro['S0']*np.asarray(state['group_income_factor'])[g]
    full = np.zeros(len(g)); shares = np.asarray(state['shares'])
    for k in range(5):
        ix = g == k; den = np.dot(pw[ix], mask[ix]); amount = shares[k]*state['net_cash']
        if amount > 1e-15:
            full[ix] = amount*micro['size'][ix]/den
    cons_cash = (1-state['cash_saving'])*full
    eq0 = disp/micro['income_scale']/micro['equiv']/cpi
    eq1 = (disp+full)/micro['income_scale']/micro['equiv']/cpi
    line = micro['poverty_line']
    gap = (1-mask)*np.maximum(1-eq0/line, 0)+mask*np.maximum(1-eq1/line, 0)
    real = (1-mask)*budget0/cpi+mask*(budget0+cons_cash)/cpi
    idx = {s: i for i, s in enumerate(SECTORS)}
    sub = [idx[s] for s in FOOD+ENERGY]
    return dict(cpi=cpi, budget0=budget0, cash=full*mask, ev=real-micro['B0'], gap=gap,
                log_food=contrib[[idx[s] for s in FOOD]].sum(axis=0),
                log_energy=contrib[[idx[s] for s in ENERGY]].sum(axis=0),
                log_total=contrib.sum(axis=0), subsidised_share=current_shares[sub].sum(axis=0))


def main():
    DATA.mkdir(parents=True, exist_ok=True)
    run=json.loads((OUT/'diagnostics/run_manifest.json').read_text(encoding='utf-8'))
    assert run['status']=='complete'
    for relative,expected in run['source_hashes'].items():
        assert sha(PROJECT/relative)==expected, f'Analysis input changed: {relative}'
    base = build(configurations()['main'])
    saved_dump=ms.dump
    try:
        ms.dump=lambda *a, **k: None
        micro, h, f = ms.prepare_micro(base)
        pmt_mask, pred, y, report = ms.fit_pmt(micro, h, f)
    finally:
        ms.dump=saved_dump
    states = json.loads((OUT/'equilibria/main_equilibria.json').read_text(encoding='utf-8'))
    table1 = pd.read_csv(OUT/'tables/main/Table1_main_policy_results.csv').set_index('policy')
    macro = pd.read_csv(OUT/'tables/main/Table2_main_macro_results.csv').set_index('policy')

    n = len(pmt_mask); g = micro['group']; pw = micro['pw']; hw = micro['hw']
    masks = dict(baseline=np.zeros(n), shock=np.zeros(n), perfect_targeting=(g < 2).astype(float),
                 pmt=pmt_mask, universal_cash=np.ones(n), price_support=np.ones(n))
    # Rows are already sorted by baseline equivalent income (prepare_micro).
    rank = (np.cumsum(pw)-pw/2)/pw.sum()
    vbin = np.minimum(BINS-1, (rank*BINS).astype(int))

    detail, checks = {}, []
    for p in POLICIES:
        vals, _, _ = ms.household_outcomes(states[p], micro, masks[p])
        d = household_detail(states[p], micro, masks[p])
        fgt1 = 100*np.average(d['gap'], weights=pw)
        checks.append(dict(policy=p, fgt1_recomputed=fgt1, fgt1_table1=table1.loc[p, 'fgt1_pct'],
                           abs_gap=abs(fgt1-table1.loc[p, 'fgt1_pct'])))
        assert abs(fgt1-vals['fgt1_pct']) < 1e-10 and abs(fgt1-table1.loc[p, 'fgt1_pct']) < 1e-8
        detail[p] = d

    # Implicit price-support transfer: relief on subsidised purchases at policy prices.
    relief = macro.loc['price_support', 'consumer_discount_pct']/100
    ps = detail['price_support']
    ps_benefit = relief/(1-relief)*ps['subsidised_share']*ps['budget0']
    ps_raw_total = float(np.dot(hw, ps_benefit))
    ps_macro_total=float(macro.loc['price_support','price_support_trillion_tl'])
    ps_factor=ps_macro_total/ps_raw_total
    # One proportional reconciliation preserves the entire concentration curve.
    ps_benefit*=ps_factor
    ps_total = float(np.dot(hw, ps_benefit))
    assert abs(ps_total-ps_macro_total)<1e-12
    benefit = {p: detail[p]['cash'] for p in ['perfect_targeting', 'pmt', 'universal_cash']}
    benefit['price_support'] = ps_benefit

    rows = []
    for b in range(BINS):
        ix = vbin == b; w = pw[ix]; H = hw[ix]
        row = dict(bin=b+1, pop_share=w.sum()/pw.sum(), rank_mid=(b+.5)/BINS,
                   eq_income_mean=np.average(micro['income'][ix]/micro['equiv'][ix], weights=w),
                   eq_income_over_line=np.average(micro['income'][ix]/micro['equiv'][ix], weights=w)/micro['poverty_line'],
                   food_share=100*np.average(micro['beta'][[SECTORS.index(s) for s in FOOD]][:, ix].sum(axis=0), weights=H*micro['B0'][ix]),
                   energy_share=100*np.average(micro['beta'][[SECTORS.index(s) for s in ENERGY]][:, ix].sum(axis=0), weights=H*micro['B0'][ix]))
        s = detail['shock']
        scale=np.divide(np.expm1(s['log_total'][ix]),s['log_total'][ix],
                        out=np.ones(ix.sum()),where=abs(s['log_total'][ix])>1e-14)
        row.update(shock_cpi_pct=100*np.average(s['cpi'][ix]-1, weights=w),
                   shock_cpi_food_pp=100*np.average(s['log_food'][ix]*scale, weights=w),
                   shock_cpi_energy_pp=100*np.average(s['log_energy'][ix]*scale, weights=w),
                   shock_income_pct=100*(np.dot(H, s['budget0'][ix])/np.dot(H, micro['B0'][ix])-1))
        row['shock_cpi_other_pp'] = row['shock_cpi_pct']-row['shock_cpi_food_pp']-row['shock_cpi_energy_pp']
        for p in POLICIES[1:]:
            d = detail[p]
            row[f'ev_pct_{p}'] = 100*np.dot(H, d['ev'][ix])/np.dot(H, micro['B0'][ix])
            row[f'fgt1_pct_{p}'] = 100*np.average(d['gap'][ix], weights=w)
        for p, m in masks.items():
            if p in benefit:
                row[f'receipt_pct_{p}'] = 100*np.average(m[ix], weights=w) if p != 'price_support' else np.nan
                row[f'benefit_share_{p}'] = np.dot(H, benefit[p][ix])/np.dot(hw, benefit[p])
        rows.append(row)
    prof = pd.DataFrame(rows)
    assert abs(prof.pop_share.sum()-1)<1e-12
    for p in benefit:
        assert abs(prof[f'benefit_share_{p}'].sum()-1)<1e-12
    assert np.allclose(prof.shock_cpi_food_pp+prof.shock_cpi_energy_pp+prof.shock_cpi_other_pp,
                       prof.shock_cpi_pct,atol=1e-10)
    prof.to_csv(DATA/'income_bin_profiles.csv', index=False, float_format='%.10g')

    # Concentration indices of the fiscal resource over baseline income rank.
    conc = []
    for p, ben in benefit.items():
        share = hw*ben/np.dot(hw, ben)
        conc.append(dict(policy=p, concentration_index=float(2*np.dot(share, rank)-1),
                         bottom40_share_pct=100*share[g < 2].sum(),
                         total_trillion_tl=float(np.dot(hw, ben))))
    pd.DataFrame(conc).to_csv(DATA/'benefit_concentration.csv', index=False, float_format='%.10g')

    # PMT diagnostic as a person-weighted 2-D histogram (no record-level export).
    cutoff_true = np.log1p(ms.weighted_quantile(micro['income']/micro['equiv'], pw, .4))
    edges = np.linspace(9.0, 14.5, 111)
    H2, xe, ye = np.histogram2d(np.clip(y, edges[0], edges[-1]-1e-9), np.clip(pred, edges[0], edges[-1]-1e-9),
                                bins=[edges, edges], weights=pw)
    hist = pd.DataFrame([dict(actual_lo=xe[i], actual_hi=xe[i+1], pred_lo=ye[j], pred_hi=ye[j+1], persons=H2[i, j])
                         for i in range(len(xe)-1) for j in range(len(ye)-1) if H2[i, j] > 0])
    hist.to_csv(DATA/'pmt_prediction_histogram.csv', index=False, float_format='%.10g')
    eligible = g < 2
    score_edges = np.linspace(np.quantile(pred, .001), np.quantile(pred, .999), 61)
    score_rows = []
    for name, ix in [('eligible', eligible), ('ineligible', ~eligible)]:
        cnt, _ = np.histogram(np.clip(pred[ix], score_edges[0], score_edges[-1]-1e-9), bins=score_edges, weights=pw[ix])
        score_rows += [dict(group=name, lo=score_edges[i], hi=score_edges[i+1], persons_pct=100*cnt[i]/pw.sum())
                       for i in range(len(cnt))]
    pd.DataFrame(score_rows).to_csv(DATA/'pmt_score_distribution.csv', index=False, float_format='%.10g')
    quad = dict(correct_inclusion=np.dot(pw[eligible], pmt_mask[eligible]),
                exclusion_error=np.dot(pw[eligible], 1-pmt_mask[eligible]),
                inclusion_error=np.dot(pw[~eligible], pmt_mask[~eligible]),
                correct_exclusion=np.dot(pw[~eligible], 1-pmt_mask[~eligible]))
    tot = pw.sum()
    pred_cut = float(np.sort(pred)[np.searchsorted(np.cumsum(pw[np.argsort(pred, kind='stable')]), pw[eligible].sum())])
    pmtdesign=json.loads((OUT/'diagnostics/pmt_design.json').read_text(encoding='utf-8'))
    assert abs(report['weighted_oof_r2']-pmtdesign['weighted_oof_r2'])<1e-10
    assert abs(report['exclusion']-pmtdesign['exclusion'])<1e-10
    plot_window=(y>=9.6)&(y<=14.5)&(pred>=10.3)&(pred<=14.4)
    meta = dict(weighted_oof_r2=report['weighted_oof_r2'], exclusion=report['exclusion'], leakage=report['leakage'],
                actual_cutoff_log1p=float(cutoff_true), predicted_cutoff_log1p=pred_cut,
                poverty_line_log1p=float(np.log1p(micro['poverty_line'])),
                quadrants_pct={k: 100*v/tot for k, v in quad.items()},
                price_support_benefit_trillion_tl=ps_total,
                price_support_unreconciled_trillion_tl=ps_raw_total,
                price_support_proportional_reconciliation_factor=ps_factor,
                price_support_cost_table2_trillion_tl=float(macro.loc['price_support', 'price_support_trillion_tl']),
                cash_total_check={p: float(np.dot(hw, benefit[p])) for p in ['perfect_targeting', 'pmt', 'universal_cash']},
                fgt1_reproduction=checks, bins=BINS, households=int(n),
                cpi_decomposition='Integrated CES log-price-path contributions proportionally converted to percentage-point components; accounting decomposition of the same equilibrium',
                histogram_display_population_pct=100*pw[plot_window].sum()/pw.sum(),
                histogram_range=[9.,14.5],histogram_tail_folding=True,
                score_histogram_tail_folding='below 0.1 and above 99.9 sample percentiles; end bins retain tail mass',
                input_hashes={str(OUT/'equilibria/main_equilibria.json'):sha(OUT/'equilibria/main_equilibria.json'),
                              str(OUT/'tables/main/Table1_main_policy_results.csv'):sha(OUT/'tables/main/Table1_main_policy_results.csv'),
                              str(OUT/'tables/main/Table2_main_macro_results.csv'):sha(OUT/'tables/main/Table2_main_macro_results.csv')},
                note='Aggregated profiles only; household records are not exported.')
    (DATA/'profile_metadata.json').write_text(json.dumps(meta, indent=2), encoding='utf-8')
    print(json.dumps({k: meta[k] for k in ['weighted_oof_r2', 'exclusion', 'quadrants_pct',
                                           'price_support_benefit_trillion_tl', 'price_support_cost_table2_trillion_tl',
                                           'cash_total_check']}, indent=1))
    print(pd.DataFrame(checks).to_string())
    print(pd.DataFrame(conc).to_string())


if __name__ == '__main__':
    main()
