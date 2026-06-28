import math
import unittest

def transform_coordinates(x, y, center_x, center_y, theta, tx, ty):
    rel_x = x - center_x
    rel_y = y - center_y
    
    rot_x = rel_x * math.cos(theta) - rel_y * math.sin(theta)
    rot_y = rel_x * math.sin(theta) + rel_y * math.cos(theta)
    
    final_x = (rot_x + tx) * 0.4
    final_y = (rot_y + ty) * 0.4
    
    return final_x, final_y

class TestProjection(unittest.TestCase):
    def test_identity(self):
        # With theta = 0, tx = 0, ty = 0, it should scale by 0.4 relative to center
        cx, cy = 100.0, 100.0
        x, y = 150.0, 50.0
        fx, fy = transform_coordinates(x, y, cx, cy, 0, 0, 0)
        self.assertAlmostEqual(fx, 50.0 * 0.4)
        self.assertAlmostEqual(fy, -50.0 * 0.4)
        
    def test_rotation_90(self):
        cx, cy = 0.0, 0.0
        x, y = 10.0, 0.0
        theta = math.pi / 2
        fx, fy = transform_coordinates(x, y, cx, cy, theta, 0, 0)
        # rotated 90 degrees around origin should be (0, 10) * 0.4 = (0, 4)
        self.assertAlmostEqual(fx, 0.0)
        self.assertAlmostEqual(fy, 4.0)

    def test_translation(self):
        cx, cy = 0.0, 0.0
        x, y = 0.0, 0.0
        fx, fy = transform_coordinates(x, y, cx, cy, 0, 10.0, -20.0)
        # Should be (0 + 10)*0.4 = 4.0, (0 - 20)*0.4 = -8.0
        self.assertAlmostEqual(fx, 4.0)
        self.assertAlmostEqual(fy, -8.0)

if __name__ == '__main__':
    unittest.main()
