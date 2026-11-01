"""Paths and deterministic input contracts for stage 5 (no working-directory dependency)."""
from pathlib import Path
import sys, json, hashlib, os
import numpy as np
import pandas as pd
from supplementary_catalog import load_supplementary, save_supplementary

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT.parent
DATA, OUT = ROOT/'datas', ROOT/'outputs'
MICRO = Path(os.environ.get('HBS_DATA_DIR', PROJECT/'3_household_groups/datas')).expanduser().resolve()
SAM = DATA/'SAM_2023_64_sectors_5_households.xlsx'
ELASTICITIES = DATA/'selected_elasticities.xlsx'
sys.path.insert(0, str(PROJECT/'4_cge_model/codes'))
import cge_model as cge
GROUPS = list(cge.GROUPS)
SECTORS = list(cge.SECTORS)
FOOD = ['S00', 'S02', 'S04']
ENERGY = ['S09', 'S23']
SEED = 20261025

def dump(path, obj):
    def convert(x):
        if isinstance(x, np.ndarray): return x.tolist()
        if isinstance(x, np.generic): return x.item()
        if isinstance(x, Path): return str(x)
        raise TypeError(type(x).__name__)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False,
                               default=convert), encoding='utf-8')

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def table(name, rows, supplementary=False):
    folder = OUT/'tables'/('supplementary' if supplementary else 'main')
    df = rows if isinstance(rows, pd.DataFrame) else pd.DataFrame(rows)
    if supplementary:
        save_supplementary(name,df)
    else:
        df.to_csv(folder/f'{name}.csv', index=False, encoding='utf-8-sig', float_format='%.12g')
    return df

def configurations():
    preferences=json.loads((PROJECT/'4_cge_model/datas/household_preferences.json').read_text(encoding='utf-8'))
    main = dict(household_structure='nested',household_sigma=None,household_nest_sigmas=preferences['nested_sigmas'],food=.2, energy=.4, budget=.005, admin=.03, trade_scale=1.,
                factor_scale=1., subsidy_sectors=FOOD+ENERGY,
                symmetric=False, investment_closure='signed_shares', cash_saving=0.)
    changes = {
        'food_only':dict(energy=0.), 'energy_only':dict(food=0.),
        'mild_joint':dict(food=.1, energy=.2), 'severe_joint':dict(food=.4, energy=.8),
        'low_budget':dict(budget=.0025), 'high_budget':dict(budget=.01),
        'low_trade_elasticity':dict(trade_scale=.75), 'high_trade_elasticity':dict(trade_scale=1.25),
        'low_factor_elasticity':dict(factor_scale=.75), 'high_factor_elasticity':dict(factor_scale=1.25),
        'zero_admin':dict(admin=0.), 'high_admin':dict(admin=.10),
        'energy_support_only':dict(subsidy_sectors=ENERGY),
        'symmetric_world_prices':dict(symmetric=True),
        'fixed_negative_investment':dict(investment_closure='fixed_negative'),
        'cash_saving_10pct':dict(cash_saving=.10),
        'consumption_CD':dict(household_structure='flat',household_sigma=1.,household_nest_sigmas=None),
        'consumption_flat_CES2':dict(household_structure='flat',household_sigma=2.,household_nest_sigmas=None),
        'upper_substitution_050':dict(household_nest_sigmas=dict(preferences['nested_sigmas'],upper=.5)),
        'upper_substitution_085':dict(household_nest_sigmas=dict(preferences['nested_sigmas'],upper=.85)),
        'low_within_substitution':dict(household_nest_sigmas=dict(upper=.25,food=.25,energy=.2,other=.25)),
        'high_within_substitution':dict(household_nest_sigmas=dict(upper=.25,food=1.,energy=.8,other=1.)),
    }
    return {'main':main, **{k:dict(main, **v) for k,v in changes.items()}}
