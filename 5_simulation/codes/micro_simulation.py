"""Survey bridge, cross-fitted PMT, exact weighted receipt and arithmetic microsimulation.

All record-level objects stay in memory. Monetary amounts use the CGE's internal
trillion-TL scale; observed income and the poverty line remain HBS annual TL.
"""
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.pipeline import make_pipeline
from sklearn.linear_model import Ridge
from sklearn.model_selection import KFold
from sklearn.metrics import r2_score
from common import *

def weighted_quantile(x, w, p):
    ix = np.argsort(x, kind='stable')
    return float(x[ix][np.searchsorted(np.cumsum(w[ix]), p*w.sum())])

def exact_mask(w, order, target):
    a = np.zeros(len(w))
    a[order] = np.clip((target-(np.cumsum(w[order])-w[order]))/w[order], 0, 1)
    assert abs(np.dot(a,w)-target) <= max(1e-7, target*1e-12)
    return a

def group_shares(micro, mask):
    mass = micro['pw']*mask
    return np.bincount(micro['group'], weights=mass, minlength=5)/mass.sum()

def errors(micro, mask):
    w=micro['pw']; eligible=micro['group']<2
    return dict(exclusion=1-np.dot(w[eligible],mask[eligible])/w[eligible].sum(),
                leakage=np.dot(w[~eligible],mask[~eligible])/np.dot(w,mask),
                coverage=np.dot(w,mask)/w.sum())

