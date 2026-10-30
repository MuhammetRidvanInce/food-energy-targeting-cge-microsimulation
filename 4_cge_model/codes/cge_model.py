"""Static computable general equilibrium model with 64 sectors and five household groups.

Inputs: the SAM and selected elasticity workbook under ../datas/.
Importing this module neither solves the model nor writes files. See README.md.
Monetary API inputs/outputs use thousand TRY; internal calculations use trillion TRY.
Quantities are volumes valued at benchmark prices rather than physical units.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
from io import BytesIO
import json
import math
from pathlib import Path
from typing import Mapping

import numpy as np
import pandas as pd
import pyomo.environ as pyo
from pyomo.opt import check_optimal_termination

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SAM = ROOT / "datas" / "SAM_2023_64_sectors_5_households.xlsx"
DEFAULT_ELASTICITIES = ROOT / "datas" / "parameters" / "selected_elasticities.xlsx"
SCALE = 1e9  # thousand TRY / trilyon TL
SECTORS = tuple(f"S{i:02d}" for i in range(64))
GROUPS = tuple(f"Q{i}" for i in range(1, 6))
ACCOUNTS = SECTORS + ("LAB", "CAP", "PTAX", "CTAX", "DTAX") + GROUPS + ("GOV", "INV", "EXT", "HH_REC")
ELASTICITY_SHEETS = {'sigma': 'Armington', 'psi': 'CET', 'omega': 'CES'}


@dataclass
class Benchmark:
    """Validated SAM in internal units and population in persons."""
    sam: pd.DataFrame
    population: pd.Series
    sectors: pd.DataFrame
    path: Path
    sha256: str


def load_benchmark(path: str | Path = DEFAULT_SAM) -> Benchmark:
    """Validate the expected account structure and supported flows."""
    path = Path(path).resolve()
    full = pd.read_excel(path, sheet_name="SAM_78", index_col=0)
    expected = list(ACCOUNTS) + ["TOTAL"]
    if full.index.tolist() != expected or full.columns.tolist() != expected:
        raise ValueError("SAM_78 requires a 79-by-79 block including S00–S63, five groups and TOTAL.")
    if not np.isfinite(full.to_numpy(dtype=float)).all():
        raise ValueError("The SAM contains missing or non-finite cells.")
    raw = full.loc[list(ACCOUNTS), list(ACCOUNTS)].astype(float)
    for computed, stored in [(raw.sum(axis=0), full.loc['TOTAL', list(ACCOUNTS)]),
                             (raw.sum(axis=1), full.loc[list(ACCOUNTS), 'TOTAL']),
                             (raw.sum(axis=0), raw.sum(axis=1))]:
        if not np.allclose(computed, stored, atol=0.001, rtol=1e-12):
            raise ValueError("Inconsistent SAM totals or account balances.")
    if not np.isclose(raw.to_numpy().sum(), full.loc['TOTAL', 'TOTAL'], atol=.001, rtol=1e-12):
        raise ValueError("Inconsistent SAM grand total.")


    allowed = pd.DataFrame(False, index=ACCOUNTS, columns=ACCOUNTS)
    allowed.loc[list(SECTORS), list(SECTORS) + list(GROUPS) + ['GOV', 'INV', 'EXT']] = True
    allowed.loc[['LAB', 'CAP', 'PTAX', 'CTAX', 'EXT'], list(SECTORS)] = True
    allowed.loc[list(GROUPS), ['LAB', 'CAP', 'HH_REC']] = True
    allowed.loc[['CTAX', 'DTAX', 'INV', 'HH_REC'], list(GROUPS)] = True
    allowed.loc['CTAX', ['GOV', 'INV']] = True
    allowed.loc['GOV', ['PTAX', 'CTAX', 'DTAX']] = True
    allowed.loc['INV', ['GOV', 'EXT']] = True
    if np.max(np.abs(raw.where(~allowed, 0).to_numpy())) > .001:
        raise ValueError("The SAM includes an unsupported flow.")
    negative_ok = pd.DataFrame(False, index=ACCOUNTS, columns=ACCOUNTS)
    negative_ok.loc[['PTAX', 'CTAX'], :] = True
    negative_ok.loc['GOV', ['PTAX', 'CTAX']] = True
    negative_ok.loc[list(SECTORS), 'INV'] = True
    negative_ok.loc['INV', :] = True
    if raw.where(~negative_ok, 0).to_numpy().min() < 0:
        raise ValueError("Negative factor, consumption, trade or reconciliation flow.")
    profiles = pd.read_excel(path, sheet_name='Group_Summary', index_col=0)
    population = profiles.loc['Represented population', list(GROUPS)].astype(float)
    if not np.isfinite(population).all() or (population <= 0).any():
        raise ValueError("Valid population totals are required for all five groups.")
    labels = pd.read_excel(path, sheet_name='Accounts').set_index('Account').loc[list(SECTORS)]
    return Benchmark(raw / SCALE, population, labels, path, hashlib.sha256(path.read_bytes()).hexdigest())


def load_elasticities(path: str | Path = DEFAULT_ELASTICITIES) -> pd.DataFrame:
    """Map 192 values from three sheets by sector code; retain sources in attrs.

    Read and hash the same bytes; invalid or missing inputs raise an error.
    Each sheet must contain S00–S63 exactly once, in any order.
    """
    path = Path(path).resolve()
    content = path.read_bytes()
    table = pd.DataFrame(index=pd.Index(SECTORS, name='sector'))
    table['category'] = ['Agriculture' if k < 3 else 'Industry' if k < 27 else 'Services'
                         for k in range(len(SECTORS))]
    sources = {}
    headers = ['Model sector', 'Elasticity value', 'Source and adaptation']
    with pd.ExcelFile(BytesIO(content)) as workbook:
        if set(workbook.sheet_names) != set(ELASTICITY_SHEETS.values()):
            raise ValueError("The workbook must contain exactly the Armington, CET and CES sheets.")
        for name, sheet in ELASTICITY_SHEETS.items():
            frame = workbook.parse(sheet, dtype=object)
            if frame.columns.tolist() != headers or len(frame) != len(SECTORS):
                raise ValueError(f"{sheet}: expected three columns and 64 sector rows.")
            codes = frame.iloc[:, 0].astype('string').str.strip().str.extract(r'^(S\d{2})(?:\s|$)', expand=False)
            if codes.isna().any() or codes.duplicated().any() or set(codes) != set(SECTORS):
                raise ValueError(f"{sheet}: S00–S63 must be complete and unique.")
            raw_values = frame.iloc[:, 1]
            if raw_values.map(lambda x: isinstance(x, (bool, np.bool_))).any():
                raise ValueError(f"{sheet}: elasticity cells must be numeric.")
            values = pd.to_numeric(raw_values, errors='coerce').to_numpy(dtype=float)
            if not np.isfinite(values).all() or (values <= 0).any():
                raise ValueError(f"{sheet}: all elasticities must be finite and positive.")
            refs = frame.iloc[:, 2]
            if refs.isna().any() or not refs.map(lambda x: isinstance(x, str) and bool(x.strip())).all():
                raise ValueError(f"{sheet}: a source description is required for each sector.")
            table[name] = pd.Series(values, index=codes.tolist()).reindex(SECTORS)
            sources[name] = dict(zip(codes.tolist(), refs.tolist()))
    table.attrs.update(source_path=str(path), source_sha256=hashlib.sha256(content).hexdigest(),
                       sources=sources, overrides={})
    return table


def elasticity_table(sigma=None, psi=None, omega=None, *,
                     elasticities_path: str | Path = DEFAULT_ELASTICITIES) -> pd.DataFrame:
    """None reads Excel values; a number sets a common value; a mapping overrides selected sectors.

    category is a reporting label. Input hashes, sources and explicit overrides
   are retained in the returned table attrs. Each call reads the workbook afresh.
    """
    table = load_elasticities(elasticities_path)
    for name, spec in [('sigma', sigma), ('psi', psi), ('omega', omega)]:
        if spec is None:
            continue
        if isinstance(spec, Mapping):
            if set(spec) - set(SECTORS):
                raise ValueError(f"Unknown sector: {set(spec) - set(SECTORS)}")
            changes = {i: float(value) for i, value in spec.items()}
        else:
            changes = {i: float(spec) for i in SECTORS}
        for i, value in changes.items():
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name}[{i}] must be finite and positive.")
            table.loc[i, name] = value
            table.attrs['sources'][name][i] = 'Explicit parameter override through the API'
        if changes:
            table.attrs['overrides'][name] = changes
    return table


def _ces_cost(prices, shares, elasticity):
    """Calibrated share form with zero shares omitted and an explicit unit-elasticity limit."""
    terms = [(p, float(s)) for p, s in zip(prices, shares) if s > 0]
    if len(terms) == 1:
        return terms[0][0]
    if abs(elasticity - 1.0) < 1e-8:
        return pyo.exp(sum(s * pyo.log(p) for p, s in terms))
    return sum(s * p ** (1 - elasticity) for p, s in terms) ** (1 / (1 - elasticity))


def build_model(benchmark: Benchmark | None = None, *, sam_path=DEFAULT_SAM,
                sigma=None, psi=None, omega=None, investment_closure='signed_shares',
                elasticities_path=DEFAULT_ELASTICITIES):
    """Build the calibrated model; apply exogenous shocks through set_scenario before solving.

    signed_shares: signed benchmark net-investment expenditure shares.
    fixed_negative: sensitivity closure holding negative net-investment volumes fixed.
    elasticities_path: three-sheet sector elasticity workbook; explicit sigma/psi/omega
    arguments override only the specified values.
    """
    b = load_benchmark(sam_path) if benchmark is None else benchmark
    a = b.sam
    ss, hh = list(SECTORS), list(GROUPS)
    if investment_closure not in {'signed_shares', 'fixed_negative'}:
        raise ValueError("investment_closure: must be signed_shares or fixed_negative.")
    el = elasticity_table(sigma, psi, omega, elasticities_path=elasticities_path)
    L0, K0 = a.loc['LAB', ss], a.loc['CAP', ss]
    X0 = L0 + K0
    I0 = a.loc[ss, ss]
    Z0 = X0 + I0.sum(axis=0)
    E0, M0 = a.loc[ss, 'EXT'], a.loc['EXT', ss]
    D0 = Z0 + a.loc['PTAX', ss] + a.loc['CTAX', ss] - E0
    C0, G0, V0 = a.loc[ss, hh], a.loc[ss, 'GOV'], a.loc[ss, 'INV']
    Q0 = D0 + M0
    if min(X0.min(), Z0.min(), D0.min(), Q0.min()) <= 0:
        raise ValueError("Every sector requires positive value added, output, domestic supply and composite supply.")
    Lh0, Kh0 = a.loc[hh, 'LAB'], a.loc[hh, 'CAP']
    R0 = a.loc[hh, 'HH_REC'] - a.loc['HH_REC', hh]
    Y0 = Lh0 + Kh0 + R0
    B0 = C0.sum(axis=0) + a.loc['CTAX', hh]
    Sp0 = a.loc['INV', hh]
    if min(Y0.min(), B0.min(), C0.sum().min(), G0.sum(), V0.sum()) <= 0:
        raise ValueError("Positive income, consumption and aggregate final use are required.")
    if abs(R0.sum()) > 1e-10:
        raise ValueError("Household income reconciliation must sum to zero.")
    if not np.allclose(Q0, I0.sum(axis=1) + C0.sum(axis=1) + G0 + V0, atol=1e-10, rtol=1e-10):
        raise ValueError("Composite supply and use do not balance.")
    th = a.loc['CTAX', hh] / C0.sum(axis=0)
    tg, ti = a.loc['CTAX', 'GOV'] / G0.sum(), a.loc['CTAX', 'INV'] / V0.sum()
    tz, tc = a.loc['PTAX', ss] / Z0, a.loc['CTAX', ss] / Z0
    if min((1 + th).min(), 1 + tg, 1 + ti, (1 + tz + tc).min()) <= 0:
        raise ValueError("Tax-inclusive price multipliers must be positive.")
    beta = C0.multiply(1 + th, axis=1).divide(B0, axis=1)
    inv_budget0 = V0.sum() * (1 + ti)

    m = pyo.ConcreteModel(name='FoodEnergy_CGE_64x5')
    m._benchmark = b
    m._elasticities = el
    m._investment_closure = investment_closure
    m._cal = dict(L0=L0, K0=K0, X0=X0, I0=I0, Z0=Z0, E0=E0, M0=M0,
                  D0=D0, Q0=Q0, C0=C0, G0=G0, V0=V0, Lh0=Lh0, Kh0=Kh0,
                  R0=R0, Y0=Y0, B0=B0, Sp0=Sp0, th=th, tg=tg, ti=ti,
                  tz=tz, tc=tc, beta=beta, inv_budget0=inv_budget0)
    m.i = pyo.Set(initialize=ss, ordered=True)
    m.h = pyo.Set(initialize=hh, ordered=True)
    m.w = pyo.Param(initialize=1.0, mutable=True, within=pyo.PositiveReals)
    m.Pwm = pyo.Param(m.i, initialize=1.0, mutable=True, within=pyo.PositiveReals)
    m.Pwe = pyo.Param(m.i, initialize=1.0, mutable=True, within=pyo.PositiveReals)
    m.transfer = pyo.Param(m.h, initialize=0.0, mutable=True, within=pyo.NonNegativeReals)
    m.subsidy = pyo.Param(m.i, initialize=0.0, mutable=True, within=pyo.UnitInterval)
    m.Sf = pyo.Param(initialize=float(a.loc['INV', 'EXT']))
    for name in ('z', 'q', 'pd', 'pq'):
        setattr(m, name, pyo.Var(m.i, initialize=1.0, bounds=(1e-9, None)))
    m.r = pyo.Var(initialize=1.0, bounds=(1e-9, None))
    m.exchange_rate = pyo.Var(initialize=1.0, bounds=(1e-9, None))
    m.investment_scale = pyo.Var(initialize=1.0, bounds=(1e-9, None))
    m.pm = pyo.Expression(m.i, rule=lambda m, i: m.exchange_rate * m.Pwm[i])
    m.pe = pyo.Expression(m.i, rule=lambda m, i: m.exchange_rate * m.Pwe[i])
    m.pv = pyo.Expression(m.i, rule=lambda m, i:
        _ces_cost([m.w, m.r], [L0[i] / X0[i], K0[i] / X0[i]], el.loc[i, 'omega']))
    m.pz = pyo.Expression(m.i, rule=lambda m, i:
        (X0[i] * m.pv[i] + sum(I0.loc[j, i] * m.pq[j] for j in ss if I0.loc[j, i] != 0)) / Z0[i])

    def revenue(m, i):
        if E0[i] == 0:
            return m.pd[i]
        share = E0[i] / (D0[i] + E0[i])
        power = 1 + el.loc[i, 'psi']
        return ((1-share) * m.pd[i]**power + share * m.pe[i]**power)**(1/power)
    m.p_supply = pyo.Expression(m.i, rule=revenue)
    m.zero_profit = pyo.Constraint(m.i, rule=lambda m, i: m.p_supply[i] == m.pz[i])
    m.armington_price = pyo.Constraint(m.i, rule=lambda m, i: m.pq[i] ==
        _ces_cost([m.pd[i], m.pm[i]], [D0[i]/Q0[i], M0[i]/Q0[i]], el.loc[i, 'sigma']))
    m.Z = pyo.Expression(m.i, rule=lambda m, i: Z0[i] * m.z[i])
    m.X = pyo.Expression(m.i, rule=lambda m, i: X0[i] * m.z[i])
    m.Q = pyo.Expression(m.i, rule=lambda m, i: Q0[i] * m.q[i])
    m.L = pyo.Expression(m.i, rule=lambda m, i:
        L0[i] * m.z[i] * (m.pv[i]/m.w)**el.loc[i, 'omega'] if L0[i] else 0.0)
    m.K = pyo.Expression(m.i, rule=lambda m, i:
        K0[i] * m.z[i] * (m.pv[i]/m.r)**el.loc[i, 'omega'] if K0[i] else 0.0)
    m.E = pyo.Expression(m.i, rule=lambda m, i:
        E0[i] * m.z[i] * (m.pe[i]/m.p_supply[i])**el.loc[i, 'psi'] if E0[i] else 0.0)
    m.D = pyo.Expression(m.i, rule=lambda m, i:
        D0[i] * m.z[i] * (m.pd[i]/m.p_supply[i])**el.loc[i, 'psi'])
    m.M = pyo.Expression(m.i, rule=lambda m, i:
        M0[i] * m.q[i] * (m.pq[i]/m.pm[i])**el.loc[i, 'sigma'] if M0[i] else 0.0)
    m.domestic_match = pyo.Constraint(m.i, rule=lambda m, i:
        m.D[i]/D0[i] == m.q[i] * (m.pq[i]/m.pd[i])**el.loc[i, 'sigma'])
    m.I = pyo.Expression(m.i, m.i, rule=lambda m, j, i: I0.loc[j, i] * m.z[i])
    m.factor_income = pyo.Expression(expr=m.w*L0.sum() + m.r*K0.sum())
    m.Rh = pyo.Expression(m.h, rule=lambda m, h: R0[h]*m.factor_income/X0.sum())
    m.Y_regular = pyo.Expression(m.h, rule=lambda m, h: m.w*Lh0[h] + m.r*Kh0[h] + m.Rh[h])
    m.Yh = pyo.Expression(m.h, rule=lambda m, h: m.Y_regular[h] + m.transfer[h])
    m.Tdh = pyo.Expression(m.h, rule=lambda m, h: a.loc['DTAX', h]/Y0[h] * m.Y_regular[h])
    m.Sph = pyo.Expression(m.h, rule=lambda m, h: Sp0[h]/Y0[h] * m.Y_regular[h])
    m.Bh = pyo.Expression(m.h, rule=lambda m, h: m.Yh[h] - m.Tdh[h] - m.Sph[h])
    m.pch_gross = pyo.Expression(m.i, m.h, rule=lambda m, i, h: (1 + th[h])*m.pq[i])
    m.pch = pyo.Expression(m.i, m.h, rule=lambda m, i, h: (1-m.subsidy[i])*m.pch_gross[i,h])
    m.Ch = pyo.Expression(m.i, m.h, rule=lambda m, i, h: beta.loc[i,h]*m.Bh[h]/m.pch[i,h])
    m.C = pyo.Expression(m.i, rule=lambda m, i: sum(m.Ch[i,h] for h in hh))
    m.G = pyo.Param(m.i, initialize=G0.to_dict())
    m.pcg = pyo.Expression(m.i, rule=lambda m, i: (1+tg)*m.pq[i])
    m.pci = pyo.Expression(m.i, rule=lambda m, i: (1+ti)*m.pq[i])
    def investment(m, i):
        if investment_closure == 'fixed_negative' and V0[i] < 0:
            return float(V0[i])
        return V0[i] * m.investment_scale / m.pq[i]
    m.INV = pyo.Expression(m.i, rule=investment)
    m.Tproduction = pyo.Expression(m.i, rule=lambda m, i: tz[i]*m.pz[i]*m.Z[i])
    m.Tproduct = pyo.Expression(m.i, rule=lambda m, i: tc[i]*m.pz[i]*m.Z[i])
    m.Th = pyo.Expression(m.h, rule=lambda m, h: sum(th[h]*m.pq[i]*m.Ch[i,h] for i in ss))
    m.Tg = pyo.Expression(expr=sum(tg*m.pq[i]*m.G[i] for i in ss))
    m.Tinv = pyo.Expression(expr=sum(ti*m.pq[i]*m.INV[i] for i in ss))
    m.T = pyo.Expression(expr=sum(m.Tdh[h]+m.Th[h] for h in hh) + m.Tg + m.Tinv
                        + sum(m.Tproduction[i]+m.Tproduct[i] for i in ss))
    m.price_support_cost = pyo.Expression(expr=sum(m.subsidy[i]*m.pch_gross[i,h]*m.Ch[i,h] for i in ss for h in hh))
    m.cash_cost = pyo.Expression(expr=sum(m.transfer[h] for h in hh))
    m.government_consumption_cost = pyo.Expression(expr=sum(m.pcg[i]*m.G[i] for i in ss))
    m.Sg = pyo.Expression(expr=m.T-m.government_consumption_cost-m.cash_cost-m.price_support_cost)
    m.savings = pyo.Expression(expr=sum(m.Sph[h] for h in hh)+m.Sg+m.exchange_rate*m.Sf)
    m.investment_balance = pyo.Constraint(expr=sum(m.pci[i]*m.INV[i] for i in ss)/inv_budget0 == m.savings/inv_budget0)
    m.goods_gap = pyo.Expression(m.i, rule=lambda m,i: m.Q[i]-m.C[i]-m.G[i]-m.INV[i]-sum(m.I[i,j] for j in ss))

    m._omitted_market = str(Q0.idxmax())
    m.commodity_market = pyo.Constraint(m.i, rule=lambda m,i:
        pyo.Constraint.Skip if i == m._omitted_market else m.goods_gap[i]/Q0[i] == 0)
    m.labor_market = pyo.Constraint(expr=sum(m.L[i] for i in ss)/L0.sum() == 1)
    m.capital_market = pyo.Constraint(expr=sum(m.K[i] for i in ss)/K0.sum() == 1)
    m.foreign_balance = pyo.Constraint(expr=(sum(m.Pwe[i]*m.E[i]-m.Pwm[i]*m.M[i] for i in ss)+m.Sf)/M0.sum() == 0)
    m.obj = pyo.Objective(expr=0.0)
    return m


def set_scenario(m, *, import_prices=None, export_prices=None, transfers=None, subsidies=None):
    """Update supplied mappings while retaining other exogenous values.

    Prices are benchmark-one indices; transfers are group totals in thousand TRY;
    subsidies are sector consumer-price discounts in [0,1).
    Start a new scenario with build_model() or a clean benchmark clone.
    """
    plans = []
    for spec, component, keys, multiplier, kind in [
        (import_prices, m.Pwm, SECTORS, 1, 'price'),
        (export_prices, m.Pwe, SECTORS, 1, 'price'),
        (transfers, m.transfer, GROUPS, 1/SCALE, 'transfer'),
        (subsidies, m.subsidy, SECTORS, 1, 'subsidy'),
    ]:
        if spec is None:
            continue
        if not isinstance(spec, Mapping) or set(spec)-set(keys):
            raise ValueError("Unknown account or invalid type in the scenario mapping.")
        for key, val in spec.items():
            val = float(val)
            if (not math.isfinite(val) or (kind == 'price' and val <= 0)
                or (kind == 'transfer' and val < 0) or (kind == 'subsidy' and not 0 <= val < 1)):
                raise ValueError(f"Invalid {kind} value: {key}={val}")
            plans.append((component, key, val*multiplier))
    for component, key, val in plans:
        component[key] = val
    return m


def diagnostics(m):
    """Check accounting, budgets, finite values and equations, including the omitted market."""
    v, c = pyo.value, m._cal
    worst, max_residual = '', 0.0
    for var in m.component_data_objects(pyo.Var):
        x = v(var)
        if (not math.isfinite(x) or (var.has_lb() and x < v(var.lb)-1e-10)
                or (var.has_ub() and x > v(var.ub)+1e-10)):
            raise ArithmeticError(f"Invalid variable: {var.name}")
    for con in m.component_data_objects(pyo.Constraint, active=True):
        lo = v(con.lower) if con.has_lb() else -math.inf
        hi = v(con.upper) if con.has_ub() else math.inf
        body = v(con.body)
        gap = max(lo-body, body-hi, 0.0)
        if not math.isfinite(body):
            raise ArithmeticError(f"Sonlu olmayan denklem: {con.name}")
        if gap > max_residual:
            worst, max_residual = con.name, gap
    goods = {i: v(m.goods_gap[i]) for i in m.i}
    income_gdp = v(m.factor_income + m.T - sum(m.Tdh[h] for h in m.h) - m.price_support_cost)
    expenditure_gdp = v(sum(m.pch[i,h]*m.Ch[i,h] for i in m.i for h in m.h)
                        + m.government_consumption_cost + sum(m.pci[i]*m.INV[i] for i in m.i)
                        + sum(m.pe[i]*m.E[i]-m.pm[i]*m.M[i] for i in m.i))
    hh_gap = max(abs(v(m.Bh[h]-sum(m.pch[i,h]*m.Ch[i,h] for i in m.i)))/c['B0'][h] for h in m.h)
    if min(v(m.Y_regular[h]) for h in m.h) <= 0 or min(v(m.Bh[h]) for h in m.h) <= 0:
        raise ArithmeticError("Non-positive household income or consumption budget under the shock.")
    return dict(max_scaled_equation_residual=max_residual, worst_equation=worst,
                max_relative_goods_gap=max(abs(goods[i])/c['Q0'][i] for i in m.i),
                max_goods_gap_bin_tl=max(abs(g) for g in goods.values())*SCALE,
                omitted_market=m._omitted_market, omitted_market_gap_bin_tl=goods[m._omitted_market]*SCALE,
                household_budget_relative_gap=hh_gap,
                gdp_identity_relative_gap=abs(income_gdp-expenditure_gdp)/max(abs(income_gdp),1e-12),
                government_budget_gap_bin_tl=abs(v(m.T-m.Sg-m.government_consumption_cost-m.cash_cost-m.price_support_cost))*SCALE)


def solve_model(m, *, solver='ipopt', executable=None, tee=False, tolerance=1e-8):
    """Solve; require optimal termination and independent accounting checks."""
    for i in m.i:
        if not 0 <= pyo.value(m.subsidy[i]) < 1:
            raise ValueError("The consumer subsidy rate must satisfy 0 <= rate < 1.")
    opt = pyo.SolverFactory(solver, **({'executable': executable} if executable else {}))
    if not opt.available(exception_flag=False):
        raise RuntimeError("IPOPT was not found. Add it to PATH or supply executable= with its full path.")
    if solver == 'ipopt':
        opt.options.update(dict(tol=1e-10, constr_viol_tol=1e-10, max_iter=2000,
                                bound_relax_factor=0, print_level=0))
    solution = opt.solve(m, tee=tee)
    if not check_optimal_termination(solution):
        raise RuntimeError(f"Solution failed: {solution.solver.termination_condition}")
    d = diagnostics(m)
    if max(d[k] for k in ('max_scaled_equation_residual', 'max_relative_goods_gap',
                          'household_budget_relative_gap', 'gdp_identity_relative_gap')) > tolerance:
        raise ArithmeticError(f"Solution failed the accounting checks: {d}")
    d['termination'] = str(solution.solver.termination_condition)
    m._last_diagnostics = d
    return d


def solution_sam(m) -> pd.DataFrame:
    """Current-price SAM in thousand TRY without totals. Policy flows enter GOV–HH accounts.

    Price support appears as sector payments from GOV, separate from goods volumes.
    """
    v = pyo.value
    s = pd.DataFrame(0.0, index=ACCOUNTS, columns=ACCOUNTS)
    for i in m.i:
        for j in m.i:
            s.loc[i,j] = v(m.pq[i]*m.I[i,j])
        for h in m.h:
            s.loc[i,h] = v((m.pch[i,h]-(m.pch_gross[i,h]-m.pq[i]))*m.Ch[i,h])
        s.loc[i,'GOV'] = v(m.pq[i]*m.G[i] + sum(m.subsidy[i]*m.pch_gross[i,h]*m.Ch[i,h] for h in m.h))
        s.loc[i,'INV'] = v(m.pq[i]*m.INV[i])
        s.loc[i,'EXT'], s.loc['EXT',i] = v(m.pe[i]*m.E[i]), v(m.pm[i]*m.M[i])
        s.loc['LAB',i], s.loc['CAP',i] = v(m.w*m.L[i]), v(m.r*m.K[i])
        s.loc['PTAX',i], s.loc['CTAX',i] = v(m.Tproduction[i]), v(m.Tproduct[i])
    for h in m.h:
        s.loc[h,'LAB'] = v(m.w)*m._cal['Lh0'][h]
        s.loc[h,'CAP'] = v(m.r)*m._cal['Kh0'][h]
        s.loc[h,'GOV'] = v(m.transfer[h])
        s.loc[h,'HH_REC'], s.loc['HH_REC',h] = max(v(m.Rh[h]),0), max(-v(m.Rh[h]),0)
        s.loc['DTAX',h], s.loc['CTAX',h], s.loc['INV',h] = v(m.Tdh[h]), v(m.Th[h]), v(m.Sph[h])
    s.loc['CTAX','GOV'], s.loc['CTAX','INV'] = v(m.Tg), v(m.Tinv)
    s.loc['GOV','PTAX'] = sum(v(m.Tproduction[i]) for i in m.i)
    s.loc['GOV','CTAX'] = s.loc['CTAX'].sum()
    s.loc['GOV','DTAX'] = sum(v(m.Tdh[h]) for h in m.h)
    s.loc['INV','GOV'], s.loc['INV','EXT'] = v(m.Sg), v(m.exchange_rate*m.Sf)
    return s*SCALE


def results(m) -> dict:
    """Prices, group accounts, volumes and scaling information for microsimulation.

    Poverty indices are computed separately. Monetary and volume tables use thousand TRY;
    population is in persons; prices and ratios are dimensionless benchmark indices.
    """
    d = diagnostics(m)
    if max(d[k] for k in ('max_scaled_equation_residual', 'max_relative_goods_gap',
                          'household_budget_relative_gap', 'gdp_identity_relative_gap')) > 1e-8:
        raise ArithmeticError("Solve this scenario with solve_model before extracting results.")
    v, c = pyo.value, m._cal
    sector = m._benchmark.sectors.copy()
    for name in ('sigma', 'psi', 'omega'):
        sector[name] = m._elasticities[name]
    for name, component in [('composite_price',m.pq), ('domestic_price',m.pd),
                            ('producer_price',m.pz), ('import_price',m.pm), ('export_price',m.pe)]:
        sector[name] = [v(component[i]) for i in m.i]
    for name, component in [('output_volume',m.Z), ('value_added_volume',m.X),
                            ('composite_volume',m.Q), ('labor_volume',m.L), ('capital_volume',m.K),
                            ('imports_volume',m.M), ('exports_volume',m.E), ('investment_volume',m.INV)]:
        sector[name] = [v(component[i])*SCALE for i in m.i]
    house = pd.DataFrame(index=list(m.h))
    house['population'] = m._benchmark.population
    for name, comp in [('regular_income',m.Y_regular), ('reconciliation',m.Rh), ('gross_income',m.Yh),
                       ('direct_tax',m.Tdh), ('saving',m.Sph), ('consumption_budget',m.Bh), ('cash_transfer',m.transfer)]:
        house[name] = [v(comp[h])*SCALE for h in m.h]
    house['labor_income'] = [v(m.w)*c['Lh0'][h]*SCALE for h in m.h]
    house['capital_income'] = [v(m.r)*c['Kh0'][h]*SCALE for h in m.h]
    house['disposable_income'] = house.gross_income-house.direct_tax
    house['income_factor'] = [v(m.Y_regular[h])/c['Y0'][h] for h in m.h]
    house['cpi_cobb_douglas'] = [math.exp(sum(c['beta'].loc[i,h]*math.log(v(m.pch[i,h])/(1+c['th'][h])) for i in m.i)) for h in m.h]
    house['cpi_laspeyres'] = [sum(c['beta'].loc[i,h]*v(m.pch[i,h])/(1+c['th'][h]) for i in m.i) for h in m.h]
    house['real_consumption_change_pct'] = [100*(v(m.Bh[h])/c['B0'][h]/house.loc[h,'cpi_cobb_douglas']-1) for h in m.h]
    prices = pd.DataFrame({h:[v(m.pch[i,h]) for i in m.i] for h in m.h}, index=list(m.i))
    ratios = prices.divide(1+c['th'], axis=1)
    consumption = pd.DataFrame({h:[v(m.Ch[i,h])*SCALE for i in m.i] for h in m.h}, index=list(m.i))
    gdp = v(m.factor_income+m.T-sum(m.Tdh[h] for h in m.h)-m.price_support_cost)*SCALE
    macro = dict(wage=v(m.w), capital_rental=v(m.r), exchange_rate=v(m.exchange_rate),
                 gdp_nominal=gdp, government_saving=v(m.Sg)*SCALE, tax_revenue=v(m.T)*SCALE,
                 government_consumption=v(m.government_consumption_cost)*SCALE,
                 private_saving=sum(v(m.Sph[h]) for h in m.h)*SCALE,
                 foreign_saving_domestic=v(m.exchange_rate*m.Sf)*SCALE,
                 investment_budget=v(m.savings)*SCALE, cash_cost=v(m.cash_cost)*SCALE,
                 price_support_cost=v(m.price_support_cost)*SCALE)
    return dict(sectors=sector, households=house, consumer_prices=prices,
                consumer_price_ratios=ratios, consumption=consumption, macro=macro,
                diagnostics=d, metadata=dict(monetary_unit='thousand TRY',
                quantity_unit='benchmark-price value in thousand TRY', internal_scale=SCALE,
                sam_sha256=m._benchmark.sha256, investment_closure=m._investment_closure,
                elasticities_path=m._elasticities.attrs['source_path'],
                elasticities_sha256=m._elasticities.attrs['source_sha256'],
                elasticity_overrides={name: values.copy() for name, values in
                                      m._elasticities.attrs['overrides'].items()}))


def self_check(*, executable=None, elasticities_path=DEFAULT_ELASTICITIES) -> dict:
    """Test benchmark, shocks, boundary branches, homogeneity and elasticities without writing files."""
    b = load_benchmark()
    base = build_model(b, elasticities_path=elasticities_path)
    checks = {'baseline': solve_model(base, executable=executable)}
    recovered = solution_sam(base)
    original = b.sam*SCALE
    diff = (recovered-original).abs()
    relative = float((diff/np.maximum(original.abs(),1e6)).to_numpy().max())
    if relative > 1e-8:
        raise AssertionError(f"Benchmark SAM replication failed: {relative}")
    checks['benchmark_reproduction'] = dict(max_cell_gap_bin_tl=float(diff.to_numpy().max()),
                                          max_cell_scaled_gap=relative,
                                          max_price_deviation=max(abs(pyo.value(base.pq[i])-1) for i in base.i))
    cases = [
        ('import_price_shock', {}, dict(import_prices={'S00':1.2,'S02':1.2,'S04':1.2,'S09':1.4,'S23':1.4})),
        ('cash_transfer', {}, dict(transfers={'Q1':5e7, 'Q2':5e7})),
        ('consumer_price_support', {}, dict(subsidies={'S00':.05,'S02':.05,'S04':.05,'S09':.05,'S23':.05})),
        ('unit_elasticities', dict(sigma=1.,omega=1.), dict(import_prices={'S04':1.1})),
        ('fixed_negative_investment', dict(investment_closure='fixed_negative'), dict(import_prices={'S09':1.4})),
    ]
    default = base._elasticities
    for factor in (.75,1.25):
        cases.append((f'elasticity_scale_{factor}', {k:(default[k]*factor).to_dict() for k in ('sigma','psi','omega')},
                      dict(import_prices={'S04':1.2,'S23':1.4})))
    for name, kwargs, scenario in cases:
        model = build_model(b, elasticities_path=elasticities_path, **kwargs)
        set_scenario(model, **scenario)
        checks[name] = solve_model(model, executable=executable)
        for i in ('S44','S63'):
            if pyo.value(model.M[i]) != 0 or pyo.value(model.E[i]) != 0:
                raise AssertionError("Zero-trade branch failed.")
        if pyo.value(model.L['S44']) != 0 or pyo.value(model.K['S63']) != 0:
            raise AssertionError("Single-factor branch failed.")
        flow = solution_sam(model)
        balance = float(np.max(np.abs(flow.sum(axis=0)-flow.sum(axis=1))))
        checks[name]['solution_sam_balance_gap_bin_tl'] = balance
        if balance/(original.to_numpy().sum()) > 1e-9:
            raise AssertionError("Post-shock SAM balance failed.")
        checks[name]['exchange_rate'] = pyo.value(model.exchange_rate)
        if name == 'fixed_negative_investment':
            for i in SECTORS:
                if model._cal['V0'][i] < 0 and pyo.value(model.INV[i]) != model._cal['V0'][i]:
                    raise AssertionError("Fixed negative net-investment volume changed.")
        if name == 'cash_transfer':
            for h in GROUPS:
                if abs(pyo.value(model.Bh[h]-(model.Y_regular[h]-model.Tdh[h]-model.Sph[h]+model.transfer[h]))) > 1e-10:
                    raise AssertionError("Cash transfer and group budget do not match.")
    homogeneous = build_model(b, elasticities_path=elasticities_path)
    homogeneous.w = 2.0
    checks['numeraire_homogeneity'] = solve_model(homogeneous, executable=executable)
    quantity_error = max(abs(pyo.value(homogeneous.z[i])-pyo.value(base.z[i])) for i in SECTORS)
    price_error = max(abs(pyo.value(homogeneous.pq[i])/2-pyo.value(base.pq[i])) for i in SECTORS)
    if max(quantity_error,price_error) > 1e-7:
        raise AssertionError("Numeraire scaling changed the real equilibrium.")
    checks['numeraire_homogeneity'].update(quantity_error=quantity_error, price_error=price_error)
    checks['passed'] = True
    checks['sam_sha256'] = b.sha256
    checks['elasticities_path'] = default.attrs['source_path']
    checks['elasticities_sha256'] = default.attrs['source_sha256']
    return checks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--self-check', action='store_true', help='Run integrated model validation.')
    parser.add_argument('--solver-executable', default=None, help='Optional full path to the IPOPT executable.')
    parser.add_argument('--elasticities-file', type=Path, default=DEFAULT_ELASTICITIES,
                        help='Optional Excel workbook with Armington/CET/CES sheets.')
    args = parser.parse_args()
    if args.self_check:
        report = self_check(executable=args.solver_executable, elasticities_path=args.elasticities_file)
    else:
        model = build_model(elasticities_path=args.elasticities_file)
        report = solve_model(model, executable=args.solver_executable)
        report['macro_bin_tl'] = results(model)['macro']
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
