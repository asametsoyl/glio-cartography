"""Registration sanity on real DLPFC pairs. Labels (obs['Truth']) are NOT used by the registration; they only
score it: share of registered nearest-neighbour spot pairs with the same cortical layer, vs the same measure after a
500 um shift. Run after: python benchmarks/fetch_data.py dlpfc_maynard2021
"""
import sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np, anndata as ad
from scipy.spatial import cKDTree
from spatialcore.io import volume_from_anndata
from spatialcore.config import RegistrationConfig
from spatialcore.registration import register_volume
R=str(Path(__file__).resolve().parent/'data/dlpfc_maynard2021/1_DLPFC')+'/'
for donor,ids in {'Br8100':['151673','151674','151675','151676'],'Br5292':['151507','151508','151509','151510']}.items():
    ad_={i:ad.read_h5ad(R+i+'.h5ad') for i in ids}
    vs=volume_from_anndata(ad_,order=ids,thickness_um=10.,thickness_source='nominal')
    t0=time.time(); rep=register_volume(vs,RegistrationConfig(n_starts=24,model='rigid'))
    lab={i:ad_[i].obs['Truth'].astype(str).to_numpy() for i in ids}
    print(donor,'%.0fs'%(time.time()-t0))
    for p in rep.pairs:
        T=p.transform.decompose()
        ru,rl=vs.rows(p.upper),vs.rows(p.lower)
        reg=vs.obs[['x_registered','y_registered']].to_numpy()
        # label agreement between each lower spot and nearest upper spot in the registered frame (pair frame)
        Xl=p.transform.apply(vs.obs[['x_raw','y_raw']].to_numpy()[rl]); Xu=vs.obs[['x_raw','y_raw']].to_numpy()[ru]
        d,j=cKDTree(Xu).query(Xl); m=d<60
        ok=(lab[p.lower][m]==lab[p.upper][j[m]])&(lab[p.lower][m]!='nan')
        # null: shift 500um
        d2,j2=cKDTree(Xu).query(Xl+np.array([500.,0])); m2=d2<60
        ok2=(lab[p.lower][m2]==lab[p.upper][j2[m2]])
        print(' ',p.upper,p.lower,'angle %.1f deg scale %.3f'%(T['angle_deg'],T['scale']),'t=(%.0f,%.0f)um'%tuple(p.transform.t),p.qc.status,'overlap %.2f gain %.3f coh %.2f'%(p.qc.overlap,p.qc.expr_gain,p.qc.coherence),'sigma_pos %.0f deform %.0f'%(p.sigma_pos_um,p.deformation_um),'| layer agreement %.2f (n=%d) vs shifted-null %.2f'%(ok.mean(),m.sum(),ok2.mean()), p.qc.reasons)
