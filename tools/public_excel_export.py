"""Portable workbook export; formula caches come from the scientific Python code."""
from pathlib import Path
import re
import xlsxwriter
from xlsxwriter.utility import xl_cell_to_rowcol

def export_jobs(jobs):
    for job in jobs:
        target=Path(job.get('output',job.get('path')))
        target.parent.mkdir(parents=True,exist_ok=True)
        expected={(x['sheet'],x['cell']):x['value'] for x in job.get('expected',[])}
        with xlsxwriter.Workbook(target,{'strings_to_urls':False}) as book:
            for spec in job['sheets']:
                sh=book.add_worksheet(spec['name'])
                for r,row in enumerate(spec['values']):
                    for c,value in enumerate(row):
                        if value is None:continue
                        if isinstance(value,str):sh.write_string(r,c,value)
                        else:sh.write(r,c,value)
                for item in spec.get('formulas',[]):
                    cell,formula=item['cell'],item['formula']
                    key=(spec['name'],cell)
                    if key in expected:cache=expected[key]
                    elif match:=re.fullmatch(r'=IF\((E\d+)<=0\.001,"Pass","Difference detected"\)',formula):
                        cache='Pass' if expected[(spec['name'],match[1])]<=.001 else 'Difference detected'
                    else:raise ValueError('Missing formula cache: '+str(key))
                    r,c=xl_cell_to_rowcol(cell)
                    sh.write_formula(r,c,formula,None,cache)
        print('Exported',target.name)
