"""Run independent robustness cases in isolated folders, then verify and merge.

Each subprocess invokes the original per-case search without changing its grid,
solver, random seed or tolerances. Only aggregate outputs are copied to workers.
"""
from pathlib import Path
import os,sys,json,time,shutil,subprocess,hashlib
from concurrent.futures import ThreadPoolExecutor,as_completed
import pandas as pd
import common as cm

INPUTS=['diagnostics/pmt_design.json','diagnostics/micro_calibration.json',
        'diagnostics/pmt_epsilon_constraint.json','tables/main/Table1_main_policy_results.csv',
        'diagnostics/pmt_coverage_optimization_final.json']

def main():
    started=time.time();out=cm.OUT
    names=list(cm.configurations())+[f'pmt_partition_{x}' for x in (20261026,20261027,20261028)]
    protected={str((out/r).relative_to(cm.ROOT)):cm.sha(out/r) for r in INPUTS}
    version=''.join(cm.sha(out/r) for r in INPUTS)+''.join(cm.sha(p) for p in sorted(Path(__file__).parent.glob('*.py')))
    version+=cm.sha(Path(cm.cge.__file__))
    run_id=hashlib.sha256(version.encode()).hexdigest()[:16]
    workers=out/'diagnostics/coverage_workers'/run_id;workers.mkdir(parents=True,exist_ok=True)
    def run(name):
        target=workers/name
        for rel in INPUTS:
            p=target/rel;p.parent.mkdir(parents=True,exist_ok=True)
            if not p.exists():shutil.copy2(out/rel,p)
            assert cm.sha(p)==cm.sha(out/rel),(name,rel)
        code=("from pathlib import Path; import common as cm; "
              f"cm.OUT=Path({str(target)!r}); "
              "import pmt_coverage_robustness as run; run.main()")
        with (target/'worker.log').open('w',encoding='utf-8') as log:
            result=subprocess.run([sys.executable,'-B','-c',code,'--only',name],
                                  cwd=Path(__file__).parent,stdout=log,stderr=subprocess.STDOUT,
                                  env={**os.environ,'PYTHONIOENCODING':'utf-8','OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'1','MKL_NUM_THREADS':'1'})
        if result.returncode:raise RuntimeError(f'Case {name} failed; see {target / "worker.log"}')
        audit=json.loads((target/'diagnostics/pmt_coverage_robustness.json').read_text(encoding='utf-8'))
        assert audit['status']=='complete' and list(audit['cases'])==[name]
        for rel,digest in audit['protected_hashes'].items():assert cm.sha(cm.ROOT/rel)==digest
        return name,target,audit
    complete={}
    with ThreadPoolExecutor(max_workers=min(4,os.cpu_count() or 1)) as pool:
        futures=[pool.submit(run,n) for n in names]
        for future in as_completed(futures):
            name,target,audit=future.result();complete[name]=(target,audit)
            case=audit['cases'][name]
            print(f'Completed {name}: minimum {case["numerical_minimum"]["coverage_pct"]:.4f}%; {len(complete)}/{len(names)} cases',flush=True)
    first=complete[names[0]][1];cases={};frames=[];summaries=[]
    for name in names:
        target,audit=complete[name]
        assert audit['source_hashes']==first['source_hashes']
        for k in ['population','target_population','initial_poor_population']:assert abs(audit[k]-first[k])<1e-6
        cases[name]=audit['cases'][name]
        frames.append(pd.read_csv(target/'tables/PMT_coverage_robustness_curves.csv'))
        summaries.extend(cases[name]['selected'])
    pd.concat(frames,ignore_index=True).to_csv(out/'tables/PMT_coverage_robustness_curves.csv',index=False,float_format='%.12g')
    pd.DataFrame(summaries).to_csv(out/'tables/PMT_coverage_robustness_summary.csv',index=False,float_format='%.12g')
    shutil.copy2(complete['main'][0]/'tables/PMT_coverage_feedback.csv',out/'tables/PMT_coverage_feedback.csv')
    for rel,digest in protected.items():assert cm.sha(cm.ROOT/rel)==digest
    merged={**first,'status':'complete','completed_case_count':len(cases),'cases':cases,
            'protected_hashes':protected,'elapsed_seconds':time.time()-started,
            'execution':'Independent, isolated subprocesses; unchanged per-case numerical search.',
            'parallel_runner_sha256':cm.sha(Path(__file__)),
            'case_audits':{n:str((v[0]/'diagnostics/pmt_coverage_robustness.json').relative_to(out)) for n,v in complete.items()}}
    cm.dump(out/'diagnostics/pmt_coverage_robustness.json',merged)
    print('COMPLETE',len(cases),'independently verified cases',flush=True)

if __name__=='__main__':main()
