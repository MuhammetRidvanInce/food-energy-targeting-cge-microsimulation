"""Publication layouts adapted from the user's preferred claude_figures set.

Reads stage-5 tables and verified aggregated profiles produced by figure_profiles.
Output: outputs/figures/{main,supplementary}/fig*.{pdf,svg,png,tiff}.
Run through publication_outputs.py so input checks and profiles are regenerated.
"""
import json
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Rectangle, FancyArrowPatch, Patch
from matplotlib.lines import Line2D
from matplotlib.colors import LinearSegmentedColormap, TwoSlopeNorm, LogNorm
import matplotlib.patheffects as pe

import re
from common import OUT, load_supplementary
FIG = OUT/'figures'
DATA = FIG/'data'
TAB = OUT/'tables'
NAME_MAP = {
    'Fig1_framework':'fig1', 'Fig2_exposure_incidence':'fig2',
    'Fig3_poverty_outcomes':'fig3', 'Fig4_welfare_incidence':'fig4',
    'Fig5_targeting_errors':'fig5', 'Fig6_composition_decomposition':'fig6',
    'FigS1_robustness':'figS2', 'FigS2_sector_output':'figS4',
    'FigS3_macro_fiscal':'figS3', 'FigS4_measurement_sensitivity':'figS5',
    'FigS5_pmt_diagnostics':'figS1'}

# ---------------------------------------------------------------- style
MM = 1/25.4
DOUBLE, ONEHALF, SINGLE = 190*MM, 140*MM, 90*MM
INK, MUTED, FAINT, RULE, GRID = '#1F1F1F', '#5A5A5A', '#8C8C8C', '#7A7A7A', '#E4E4E4'
POL = ['perfect_targeting', 'pmt', 'universal_cash', 'price_support']
LAB = {'perfect_targeting': 'Perfect targeting', 'pmt': 'Out-of-fold PMT', 'universal_cash': 'Universal cash',
       'price_support': 'Price support', 'shock': 'Shock, no policy', 'baseline': 'Pre-shock benchmark'}
COL = {'perfect_targeting': '#1D5FA8', 'pmt': '#3FA7D6', 'universal_cash': '#C77C02', 'price_support': '#B23A6F',
       'shock': '#3A3A3A', 'baseline': '#9A9A9A'}
MRK = {'perfect_targeting': 'o', 'pmt': 's', 'universal_cash': '^', 'price_support': 'D', 'shock': 'X'}
plt.rcParams.update({
    'font.family': 'Arial', 'font.size': 7.5, 'axes.titlesize': 8, 'axes.labelsize': 7.5,
    'xtick.labelsize': 7, 'ytick.labelsize': 7, 'legend.fontsize': 7,
    'axes.linewidth': .6, 'axes.edgecolor': RULE, 'axes.labelcolor': INK, 'text.color': INK,
    'xtick.color': MUTED, 'ytick.color': MUTED, 'xtick.major.width': .6, 'ytick.major.width': .6,
    'xtick.major.size': 2.5, 'ytick.major.size': 2.5, 'axes.spines.top': False, 'axes.spines.right': False,
    'grid.color': GRID, 'grid.linewidth': .5, 'lines.linewidth': 1.3, 'lines.markersize': 3.6,
    'legend.frameon': False, 'legend.handlelength': 1.8, 'legend.borderaxespad': .2,
    'axes.titlelocation': 'left', 'axes.titlepad': 6,
    'pdf.fonttype': 42, 'ps.fonttype': 42, 'svg.fonttype': 'none',
    'savefig.dpi': 600, 'savefig.facecolor': 'white', 'figure.facecolor': 'white',
    'mathtext.fontset': 'custom', 'mathtext.rm': 'Arial', 'mathtext.it': 'Arial:italic', 'mathtext.bf': 'Arial:bold'})
DIVERGE = LinearSegmentedColormap.from_list('targeted_universal', [
    '#123E73', COL['perfect_targeting'], '#8CB8E0', '#F4F4F2', '#EBC27E', COL['universal_cash'], '#7A4A00'])
CAPTIONS = []


def tab(name, supp=False):
    return load_supplementary(name) if supp else pd.read_csv(TAB/'main'/f'{name}.csv', encoding='utf-8-sig')


def panel(ax, letter, title=None, pad=5):
    """Bold panel letter left of the axes, title on the same baseline."""
    ax.set_title(title or '', fontsize=8, color=INK, pad=pad)
    ax.annotate(letter, xy=(0, 1), xycoords='axes fraction', xytext=(-8, pad), textcoords='offset points',
                ha='right', va='baseline', fontsize=9, fontweight='bold')


def num(v, fmt='.3f', sign=False):
    """Number with a typographic minus sign."""
    if fmt.endswith('f') and abs(v) < .5*10**-int(fmt[1:-1]):
        v = 0.0  # avoid "-0.00"
    return format(v, ('+' if sign else '')+fmt).replace('-', '−')


def save(fig, name, caption, supp=False):
    name=NAME_MAP[name]
    folder = FIG/('supplementary' if supp else 'main')
    folder.mkdir(parents=True, exist_ok=True)
    fig.savefig(folder/f'{name}.pdf', bbox_inches='tight', pad_inches=.03)
    fig.savefig(folder/f'{name}.svg', bbox_inches='tight', pad_inches=.03)
    fig.savefig(folder/f'{name}.png', dpi=600, bbox_inches='tight', pad_inches=.03)
    fig.savefig(folder/f'{name}.tiff', dpi=600, bbox_inches='tight', pad_inches=.03,
                pil_kwargs={'compression': 'tiff_lzw'})
    plt.close(fig)
    CAPTIONS.append((name, caption, supp))
    print('saved', name, flush=True)


def quintile_bands(ax, top_labels=True):
    for k in range(5):
        if k % 2 == 0:
            ax.axvspan(20*k, 20*(k+1), color='#F3F3F3', zorder=0, lw=0)
        if top_labels:
            ax.text(20*k+10, 1.01, f'Q{k+1}', transform=ax.get_xaxis_transform(), ha='center', va='bottom',
                    fontsize=6.3, color=FAINT)
    ax.set(xlim=(0, 100), xticks=range(0, 101, 20))


def zero_line(ax, axis='y'):
    (ax.axhline if axis == 'y' else ax.axvline)(0, color=RULE, lw=.7, zorder=1)


