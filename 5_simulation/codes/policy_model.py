"""Equal-net-cost policy extension of stage 4, with explicit administrative purchases.

Named expressions are updated in place so all market, fiscal and income equations
continue to reference the same objects. Stage 4's source is not modified.
"""
import pyomo.environ as pyo
from common import *

def build(cfg):
    el=cge.load_elasticities(ELASTICITIES)
    return cge.build_model(sam_path=SAM,elasticities_path=ELASTICITIES,
        sigma=(el.sigma*cfg['trade_scale']).to_dict(),
        psi=(el.psi*cfg['trade_scale']).to_dict(),
        omega=(el.omega*cfg['factor_scale']).to_dict(),
        investment_closure=cfg['investment_closure'], household_sigma=cfg.get('household_sigma'),
        household_structure=cfg.get('household_structure'),household_nest_sigmas=cfg.get('household_nest_sigmas'))

def gdp(m):
    return pyo.value(m.factor_income+m.T-sum(m.Tdh[h] for h in m.h)-m.price_support_cost)

def shock_model(base,cfg):
    m=base.clone()
    prices={**{s:1+cfg['food'] for s in FOOD},**{s:1+cfg['energy'] for s in ENERGY}}
    cge.set_scenario(m,import_prices=prices,export_prices=prices if cfg['symmetric'] else None)
    cge.solve_model(m)
    return m

def policy_model(shock,cfg,kind,shares,budget):
    m=shock.clone(); c=m._cal; v=pyo.value
    m.policy_cash=pyo.Var(initialize=budget*(1-cfg['admin']),bounds=(0,None))
    m.policy_relief=pyo.Var(initialize=.02,bounds=(0,.95))
    if kind=='cash':m.policy_relief.fix(0.)
    elif kind=='price':m.policy_cash.fix(0.)
    else:raise ValueError(kind)
    shares=np.asarray(shares,dtype=float)
    assert np.isclose(shares.sum(),1) and (shares>=0).all()
    m.policy_admin=pyo.Expression(expr=cfg['admin']/(1-cfg['admin'])*m.policy_cash)
    m.admin_quantity=pyo.Expression(expr=m.policy_admin/m.pcg['S54'])
    for k,h in enumerate(GROUPS):
        m.Yh[h].set_value(m.Y_regular[h]+float(shares[k])*m.policy_cash)
        m.Sph[h].set_value(m.Sph[h].expr+cfg['cash_saving']*float(shares[k])*m.policy_cash)
    for i in m.i:
        if i in cfg['subsidy_sectors']:
            for h in m.h:m.pch[i,h].set_value((1-m.policy_relief)*m.pch_gross[i,h])
    m.cash_cost.set_value(m.policy_cash)
    m.price_support_cost.set_value(sum(m.policy_relief*m.pch_gross[i,h]*m.Ch[i,h]
                                      for i in cfg['subsidy_sectors'] for h in m.h))
    m.government_consumption_cost.set_value(m.government_consumption_cost.expr+m.policy_admin)
    m.Tg.set_value(m.Tg.expr+c['tg']*m.pq['S54']*m.admin_quantity)
    m.goods_gap['S54'].set_value(m.goods_gap['S54'].expr-m.admin_quantity)
    # Reference is the no-policy equilibrium under the SAME external shock.
    m.equal_net_cost=pyo.Constraint(expr=(v(shock.Sg)-m.Sg)/budget==1)
    m._policy_shares=shares; m._policy_cfg=cfg
    d=cge.solve_model(m)
    d['equal_net_cost_relative_gap']=abs(v(shock.Sg-m.Sg)-budget)/budget
    assert d['equal_net_cost_relative_gap']<1e-8
    # Validate ownership after cloning and named-expression extension.
    from pyomo.core.expr.visitor import identify_variables
    assert all(x.model() is m for con in m.component_data_objects(pyo.Constraint,active=True)
               for x in identify_variables(con.body,include_fixed=True))
    return m,d