def prepare_micro(base):
    h=pd.read_csv(MICRO/'hane_cd_2024.csv', sep=';').copy()
    f=pd.read_csv(MICRO/'fert_cd_2024.csv', sep=';')
    t=pd.read_csv(MICRO/'tuketim_cd_2024.csv', sep=';')
    h['eq']=h.YILKULGEL/h.EFB_OECD
    h['pw']=h.FAKTOR*h.HHB
    h=h.sort_values(['eq','BIRIMNO'],kind='stable').reset_index(drop=True)
    g=np.minimum(4,((h.pw.cumsum()-h.pw/2)/h.pw.sum()*5).astype(int)).to_numpy()
    hw=h.FAKTOR.to_numpy(); pw=h.pw.to_numpy(); income=h.YILKULGEL.to_numpy()
    assert (hw>0).all() and (income>=0).all() and (h.EFB_OECD>0).all()
    assert f.groupby('BIRIMNO').INDEKS_ARL.nunique().max()==1
    def ps(cols):
        return (f[cols].fillna(0).sum(axis=1)*f.INDEKS_ARL).groupby(f.BIRIMNO).sum().reindex(h.BIRIMNO).to_numpy()
    wage=ps(['GELIR_NAKDI_UCRET_YEVMIYE','GELIR_NAKDI_IKRAMIYE_PRIM','GELIR_AYNI_UCRET_YEVMIYE'])
    mixed=ps(['GELIR_NAKDI_MUTESEBBIS','GELIR_AYNI_MUTESEBBIS','GELIR_TARIM_NET'])
    fin=ps(['GELIR_BANKA_TAHVIL','GELIR_BIREYSEL','GELIR_DIGER_MENKUL'])
    hi=f.groupby('BIRIMNO').INDEKS_ARL.first().reindex(h.BIRIMNO).to_numpy()
    rent=(h.GELIR_NAKDI_GAYRIMENKUL.fillna(0)+h.GELIR_AYNI_GAYRIMENKUL.fillna(0)).to_numpy()*hi
    lp=np.maximum(wage+.5*mixed,0)
    kp=np.maximum(fin+rent+12*h.KIRA_IZAFI.fillna(0).to_numpy()+.5*mixed,0)
    c=base._cal
    L=lp*c['Lh0'].sum()/np.dot(lp,hw); K=kp*c['Kh0'].sum()/np.dot(kp,hw)
    Y=income*c['Y0'].sum()/np.dot(income,hw); R=Y-L-K
    tax=(base._benchmark.sam.loc['DTAX',GROUPS]/c['Y0']).to_numpy()[g]
    income_scale=np.dot((1-tax)*Y,hw)/np.dot(income,hw)
    assert np.allclose((1-tax)*Y/income_scale, income, rtol=1e-10, atol=1e-6)
    t['code']=t.HBS_KOD5.astype(int).astype(str).str.zfill(5)
    pivot=t.pivot_table(index='code',columns='BIRIMNO',values='DEGER',aggfunc='sum',fill_value=0).reindex(columns=h.BIRIMNO,fill_value=0)
    bridge=pd.read_excel(SAM,sheet_name='Consumption_Bridge').set_index('Account')
    baskets=[]
    for s in SECTORS:
        expr=str(bridge.loc[s,'COICOP basket'])
        prefixes=tuple(x.strip().replace('*','') for x in expr.split('|'))
        match=np.ones(len(pivot),bool) if expr.strip()=='*' else pivot.index.str.startswith(prefixes)
        baskets.append(pivot.loc[match].sum(axis=0).to_numpy()*hw)
    baskets=np.asarray(baskets); matrix=np.zeros_like(baskets)
    gross=c['C0'].multiply(1+c['th'],axis=1).to_numpy()
    annual=h.HARCAMA.to_numpy()*12*hw
    checks=[]
    for k,q in enumerate(GROUPS):
        idx=g==k; row=gross[:,k]; col=annual[idx]/annual[idx].sum()*row.sum()
        share=baskets[:,idx]; denom=share.sum(axis=1)
        fallback=annual[idx]/annual[idx].sum()
        share=np.divide(share,denom[:,None],out=np.tile(fallback,(64,1)),where=denom[:,None]>0)
        block=row[:,None]*((1-1e-8)*share+1e-8*fallback)
        for it in range(1,10001):
            rs=block.sum(axis=1)
            block*=np.divide(row,rs,out=np.zeros_like(row),where=rs>0)[:,None]
            block*=col/block.sum(axis=0)
            err=max(np.max(abs(block.sum(axis=1)-row)/np.maximum(row,1e-14)),
                    np.max(abs(block.sum(axis=0)-col)/np.maximum(col,1e-14)))
            if err<1e-10:break
        else: raise ArithmeticError('Household IPF did not converge')
        matrix[:,idx]=block
        checks.append(dict(group=q,iterations=it,max_relative_margin_error=err))
    B0=matrix.sum(axis=0)/hw; beta=matrix/matrix.sum(axis=0)
    S0=(1-tax)*Y-B0
    group_checks=[]
    for k,q in enumerate(GROUPS):
        idx=g==k
        gaps={n:float(np.dot(x[idx],hw[idx])-c[col][q]) for n,x,col in
              [('L',L,'Lh0'),('K',K,'Kh0'),('Y',Y,'Y0'),('R',R,'R0'),('B',B0,'B0'),('S',S0,'Sp0')]}
        assert max(map(abs,gaps.values()))<1e-8, gaps
        assert np.isclose(pw[idx].sum(),base._benchmark.population[q])
        group_checks.append(dict(group=q,**gaps))
    m=dict(hw=hw,pw=pw,size=h.HHB.to_numpy(),equiv=h.EFB_OECD.to_numpy(),income=income,
           group=g,L=L,K=K,Y=Y,R=R,tax=tax,S0=S0,B0=B0,beta=beta,income_scale=income_scale,
           poverty_line=.6*weighted_quantile(income/h.EFB_OECD.to_numpy(),pw,.5))
    dump(OUT/'diagnostics/micro_calibration.json',dict(households=len(h),persons=len(f),expenses=len(t),
         ipf=checks,group_checks=group_checks,income_scale_trillion_tl_per_hbs_tl=income_scale,
         poverty_line_hbs_annual_equivalent_tl=m['poverty_line'],
         zero_income_households=int((income==0).sum()),raw_records_exported=False))
    return m,h,f