# ---------------------------------------------------------------- Figure 1
def fig1_framework():
    t2 = tab('Table2_main_macro_results').set_index('policy')
    pmt = json.loads((OUT/'diagnostics/pmt_design.json').read_text(encoding='utf-8'))
    cal = json.loads((OUT/'diagnostics/micro_calibration.json').read_text(encoding='utf-8'))
    run = json.loads((OUT/'diagnostics/publication_run_summary.json').read_text(encoding='utf-8'))
    grid = tab('S4_error_grid_draws', True)
    fig = plt.figure(figsize=(DOUBLE, 3.5))
    ax = fig.add_axes([0, 0, 1, 1]); ax.set(xlim=(0, 100), ylim=(0, 60)); ax.axis('off')

    def box(x, y, w, h, title, lines, accent, fill='#FFFFFF', title_size=7.6):
        ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle='round,pad=0,rounding_size=1.1',
                                    fc=fill, ec=accent, lw=.9, zorder=2))
        ax.add_patch(Rectangle((x+.9, y+h-.65), w-1.8, .35, fc=accent, ec='none', zorder=3))
        ax.text(x+1.4, y+h-1.9, title, ha='left', va='top', fontsize=title_size, fontweight='bold', zorder=4)
        ax.text(x+1.4, y+h-5.6, '\n'.join(lines), ha='left', va='top', fontsize=6.5, color='#2B2B2B',
                linespacing=1.45, zorder=4)

    def arrow(p, q, text=None, tx=None, ty=None, ha='center', rad=0., color='#4A4A4A'):
        ax.add_patch(FancyArrowPatch(p, q, arrowstyle='-|>,head_length=2.6,head_width=1.5', mutation_scale=1,
                                     lw=.9, color=color, connectionstyle=f'arc3,rad={rad}', zorder=5,
                                     shrinkA=0, shrinkB=0))
        if text:
            ax.text(tx, ty, text, ha=ha, va='center', fontsize=6.1, color=MUTED, style='italic', zorder=6,
                    bbox=dict(fc='white', ec='none', pad=.6))

    navy, grey = '#24476B', '#6E6E6E'
    gdp = run['baseline_gdp_trillion_tl']
    # Inputs
    box(0.6, 25.5, 21.0, 20.5, 'Social accounting matrix 2023',
        ['Supply–use tables → I–O table', '64 sectors (NACE A64)', '5 income quintiles (HBS split)',
         'Factor, tax, saving and', 'rest-of-world accounts', f'GDP {gdp:.1f} trillion TL'], grey, title_size=7.2)
    box(57.0, 49.2, 24.0, 10.3, 'Household Budget Survey 2024',
        [f"{cal['households']:,} households · {cal['persons']:,} persons",
         f"{cal['expenses']:,} expenditure records"], grey, title_size=7.2)
    box(27.4, 49.2, 25.6, 10.3, 'External import-price shock',
        ['Food +20%  (A01, A03, C10–12)', 'Energy +40%  (C19, D35)'], '#8A6D3B', title_size=7.2)
    # Core models
    box(27.4, 25.5, 25.6, 20.5, 'Computable general equilibrium',
        ['CES value added · Leontief inputs', 'Armington imports · CET exports',
         '192 sector-specific elasticities', 'Wage numéraire · fixed foreign saving',
         'Savings-driven investment', 'Net cost: Sg(shock) − Sg(policy)',
         '= 0.5% of benchmark GDP'], navy, title_size=7.2)
    box(57.0, 25.5, 24.0, 20.5, 'Household microsimulation',
        ['Quintile prices and factor returns', 'applied to each household',
         'Own Cobb–Douglas cost-of-living', 'index (IPF-reconciled baskets)',
         'Recipient selection within', 'quintiles (exact person weights)'], navy, title_size=7.2)
    box(85.0, 25.5, 14.4, 20.5, 'Outcomes',
        ['Fixed real poverty line', 'FGT0 · FGT1 · FGT2', 'Money-metric EV', 'Gini · loser shares',
         'GDP, investment', 'Sector output'], grey, title_size=7.2)
    # Policies
    ax.add_patch(FancyBboxPatch((27.4, 8.0), 53.6, 10.4, boxstyle='round,pad=0,rounding_size=1.1',
                                fc='#FAFAFA', ec='#B5B5B5', lw=.8, zorder=2))
    ax.text(28.8, 16.9, f"Four policies at identical net fiscal cost ({t2.loc['pmt', 'net_fiscal_cost_trillion_tl']:.3f} trillion TL)",
            ha='left', va='top', fontsize=7.0, fontweight='bold', zorder=4)
    items = [('perfect_targeting', 'Perfect targeting', 'bottom 40%, no error'),
             ('pmt', 'Out-of-fold PMT', f"ridge, R² = {pmt['weighted_oof_r2']:.2f}"),
             ('universal_cash', 'Universal cash', 'equal per person'),
             ('price_support', 'Price support', 'consumer discount')]
    for j, (k, name, sub) in enumerate(items):
        x0 = 28.8+j*13.1
        ax.plot(x0+.6, 12.3, MRK[k], ms=5, color=COL[k], mec='white', mew=.6, zorder=5)
        ax.text(x0+1.8, 12.3, name, ha='left', va='center', fontsize=6.5, fontweight='bold', zorder=5)
        ax.text(x0+1.8, 10.0, sub, ha='left', va='center', fontsize=6.0, color=MUTED, zorder=5)
    # Flows
    arrow((21.6, 35.75), (27.4, 35.75), 'calibration', 24.5, 33.2)
    arrow((40.2, 49.2), (40.2, 46.0))
    arrow((69.0, 49.2), (69.0, 46.0))
    ax.text(69.8, 47.6, 'incomes, baskets, PMT covariates', ha='left', va='center', fontsize=6.0, color=MUTED,
            style='italic', zorder=6)
    arrow((53.0, 35.75), (57.0, 35.75))
    ax.text(55.0, 38.0, 'prices', ha='center', va='center', fontsize=6.0, color=MUTED, style='italic')
    arrow((81.0, 35.75), (85.0, 35.75))
    arrow((40.2, 18.4), (40.2, 25.5), 'quintile cash shares or\nprice relief (pre-solution)', 41.0, 21.95, ha='left')
    arrow((69.0, 18.4), (69.0, 25.5), 'recipients by\nPMT score', 69.8, 21.95, ha='left')
    # Experiments ribbon
    ax.add_patch(FancyBboxPatch((0.6, .8), 98.8, 4.6, boxstyle='round,pad=0,rounding_size=.8', fc='#F1F4F7',
                                ec='none', zorder=1))
    exp = (f"Checks and experiments:  {run['checked_policy_and_shock_equilibria']} verified equilibria  ·  "
           f"{run['configurations']} configurations  ·  {len(grid):,} error-grid allocations  ·  "
           f"{len(tab('S6_score_degradation_draws', True))} score-noise allocations  ·  1,000 paired bootstrap draws")
    ax.text(50, 3.1, exp, ha='center', va='center', fontsize=6.3, color='#2B2B2B')
    save(fig, 'Fig1_framework',
         'Analytical framework. The 2023 social accounting matrix (64 sectors, five person-weighted income quintiles) '
         'calibrates a static computable general equilibrium model; the 2024 Household Budget Survey supplies '
         'household incomes, expenditure baskets and proxy-means-test covariates. Quintile-level cash shares or the '
         'consumer price relief enter the CGE before it is solved; the resulting quintile prices and factor returns are '
         'passed to every household, where recipient selection, household-specific cost-of-living indices and welfare '
         'measures are evaluated. All four policies reduce government saving by the same amount relative to the '
         'same-shock no-policy equilibrium.')


