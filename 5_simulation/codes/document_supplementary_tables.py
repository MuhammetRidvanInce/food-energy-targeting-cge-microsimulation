"""Write plain two-sheet supplementary Excel workbooks with English documentation.

Run from any directory: python path/to/5_simulation/codes/document_supplementary_tables.py
Refreshes stored results and documentation without rerunning simulations.
"""
from pathlib import Path
import csv, hashlib, json, math, re, textwrap
from openpyxl import Workbook, load_workbook
from openpyxl.utils import get_column_letter

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / 'outputs/tables/supplementary'
DATA_SHEET, DOCS = 'Data', 'Variable Descriptions'
NAVY, BLUE, GREY, INK = '24476B', 'EAF1F8', 'F3F5F7', '243746'
D = json.loads((ROOT/'codes/supplementary_metadata_en.json').read_text(encoding='utf-8'))['variables']
R = 'codes/run_simulations.py: main()'
POLICY_LABELS = {'baseline':'Benchmark', 'shock':'Unsupported shock',
    'perfect_targeting':'Perfect targeting', 'pmt':'Out-of-fold PMT',
    'universal_cash':'Universal cash', 'price_support':'Price support'}
POLICY = {
    'baseline':'Unshocked benchmark equilibrium, without the new support programme.',
    'shock':'No-policy reference equilibrium under the external price shock specified by case.',
    'perfect_targeting':'Perfectly targeted cash: equal per-person payments to everyone in the lowest two benchmark income groups.',
    'pmt':'Out-of-fold proxy means test (PMT): recipients selected by predicted income; coverage equals target-population size; equal per-person payments.',
    'universal_cash':'Universal cash: equal per-person payment to every represented person.',
    'price_support':'Price support: a common proportional discount on eligible household purchases, solved at the same final net fiscal cost.'}
CASES = {
    'consumption_CD':'Cobb-Douglas consumption (elasticity 1) in both CGE and microsimulation; all other main settings unchanged.',
    'consumption_flat_CES2':'Single-level CES consumption with elasticity 2 in CGE and microsimulation.',
    'upper_substitution_050':'Food-energy-other upper-nest elasticity is 0.50; within-nest elasticities retain their main values.',
    'upper_substitution_085':'Food-energy-other upper-nest elasticity is 0.85; within-nest elasticities retain their main values.',
    'low_within_substitution':'Within-nest elasticities are food 0.25, energy 0.20 and other 0.25; upper-nest elasticity remains 0.25.',
    'high_within_substitution':'Within-nest elasticities are food 1.00, energy 0.80 and other 1.00; upper-nest elasticity remains 0.25.',
    'main':'Food import prices +20%; energy import prices +40%; net fiscal cost 0.5% of benchmark GDP; administration 3% of gross cash-programme spending. Uses benchmark sector elasticities, signed investment shares and full consumption of new cash.',
    'food_only':'Food import prices +20%; no energy import-price shock.',
    'energy_only':'Energy import prices +40%; no food import-price shock.',
    'mild_joint':'Milder joint shock: food +10%, energy +20%.',
    'severe_joint':'More severe joint shock: food +40%, energy +80%.',
    'low_budget':'Net fiscal cost is 0.25% of benchmark GDP.',
    'high_budget':'Net fiscal cost is 1% of benchmark GDP.',
    'low_trade_elasticity':'All Armington σ and CET ψ values are multiplied by 0.75.',
    'high_trade_elasticity':'All Armington σ and CET ψ values are multiplied by 1.25.',
    'low_factor_elasticity':'All capital–labour CES elasticities ω are multiplied by 0.75.',
    'high_factor_elasticity':'All capital–labour CES elasticities ω are multiplied by 1.25.',
    'zero_admin':'The cash-programme administration rate is zero.',
    'high_admin':'Administration absorbs 10% of gross cash-programme expenditure.',
    'energy_support_only':'Consumer price support applies only to energy sectors S09 (C19) and S23 (D35).',
    'symmetric_world_prices':'World export prices in shocked sectors increase by the same rates as their world import prices.',
    'fixed_negative_investment':'The five negative net investment quantities remain at benchmark levels; positive components absorb investment adjustment.',
    'cash_saving_10pct':'Households save 10% of new cash transfers and consume 90%.'}
