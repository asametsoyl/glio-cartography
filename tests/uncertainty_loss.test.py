import unittest
import torch
import torch.nn as nn
import torch.optim as optim

class TestUncertaintyLoss(unittest.TestCase):
    def test_loss_convergence(self):
        # Create a mock parameter for 6 tasks
        log_vars = nn.Parameter(torch.zeros(6))
        optimizer = optim.Adam([log_vars], lr=0.1)

        # Generate fake losses
        loss_ct = torch.tensor(2.5)
        loss_zone = torch.tensor(1.2)
        loss_surv = torch.tensor(5.0)
        loss_dgi = torch.tensor(0.8)
        loss_smooth = torch.tensor(1.5)
        loss_attn_reg = torch.tensor(0.4)

        # Train loop for a few steps to see if parameter updates
        initial_val = log_vars.clone().detach()

        for _ in range(5):
            optimizer.zero_grad()
            s = log_vars
            total = (torch.exp(-s[0]) * loss_ct + s[0] +
                     torch.exp(-s[1]) * loss_zone + s[1] +
                     torch.exp(-s[2]) * loss_surv + s[2] +
                     torch.exp(-s[3]) * loss_dgi + s[3] +
                     torch.exp(-s[4]) * loss_smooth + s[4] +
                     torch.exp(-s[5]) * loss_attn_reg + s[5])
            total.backward()
            optimizer.step()

        # The parameters should have been updated
        self.assertFalse(torch.equal(log_vars, initial_val))
        print("Updated scale factors:", log_vars.detach().numpy())

if __name__ == '__main__':
    unittest.main()
