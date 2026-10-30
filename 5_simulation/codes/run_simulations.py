"""Run the complete stage-5 analysis. python -B codes/run_simulations.py

No legacy numerical outputs are read. All GE equilibria use the current 64-sector
stage-4 engine and the frozen stage-5 SAM/elasticity inputs.
"""
import os
for key in ['OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS']:
    os.environ.setdefault(key,'1')
import time, platform, importlib.metadata
from common import *
from policy_model import *
from micro_simulation import *

def main():
    started=time.time(); cfgs=configurations()
    for sub in ['diagnostics','equilibria','tables/main','tables/supplementary','figures/main','figures/supplementary','figures/data','reports']:
        (OUT/sub).mkdir(parents=True,exist_ok=True)
    dump(OUT/'diagnostics/run_manifest.json',dict(status='running',started_unix=started))
    tracked=[SAM,ELASTICITIES,PROJECT/'4_cge_model/codes/cge_model.py']
    tracked += [MICRO/x for x in ['hane_cd_2024.csv','fert_cd_2024.csv','tuketim_cd_2024.csv']]
    tracked += [ROOT/'codes'/name for name in
                ['common.py','micro_simulation.py','policy_model.py','run_simulations.py']]
    hashes={source_key(p):sha(p) for p in tracked}
    dump(DATA/'analysis_design.json',dict(seed=SEED,configurations=cfgs,
        monetary_unit='trillion TL in all stage-5 calculations and equilibrium files',
        imported_sam_unit='thousand TRY, converted by stage 4 using 1e9',
        main_budget='0.5% of benchmark GDP; identical fall in government savings relative to same-shock no-policy equilibrium',
        administration='3% of gross cash program spending; purchases of public administration services S54',
        target='bottom two person-weighted equivalent-income quintiles',
        benefit='equal per recipient person, full benefit with split weights for fractional boundary households',
        poverty='fixed real 60% of baseline person-weighted median equivalent HBS annual disposable income',
        linkage='group allocation enters CGE before solution; within-group arithmetic microsimulation follows',
        uncertainty='1000 paired household exponential multipliers, conditional on calibrated equilibrium, PMT and transfer amounts',
        grid=dict(exclusion=[0,.1,.2,.3,.4,.5,.6,.7,.8,.9,.95],leakage_step=.02,max_leakage=.94,recipient_seeds=10),
        score_design='OOF log-income scores plus synthetic normal noise, fixed target-population coverage; 10 recipient seeds per level',
        source_hashes=hashes))
    base=build(cfgs['main']);base_check=cge.solve_model(base)
    micro,h,f=prepare_micro(base)
    pmt_mask,pred,y,pmt_report=fit_pmt(micro,h,f)
    n=len(pmt_mask); zeros=np.zeros(n); ones=np.ones(n)
    perfect=(micro['group']<2).astype(float)
    masks={'perfect_targeting':perfect,'pmt':pmt_mask,'universal_cash':ones,'price_support':ones}
    main_states={};main_contrib={};metrics_rows=[];macro_rows=[];group_rows=[];sector_rows=[]
    valid=[dict(label='benchmark',**base_check,max_sam_account_gap_trillion_tl=check_policy_sam(base))]
    baseline=snapshot(base,base)
    vals,gr,fc=household_outcomes(baseline,micro,zeros)
    metrics_rows.append(dict(case='main',policy='baseline',**vals));macro_rows.append(dict(case='main',policy='baseline',**baseline['macro']))
    main_states['baseline']=baseline;main_contrib['baseline']=fc
    group_rows.extend(dict(policy='baseline',**r) for r in gr)
    main_shock=None

    def solve_policy(shock,b,cfg,mask,kind,label):
        shares=group_shares(micro,mask)
        pol,d=policy_model(shock,cfg,kind,shares,gdp(b)*cfg['budget'])
        d['max_sam_account_gap_trillion_tl']=check_policy_sam(pol)
        valid.append(dict(label=label,**d))
        st=snapshot(pol,b,shares=shares,cash_saving=cfg['cash_saving'],reference_sg=pyo.value(shock.Sg))
        return st

    for j,(case,cfg) in enumerate(cfgs.items()):
        print(f'Configuration {j+1}/{len(cfgs)}: {case}',flush=True)
        b=base if case=='main' else build(cfg)
        if case!='main':cge.solve_model(b)
        sh=shock_model(b,cfg)
        valid.append(dict(label=f'{case}/shock',**cge.diagnostics(sh),max_sam_account_gap_trillion_tl=check_policy_sam(sh)))
        st=snapshot(sh,b)
        vals,gr,fc=household_outcomes(st,micro,zeros)
        metrics_rows.append(dict(case=case,policy='shock',**vals));macro_rows.append(dict(case=case,policy='shock',**st['macro']))
        if case=='main':
            main_shock=sh;main_states['shock']=st;main_contrib['shock']=fc
            group_rows.extend(dict(policy='shock',**r) for r in gr)
        for policy,mask in masks.items():
            st=solve_policy(sh,b,cfg,mask,'price' if policy=='price_support' else 'cash',f'{case}/{policy}')
            vals,gr,fc=household_outcomes(st,micro,mask)
            metrics_rows.append(dict(case=case,policy=policy,**vals));macro_rows.append(dict(case=case,policy=policy,**st['macro']))
            if case=='main':
                main_states[policy]=st;main_contrib[policy]=fc
                group_rows.extend(dict(policy=policy,**r) for r in gr)
                sector_rows.extend(dict(policy=policy,**r) for r in st['sectors'])
        table('S1_configuration_results',metrics_rows,True)
        table('S2_macro_results',macro_rows,True)
        dump(OUT/'diagnostics/equilibrium_checks.json',valid)
    table('Table1_main_policy_results',[r for r in metrics_rows if r['case']=='main'])
    table('Table2_main_macro_results',[r for r in macro_rows if r['case']=='main'])
    table('Table3_quintile_results',group_rows)
    table('S3_sector_results',sector_rows,True)
    dump(OUT/'equilibria/main_equilibria.json',main_states)
    pairs=[('perfect_targeting','universal_cash'),('pmt','universal_cash'),('universal_cash','price_support'),('pmt','price_support')]
    intervals=paired_intervals(main_contrib,micro,pairs)
    table('Table4_conditional_intervals',intervals)
    uni=float(np.average(main_contrib['universal_cash'],weights=micro['pw']))
    cfg=cfgs['main']; grid_rows=[]; threshold_rows=[]
    print('Targeting-error surface: 48 leakage levels, 10 recipient draws',flush=True)
    pop=np.bincount(micro['group'],weights=micro['pw'],minlength=5)
    for li,leak in enumerate(np.round(np.arange(0,.941,.02),2)):
        shares=np.r_[(1-leak)*pop[:2]/pop[:2].sum(),leak*pop[2:]/pop[2:].sum()]
        pol,d=policy_model(main_shock,cfg,'cash',shares,gdp(base)*cfg['budget'])
        valid.append(dict(label=f'grid/leak_{leak:.2f}',**d,max_sam_account_gap_trillion_tl=check_policy_sam(pol)))
        st=snapshot(pol,base,shares=shares,reference_sg=pyo.value(main_shock.Sg))
        for exclusion in [0,.1,.2,.3,.4,.5,.6,.7,.8,.9,.95]:
            for seed in range(10):
                mask=random_receipt(micro,exclusion,float(leak),SEED+seed)
                if mask is None:continue
                vals,_,_=household_outcomes(st,micro,mask)
                grid_rows.append(dict(exclusion=exclusion,leakage=leak,seed=seed,
                    fgt1_pct=vals['fgt1_pct'],difference_vs_universal_pp=vals['fgt1_pct']-uni,
                    bottom40_ev_pct=vals['bottom40_ev_pct']))
        if li%8==0:print(f'  leakage {leak:.2f}',flush=True)
    grid=table('S4_error_grid_draws',grid_rows,True)
    grouped=grid.groupby(['exclusion','leakage'],as_index=False).agg(
        mean_difference_pp=('difference_vs_universal_pp','mean'),seed_sd_pp=('difference_vs_universal_pp','std'),
        min_seed_difference_pp=('difference_vs_universal_pp','min'),max_seed_difference_pp=('difference_vs_universal_pp','max'))
    table('S5_error_grid_summary',grouped,True)
    for e,sub in grouped.groupby('exclusion'):
        sub=sub.sort_values('leakage');cross=sub[sub.mean_difference_pp>=0]
        hi=None if cross.empty else float(cross.iloc[0].leakage)
        lo=None if hi is None else max(0.,round(hi-.02,2))
        threshold_rows.append(dict(exclusion=e,last_grid_leakage_targeting_better=lo,
            first_grid_leakage_universal_better=hi,max_feasible_grid_leakage=sub.leakage.max(),
            definition='First nonnegative mean FGT1(targeted)-FGT1(universal), bracketed on 0.02 grid'))
    table('Table5_targeting_thresholds',threshold_rows)

    print('Recipient composition: error-matched and group-matched policies',flush=True)
    match_rows=[];pmte=pmt_report['exclusion'];pmtl=pmt_report['leakage']
    error_mask=random_receipt(micro,pmte,pmtl,SEED)
    error_state=solve_policy(main_shock,base,cfg,error_mask,'cash','error_matched')
    for seed in range(30):
        group_mask=group_matched_receipt(micro,pmt_mask,SEED+seed)
        error_mask=random_receipt(micro,pmte,pmtl,SEED+seed)
        gv,_,_=household_outcomes(main_states['pmt'],micro,group_mask)
        ev,_,_=household_outcomes(error_state,micro,error_mask)
        pv=float(np.average(main_contrib['pmt'],weights=micro['pw']))
        match_rows.append(dict(seed=seed,pmt_fgt1_pct=pv,group_matched_fgt1_pct=gv['fgt1_pct'],
            error_matched_fgt1_pct=ev['fgt1_pct'],within_group_selection_pp=pv-gv['fgt1_pct'],
            between_group_allocation_pp=gv['fgt1_pct']-ev['fgt1_pct'],
            total_composition_pp=pv-ev['fgt1_pct']))
    table('Table6_recipient_composition',match_rows)

    print('Fixed-coverage score degradation and independent-score limit',flush=True)
    quality_rows=[];quality_summary=[]
    w=micro['pw'];target=w[perfect==1].sum();wm=lambda a:np.average(a,weights=w)
    variance=wm((y-wm(y))**2);error=pred-y
    levels=[.4,.3,.2,0.,-.5,-1.,-2.,-4.,-8.,None]
    for level in levels:
        contributions=[];exclusions=[];leakages=[];fgts=[]
        label='independent' if level is None else f'r2_{level:g}'
        for seed in range(10):
            rng=np.random.default_rng(SEED+100+seed);noise=rng.normal(size=n)
            noise-=wm(noise);noise/=np.sqrt(wm(noise**2))
            if level is None:score=noise
            else:
                target_mse=(1-level)*variance;cross=wm(error*noise)
                discriminant=cross**2+target_mse-wm(error**2)
                assert discriminant>=0
                scale=-cross+np.sqrt(discriminant);score=pred+scale*noise
                assert abs(r2_score(y,score,sample_weight=w)-level)<1e-10
            mask=exact_mask(w,np.argsort(score,kind='stable'),target)
            st=solve_policy(main_shock,base,cfg,mask,'cash',f'quality/{label}/{seed}')
            vals,_,fc=household_outcomes(st,micro,mask)
            er=errors(micro,mask)
            quality_rows.append(dict(level=label,r2=level,seed=seed,**er,**vals,
                difference_vs_universal_pp=vals['fgt1_pct']-uni))
            contributions.append(fc-main_contrib['universal_cash'])
            exclusions.append(er['exclusion']);leakages.append(er['leakage']);fgts.append(vals['fgt1_pct'])
        # Joint conditional interval: draw recipient seed and household multipliers.
        rng=np.random.default_rng(SEED+200);C=np.asarray(contributions);draws=[]
        for _ in range(1000):
            k=rng.integers(10);mw=w*rng.exponential(size=n)
            draws.append(np.average(C[k],weights=mw))
        lo,hi=np.quantile(draws,[.025,.975])
        quality_summary.append(dict(level=label,r2=level,mean_exclusion_pct=100*np.mean(exclusions),
            mean_leakage_pct=100*np.mean(leakages),mean_fgt1_pct=np.mean(fgts),
            difference_vs_universal_pp=np.mean(fgts)-uni,lower95_pp=lo,upper95_pp=hi,recipient_seeds=10))
        print(f'  {label}: mean difference {np.mean(fgts)-uni:+.4f} pp',flush=True)
    table('S6_score_degradation_draws',quality_rows,True)
    table('Table7_score_degradation',quality_summary)

    sensitivity=[]
    for frac in [.5,.6,.7]:
        for homogeneous in [False,True]:
            for policy,mask in masks.items():
                vals,_,_=household_outcomes(main_states[policy],micro,mask,
                    homogeneous=homogeneous,poverty_fraction=frac)
                sensitivity.append(dict(poverty_line_fraction=frac,homogeneous_within_quintile=homogeneous,policy=policy,**vals))
    table('S7_micro_sensitivity',sensitivity,True)
    el=cge.load_elasticities(ELASTICITIES).reset_index().rename(columns={'index':'sector'})
    for name in ['sigma','psi','omega']:
        el[name+'_source']=[cge.load_elasticities(ELASTICITIES).attrs['sources'][name][s] for s in SECTORS]
    table('S8_elasticity_assignment',el,True)
    dump(OUT/'diagnostics/equilibrium_checks.json',valid)
    dump(OUT/'diagnostics/uncertainty_design.json',dict(replications=1000,household_multiplier='independent Exponential(1)',
        paired=True,seed=SEED,conditional_on=['SHM calibration','CGE equilibrium','poverty line','PMT fitted model','policy amounts'],
        score_intervals='Recipient seed resampled in addition to household multipliers',
        additional_uncertainty=['survey strata and PSU structure','elasticity estimation','external PMT validity','model refitting'],
        interpretation='Conditional empirical-distribution intervals; macro/parameter uncertainty separately assessed by scenarios'))
    for path in tracked:assert hashes[source_key(path)]==sha(path),'Input changed during analysis'
    pivot=pd.DataFrame(metrics_rows)
    ranks=pivot[pivot.policy.isin(masks)].pivot(index='case',columns='policy',values='fgt1_pct')
    table('S9_policy_rankings',ranks.rank(axis=1).reset_index(),True)
    summary=dict(status='complete',elapsed_seconds=time.time()-started,configurations=len(cfgs),
        checked_policy_and_shock_equilibria=len(valid),baseline_gdp_trillion_tl=gdp(base),
        main_net_budget_trillion_tl=gdp(base)*cfg['budget'],
        main_results=[r for r in metrics_rows if r['case']=='main'],intervals=intervals,
        perfect_targeting_best_configurations=int((ranks.idxmin(axis=1)=='perfect_targeting').sum()),
        pmt_better_than_universal_configurations=int((ranks.pmt<ranks.universal_cash).sum()),
        pmt_design=pmt_report,score_summary=quality_summary,
        max_scaled_equation_residual=max(d['max_scaled_equation_residual'] for d in valid),
        max_relative_goods_gap=max(d['max_relative_goods_gap'] for d in valid),
        max_sam_account_gap_trillion_tl=max(d.get('max_sam_account_gap_trillion_tl',0) for d in valid),
        source_hashes=hashes,python=platform.python_version(),
        packages={k:importlib.metadata.version(k) for k in ['numpy','pandas','scipy','scikit-learn','pyomo','matplotlib','openpyxl']})
    dump(OUT/'diagnostics/run_manifest.json',summary)
    dump(OUT/'diagnostics/publication_run_summary.json',{k:summary[k] for k in ['baseline_gdp_trillion_tl','checked_policy_and_shock_equilibria','configurations']})
    from document_supplementary_tables import main as refresh_supplementary
    refresh_supplementary()
    print(f'COMPLETE: {len(valid)} checked equilibria, {time.time()-started:.1f}s',flush=True)

if __name__=='__main__':main()