TITLES = {
    'S1_configuration_results':('Distributional outcomes by configuration','One row per configuration–policy combination: each structural or consumption-preference configuration has five shock/policy outcomes, plus one common benchmark row.'),
    'S2_macro_results':('Macroeconomic and fiscal outcomes','One row per configuration–policy combination. Levels, percentage changes and indices have distinct units.'),
    'S3_sector_results':('Sector outcomes under the main policies','One row per policy–sector combination: main configuration × 4 supported policies × 64 sectors.'),
    'S4_error_grid_draws':('Targeting-error grid: individual draws','One row per recipient draw in an exclusion–leakage cell: 427 feasible cells × 10 draws.'),
    'S5_error_grid_summary':('Targeting-error grid: cell summaries','One row summarises the ten S4 recipient draws for an exclusion–leakage cell; 427 cells in total.'),
    'S6_score_degradation_draws':('Score-degradation experiment: individual draws','One row per score-level–draw combination: 9 finite noise levels plus an independent-score endpoint × 10 draws.'),
    'S7_micro_sensitivity':('Poverty-line and expenditure-basket sensitivity','One row per poverty-line–basket–policy combination: 3 × 2 × 4 = 24 outcomes.'),
    'S8_elasticity_assignment':('Sector elasticities and source assignments','One row per model sector. Armington, CET and CES parameters for 64 sectors give 192 benchmark parameter values.'),
    'S9_policy_rankings':('Policy rankings by configuration','One row per configuration. Four supported policies are ranked by their FGT1 outcomes within that configuration.'),
    'S10_negative_income_diagnostic':('Negative-income boundary diagnostic','One row per configuration with negative reconstructed household income. An empty Data sheet means no configuration was flagged; see income_boundary_check.json for the complete audit.')}
SECTOR_NAMES = [
    'Crop and animal production, hunting and related services',
    'Forestry and logging', 'Fishing and aquaculture', 'Mining and quarrying',
    'Manufacture of food, beverages and tobacco products',
    'Manufacture of textiles, wearing apparel, leather and related products',
    'Manufacture of wood and cork products, except furniture; articles of straw and plaiting materials',
    'Manufacture of paper and paper products', 'Printing and reproduction of recorded media',
    'Manufacture of coke and refined petroleum products', 'Manufacture of chemicals and chemical products',
    'Manufacture of basic pharmaceutical products and pharmaceutical preparations',
    'Manufacture of rubber and plastic products', 'Manufacture of other non-metallic mineral products',
    'Manufacture of basic metals', 'Manufacture of fabricated metal products, except machinery and equipment',
    'Manufacture of computer, electronic and optical products', 'Manufacture of electrical equipment',
    'Manufacture of machinery and equipment n.e.c.', 'Manufacture of motor vehicles, trailers and semi-trailers',
    'Manufacture of other transport equipment', 'Manufacture of furniture and other manufactured goods',
    'Repair and installation of machinery and equipment', 'Electricity, gas, steam and air conditioning supply',
    'Water collection, treatment and supply', 'Sewerage, waste collection, treatment, disposal, materials recovery and remediation',
    'Construction', 'Wholesale and retail trade and repair of motor vehicles and motorcycles',
    'Wholesale trade, except motor vehicles and motorcycles', 'Retail trade, except motor vehicles and motorcycles',
    'Land transport and transport via pipelines', 'Water transport', 'Air transport',
    'Warehousing and support activities for transportation', 'Postal and courier activities',
    'Accommodation and food service activities', 'Publishing activities',
    'Motion picture, video, television, sound recording and music publishing; programming and broadcasting',
    'Telecommunications', 'Computer programming, consultancy and related activities; information services',
    'Financial services, except insurance and pension funding',
    'Insurance, reinsurance and pension funding, except compulsory social security',
    'Activities auxiliary to financial services and insurance', 'Other real estate activities',
    'Imputed owner-occupied housing services',
    'Legal and accounting activities; head offices and management consultancy',
    'Architectural and engineering activities; technical testing and analysis',
    'Scientific research and development', 'Advertising and market research',
    'Other professional, scientific and technical activities; veterinary activities',
    'Rental and leasing activities', 'Employment activities',
    'Travel agencies, tour operators and other reservation services',
    'Security and investigation; services to buildings and landscaping; office administration and business support',
    'Public administration and defence; compulsory social security', 'Education', 'Human health activities',
    'Residential care and social work without accommodation', 'Creative, arts, entertainment and cultural activities',
    'Sports, amusement and recreation activities', 'Activities of membership organisations',
    'Repair of computers and personal and household goods', 'Other service activities',
    'Activities of households as employers of domestic personnel']

