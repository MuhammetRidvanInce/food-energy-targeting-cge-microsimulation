"""Isolated parallel execution of unchanged per-case competing-minimum checks."""
from pathlib import Path
import os,sys,json,time,shutil,subprocess,hashlib
from concurrent.futures import ThreadPoolExecutor,as_completed
import pandas as pd
import common as cm

INPUTS=['diagnostics/pmt_coverage_robustness.json','diagnostics/pmt_coverage_optimization_final.json',
        'diagnostics/pmt_coverage_optimization.json','tables/PMT_coverage_robustness_curves.csv']

def main():
    started=time.time();out=cm.OUT
    prior=json.loads((out/INPUTS[0]).read_text(encoding='utf-8'))
    assert prior['status']=='complete' and prior['completed_case_count']==len(cm.configurations())+3
    names=list(prior['cases']);source_sha=cm.sha(out/INPUTS[0])
    version=''.join(cm.sha(out/r) for r in INPUTS)+''.join(cm.sha(p) for p in sorted(Path(__file__).parent.glob('*.py')))
    version+=cm.sha(Path(cm.cge.__file__))
    run_id=hashlib.sha256(version.encode()).hexdigest()[:16]
    workers=out/'diagnostics/refinement_workers'/run_id;workers.mkdir(parents=True,exist_ok=True)
    def run(name):
        target=workers/name
        for rel in INPUTS:
            p=target/rel;p.parent.mkdir(parents=True,exist_ok=True)
            if not p.exists():shutil.copy2(out/rel,p)
            assert cm.sha(p)==cm.sha(out/rel),(name,rel)
        code=("from pathlib import Path; import common as cm; "
              f"cm.OUT=Path({str(target)!r}); "
              "import refine_coverage_robustness as run; run.main()")
        with (target/'worker.log').open('w',encoding='utf-8') as log:
            result=subprocess.run([sys.executable,'-B','-c',code,'--only',name],
                                  cwd=Path(__file__).parent,stdout=log,stderr=subprocess.STDOUT,
                                  env={**os.environ,'PYTHONIOENCODING':'utf-8','OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'1','MKL_NUM_THREADS':'1'})
        if result.returncode:raise RuntimeError(f'Refinement {name} failed; see {target / "worker.log"}')
        audit=json.loads((target/'diagnostics/pmt_coverage_robustness_refined.json').read_text(encoding='utf-8'))
        assert audit['status']=='complete' and list(audit['cases'])==[name]
        assert audit['prior_sha256']==source_sha
        return name,target,audit
    complete={}
    worker_count=max(1,min(int(os.environ.get('CES_REFINEMENT_WORKERS','6')),6,os.cpu_count() or 1))
    with ThreadPoolExecutor(max_workers=worker_count) as pool:
        futures=[pool.submit(run,n) for n in names]
        for future in as_completed(futures):
            name,target,audit=future.result();complete[name]=(target,audit)
            case=audit['cases'][name]
            print(f'Refined {name}: minimum {case["numerical_minimum"]["coverage_pct"]:.4f}%; {len(complete)}/{len(names)} cases',flush=True)
    first=complete[names[0]][1];cases={};frames=[];summaries=[]
    for name in names:
        target,audit=complete[name]
        assert audit['code_sha256']==first['code_sha256']
        cases[name]=audit['cases'][name]
        frame=pd.read_csv(target/'tables/PMT_coverage_robustness_refined_curves.csv')
        frames.append(frame[frame.configuration==name])
        summaries.extend(cases[name]['selected'])
    assert abs(cases['main']['numerical_minimum']['fgt1_pct']-cases['energy_support_only']['numerical_minimum']['fgt1_pct'])<1e-6
    pd.concat(frames,ignore_index=True).to_csv(out/'tables/PMT_coverage_robustness_refined_curves.csv',index=False,float_format='%.12g')
    pd.DataFrame(summaries).to_csv(out/'tables/PMT_coverage_robustness_refined_summary.csv',index=False,float_format='%.12g')
    for rel,digest in prior['protected_hashes'].items():assert cm.sha(cm.ROOT/rel)==digest
    assert cm.sha(out/INPUTS[0])==source_sha
    merged={**first,'status':'complete','completed_case_count':len(names),'cases':cases,
            'parallel_workers':worker_count,
            'elapsed_seconds':time.time()-started,'parallel_runner_sha256':cm.sha(Path(__file__)),
            'execution':'Independent, isolated subprocesses; unchanged per-case refinement.',
            'case_audits':{n:str((v[0]/'diagnostics/pmt_coverage_robustness_refined.json').relative_to(out)) for n,v in complete.items()}}
    cm.dump(out/'diagnostics/pmt_coverage_robustness_refined.json',merged)
    print('COMPLETE',len(cases),'independently verified refinement cases',flush=True)

if __name__=='__main__':main()