def fit_pmt(micro,h,f):
    categorical=['HH_TIP_HBA','KONUT_TIP','MULKIYET','ISITMA_SISTEM','YAKIT_TUR','BANYO','TUVALET',
        'BORULU_SU_SISTEM','DOGALGAZ','BILGISAYAR_SAHIP','INTERNET_SAHIP','BULASIK_MAKINE_SAHIP',
        'CAMASIR_KURUTMA_SAHIP','KLIMA_SAHIP','GARAJ','MUSKONUT_SAHIPLIGI','APARTMAN_SAHIPLIGI','YAZLIK_SAHIPLIGI']
    numeric=['HHB','ODA_SAYI','KONUT_ALAN','CEP_TELEFON_SAYI','OTOMOBIL_SAYI','MOTOSIKLET_SAYI']
    X=h[categorical+numeric].copy()
    for key,condition in [('children',f.YAS<15),('older',f.YAS>=65),('adults',(f.YAS>=15)&(f.YAS<65))]:
        X[key]=condition.groupby(f.BIRIMNO).sum().reindex(h.BIRIMNO).to_numpy(); numeric.append(key)
    first=f.sort_values(['BIRIMNO','FERTNO']).drop_duplicates('BIRIMNO').set_index('BIRIMNO')
    X['first_member_education']=first.OKUL_BITEN.reindex(h.BIRIMNO).to_numpy()
    categorical.append('first_member_education')
    X[categorical]=X[categorical].fillna(-999).astype(str)
    y=np.log1p(micro['income']/micro['equiv']); w=micro['pw']; pred=np.zeros(len(y))
    folds=KFold(5,shuffle=True,random_state=SEED)
    for train,test in folds.split(X):
        pre=ColumnTransformer([
            ('numeric',make_pipeline(SimpleImputer(strategy='median'),StandardScaler()),numeric),
            ('categorical',OneHotEncoder(handle_unknown='ignore'),categorical)])
        model=make_pipeline(pre,Ridge(alpha=10.,solver='lsqr'))
        model.fit(X.iloc[train],y[train],ridge__sample_weight=w[train]/w[train].mean())
        pred[test]=model.predict(X.iloc[test])
    mask=exact_mask(w,np.argsort(pred,kind='stable'),w[micro['group']<2].sum())
    report=dict(folds=5,seed=SEED,alpha=10,weighted_oof_r2=r2_score(y,pred,sample_weight=w),
        categorical_features=categorical,numeric_features=numeric,**errors(micro,mask),
        group_cash_shares=group_shares(micro,mask),
        method='Household-level out-of-fold ridge, person-weighted log1p equivalent income; fold-local preprocessing',
        interpretation='Within-survey validation; geographic and administrative transportability require external validation')
    dump(OUT/'diagnostics/pmt_design.json',report)
    return mask,pred,y,report

def random_receipt(micro,exclusion,leakage,seed,poorest_excluded=False):
    g=micro['group']; w=micro['pw']; ne=w[g<2].sum(); nn=w[g>=2].sum()
    outside=leakage/(1-leakage)*(1-exclusion)*ne/nn if leakage else 0.
    if outside>1+1e-12:return None
    rng=np.random.default_rng(seed); mask=np.zeros(len(w))
    for k in range(5):
        ix=np.flatnonzero(g==k)
        order=ix[np.argsort(-micro['income'][ix]/micro['equiv'][ix],kind='stable')] if poorest_excluded else rng.permutation(ix)
        mask+=exact_mask(w,order,w[ix].sum()*((1-exclusion) if k<2 else min(outside,1.)))
    e=errors(micro,mask)
    assert abs(e['exclusion']-exclusion)<1e-10 and abs(e['leakage']-leakage)<1e-10
    return mask

def group_matched_receipt(micro,reference,seed):
    w=micro['pw']; g=micro['group']; rng=np.random.default_rng(seed); a=np.zeros(len(w))
    for k in range(5):
        ix=np.flatnonzero(g==k)
        a+=exact_mask(w,rng.permutation(ix),np.dot(w[ix],reference[ix]))
    return a