# ---------------------------------------------------------------- Figure 2
def fig2_exposure():
    p = pd.read_csv(DATA/'income_bin_profiles.csv')
    conc = pd.read_csv(DATA/'benefit_concentration.csv').set_index('policy')
    x = 100*p.rank_mid
    fig, axs = plt.subplots(1, 3, figsize=(DOUBLE, 2.45), gridspec_kw=dict(width_ratios=[1, 1.1, 1], wspace=.42))
    a, b, c = axs
    # a: exposure
    quintile_bands(a)
    a.plot(x, p.food_share, '-o', color='#2F2F2F', ms=2.8, label='Food (A01, A03, C10–12)')
    a.plot(x, p.energy_share, '-s', color=FAINT, ms=2.6, mfc='white', label='Energy (C19, D35)')
    a.set(ylim=(0, 42), ylabel='Share of household budget (%)', xlabel='Baseline income percentile')
    a.grid(axis='y'); a.legend(loc='upper center', bbox_to_anchor=(.5, -.24), ncol=1, fontsize=6.3)
    panel(a, 'a', 'Budget exposure', pad=13)
    # b: cost-of-living decomposition
    quintile_bands(b)
    w = 4.2
    parts = [('shock_cpi_food_pp', 'Food', '#3A3A3A'), ('shock_cpi_energy_pp', 'Energy', '#8E8E8E'),
             ('shock_cpi_other_pp', 'Other goods (indirect)', '#C9C9C9')]
    bottom = np.zeros(len(p))
    for col, name, colr in parts:
        b.bar(x, p[col], w, bottom=bottom, color=colr, ec='white', lw=.4, label=name, zorder=2)
        bottom += p[col]
    b.plot(x, p.shock_income_pct, '-', color=INK, lw=1.0, zorder=3, label='Nominal household budget')
    b.set(ylim=(0, 3.4), ylabel='Change under shock, no policy (%)', xlabel='Baseline income percentile')
    b.grid(axis='y', zorder=0)
    for i, ha, dx in ((0, 'left', -4), (-1, 'right', 4)):
        b.annotate(f'{p.shock_cpi_pct.iloc[i]:.2f}%', (x.iloc[i], p.shock_cpi_pct.iloc[i]), xytext=(dx, 2.5),
                   textcoords='offset points', ha=ha, fontsize=6.3, fontweight='bold')
    hs, ls = b.get_legend_handles_labels()
    b.legend(hs[1:]+hs[:1], ls[1:]+ls[:1], loc='upper center', bbox_to_anchor=(.5, -.24), ncol=2, fontsize=6.3,
             columnspacing=1)
    panel(b, 'b', 'Cost-of-living shock', pad=13)
    # c: concentration curves
    cx = np.r_[0, 100*np.cumsum(p.pop_share)]
    c.plot([0, 100], [0, 100], color=FAINT, lw=.7, zorder=1)
    for k in POL:
        cy = np.r_[0, 100*np.cumsum(p[f'benefit_share_{k}'])]
        c.plot(cx, cy, color=COL[k], lw=1.4, zorder=3,
               label=f"{LAB[k]}  ({num(conc.loc[k, 'concentration_index'], '.2f', True)})")
    c.axvline(40, color=RULE, lw=.6, ls=(0, (2, 2)), zorder=1)
    c.text(41, 4, 'target\npopulation', fontsize=6, color=MUTED, va='bottom')
    c.set(xlim=(0, 100), ylim=(0, 101), xticks=range(0, 101, 20), yticks=range(0, 101, 20),
          xlabel='Cumulative population (%)', ylabel='Cumulative share of fiscal resource (%)')
    c.set_aspect('auto')
    c.legend(loc='upper center', bbox_to_anchor=(.5, -.24), ncol=1, fontsize=6.3, title='Concentration index',
             title_fontsize=6.3)
    panel(c, 'c', 'Who receives the budget', pad=13)
    save(fig, 'Fig2_exposure_incidence',
         'Exposure to the shock and incidence of the fiscal resource across the baseline income distribution. '
         'Households are ranked by baseline equivalent disposable income and grouped into twenty person-weighted bins; '
         'shading marks quintiles. (a) Expenditure shares of the shocked food and energy commodities. '
         '(b) Shock-induced change in the household-specific cost-of-living index, split into the direct contributions of '
         'food and energy and the indirect contribution of all other goods, together with the change in nominal household '
         'budgets under the same equilibrium. (c) Concentration curves of the transfer or implicit price subsidy over the '
         'baseline income rank; the concentration index is negative when the resource is concentrated among poorer '
         'people. Price-support benefits inferred from household baskets are proportionally reconciled to the solved '
         'macro outlay; their normalized distribution is unchanged. The CPI bars allocate the same-equilibrium '
         'log-index contributions proportionally to the total percentage change. Cash curves describe net benefits '
         'received by households, excluding programme administration.')


# ---------------------------------------------------------------- Figure 3
def fig3_poverty():
    t1 = tab('Table1_main_policy_results').set_index('policy')
    ci = tab('Table4_conditional_intervals')
    fig, (a, b) = plt.subplots(1, 2, figsize=(DOUBLE, 2.55), gridspec_kw=dict(width_ratios=[1, .8], wspace=.75))
    metrics = [('fgt0_pct', 'Headcount\n(FGT0)'), ('fgt1_pct', 'Poverty gap\n(FGT1)'), ('fgt2_pct', 'Severity\n(FGT2)')]
    h = .19
    for i, (m, name) in enumerate(metrics):
        rise = t1.loc['shock', m]-t1.loc['baseline', m]
        for j, k in enumerate(POL):
            v = 100*(t1.loc['shock', m]-t1.loc[k, m])/rise
            y = i+(j-1.5)*h
            a.barh(y, v, h*.86, color=COL[k], zorder=2)
            a.text(v+4, y, f'{v:.0f}', va='center', ha='left', fontsize=6.2, color=INK)
    a.axvline(100, color=INK, lw=.8, zorder=3)
    a.text(103, 2.6, 'full offset', ha='left', va='center', fontsize=6.2, color=INK)
    a.set(yticks=range(3), yticklabels=[n for _, n in metrics], xlim=(0, 340), ylim=(2.72, -.5),
          xlabel='Offset of the shock-induced rise in poverty (%)')
    a.tick_params(axis='y', length=0)
    a.grid(axis='x', zorder=0)
    handles = [Patch(color=COL[k], label=LAB[k]) for k in POL]
    a.legend(handles=handles, loc='upper center', bbox_to_anchor=(.45, -.2), ncol=2, fontsize=6.5)
    panel(a, 'a', 'Poverty offset at equal net cost')

    rows = [('perfect_targeting', 'universal_cash'), ('pmt', 'universal_cash'),
            ('pmt', 'price_support'), ('universal_cash', 'price_support')]
    short = {'perfect_targeting': 'Perfect targeting', 'pmt': 'PMT', 'universal_cash': 'Universal cash',
             'price_support': 'price support'}
    for j, (p, q) in enumerate(rows):
        r = ci[(ci.policy_a == p) & (ci.policy_b == q)].iloc[0]
        b.plot([r.lower95_pp, r.upper95_pp], [j, j], color=COL[p], lw=2.2, solid_capstyle='butt', zorder=2)
        b.plot(r.difference_pp, j, MRK[p], color=COL[p], ms=5.5, mec='white', mew=.8, zorder=3)
        b.text(1.03, j, f'{num(r.difference_pp)}  [{num(r.lower95_pp)}, {num(r.upper95_pp)}]',
               transform=b.get_yaxis_transform(), ha='left', va='center', fontsize=6.3, color=INK)
    b.axvline(0, color=RULE, lw=.7)
    b.set(yticks=range(len(rows)), yticklabels=[f'{short[p]} − {short[q].lower() if q=="universal_cash" else short[q]}'
                                               for p, q in rows],
          xlim=(-.6, .02), ylim=(len(rows)-.5, -.6), xlabel='Difference in FGT1 (pp)\n← favours first policy')
    b.set_xticks([-.6, -.5, -.4, -.3, -.2, -.1, 0])
    b.tick_params(axis='y', length=0)
    b.grid(axis='x', zorder=0)
    b.text(1.03, -.55, 'Estimate [95% CI]', transform=b.get_yaxis_transform(), ha='left', va='center',
           fontsize=6.3, color=MUTED)
    panel(b, 'b', 'Paired differences in the poverty gap')
    save(fig, 'Fig3_poverty_outcomes',
         'Poverty outcomes under the main configuration. (a) Share of the shock-induced increase in each '
         'Foster–Greer–Thorbecke index that is reversed by each instrument, '
         '100 × (FGT_shock − FGT_policy)/(FGT_shock − FGT_benchmark); values above 100 leave poverty below its pre-shock level. '
         'The shock raises FGT0, FGT1 and FGT2 by {:.3f}, {:.3f} and {:.3f} percentage points. '
         '(b) Paired differences in FGT1 with conditional 95% intervals from 1,000 household exponential-multiplier draws; '
         'equilibria, the fitted PMT and transfer amounts are held fixed.'.format(
             *[t1.loc['shock', m]-t1.loc['baseline', m] for m, _ in metrics]))


