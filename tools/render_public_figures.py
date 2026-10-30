"""Regenerate all fourteen English figures using published aggregate data only."""
from pathlib import Path
import sys
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'5_simulation/codes'))
import figure_design as fd
import coverage_publication_outputs as cv

def main():
    def save(fig,name,caption='',supp=False,tr=False):
        if tr:fd.plt.close(fig);return
        name=fd.NAME_MAP.get(name,name)
        folder=ROOT/'5_simulation/outputs/figures'/('supplementary' if supp else 'main')
        folder.mkdir(parents=True,exist_ok=True)
        fig.savefig(folder/f'{name}.png',dpi=600,bbox_inches='tight',pad_inches=.04)
        fd.plt.close(fig);print('Rendered',name,flush=True)
    fd.save=save;cv.save=lambda fig,name,supp=False,tr=False:save(fig,name,supp=supp,tr=tr)
    for fn in ['fig2_exposure','fig3_poverty','fig4_incidence','fig5_targeting_errors','fig6_decomposition',
               'figS1_robustness','figS2_sectors','figS3_macro','figS4_measurement','figS5_pmt']:
        getattr(fd,fn)()
    cv.framework(False)
    out=ROOT/'5_simulation/outputs'
    curve=pd.read_excel(out/'tables/supplementary/S14_coverage_pareto_frontier.xlsx',sheet_name='Data')
    eps=pd.read_excel(out/'tables/supplementary/S15_epsilon_constraint_solutions.xlsx',sheet_name='Data')
    intervals=pd.read_csv(out/'tables/PMT_coverage_tradeoff_intervals.csv')
    robust=pd.read_csv(out/'tables/PMT_coverage_robustness_refined_summary.csv')
    cv.figures(curve,eps,intervals,robust)
if __name__=='__main__':main()