def definition(key,stem):
    if stem=='S9_policy_rankings' and key in POLICY:
        return (POLICY_LABELS[key]+' rank', 'Rank; 1 is best',
            'Rank of this policy when the four supported policies in the same configuration are ordered by ascending FGT1.',
            '1 indicates the lowest poverty gap. pandas rank assigns average ranks to ties; fractional ranks are therefore possible. The current results contain ranks 1–4.', R)
    return D[key]

TITLES.update({
    'PMT_predictors':('PMT predictors and fold-local preprocessing','Five predictor blocks containing 19 categorical and 9 numeric inputs.'),
    'Quintile_results':('Quintile outcomes under the main policies','One row per policy and benchmark income quintile: 4 supported policies x 5 groups.'),
    'Score_degradation_summary':('Score degradation: means and conditional intervals','Ten score levels; each mean uses ten recipient seeds. Conditional intervals combine recipient and household-weight variation.')})

def write_workbook(key,df):
    """No cell styles, filters, frozen panes, tables, or custom row/column sizes."""
    from supplementary_catalog import TABLE_FILES
    import pandas as pd
    title,scope=TITLES[key]
    wb=Workbook();ws=wb.active;ws.title=DATA_SHEET;notes=wb.create_sheet(DOCS)
    headers=list(df.columns);ws.append(headers)
    def value(x):
        if pd.isna(x):return None
        if hasattr(x,'item'):return x.item()
        return x
    for record in df.itertuples(index=False,name=None):ws.append([value(x) for x in record])
    notes.append(['Variable (data column)','Description','Unit / stored scale','Definition / calculation','Reference, interpretation and scope','Code / source'])
    for k in headers:notes.append([k,*definition(k,key)])
    notes.append([])
    notes.append(['Table',title]);notes.append(['Scope',scope])
    notes.append(['Units','Percent fields use 7.2 for 7.2%; percentage-point fields report differences. Fractions use 0.30 for 30%. One trillion TL equals 1,000 billion TL.'])
    notes.append(['Weights','Person weight equals household expansion weight times household size. Poverty and targeting rates use person weights; aggregate consumption welfare uses household weights and initial spending.'])
    notes.append(['Default poverty line','60% of the benchmark person-weighted median equivalent disposable income; held fixed in real terms across policies.'])
    notes.append(['Missing values','Empty cells retain missing or inapplicable source entries.'])
    notes.append(['Reproduction','Generated by codes/document_supplementary_tables.py from stored model outputs. The two worksheets contain data and documentation only.'])
    if 'case' in df:
        for code in df['case'].drop_duplicates():notes.append(['Scenario: '+code,CASES[code]])
    pols=set(df['policy']) if 'policy' in df else set(headers)&set(POLICY)
    for code in POLICY:
        if code in pols:notes.append(['Policy: '+code,POLICY[code]])
    if key in ('S4_error_grid_draws','S5_error_grid_summary','S6_score_degradation_draws','Score_degradation_summary'):
        notes.append(['Experimental comparison','Main configuration; differences are relative to universal cash at the same net cost. Tables S4 and S5 contain random error-grid draws and summaries; Tables S6 and S7 contain score-level summaries and individual draws.'])
        notes.append(['Ranges and intervals','Error-grid minimum/maximum values describe recipient-draw ranges. Table S6 lower95_pp and upper95_pp are joint conditional household-weight and recipient-seed intervals.'])
    if 'sector' in df:
        sam=load_workbook(ROOT/'datas/SAM_2023_64_sectors_5_households.xlsx',read_only=True,data_only=True)
        for row in sam['Accounts'].iter_rows(min_row=2,values_only=True):
            if re.fullmatch(r'S\d{2}',str(row[0])):notes.append(['Sector: '+row[0],row[1],SECTOR_NAMES[int(row[0][1:])]])
        sam.close()
    if key=='S8_elasticity_assignment':notes.append(['Parameter sources','Original source statements and links in Data are retained. All variable definitions in this sheet are in English.'])
    if key=='S7_micro_sensitivity':
        notes.append(['Basket: False','Use household-specific calibrated expenditure baskets.'])
        notes.append(['Basket: True','Use a common expenditure basket within each benchmark quintile.'])
    dest=FOLDER/TABLE_FILES[key];dest.parent.mkdir(parents=True,exist_ok=True)
    tmp=dest.with_suffix('.tmp.xlsx');wb.save(tmp);wb.close()
    verify(tmp,df);tmp.replace(dest)
    return {'file':dest.name,'rows':len(df),'variables':len(headers),'sheets':[DATA_SHEET,DOCS]}

