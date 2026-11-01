"""Reproduce CES simulation outputs in dependency order; no CD outputs are copied."""
from pathlib import Path
import sys,subprocess,json,time,os,argparse
HERE=Path(__file__).resolve().parent
OUT=HERE.parent/'outputs'
STEPS=['run_simulations.py','income_diagnostics.py','publication_outputs.py','validate_results.py',
'pmt_coverage_sensitivity.py','pmt_coverage_optimization.py','pmt_coverage_competing_minima.py',
'summarize_pmt_coverage_optimization.py','pmt_coverage_tradeoff.py','pmt_epsilon_constraint.py',
'pmt_coverage_robustness.py','refine_coverage_robustness.py','coverage_publication_outputs.py']
def main():
    parser=argparse.ArgumentParser();parser.add_argument('--start-at',choices=STEPS);args=parser.parse_args()
    for name in ['diagnostics','logs','reports','tables/main','tables/supplementary','figures/main','figures/supplementary','figures/data','equilibria']:
        (OUT/name).mkdir(parents=True,exist_ok=True)
    audit=OUT/'diagnostics/CES_pipeline.json'
    if args.start_at:
        state=json.loads(audit.read_text(encoding='utf-8'))
        state['steps']=[r for r in state['steps'] if STEPS.index(r['script'])<STEPS.index(args.start_at)]
        state['status']='running';state.pop('failed_script',None)
    else:state={'status':'running','household_utility':'nested_CES','started':time.time(),'steps':[]}
    audit.write_text(json.dumps(state,indent=2),encoding='utf-8')
    for name in STEPS[STEPS.index(args.start_at) if args.start_at else 0:]:
        print('START',name,flush=True);start=time.time()
        with (OUT/'logs'/name.replace('.py','.log')).open('w',encoding='utf-8') as log:
            proc=subprocess.Popen([sys.executable,'-B',str(HERE/name)],cwd=HERE,stdout=log,stderr=subprocess.STDOUT,env={**os.environ,'PYTHONIOENCODING':'utf-8','OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'1','MKL_NUM_THREADS':'1'})
            code=proc.wait()
        state['steps'].append({'script':name,'exit_code':code,'seconds':time.time()-start})
        if code:state['status']='failed';state['failed_script']=name
        (OUT/'diagnostics/CES_pipeline.json').write_text(json.dumps(state,indent=2),encoding='utf-8')
        print('FINISH',name,code,round(time.time()-start,1),flush=True)
        if code:sys.exit(code)
    state['status']='complete';state['seconds']=time.time()-state['started']
    (OUT/'diagnostics/CES_pipeline.json').write_text(json.dumps(state,indent=2),encoding='utf-8')
if __name__=='__main__':main()