# ---------------------------------------------------------------- Figure 4
def fig4_incidence():
    p = pd.read_csv(DATA/'income_bin_profiles.csv')
    meta = json.loads((DATA/'profile_metadata.json').read_text(encoding='utf-8'))
    x = 100*p.rank_mid
    fig, (a, b) = plt.subplots(1, 2, figsize=(DOUBLE, 2.6), gridspec_kw=dict(wspace=.28))
    quintile_bands(a)
    zero_line(a)
    a.plot(x, p.ev_pct_shock, color=COL['shock'], lw=1.1, ls=(0, (4, 2)), label=LAB['shock'], zorder=3)
    for k in POL:
        a.plot(x, p[f'ev_pct_{k}'], '-', marker=MRK[k], color=COL[k], ms=2.8, mec='white', mew=.4,
               label=LAB[k], zorder=4)
    a.axvline(40, color=RULE, lw=.6, ls=(0, (2, 2)))
    a.set(ylabel='Money-metric welfare change\n(% of initial spending)', xlabel='Baseline income percentile', ylim=(-2.5, 7))
    a.grid(axis='y')
    panel(a, 'a', 'Welfare incidence', pad=13)

    quintile_bands(b)
    rec = p.receipt_pct_pmt.to_numpy()
    target = (p.rank_mid < .4).to_numpy()
    b.bar(x[target], rec[target], 4.3, color=COL['pmt'], zorder=2)
    b.bar(x[target], 100-rec[target], 4.3, bottom=rec[target], color='white', ec=COL['pmt'], lw=.5,
          hatch='//////', zorder=2)
    b.bar(x[~target], rec[~target], 4.3, color='white', ec=COL['pmt'], lw=.5, hatch='//////', zorder=2)
    b.plot([0, 40, 40, 100], [100, 100, 0, 0], color=COL['perfect_targeting'], lw=1.3, zorder=3)
    b.axhline(100, xmin=.4, xmax=1, color=COL['universal_cash'], lw=1.3, zorder=3)
    b.text(70, 102, 'Universal cash', color=INK, fontsize=6.4, ha='center', va='bottom')
    b.text(20, 102, 'Perfect targeting & universal', color=INK, fontsize=6.4, ha='center', va='bottom')
    q = meta['quadrants_pct']
    b.annotate(f"Exclusion error\n{100*meta['exclusion']:.1f}% of target", xy=(30, 90), xytext=(48, 74),
               fontsize=6.4, ha='left', va='center', arrowprops=dict(arrowstyle='-', lw=.5, color=MUTED))
    b.annotate(f"Leakage\n{100*meta['leakage']:.1f}% of recipients", xy=(52, 30), xytext=(62, 50),
               fontsize=6.4, ha='left', va='center', arrowprops=dict(arrowstyle='-', lw=.5, color=MUTED))
    b.set(ylim=(0, 112), yticks=range(0, 101, 20), ylabel='Persons receiving cash (%)', xlabel='Baseline income percentile')
    panel(b, 'b', 'Cash coverage under PMT', pad=13)
    h1, l1 = a.get_legend_handles_labels()
    extra = [Patch(fc=COL['pmt'], label='PMT recipients'),
             Patch(fc='white', ec=COL['pmt'], hatch='//////', lw=.5, label='PMT targeting error')]
    fig.legend(h1+extra, l1+[e.get_label() for e in extra], loc='lower center', ncol=4, bbox_to_anchor=(.5, -.13),
               fontsize=6.6, columnspacing=1.4)
    save(fig, 'Fig4_welfare_incidence',
         'Distributional incidence across twenty person-weighted bins of baseline equivalent income. '
         '(a) Household money-metric change in real consumption relative to the pre-shock benchmark, normalised by '
         'initial spending; the dotted vertical line marks the target population (bottom 40%). '
         '(b) Share of persons receiving cash under out-of-fold PMT targeting. Hatched areas show exclusion of '
         'eligible people (left of the threshold) and receipt by non-target people (right of the threshold); '
         'perfect targeting and universal cash are shown as reference lines. Exclusion and leakage are '
         'equal because coverage is fixed at the size of the target population.')


