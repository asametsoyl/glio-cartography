"""Phantom pair-level registration error vs the predicted position uncertainty. Usage: python phantom_registration_eval.py EMH"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
from spatialcore.config import PhantomConfig, RegistrationConfig, QCConfig
from spatialcore.synthetic import build_phantom
from spatialcore.registration import register_pair, Transform
cfg,qc=RegistrationConfig(n_starts=12),QCConfig()
for tier in sys.argv[1]:
  R=[]
  for sd in [9,10,11,12]:
    p=build_phantom(PhantomConfig.from_tier(tier,n_genes=500,seed=sd)); v,t=p.volume,p.truth
    xy=v.obs[['x_raw','y_raw']].to_numpy(); c=np.array(t.config.extent_um)/2
    for kf,km in [(0,1),(1,2),(2,3),(3,4),(4,5)]:
        if f"s{kf:02d}" not in t.section_ids or f"s{km:02d}" not in t.section_ids: continue
        ra,rb=v.rows(f"s{kf:02d}"),v.rows(f"s{km:02d}")
        r=register_pair(v.X[ra],v.X[rb],xy[ra],xy[rb],cfg,qc,('a','b'))
        f,m=t.transforms[kf],t.transforms[km]
        Traw=Transform(np.eye(2),c).compose(Transform(f['A'],f['t'])).compose(Transform(m['A'],m['t']).inverse()).compose(Transform(np.eye(2),-c))
        err=np.linalg.norm(r.transform.apply(xy[rb])-Traw.apply(xy[rb]),axis=1)
        rms2d=np.sqrt((err**2).mean()); R.append((rms2d/np.sqrt(2), r.sigma_pos_um))
  R=np.array(R); ratio=R[:,0]/R[:,1]
  print(tier,'pairs',len(R),'actual per-coord rms: median %.1f | predicted median %.2f | ratio median %.1f  p10 %.1f p90 %.1f'%(np.median(R[:,0]),np.median(R[:,1]),np.median(ratio),np.percentile(ratio,10),np.percentile(ratio,90)))