def verify(path,df):
    import pandas as pd
    wb=load_workbook(path,data_only=False)
    assert wb.sheetnames==[DATA_SHEET,DOCS]
    ws=wb[DATA_SHEET]
    assert [c.value for c in ws[1]]==list(df.columns)
    assert ws.max_row==len(df)+1
    for row,expected in zip(ws.iter_rows(min_row=2),df.itertuples(index=False,name=None)):
        for c,v in zip(row,expected):
            if pd.isna(v):assert c.value is None
            elif isinstance(v,(float,int)) and not isinstance(v,bool):assert math.isclose(c.value,v,rel_tol=2e-14,abs_tol=0),(path,c.coordinate,c.value,v)
            else:assert c.value==v,(path,c.coordinate,c.value,v)
    assert [wb[DOCS].cell(r,1).value for r in range(2,len(df.columns)+2)]==list(df.columns)
    for sheet in wb:
        assert sheet.freeze_panes is None and not sheet.auto_filter.ref
        assert not sheet.tables and not sheet.merged_cells.ranges and not sheet.conditional_formatting
        assert not sheet.row_dimensions and not sheet.column_dimensions
        for row in sheet:
            for cell in row:
                assert not cell.has_style and cell.comment is None and cell.data_type not in ('f','e')
    for row in wb[DOCS]:
        for c in row:
            if isinstance(c.value,str):assert not re.search('[çğıöşüÇĞİÖŞÜ]',c.value),(path,c.value)
    wb.close()

def derived_tables():
    import pandas as pd
    from supplementary_catalog import load_supplementary
    supported=['perfect_targeting','pmt','universal_cash','price_support']
    q=pd.read_csv(ROOT/'outputs/tables/main/Table3_quintile_results.csv')
    write_workbook('Quintile_results',q[q.policy.isin(supported)].reset_index(drop=True))
    write_workbook('Score_degradation_summary',pd.read_csv(ROOT/'outputs/tables/main/Table7_score_degradation.csv'))
    predictor_blocks=[
        ('Categorical','Household type; dwelling type; tenure; heating system; fuel type; bathroom; toilet; piped water; natural gas.',9),
        ('Categorical','Computer; internet; dishwasher; tumble dryer; air conditioner; garage; detached dwelling ownership; apartment ownership; summer dwelling ownership.',9),
        ('Categorical','Education of the first recorded household member.',1),
        ('Numeric','Household size; number of rooms; dwelling area; counts of mobile phones, cars and motorcycles.',6),
        ('Numeric','Counts of children under 15, persons aged 65 or older, and adults aged 15-64.',3)]
    preprocessing={'Categorical':'Separate missing category and one-hot encoding with unknown-category handling; fitted within each training fold.','Numeric':'Training-fold median imputation and standardisation.'}
    p=pd.DataFrame(predictor_blocks,columns=['predictor_type','predictors','predictor_count'])
    p['preprocessing']=p.predictor_type.map(preprocessing)
    write_workbook('PMT_predictors',p)
    d=load_supplementary('S3_sector_results')
    eq=json.loads((ROOT/'outputs/equilibria/main_equilibria.json').read_text(encoding='utf-8'))
    shock=pd.DataFrame(eq['shock']['sectors']).set_index('sector').output_pct
    d['output_relative_to_shock_pct']=100*((1+d.output_pct/100)/(1+d.sector.map(shock)/100)-1)
    write_workbook('S3_sector_results',d)

def main():
    from supplementary_catalog import TABLE_FILES,load_supplementary
    derived_tables()
    available={key:file for key,file in TABLE_FILES.items() if (FOLDER/file).exists()}
    report=[write_workbook(key,load_supplementary(key)) for key in available]
    summary=dict(workbooks=report,description_language='English',plain_format=True,all_columns_documented=True,data_values_verified=True,formulas_added=0)
    (ROOT/'outputs/diagnostics/supplementary_workbook_documentation.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    index=['# Supplementary tables','', 'Each table is supplied as one plain Excel workbook with Data and Variable Descriptions worksheets. Definitions are in English. Numbering follows first citation in the main article.','']
    for key,item in zip(available,report):index.extend([f"- [{item['file']}](../tables/supplementary/{item['file']}): {TITLES[key][0]} ({item['rows']} rows)."])
    (ROOT/'outputs/reports/Supplementary_Tables.md').write_text('\n'.join(index)+'\n',encoding='utf-8')
    print(json.dumps({'workbooks':len(report),'documented_columns':sum(r['variables'] for r in report),'data_rows':sum(r['rows'] for r in report),'plain_format':True}))

if __name__=='__main__':main()