def snapshot(m,base,*,shares=None,cash_saving=0.,reference_sg=None,budget=0.):
    v=pyo.value; c=m._cal
    has=hasattr(m,'policy_cash')
    cash=v(m.policy_cash) if has else 0.
    shares=np.zeros(5) if shares is None or cash==0 else np.asarray(shares)
    prices=np.array([[v(m.pch[i,h]) for h in GROUPS] for i in SECTORS])
    ratio=prices/(1+c['th'].to_numpy())[None,:]
    admin=v(m.policy_admin) if has else 0.
    d=cge.diagnostics(m)
    real_gdp=v(sum((1+c['th'][h])*m.Ch[i,h] for i in m.i for h in m.h)
        +sum((1+c['tg'])*m.G[i]+(1+c['ti'])*m.INV[i]+m.E[i]-m.M[i] for i in m.i))
    if has:real_gdp+=(1+c['tg'])*v(m.admin_quantity)
    macro=dict(gdp_nominal_trillion_tl=gdp(m),real_gdp_baseprice_pct=100*(real_gdp/gdp(base)-1),
        investment_baseprice_pct=100*(sum(v(m.INV[i]) for i in m.i)/c['V0'].sum()-1),
        exchange_rate=v(m.exchange_rate),capital_rental=v(m.r),
        net_fiscal_cost_trillion_tl=0 if reference_sg is None else reference_sg-v(m.Sg),
        net_cost_gdp_pct=0 if reference_sg is None else 100*(reference_sg-v(m.Sg))/gdp(base),
        net_cash_trillion_tl=cash,price_support_trillion_tl=v(m.price_support_cost),
        admin_cost_trillion_tl=admin,gross_program_cost_trillion_tl=cash+admin+v(m.price_support_cost),
        tax_revenue_trillion_tl=v(m.T),government_saving_trillion_tl=v(m.Sg),
        consumer_discount_pct=100*v(m.policy_relief) if has else 0.)
    sectors=[]
    for i in SECTORS:
        sectors.append(dict(sector=i,nace=str(base._benchmark.sectors.loc[i,'NACE']),
            output_pct=100*(v(m.Z[i])/c['Z0'][i]-1),composite_price_pct=100*(v(m.pq[i])-1),
            imports_volume_trillion_tl=v(m.M[i]),exports_volume_trillion_tl=v(m.E[i])))
    return dict(household_utility='nested_CES' if m._household_structure=='nested' else 'CES',
        household_sigma=[m._household_sigma[h] for h in GROUPS] if m._household_structure=='flat' else None,
        household_nest_sigmas={k:[values[h] for h in GROUPS] for k,values in m._household_nest_sigmas.items()},
        consumption_nests=m._consumption_nests,w=v(m.w),r=v(m.r),factor_index=v(m.factor_income)/c['X0'].sum(),
        group_income_factor=[v(m.Y_regular[h])/c['Y0'][h] for h in GROUPS],
        group_budget=[v(m.Bh[h]) for h in GROUPS],group_beta=c['beta'].to_numpy(),
        price_ratios=ratio,consumption_expenditure=np.array([[v(m.pch[i,h]*m.Ch[i,h]) for h in GROUPS] for i in SECTORS]),
        net_cash=cash,shares=shares,cash_saving=cash_saving,macro=macro,sectors=sectors,diagnostics=d)

def check_policy_sam(m):
    """Extend stage-4 reconstruction to endogenous cash, price relief and admin goods."""
    s=cge.solution_sam(m)/cge.SCALE; v=pyo.value
    assert v(m.L['S44'])==0 and v(m.K['S63'])==0
    assert all(v(comp[i])==0 for comp in [m.M,m.E] for i in ['S44','S63'])
    if hasattr(m,'policy_cash'):
        for k,h in enumerate(GROUPS):s.loc[h,'GOV']=m._policy_shares[k]*v(m.policy_cash)
        for i in m._policy_cfg['subsidy_sectors']:
            s.loc[i,'GOV']+=sum(v(m.policy_relief*m.pch_gross[i,h]*m.Ch[i,h]) for h in GROUPS)
        s.loc['S54','GOV']+=v(m.pq['S54']*m.admin_quantity)
    gap=(s.sum(axis=1)-s.sum(axis=0)).abs()
    assert gap.max()<1e-8, gap.nlargest(5)
    return float(gap.max())