# ---------------------------------------------------------------- Figure 5
def fig5_targeting_errors():
    s5 = tab('S5_error_grid_summary', True)
    t7 = tab('Table7_score_degradation')
    ci = tab('Table4_conditional_intervals')
    meta = json.loads((DATA/'profile_metadata.json').read_text(encoding='utf-8'))
    piv = s5.pivot(index='exclusion', columns='leakage', values='mean_difference_pp')
    X, Y, Z = 100*piv.columns.to_numpy(), 100*piv.index.to_numpy(), piv.to_numpy()
    lim = .55
    fig, (a, b) = plt.subplots(1, 2, figsize=(DOUBLE, 2.95), gridspec_kw=dict(width_ratios=[1.12, 1], wspace=.52))
    a.add_patch(Rectangle((0, 0), 100, 100, fc='#F5F5F5', ec='#CFCFCF', hatch='/////', lw=0, zorder=0))
    levels = np.arange(-lim, lim+1e-9, .05)
    cf = a.contourf(X, Y, Z, levels=levels, cmap=DIVERGE, norm=TwoSlopeNorm(0, -lim, lim), zorder=1)
    cs = a.contour(X, Y, Z, levels=[-.4, -.3, -.2, -.1, .1, .2, .3], colors='white', linewidths=.5, zorder=2)
    a.clabel(cs, fmt=lambda v: num(v, '.1f', True), fontsize=5.6, inline_spacing=2)
    a.contour(X, Y, Z, levels=[0], colors=INK, linewidths=1.2, zorder=3)
    a.plot([0, 95], [0, 95], color=INK, lw=.6, ls=(0, (3, 2)), zorder=3)
    a.text(31, 14, 'fixed coverage\n(exclusion = leakage)', fontsize=5.9, color=INK, ha='left', va='center',
           bbox=dict(fc='white', ec='none', alpha=.75, pad=1))
    q = t7[t7.level != 'independent']
    a.plot(q.mean_leakage_pct, q.mean_exclusion_pct, 'o', ms=2.8, color='white', mec=INK, mew=.6, zorder=4)
    ex = 100*meta['exclusion']
    a.plot(ex, ex, '*', ms=9, color=COL['pmt'], mec=INK, mew=.6, zorder=5)
    a.annotate('OOF PMT', (ex, ex), xytext=(-24, 14), textcoords='offset points', fontsize=6.4,
               arrowprops=dict(arrowstyle='-', lw=.5, color=INK))
    a.text(57, 30, 'break-even', rotation=-84, fontsize=6.2, color=INK, ha='center',
           path_effects=[pe.withStroke(linewidth=1.6, foreground='white')])
    a.text(97, 6, 'infeasible:\ncoverage exceeds\nnon-target\npopulation', fontsize=5.8, color=MUTED, ha='right',
           va='bottom', bbox=dict(fc='white', ec='none', pad=1))
    a.set(xlim=(0, 95), ylim=(0, 95), xticks=range(0, 91, 15), yticks=range(0, 91, 15),
          xlabel='Leakage: cash paid outside target population (%)', ylabel='Exclusion of target population (%)')
    cb = fig.colorbar(cf, ax=a, fraction=.05, pad=.03, ticks=[-.5, -.25, 0, .25, .5])
    cb.set_label('FGT1, targeted − universal (pp)', fontsize=6.8)
    cb.ax.tick_params(labelsize=6.3, width=.5, length=2); cb.outline.set_linewidth(.5)
    cb.ax.text(.5, -.02, 'targeted\nbetter', transform=cb.ax.transAxes, ha='center', va='top', fontsize=5.6, color=MUTED)
    cb.ax.text(.5, 1.02, 'universal\nbetter', transform=cb.ax.transAxes, ha='center', va='bottom', fontsize=5.6, color=MUTED)
    panel(a, 'a', 'Error surface, random selection', pad=12)

    d = s5[(s5.exclusion-s5.leakage).abs() < 1e-9].sort_values('exclusion')
    zero_line(b)
    b.fill_between(100*d.exclusion, d.min_seed_difference_pp, d.max_seed_difference_pp, color='#BDBDBD', alpha=.5, lw=0)
    b.plot(100*d.exclusion, d.mean_difference_pp, '-', color='#6B6B6B', lw=1.2, label='Random selection within strata')
    b.fill_between(q.mean_exclusion_pct, q.lower95_pp, q.upper95_pp, color=COL['pmt'], alpha=.22, lw=0)
    b.plot(q.mean_exclusion_pct, q.difference_vs_universal_pp, '-o', color=COL['pmt'], ms=3, mec='white', mew=.4,
           label='Score-based selection (noisy PMT)')
    r = ci[(ci.policy_a == 'pmt') & (ci.policy_b == 'universal_cash')].iloc[0]
    b.errorbar(ex, r.difference_pp, yerr=[[r.difference_pp-r.lower95_pp], [r.upper95_pp-r.difference_pp]], fmt='*',
               ms=8, color=COL['pmt'], mec=INK, mew=.5, ecolor=INK, elinewidth=.7, capsize=2, label='Out-of-fold PMT', zorder=5)
    ind = t7[t7.level == 'independent'].iloc[0]
    b.errorbar(ind.mean_exclusion_pct, ind.difference_vs_universal_pp,
               yerr=[[ind.difference_vs_universal_pp-ind.lower95_pp], [ind.upper95_pp-ind.difference_vs_universal_pp]],
               fmt='D', ms=3.8, color='white', mec=INK, mew=.8, ecolor=INK, elinewidth=.7, capsize=2,
               label='Independent (uninformative) score', zorder=5)
    for _, rr in q.iterrows():
        if rr.r2 in (.4, 0., -1., -8.):
            b.annotate(f'R² = {num(rr.r2, "g")}', (rr.mean_exclusion_pct, rr.difference_vs_universal_pp),
                       xytext=(4, -9), textcoords='offset points', fontsize=5.8, color=MUTED)
    # Composition gap at the PMT error rate.
    # Use the exact matched-recipient experiment, rather than interpolate the grid.
    matched=tab('Table6_recipient_composition')
    uni=tab('Table1_main_policy_results').set_index('policy').loc['universal_cash','fgt1_pct']
    rnd=matched.error_matched_fgt1_pct.mean()-uni
    b.plot(ex,rnd,'o',ms=2.8,color='#6B6B6B',zorder=5)
    b.annotate('', (ex-1.2, r.difference_pp+.012), (ex-1.2, rnd), arrowprops=dict(arrowstyle='<->', lw=.6, color=INK,
               shrinkA=0, shrinkB=0))
    b.annotate(f'{num(r.difference_pp-rnd, ".3f", True)} pp from\nwho is selected', (ex-1.4, (rnd+r.difference_pp)/2),
               xytext=(36, -.47), textcoords='data', fontsize=6, ha='left', va='center', color=INK,
               arrowprops=dict(arrowstyle='-', lw=.5, color=MUTED, shrinkA=1, shrinkB=1))
    b.set(xlim=(0, 92), ylim=(-.56, .3), xlabel='Exclusion = leakage at fixed coverage (%)',
          ylabel='FGT1, targeted − universal (pp)')
    b.grid(axis='y')
    b.legend(loc='upper left', fontsize=6.2)
    panel(b, 'b', 'Same error rates, different recipients', pad=12)
    save(fig, 'Fig5_targeting_errors',
         'Targeting errors and the policy ranking. (a) Mean FGT1 difference between targeted and universal cash '
         'over exclusion and leakage rates, with random selection stratified by quintile '
         '(ten draws per cell; each leakage level is a separately solved equilibrium). Contours interpolate the evaluated '
         'grid; the black contour marks equal mean poverty gaps and hatched space is infeasible. Open circles and the '
         'PMT star mark error coordinates only; their welfare values follow the score-selection experiment in panel (b). '
         'All lie on the fixed-coverage diagonal. (b) The same comparison along '
         'that diagonal. Random selection (grey; band = range across draws) is contrasted with selection by '
         'increasingly noisy PMT scores (blue; band = joint 95% interval over recipient seeds and household '
         'multipliers), labelled by out-of-fold R². The vertical arrow is the gain from ranking recipients by the '
         'PMT score instead of drawing them at random at the same error rates. Its random-policy endpoint uses '
         'the exact error-matched experiment averaged over 30 draws; the grey line interpolates grid-node means.')


