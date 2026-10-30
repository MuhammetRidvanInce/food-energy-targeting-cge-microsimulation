"""Rebuild the preferred publication figure design and readable tables.

The user-provided reference layouts are integrated into figure_design.py.
Verified household profiles are rebuilt locally; CGE equilibria are reused.
"""
from common import *
import figure_design as design
import figure_profiles as profiles
LABELS=design.LAB
POLICIES=design.POL
COLORS=design.COL

def read(name,supp=False):
    return load_supplementary(name) if supp else pd.read_csv(OUT/'tables/main'/(name+'.csv'))

def md_table(df):
    def fmt(x):
        if pd.isna(x):return '—'
        if isinstance(x,(float,np.floating)):return f'{x:.3f}'
        return str(x).replace('|',' / ').replace('\n',' ')
    lines=['| '+' | '.join(map(str,df.columns))+' |','| '+' | '.join(['---']*len(df.columns))+' |']
    lines+=['| '+' | '.join(fmt(x) for x in row)+' |' for row in df.itertuples(index=False,name=None)]
    return '\n'.join(lines)

def readable_tables():
    d=read('Table1_main_policy_results')
    cols=['policy','fgt0_pct','fgt1_pct','fgt2_pct','gini','bottom40_ev_pct','bottom40_loser_pct']
    a=d[cols].copy();a.policy=a.policy.map(LABELS)
    a.columns=['Policy','FGT0 (%)','FGT1 (%)','FGT2 (%)','Gini','Bottom-40 EV (%)','Bottom-40 losers (%)']
    tables=[('Table 1. Main distributional results',a,
        'All monetary policy instruments face the same net fiscal cost. EV is household money-metric real consumption change relative to the benchmark, normalized by initial spending. Poverty indicators use person weights.')]
    a=read('Table2_main_macro_results')[['policy','net_cost_gdp_pct','net_cash_trillion_tl','price_support_trillion_tl','admin_cost_trillion_tl','consumer_discount_pct','investment_baseprice_pct']].copy()
    a.policy=a.policy.map(LABELS);a.columns=['Policy','Net cost / GDP (%)','Cash (trillion TL)','Price support (trillion TL)','Administration (trillion TL)','Price discount (%)','Real investment (%)']
    tables.append(('Table 2. Fiscal and macroeconomic outcomes',a,'The net budget is measured against the same-shock no-policy equilibrium. Gross spending incorporates endogenous tax feedback and administrative resource costs.'))
    a=read('Table3_quintile_results');a=a[a.policy.isin(POLICIES)][['policy','group','fgt1_pct','ev_pct','cpi_base100','recipient_person_pct','cash_share_pct']].copy()
    # Price support has no cash recipients despite the unit mask used in arithmetic code.
    a.loc[a.policy=='price_support','recipient_person_pct']=0
    a.policy=a.policy.map(LABELS);a.columns=['Policy','Quintile','FGT1 (%)','EV (%)','CPI (base 100)','Cash coverage (%)','Cash share (%)']
    a.loc[a.Policy=='Price support','Cash share (%)']=0
    tables.append(('Table 3. Quintile-level incidence',a,'Quintiles are held fixed at benchmark equivalent-income ranks. Group cash shares are set before solving the CGE.'))
    a=read('Table4_conditional_intervals');a.policy_a=a.policy_a.map(LABELS);a.policy_b=a.policy_b.map(LABELS)
    a.columns=['First policy','Comparator','Difference (pp)','Lower 95% (pp)','Upper 95% (pp)','Replications']
    tables.append(('Table 4. Paired conditional uncertainty',a,'Intervals condition on the CGE calibration, policy payments, poverty line and fitted PMT. Each household receives one common exponential multiplier across compared policies.'))
    a=read('Table5_targeting_thresholds').drop(columns='definition');a.iloc[:,:]=a*100
    a.columns=['Exclusion (%)','Last grid leakage favouring targeting (%)','First grid leakage favouring universal (%)','Maximum feasible grid leakage (%)']
    tables.append(('Table 5. First policy-ranking crossings on the targeting-error grid',a,'Leakage is evaluated in two-percentage-point steps. Brackets refer to means across ten recipient draws; blank brackets indicate that no crossing occurs within the feasible evaluated grid.'))
    raw=read('Table6_recipient_composition');rows=[]
    for col,label in [('within_group_selection_pp','Within-quintile selection'),('between_group_allocation_pp','Between-quintile allocation'),('total_composition_pp','Total composition difference')]:
        rows.append({'Component':label,'Mean (pp)':raw[col].mean(),'Minimum (pp)':raw[col].min(),'Maximum (pp)':raw[col].max()})
    tables.append(('Table 6. Recipient-composition decomposition',pd.DataFrame(rows),'The decomposition is sequential: PMT minus group-matched selection, plus group-matched minus error-matched selection. The two components add exactly to PMT minus error-matched selection. Ranges describe thirty matched randomizations.'))
    a=read('Table7_score_degradation').copy();a.columns=['Score experiment','R-squared','Exclusion (%)','Leakage (%)','FGT1 (%)','Difference vs universal (pp)','Lower 95% (pp)','Upper 95% (pp)','Recipient seeds']
    tables.append(('Table 7. Fixed-coverage score degradation',a,'Coverage equals the benchmark target population in every experiment. Conditional intervals jointly resample recipient seeds and household multipliers. The independent-score limit is a separately simulated allocation.'))
    pieces=['# Main analysis tables\n\nMachine-readable companion CSV files preserve full precision. Monetary amounts are in trillion TL unless indicated otherwise.']
    for title,df,note in tables:
        pieces.append(f'## {title}\n\n{md_table(df)}\n\n{note}')
    (OUT/'tables/main/Main_Tables.md').write_text('\n\n'.join(pieces)+'\n',encoding='utf-8')

def main():
    assert json.loads((OUT/'diagnostics/run_manifest.json').read_text(encoding='utf-8'))['status']=='complete'
    profiles.main()
    design.main()
    readable_tables()
    data_files=sorted((OUT/'figures/data').glob('*'))
    dump(OUT/'diagnostics/figure_manifest.json',dict(
        figures=[dict(name=n,supplementary=s) for n,_,s in design.CAPTIONS],
        formats=['pdf','svg','png','tiff'],png_dpi=600,tiff_compression='LZW',
        source='computed stage-5 tables and independently verified aggregate household profiles',
        font='Arial',pdf_fonttype=42,
        reference_design='User-provided outputs/claude_figures (integrated into the project code)',
        profile_data_hashes={str(p.relative_to(ROOT)):sha(p) for p in data_files if p.is_file()},
        rendering_code_hashes={str((ROOT/'codes'/n).relative_to(ROOT)):sha(ROOT/'codes'/n)
                              for n in ['publication_outputs.py','figure_design.py','figure_profiles.py']}))

if __name__=='__main__':main()
