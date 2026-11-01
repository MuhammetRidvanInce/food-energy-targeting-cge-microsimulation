"""Independent checks for numerical, workbook and manuscript consistency."""
from pathlib import Path
import argparse,json,re,hashlib
import numpy as np
import pandas as pd
from openpyxl import load_workbook
from zipfile import ZipFile
from lxml import etree
from pypdf import PdfReader
from common import OUT,ROOT,PROJECT,sha,dump,configurations

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--documents');ap.add_argument('--pages',type=int);a=ap.parse_args()
    docdir=Path(a.documents) if a.documents else PROJECT/'6_manuscript'
    original=json.loads((OUT/'diagnostics/pmt_coverage_optimization.json').read_text(encoding='utf-8'))
    for rel,expected in original['protected_output_hashes'].items():assert sha(ROOT/rel)==expected,rel
    for rel,expected in original['source_hashes'].items():assert sha(PROJECT/rel)==expected,rel
    phase1=json.loads((OUT/'diagnostics/pmt_coverage_robustness.json').read_text(encoding='utf-8'))
    phase2=json.loads((OUT/'diagnostics/pmt_coverage_robustness_refined.json').read_text(encoding='utf-8'))
    assert phase1['status']==phase2['status']=='complete';assert len(phase2['cases'])==len(configurations())+3
    assert phase2['prior_sha256']==sha(OUT/'diagnostics/pmt_coverage_robustness.json')
    assert phase2['code_sha256']==sha(ROOT/'codes/refine_coverage_robustness.py')
    for arow,brow in zip(phase2['cases']['main']['selected'],phase2['cases']['energy_support_only']['selected']):
        assert abs(arow['coverage_pct']-brow['coverage_pct'])<1e-4
    checks=[d for case in phase1['cases'].values() for d in case['checks']]+[d for case in phase2['cases'].values() for d in case['checks']]
    maxima={key:max(d[key] for d in checks) for key in ['max_scaled_equation_residual','max_relative_goods_gap','household_budget_relative_gap','gdp_identity_relative_gap','sam_gap_trillion_tl','equal_net_cost_relative_gap']}
    assert max(maxima.values())<1e-8,maxima
    for case in phase2['cases'].values():
        rows=case['selected'];assert [r['choice'] for r in rows]==['minimum_gap','retain_75','retain_50']
        assert rows[0]['coverage_pct']<=rows[1]['coverage_pct']<=rows[2]['coverage_pct']
        assert np.ptp([r['net_fiscal_cost_billion_tl'] for r in rows])<1e-5
        for r in rows[1:]:assert r['fgt1_pct']<=r['fgt1_limit_pct']+1e-7
    pub=json.loads((OUT/'diagnostics/coverage_publication_outputs.json').read_text(encoding='utf-8'));assert pub['status']=='complete'
    files={};shapes={}
    for meta in pub['tables']:
        p=OUT/'tables/supplementary'/meta['file'];w=load_workbook(p,data_only=False)
        assert w.sheetnames==['Data','Variable Descriptions']
        data=w['Data'];descr=w['Variable Descriptions'];headers=[c.value for c in data[1]]
        assert headers==[row[0].value for row in list(descr.rows)[1:]]
        assert data.max_row==meta['rows']+1 and data.max_column==meta['columns']
        for sheet in w:
            assert sheet.freeze_panes is None and sheet.auto_filter.ref is None and not sheet.merged_cells.ranges
            for row in sheet:
                for cell in row:assert not cell.has_style and cell.data_type!='f' and cell.data_type!='e'
        files[meta['file']]=sha(p);shapes[meta['file']]=[meta['rows'],meta['columns']]
    c=pd.read_excel(OUT/'tables/supplementary/S14_coverage_pareto_frontier.xlsx',sheet_name='Data')
    eps=pd.read_excel(OUT/'tables/supplementary/S15_epsilon_constraint_solutions.xlsx',sheet_name='Data')
    assert len(c)>100 and c.pareto_efficient_evaluated.sum()>0
    star=c.fgt1_pct.min();assert np.allclose(c.fgt1_regret_pp,c.fgt1_pct-star,atol=1e-9)
    assert c.isna().sum().sum()==0,c.isna().sum()[c.isna().any()]
    assert np.allclose(eps.actual_fgt1_cost_pp,eps.fgt1_pct-star,atol=1e-9)
    assert eps.epsilon_slack_pp.min()>-1e-8
    for r in eps.itertuples():
        assert not ((c.coverage_pct>r.coverage_pct+1e-6)&(c.fgt1_pct<r.fgt1_pct-1e-8)).any()
    main_table=pd.read_csv(OUT/'tables/main/table5.csv')
    for r in main_table.itertuples():
        candidate=eps.iloc[(eps.coverage_pct-r.coverage_pct).abs().argmin()]
        assert abs(candidate.fgt1_pct-r.fgt1_pct)<1e-9
    figcheck=[]
    for key,supp in [('fig1',False),('fig7',False),('figS6',True),('figS7',True)]:
        folder=OUT/'figures'/('supplementary' if supp else 'main')
        for ext in ['png','svg','pdf','tiff']:assert (folder/f'{key}.{ext}').stat().st_size>1000
        pdf=PdfReader(folder/f'{key}.pdf');assert len(pdf.pages)==1 and len(pdf.pages[0].extract_text())>40
        figcheck.append(key)
    ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main','m':'http://schemas.openxmlformats.org/officeDocument/2006/math'}
    documents={}
    for name in ['Manuscript_TR.docx','Supplementary_Material.docx']:
        path=docdir/name
        if not a.documents:continue  # Analysis-only delivery: manuscript preparation is a later task.
        with ZipFile(path) as z:xml=etree.fromstring(z.read('word/document.xml'))
        paragraphs=[''.join(p.xpath('.//w:t/text() | .//m:t/text()',namespaces=ns)) for p in xml.xpath('./w:body/w:p',namespaces=ns)]
        full='\n'.join(paragraphs)
        assert not re.search(r'[A-Z]:[\\/]|5_simulation[\\/]|3_household_groups[\\/]|\[\[|\{\{cite',full)
        assert 'NaN' not in full and 'nan' not in full.split()
        if name=='Manuscript_TR.docx':
            eq=[int(m[1]) for p in paragraphs if (m:=re.search(r'\((\d+)\)$',p))]
            assert eq==list(range(1,21)),eq
            for label,nmax in [('Şekil',7),('Table',5)]:
                captions=[int(m[1]) for p in paragraphs if (m:=re.match(label+r' (\d+)\.',p))]
                assert captions==list(range(1,nmax+1)),captions
                for num in captions:
                    ix=next(i for i,p in enumerate(paragraphs) if p.startswith(f'{label} {num}.'))
                    assert re.search(label+r' '+str(num)+r'\b',' '.join(paragraphs[:ix]))
            for label,nmax in [('Table',18),('Şekil',7)]:
                seen=[]
                for m in re.finditer(label+r' S(\d+)\b',full):
                    number=int(m[1])
                    if number not in seen:seen.append(number)
                assert seen==list(range(1,nmax+1)),(label,seen)
            assert '10.1016/j.amc.2009.03.037' in full and '10.5089/9781513547046.001' in full
            # User review highlights are editable annotations, not a numerical contract.
            # Their preservation is checked against the translation source snapshot.
            if a.pages:assert a.pages<=35
        else:
            for i in range(1,19):assert re.search(r'Table S'+str(i)+r'\b',full),i
            for i in range(1,8):assert re.search(r'Figure S'+str(i)+r'\b',full),i
        documents[name]=dict(sha256=sha(path),paragraphs=len(paragraphs),pages=a.pages if name=='Manuscript_TR.docx' else None)
    audit=dict(status='passed',coverage_points=len(c),pareto_points=int(c.pareto_efficient_evaluated.sum()),robustness_cases=len(phase2['cases']),
        additional_robustness_policy_solves=len(checks),maxima=maxima,supplementary_tables=shapes,
        file_hashes=files,figures=figcheck,documents=documents,original_analytical_inputs_and_outputs_unchanged=True)
    dump(OUT/'diagnostics/coverage_delivery_validation.json',audit)
    print(json.dumps({k:v for k,v in audit.items() if k not in ['file_hashes','documents']},ensure_ascii=False))

if __name__=='__main__':main()
