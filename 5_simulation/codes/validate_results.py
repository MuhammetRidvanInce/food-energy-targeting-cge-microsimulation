"""Independent disk-level audit of the generated analysis and publication files."""
from common import *

def verify_source(path,expected):
    """Keep historical run hashes and recognise the recorded storage-only migration."""
    actual=sha(path)
    if actual==expected:return
    raise AssertionError(f'Source differs from the CES run manifest: {path}')


def main():
    r=json.loads((OUT/'diagnostics/run_manifest.json').read_text(encoding='utf-8'))
    assert r['status']=='complete'
    for relative,expected in r['source_hashes'].items():
        verify_source(PROJECT/relative,expected)
    checks=json.loads((OUT/'diagnostics/equilibrium_checks.json').read_text(encoding='utf-8'))
    assert len(checks)==r['checked_policy_and_shock_equilibria']
    for d in checks:
        for k in ['max_scaled_equation_residual','max_relative_goods_gap',
                  'household_budget_relative_gap','gdp_identity_relative_gap']:
            assert d[k]<1e-8,(d['label'],k)
        assert d['max_sam_account_gap_trillion_tl']<1e-8
        if 'equal_net_cost_relative_gap' in d:assert d['equal_net_cost_relative_gap']<1e-8
    configs=configurations()
    micro=load_supplementary('S1_configuration_results')
    macro=load_supplementary('S2_macro_results')
    policies=['perfect_targeting','pmt','universal_cash','price_support']
    for case,cfg in configs.items():
        rows=macro[(macro.case==case)&macro.policy.isin(policies)]
        assert len(rows)==4
        assert np.max(abs(rows.net_cost_gdp_pct-100*cfg['budget']))<1e-7
        assert np.max(abs(rows.gross_program_cost_trillion_tl-rows.net_cash_trillion_tl-
                          rows.price_support_trillion_tl-rows.admin_cost_trillion_tl))<1e-9
    assert np.isfinite(micro.select_dtypes('number')).all().all()
    assert micro.loc[micro.policy!='shock','negative_income_households'].max()==0
    boundary=json.loads((OUT/'diagnostics/income_boundary_check.json').read_text(encoding='utf-8'))
    assert boundary['policy_cases_with_negative_income']==0
    assert len(boundary['flagged_cases'])==int((micro.negative_income_households>0).sum())
    for case in boundary['flagged_cases']:
        assert abs(case['zero_floor_difference_pp'])<1e-5
    benchmark=micro[(micro.case=='main')&(micro.policy=='baseline')].iloc[0]
    assert abs(benchmark.all_ev_pct)<1e-8 and benchmark.bottom40_loser_pct==0
    assert micro.max_group_budget_gap_trillion_tl.max()<1e-8
    q=load_supplementary('S6_score_degradation_draws')
    assert len(q)==100 and np.max(abs(q.exclusion-q.leakage))<1e-9
    assert q.groupby('level').seed.nunique().eq(10).all()
    a=pd.read_csv(OUT/'tables/main/Table6_recipient_composition.csv')
    assert np.allclose(a.within_group_selection_pp+a.between_group_allocation_pp,a.total_composition_pp,atol=1e-9)
    ci=pd.read_csv(OUT/'tables/main/Table4_conditional_intervals.csv')
    assert (ci.lower95_pp<=ci.difference_pp).all() and (ci.upper95_pp>=ci.difference_pp).all()
    fm=json.loads((OUT/'diagnostics/figure_manifest.json').read_text(encoding='utf-8'))
    assert len(fm['figures'])==11
    for relative,expected in {**fm['profile_data_hashes'],**fm['rendering_code_hashes']}.items():
        verify_source(ROOT/relative,expected)
    profiles=pd.read_csv(OUT/'figures/data/income_bin_profiles.csv')
    profile_meta=json.loads((OUT/'figures/data/profile_metadata.json').read_text(encoding='utf-8'))
    assert len(profiles)==20 and abs(profiles.pop_share.sum()-1)<1e-8
    assert max(x['abs_gap'] for x in profile_meta['fgt1_reproduction'])<1e-8
    assert np.allclose(profiles.shock_cpi_food_pp+profiles.shock_cpi_energy_pp+profiles.shock_cpi_other_pp,
                       profiles.shock_cpi_pct,atol=1e-8)
    for p in policies:assert abs(profiles[f'benefit_share_{p}'].sum()-1)<1e-8
    assert abs(profile_meta['price_support_benefit_trillion_tl']-
               profile_meta['price_support_cost_table2_trillion_tl'])<1e-10
    for p,amount in profile_meta['cash_total_check'].items():
        recorded=macro[(macro.case=='main')&(macro.policy==p)].iloc[0].net_cash_trillion_tl
        assert abs(amount-recorded)<1e-10
    for path,expected in profile_meta['input_hashes'].items():assert sha(Path(path))==expected
    from pypdf import PdfReader
    figure_checks=[]
    for f in fm['figures']:
        folder=OUT/'figures'/('supplementary' if f['supplementary'] else 'main')
        for ext in fm['formats']:
            path=folder/f"{f['name']}.{ext}"
            assert path.stat().st_size>1000
        reader=PdfReader(folder/f"{f['name']}.pdf")
        assert len(reader.pages)==1
        assert len(reader.pages[0].extract_text().strip())>20
        figure_checks.append(dict(name=f['name'],pdf_pages=1,text_extractable=True))
    files=[p for p in OUT.rglob('*') if p.is_file() and p.name!='delivery_validation.json']
    audit=dict(status='passed',equilibria=len(checks),configurations=len(configs),score_draws=len(q),
        documented_income_boundary_cases=boundary['flagged_cases'],
        main_policy_fgt1=micro[(micro.case=='main')&micro.policy.isin(policies)][['policy','fgt1_pct']].to_dict('records'),
        figures=figure_checks,files={str(p.relative_to(ROOT)):sha(p) for p in sorted(files)},
        current_code_hashes={str(p.relative_to(ROOT)):sha(p) for p in sorted((ROOT/'codes').glob('*.py'))})
    dump(OUT/'diagnostics/delivery_validation.json',audit)
    print(f"PASS: {len(checks)} equilibria, {len(configs)} configurations, {len(q)} score draws, {len(figure_checks)} figures")

if __name__=='__main__':main()
