import unittest
import torch
import numpy as np
import sys
from pathlib import Path
from torch_geometric.data import HeteroData

# Add backend dir to path to import train_gnn
backend_dir = str(Path(__file__).parent.parent / 'python_backend')
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from train_gnn import GlioCartographyGNN, counterfactual_knockout

class TestGNNKnockout(unittest.TestCase):
    def test_knockout_simulation(self):
        # 1. Setup mock data
        data = HeteroData()
        n_spots = 20
        pca_dim = 10
        ct_names = ['TAM_Macrophage', 'T_Cells', 'Astrocytes', 'Tumor_MES']
        n_ct = len(ct_names)
        n_zones = 5
        
        # Spot features: pca_dim + n_ct
        in_ch = pca_dim + n_ct
        data['spot'].x = torch.randn(n_spots, in_ch)
        data.pca_dim = pca_dim
        
        # Add edge relations
        # contacts relation
        data['spot', 'contacts', 'spot'].edge_index = torch.tensor([
            list(range(n_spots - 1)),
            list(range(1, n_spots))
        ], dtype=torch.long)
        data['spot', 'contacts', 'spot'].edge_attr = torch.randn(n_spots - 1, 15)
        
        # diffuses relation
        data['spot', 'diffuses', 'spot'].edge_index = torch.tensor([
            list(range(n_spots - 1)),
            list(range(1, n_spots))
        ], dtype=torch.long)

        # 2. Setup mock model
        model = GlioCartographyGNN(
            in_ch=in_ch,
            edge_dim=15,
            n_ct=n_ct,
            n_zones=n_zones,
            hidden=32,
            heads=2,
            drop=0.0,
            n_gat=1,
            n_sage=1
        )
        model.eval()

        # 3. Run counterfactual knockout for 'Tumor_MES'
        mags = counterfactual_knockout(model, data, ct_names, 'Tumor_MES')
        
        self.assertIsNotNone(mags)
        self.assertEqual(len(mags), n_spots)
        # Check that magnitudes are numpy array of floats
        self.assertEqual(mags.dtype, np.float32)

if __name__ == '__main__':
    unittest.main()
