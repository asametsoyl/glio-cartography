import unittest
import numpy as np

def compute_rbf_features(distances, K_rbf=10, d_min=0.0, d_max=100.0, beta=0.1):
    distances = np.array(distances)
    mu = np.linspace(d_min, d_max, K_rbf)
    sigma = (d_max - d_min) / (K_rbf - 1) if K_rbf > 1 else 1.0
    rbf_feats = np.exp(-beta * (distances.reshape(-1, 1) - mu)**2)
    return rbf_feats

class TestRBFConv(unittest.TestCase):
    def test_rbf_shape(self):
        distances = [10.0, 20.0, 50.0, 80.0]
        feats = compute_rbf_features(distances, K_rbf=10)
        self.assertEqual(feats.shape, (4, 10))

    def test_rbf_values(self):
        distances = [50.0]
        feats = compute_rbf_features(distances, K_rbf=3, d_min=0.0, d_max=100.0, beta=0.01)
        # mu will be [0.0, 50.0, 100.0]
        # At 50.0, the distance matches the second kernel exactly, so exp(0) = 1.0
        self.assertAlmostEqual(feats[0, 1], 1.0)
        # Other kernels should be exp(-0.01 * 50^2) = exp(-25) ~ 0.0
        self.assertTrue(feats[0, 0] < 1e-5)
        self.assertTrue(feats[0, 2] < 1e-5)

if __name__ == '__main__':
    unittest.main()