# ---------------------------------------------------------------- Figure 6
def fig6_decomposition():
    t6 = tab('Table6_recipient_composition')
    t1 = tab('Table1_main_policy_results').set_index('policy')
    uni, perf = t1.loc['universal_cash', 'fgt1_pct'], t1.loc['perfect_targeting', 'fgt1_pct']
    pm = t6.pmt_fgt1_pct.mean()-uni
    em = t6.error_matched_fgt1_pct-uni
    gm = t6.group_matched_fgt1_pct-uni
    steps = [  # label, start, end, kind, range
        ('Universal\ncash', 0, 0, 'total', None, COL['universal_cash']),
        ('Random\nselection at\nPMT error rates', 0, em.mean(), 'total', (em.min(), em.max()), '#9C9C9C'),
        ('Between-\nquintile\nallocation', em.mean(), gm.mean(), 'step', (t6.between_group_allocation_pp.min(),
                                                                       t6.between_group_allocation_pp.max()), '#9CCBE8'),
        ('Within-\nquintile\nselection', gm.mean(), pm, 'step', (t6.within_group_selection_pp.min(),
                                                              t6.within_group_selection_pp.max()), '#9CCBE8'),
        ('Out-of-fold\nPMT', 0, pm, 'total', None, COL['pmt']),
        ('Gap to\nperfect\ntargeting', pm, perf-uni, 'step', None, '#A9BCD6'),
        ('Perfect\ntargeting', 0, perf-uni, 'total', None, COL['perfect_targeting'])]
    fig, ax = plt.subplots(figsize=(ONEHALF, 2.75))
    zero_line(ax)
    w = .62
    for i, (name, s, e, kind, rng, colr) in enumerate(steps):
        if abs(e-s) < 1e-12:
            ax.plot([i-w/2, i+w/2], [0, 0], color=colr, lw=2.2, solid_capstyle='butt', zorder=3)
            ax.text(i, .012, '0', ha='center', va='bottom', fontsize=6.5)
        else:
            ax.bar(i, e-s, w, bottom=s, color=colr, zorder=2, ec='white', lw=.4)
            ax.text(i, min(s, e)-.012, num(e-s), ha='center', va='top', fontsize=6.5,
                    fontweight='bold' if kind == 'total' else 'normal')
        if rng is not None:
            lo, hi = (s+rng[0], s+rng[1]) if kind == 'step' else rng
            ax.plot([i, i], [lo, hi], color=INK, lw=.7, zorder=4)
            ax.plot([i-.07, i+.07], [lo, lo], color=INK, lw=.7, zorder=4)
            ax.plot([i-.07, i+.07], [hi, hi], color=INK, lw=.7, zorder=4)
        if i < len(steps)-1:
            nxt_s = steps[i+1][1]
            ax.plot([i+w/2, i+1-w/2], [e, e] if steps[i+1][3] == 'step' else [nxt_s, nxt_s], color=FAINT, lw=.5,
                    ls=(0, (2, 1.5)), zorder=1) if steps[i+1][3] == 'step' else None
    yb = -.455
    ax.plot([1.7, 1.7, 3.3, 3.3], [yb+.012, yb, yb, yb+.012], color=MUTED, lw=.6)
    ax.text(2.5, yb-.012, f'Recipient composition: {num(pm-em.mean())} pp', ha='center', va='top', fontsize=6.3,
            color=INK)
    ax.set(xticks=range(len(steps)), ylim=(-.6, .06), xlim=(-.5, len(steps)-.5),
           ylabel='FGT1 relative to universal cash (pp)')
    ax.set_xticklabels([s[0] for s in steps], fontsize=6.5)
    ax.tick_params(axis='x', length=0)
    ax.grid(axis='y', zorder=0)
    save(fig, 'Fig6_composition_decomposition',
         'Sequential decomposition of the PMT advantage over universal cash. Totals (solid bars) are FGT1 levels relative '
         'to universal cash; floating bars are additive steps. "Random selection at PMT error rates" preserves the PMT '
         'aggregate exclusion and leakage but draws recipients proportionally within eligible and non-eligible strata. '
         'Holding instead the PMT recipient count in every quintile and randomising within quintiles isolates the '
         'between-quintile allocation; the final step to PMT is within-quintile selection. Whiskers show the range '
         'across 30 matched recipient draws. The last step is the remaining distance to error-free targeting.')


# ---------------------------------------------------------------- Supplementary
GROUPS_S1 = [
    ('Shock', [('main', 'Main: food +20%, energy +40%'), ('food_only', 'Food shock only'),
               ('energy_only', 'Energy shock only'), ('mild_joint', 'Mild joint shock (×0.5)'),
               ('severe_joint', 'Severe joint shock (×2)'), ('symmetric_world_prices', 'Export prices also shocked')]),
    ('Fiscal envelope', [('low_budget', 'Budget 0.25% of GDP'), ('high_budget', 'Budget 1.0% of GDP')]),
    ('Behavioural parameters', [('low_trade_elasticity', 'Armington/CET −25%'), ('high_trade_elasticity', 'Armington/CET +25%'),
                                ('low_factor_elasticity', 'Factor substitution −25%'),
                                ('high_factor_elasticity', 'Factor substitution +25%')]),
    ('Programme design and closure', [('zero_admin', 'No administrative cost'), ('high_admin', 'Administrative cost 10%'),
                                      ('energy_support_only', 'Price support on energy only'),
                                      ('cash_saving_10pct', '10% of cash saved'),
                                      ('fixed_negative_investment', 'Negative investment items fixed')])]


def figS1_robustness():
    s = tab('S1_configuration_results', True).pivot(index='case', columns='policy', values='fgt1_pct')
    fig, (a, b) = plt.subplots(1, 2, figsize=(DOUBLE, 4.1), sharey=True,
                               gridspec_kw=dict(width_ratios=[1.6, 1], wspace=.08))
    y, ticks, labels, heads = 0, [], [], []
    for gname, items in GROUPS_S1:
        heads.append((y, gname)); y += 1
        for case, lab in items:
            d = s.loc[case]
            for k in ['perfect_targeting', 'pmt', 'price_support']:
                a.plot(d[k]-d.universal_cash, y, MRK[k], color=COL[k], ms=4.4, mec='white', mew=.5, zorder=3)
            a.plot([min(d.perfect_targeting, d.price_support)-d.universal_cash,
                    max(d.perfect_targeting, d.price_support)-d.universal_cash], [y, y], color=GRID, lw=.8, zorder=1)
            share = 100*(d.pmt-d.universal_cash)/(d.perfect_targeting-d.universal_cash)
            b.barh(y, share, .58, color=COL['pmt'], zorder=2)
            b.text(share-1.5, y, f'{share:.1f}', va='center', ha='right', fontsize=6.1, color='white')
            ticks.append(y); labels.append(lab); y += 1
        y += .3
    for yy, name in heads:
        a.text(-.012, yy, name, fontsize=7, fontweight='bold', va='center', ha='right',
               transform=a.get_yaxis_transform())
    a.set_yticks(ticks); a.set_yticklabels(labels, fontsize=6.6)
    a.set_ylim(y-.6, -.8)
    a.axvline(0, color=RULE, lw=.7)
    a.set(xlim=(-1.02, .3), xlabel='FGT1 difference relative to universal cash (pp)')
    a.grid(axis='x', zorder=0); a.tick_params(axis='y', length=0)
    a.legend(handles=[Line2D([], [], ls='', marker=MRK[k], color=COL[k], mec='white', label=LAB[k], ms=4.5)
                      for k in ['perfect_targeting', 'pmt', 'price_support']], loc='lower left', fontsize=6.4)
    panel(a, 'a', 'Policy differences')
    b.set(xlim=(0, 100), xlabel='PMT gain as share of perfect-targeting gain (%)')
    b.grid(axis='x', zorder=0); b.tick_params(axis='y', length=0)
    panel(b, 'b', 'Targeting potential captured by PMT')
    save(fig, 'FigS1_robustness',
         'Robustness of the policy comparison across seventeen configurations, each solved as a separate equal-net-cost '
         'equilibrium against its own same-shock no-policy reference. (a) FGT1 of perfect targeting, PMT and price support '
         'relative to universal cash. (b) PMT gain over universal cash as a share of the gain from perfect targeting. '
         'The full four-policy ranking (perfect targeting, PMT, universal cash, price support) holds in every configuration.',
         True)