def household_outcomes(state,micro,mask,*,homogeneous=False,poverty_fraction=.6):
    g=micro['group']; hw=micro['hw']; pw=micro['pw']
    beta=micro['beta']
    if homogeneous: beta=np.asarray(state['group_beta'])[:,g]
    # Ratios are 64 x 5: use each household's own group's purchaser-price base.
    ratio=np.asarray(state['price_ratios'])
    cpi=np.ones(len(g))
    for k in range(5):
        ix=g==k; cpi[ix]=np.exp(np.log(ratio[:,k])@beta[:,ix])
    yf=state['w']*micro['L']+state['r']*micro['K']+micro['R']*state['factor_index']
    disp=(1-micro['tax'])*yf
    budget0=disp-micro['S0']*np.asarray(state['group_income_factor'])[g]
    full=np.zeros(len(g)); shares=np.asarray(state['shares'])
    for k in range(5):
        ix=g==k; den=np.dot(pw[ix],mask[ix])
        amount=shares[k]*state['net_cash']
        if amount>1e-15:
            assert den>0
            full[ix]=amount*micro['size'][ix]/den
    expected_cash=full*mask
    consumption_cash=(1-state['cash_saving'])*full
    budget=budget0+consumption_cash*mask
    gaps=[abs(np.dot(hw[g==k],budget[g==k])-state['group_budget'][k]) for k in range(5)]
    assert max(gaps)<1e-8, gaps
    assert budget0.min()>0 and budget.min()>0
    eq0=disp/micro['income_scale']/micro['equiv']/cpi
    eq1=(disp+full)/micro['income_scale']/micro['equiv']/cpi
    line=micro['poverty_line']*poverty_fraction/.6
    gap0=np.maximum(1-eq0/line,0); gap1=np.maximum(1-eq1/line,0)
    fgt1=100*((1-mask)*gap0+mask*gap1)
    # Fractional survey boundary: full payment to recipient share, zero to others.
    fgt0=100*((1-mask)*(eq0<line)+mask*(eq1<line))
    fgt2=100*((1-mask)*gap0**2+mask*gap1**2)
    real0=budget0/cpi; real1=(budget0+consumption_cash)/cpi
    ev=(1-mask)*real0+mask*real1-micro['B0']
    # Ignore numerical roundoff at the unchanged benchmark.
    loss_cutoff=micro['B0']*(1-1e-10)
    loser=(1-mask)*(real0<loss_cutoff)+mask*(real1<loss_cutoff)
    # Aggregate post-transfer household demand is measured against the CGE basket.
    inferred=np.column_stack([(beta[:,g==k]*(budget[g==k]*hw[g==k])[None,:]).sum(axis=1) for k in range(5)])
    macro_exp=np.asarray(state['consumption_expenditure'])
    demand_gap=100*np.abs(inferred-macro_exp).sum()/macro_exp.sum()
    bottom=g<2
    vals=dict(fgt0_pct=np.average(fgt0,weights=pw),fgt1_pct=np.average(fgt1,weights=pw),
         fgt2_pct=np.average(fgt2,weights=pw),bottom40_ev_pct=100*np.dot(hw[bottom],ev[bottom])/np.dot(hw[bottom],micro['B0'][bottom]),
         all_ev_pct=100*np.dot(hw,ev)/np.dot(hw,micro['B0']),
         bottom40_loser_pct=100*np.average(loser[bottom],weights=pw[bottom]),
         micro_macro_demand_gap_pct=demand_gap,max_group_budget_gap_trillion_tl=max(gaps),
         negative_income_households=int((((eq0<0)&(mask<1))|((eq1<0)&(mask>0))).sum()))
    # Gini uses the same full-payment mixture as FGT, including fractional recipients.
    xx=np.r_[eq0,eq1]; ww=np.r_[pw*(1-mask),pw*mask]
    keep=ww>0;xx=xx[keep];ww=ww[keep]
    order=np.argsort(xx,kind='stable');xx=xx[order];ww=ww[order]
    vals['gini']=float(np.dot(ww*xx,2*np.cumsum(ww)-ww)/(ww.sum()*np.dot(ww,xx))-1)
    groups=[]
    for k,q in enumerate(GROUPS):
        ix=g==k
        groups.append(dict(group=q,fgt1_pct=np.average(fgt1[ix],weights=pw[ix]),
            fgt0_pct=np.average(fgt0[ix],weights=pw[ix]),cpi_base100=100*np.average(cpi[ix],weights=pw[ix]),
            ev_pct=100*np.dot(hw[ix],ev[ix])/np.dot(hw[ix],micro['B0'][ix]),
            recipient_person_pct=100*np.average(mask[ix],weights=pw[ix]) if state['net_cash']>0 else 0.,
            cash_share_pct=100*shares[k] if state['net_cash']>0 else 0.,
            loser_pct=100*np.average(loser[ix],weights=pw[ix])))
    return vals,groups,fgt1

def paired_intervals(contributions,micro,pairs,reps=1000):
    keys=list(contributions); mat=np.array([contributions[k] for k in keys]).T
    rng=np.random.default_rng(SEED); draws=[]
    for start in range(0,reps,100):
        w=rng.exponential(size=(min(100,reps-start),len(micro['pw'])))*micro['pw']
        draws.append((w@mat)/w.sum(axis=1)[:,None])
    draws=np.vstack(draws); rows=[]
    for a,b in pairs:
        difference=draws[:,keys.index(a)]-draws[:,keys.index(b)]
        lo,hi=np.quantile(difference,[.025,.975])
        point=np.average(contributions[a]-contributions[b],weights=micro['pw'])
        rows.append(dict(policy_a=a,policy_b=b,difference_pp=point,lower95_pp=lo,upper95_pp=hi,replications=reps))
    return rows