SECTOR_NAMES = dict(zip([f'S{i:02d}' for i in range(64)], [
    'Crop & animal production', 'Forestry', 'Fishing & aquaculture', 'Mining & quarrying', 'Food, beverages & tobacco',
    'Textiles, apparel & leather', 'Wood products', 'Paper products', 'Printing', 'Coke & refined petroleum',
    'Chemicals', 'Pharmaceuticals', 'Rubber & plastics', 'Non-metallic minerals', 'Basic metals', 'Fabricated metals',
    'Computers & electronics', 'Electrical equipment', 'Machinery n.e.c.', 'Motor vehicles', 'Other transport equipment',
    'Furniture & other manufacturing', 'Repair & installation', 'Electricity, gas & steam', 'Water supply',
    'Sewerage & waste', 'Construction', 'Motor vehicle trade', 'Wholesale trade', 'Retail trade', 'Land transport',
    'Water transport', 'Air transport', 'Warehousing', 'Postal & courier', 'Accommodation & food service', 'Publishing',
    'Audiovisual & broadcasting', 'Telecommunications', 'IT services', 'Financial services', 'Insurance & pensions',
    'Auxiliary financial services', 'Real estate', 'Imputed rents', 'Legal, accounting & consulting',
    'Architecture & engineering', 'Scientific R&D', 'Advertising', 'Other professional services', 'Rental & leasing',
    'Employment services', 'Travel agencies', 'Security & business support', 'Public administration', 'Education',
    'Health', 'Residential care & social work', 'Arts & culture', 'Sports & recreation', 'Membership organisations',
    'Repair of personal goods', 'Other personal services', 'Households as employers']))


def figS2_sectors(n=22):
    d = tab('S3_sector_results', True)
    eq = json.loads((OUT/'equilibria/main_equilibria.json').read_text(encoding='utf-8'))
    shock = pd.DataFrame(eq['shock']['sectors']).set_index('sector').output_pct
    p = d.pivot(index='sector', columns='policy', values='output_pct')
    rel = (p.add(100).divide(shock.reindex(p.index)+100, axis=0)-1)*100
    nace = d.drop_duplicates('sector').set_index('sector').nace
    top = rel.abs().max(axis=1).nlargest(n).index
    rel = rel.loc[top].sort_values('price_support')
    fig, ax = plt.subplots(figsize=(ONEHALF, 4.1))
    yy = np.arange(len(rel))
    for i, s in enumerate(rel.index):
        if i % 2 == 0:
            ax.axhspan(i-.5, i+.5, color='#F5F5F5', lw=0, zorder=0)
        ax.plot([rel.loc[s].min(), rel.loc[s].max()], [i, i], color='#D0D0D0', lw=.8, zorder=1)
    for k in POL:
        ax.plot(rel[k], yy, MRK[k], color=COL[k], ms=4, mec='white', mew=.4, label=LAB[k], zorder=3)
    ax.axvline(0, color=RULE, lw=.7)
    ax.set_yticks(yy); ax.set_yticklabels([f'{SECTOR_NAMES[s]} ({nace[s]})' for s in rel.index], fontsize=6.4)
    ax.set(ylim=(-.6, len(rel)-.4), xlabel='Output change relative to same-shock no-policy equilibrium (%)')
    ax.grid(axis='x', zorder=0); ax.tick_params(axis='y', length=0)
    ax.legend(loc='lower right', fontsize=6.4, frameon=True, facecolor='white', edgecolor='none')
    save(fig, 'FigS2_sector_output',
         f'Incremental sectoral output responses to each instrument under the main configuration, measured against the '
         f'same-shock no-policy equilibrium. The {n} sectors with the largest absolute response under any instrument are '
         f'shown, ordered by the price-support response; Table S11 reports all 64 sectors.', True)


def figS3_macro():
    t = tab('Table2_main_macro_results').set_index('policy')
    order = ['shock']+POL
    fig, axs = plt.subplots(1, 3, figsize=(DOUBLE, 2.25), sharey=True, gridspec_kw=dict(wspace=.12))
    specs = [('real_gdp_baseprice_pct', 'Real GDP (% vs benchmark)', 'a', (-.34, 0)),
             ('investment_baseprice_pct', 'Real investment (% vs benchmark)', 'b', (-2.7, 0))]
    for ax, (col, lab, letter, xl) in zip(axs[:2], specs):
        for j, k in enumerate(order):
            v = t.loc[k, col]
            ax.barh(j, v, .6, color=COL[k], zorder=2)
            ax.text(v+.02*(xl[1]-xl[0]), j, num(v), ha='left', va='center', fontsize=6.2,
                    color=INK if k in ('pmt', 'universal_cash') else 'white')
        ax.set(xlim=xl, xlabel=lab); ax.grid(axis='x', zorder=0); ax.axvline(0, color=RULE, lw=.7)
        panel(ax, letter)
    ax = axs[2]
    for j, k in enumerate(order):
        if k == 'shock':
            continue
        cash, ps, adm = (t.loc[k, c] for c in ['net_cash_trillion_tl', 'price_support_trillion_tl', 'admin_cost_trillion_tl'])
        ax.barh(j, 1000*cash, .6, color=COL[k], zorder=2)
        ax.barh(j, 1000*ps, .6, left=1000*cash, color=COL[k], zorder=2)
        ax.barh(j, 1000*adm, .6, left=1000*(cash+ps), color='#BDBDBD', zorder=2, ec='white', lw=.3)
        ax.text(4, j, f'{1000*(cash+ps+adm):.1f}', va='center', fontsize=6.2, color=INK if k in ('pmt', 'universal_cash') else 'white')
    net = 1000*t.loc['pmt', 'net_fiscal_cost_trillion_tl']
    ax.axvline(net, color=INK, lw=.8, ls=(0, (3, 2)))
    ax.text(net-2, 0, f'net cost\n{net:.1f}', ha='right', va='center', fontsize=6.1)
    ax.set(xlim=(0, 160), xlabel='Gross programme outlay (billion TL)')
    ax.legend(handles=[Patch(color='#BDBDBD', label='Administration')], loc='upper left', fontsize=6.1,
              bbox_to_anchor=(0, 1.0))
    ax.grid(axis='x', zorder=0)
    panel(ax, 'c')
    axs[0].set_yticks(range(len(order))); axs[0].set_yticklabels([LAB[k] for k in order])
    axs[0].set_ylim(4.9, -.6)
    for a in axs:
        a.tick_params(axis='y', length=0)
    save(fig, 'FigS3_macro_fiscal',
         'Macroeconomic and fiscal adjustment under the main configuration. (a) Real GDP and (b) real investment at '
         'benchmark purchaser prices, relative to the pre-shock benchmark. (c) Gross programme outlay split into transfers '
         'or price relief and administrative purchases; the dashed line is the common net fiscal cost (0.5% of benchmark GDP). '
         'Gross and net costs differ because tax revenue and the price of fixed real public purchases respond endogenously. '
         'With fixed foreign saving, the fall in '
         'government saving is absorbed by savings-driven investment.', True)


def figS4_measurement():
    d = tab('S7_micro_sensitivity', True)
    fig, axs = plt.subplots(1, 3, figsize=(DOUBLE, 2.3), gridspec_kw=dict(wspace=.38))
    for ax, (m, name, letter) in zip(axs, [('fgt0_pct', 'Headcount, FGT0', 'a'), ('fgt1_pct', 'Poverty gap, FGT1', 'b'),
                                          ('fgt2_pct', 'Severity, FGT2', 'c')]):
        zero_line(ax)
        for hom, ls, fill, dx in [(False, '-', None, -.8), (True, (0, (2.5, 1.5)), 'white', .8)]:
            pv = d[d.homogeneous_within_quintile == hom].pivot(index='poverty_line_fraction', columns='policy', values=m)
            for k in ['perfect_targeting', 'pmt', 'price_support']:
                ax.plot(100*pv.index+dx, pv[k]-pv.universal_cash, ls=ls, marker=MRK[k], color=COL[k], ms=3.8,
                        mfc=fill or COL[k], mec=COL[k], mew=.8, lw=1.1)
        ax.set(xticks=[50, 60, 70], xlim=(46, 74), xlabel='Poverty line (% of median)')
        ax.grid(axis='y')
        panel(ax, letter, name)
    axs[0].set_ylabel('Difference vs universal cash (pp)')
    hs = [Line2D([], [], color=COL[k], marker=MRK[k], ms=3.8, label=LAB[k]) for k in ['perfect_targeting', 'pmt', 'price_support']]
    hs += [Line2D([], [], color=MUTED, ls='-', label='Household-specific baskets'),
           Line2D([], [], color=MUTED, ls=(0, (2.5, 1.5)), marker='o', mfc='white', ms=3.5, label='Quintile-average baskets')]
    fig.legend(handles=hs, loc='lower center', ncol=5, bbox_to_anchor=(.5, -.1), fontsize=6.3, columnspacing=1.2)
    save(fig, 'FigS4_measurement_sensitivity',
         'Sensitivity to welfare measurement. Equilibria and recipient rules are held fixed while the real poverty line '
         'is set at 50%, 60% or 70% of the benchmark median equivalent income, and household-specific expenditure baskets '
         '(solid) are replaced by quintile-average baskets (dashed, open markers). Each point is the difference from '
         'universal cash in the indicated FGT index.', True)


def figS5_pmt():
    hist = pd.read_csv(DATA/'pmt_prediction_histogram.csv')
    sc = pd.read_csv(DATA/'pmt_score_distribution.csv')
    meta = json.loads((DATA/'profile_metadata.json').read_text(encoding='utf-8'))
    fig, (a, b) = plt.subplots(1, 2, figsize=(DOUBLE, 2.85), gridspec_kw=dict(width_ratios=[1, 1.05], wspace=.32))
    xe = np.unique(np.r_[hist.actual_lo, hist.actual_hi]); ye = np.unique(np.r_[hist.pred_lo, hist.pred_hi])
    edges = np.linspace(9.0, 14.5, 111)
    H = np.full((110, 110), np.nan)
    i = np.searchsorted(edges, hist.actual_lo+1e-9)-1; j = np.searchsorted(edges, hist.pred_lo+1e-9)-1
    H[i, j] = hist.persons/hist.persons.sum()*100
    m = a.pcolormesh(edges, edges, H.T, cmap='Greys', norm=LogNorm(1e-3, np.nanmax(H)))
    xc, yc = meta['actual_cutoff_log1p'], meta['predicted_cutoff_log1p']
    a.axvline(xc, color=COL['perfect_targeting'], lw=.9); a.axhline(yc, color=COL['pmt'], lw=.9)
    a.plot([9, 14.5], [9, 14.5], color=FAINT, lw=.6, ls=(0, (3, 2)))
    q = meta['quadrants_pct']
    lab = dict(fontsize=6.4, ha='center', va='center', bbox=dict(fc='white', ec='none', alpha=.85, pad=1.2))
    a.text(10.75, 11.0, f"Correctly included\n{q['correct_inclusion']:.1f}%", **lab)
    a.text(10.75, 13.55, f"Excluded eligible\n{q['exclusion_error']:.1f}%", **lab)
    a.text(13.55, 11.0, f"Included ineligible\n{q['inclusion_error']:.1f}%", **lab)
    a.text(13.55, 13.55, f"Correctly excluded\n{q['correct_exclusion']:.1f}%", **lab)
    a.set(xlim=(9.6, 14.5), ylim=(10.3, 14.4), xlabel='Actual log equivalent income',
          ylabel='Out-of-fold predicted log equivalent income')
    a.text(xc+.05, 10.38, 'eligibility\nthreshold', fontsize=5.8, color=COL['perfect_targeting'], va='bottom')
    a.text(14.45, yc+.05, 'PMT cut-off', fontsize=5.8, color=INK, ha='right', va='bottom')
    cb = fig.colorbar(m, ax=a, fraction=.045, pad=.02)
    cb.set_label('Persons per cell (%)', fontsize=6.5); cb.ax.tick_params(labelsize=6, width=.5); cb.outline.set_linewidth(.5)
    panel(a, 'a', f"Prediction accuracy (weighted R² = {meta['weighted_oof_r2']:.2f})")
    for g, colr, name in [('eligible', COL['perfect_targeting'], 'Target population (bottom 40%)'),
                          ('ineligible', FAINT, 'Non-target population')]:
        s = sc[sc.group == g]; mid = (s.lo+s.hi)/2; dens = s.persons_pct/(s.hi-s.lo)
        b.fill_between(mid, dens, color=colr, alpha=.25, lw=0, step='mid')
        b.step(mid, dens, where='mid', color=colr, lw=1.1, label=name)
    b.set_ylim(0, 1.4*(sc.persons_pct/(sc.hi-sc.lo)).max())
    b.axvline(yc, color=INK, lw=.9)
    b.text(yc-.05, b.get_ylim()[1]*.97, '← cash', ha='right', va='top', fontsize=6.3)
    b.text(yc+.05, b.get_ylim()[1]*.97, 'no cash →', ha='left', va='top', fontsize=6.3)
    b.set(xlabel='Out-of-fold predicted log equivalent income', ylabel='Population density (% per log unit)')
    b.legend(loc='upper right', fontsize=6.4, bbox_to_anchor=(1, .9))
    panel(b, 'b', 'Score distributions by eligibility')
    save(fig, 'FigS5_pmt_diagnostics',
         'Out-of-fold proxy-means test. (a) Person-weighted joint distribution of actual and predicted log equivalent '
         'income (log colour scale). The vertical line is the eligibility threshold (bottom 40%) and the horizontal line '
         'the PMT cut-off that fixes coverage at the size of the target population; quadrant labels give population shares. '
         '(b) Distributions of the predicted score for the target and non-target populations. Predictions come from a '
         'five-fold cross-fitted ridge regression on housing, asset and demographic indicators; only aggregated cells '
         'are plotted. Income axes refer to log(1 + equivalent income). Quadrant shares use the full sample; '
         f'the displayed window contains {meta["histogram_display_population_pct"]:.2f}% of weighted persons. '
         'Extreme observations are retained in the edge bins of the stored histograms.', True)


def main():
    CAPTIONS.clear()
    for f in [fig1_framework, fig2_exposure, fig3_poverty, fig4_incidence, fig5_targeting_errors, fig6_decomposition,
              figS1_robustness, figS2_sectors, figS3_macro, figS4_measurement, figS5_pmt]:
        f()
    txt = ['# Figure captions\n',
           'PDF and SVG (vector graphics), 600 dpi PNG and LZW-compressed TIFF are supplied for each figure. '
           'Widths follow journal column sizes: 190 mm (double), 140 mm (1.5 column).']
    for title, supp in [('Main figures', False), ('Supplementary figures', True)]:
        txt.append(f'\n## {title}\n')
        for name, cap, s in sorted(CAPTIONS,key=lambda item:(item[2],int(re.sub('[^0-9]','',item[0])))):
            if s == supp:
                txt.append(f'**{name}.** {cap}\n')
    (FIG/'Figure_Captions.md').write_text('\n'.join(txt), encoding='utf-8')


if __name__ == '__main__':
    main()
