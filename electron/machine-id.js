// =============================================================
// GLIO-CARTOGRAPHY — Machine ID Resolution
// =============================================================
// Fix: Linux now uses /etc/machine-id instead of hostname.
// hostname is trivially mutable; machine-id requires root.
// =============================================================
'use strict';

const os = require('os');
const fs = require('fs');
const { execSyncWithRetry } = require('./utils');

let _cachedMachineId = null;

function getMachineId() {
  if (_cachedMachineId) return _cachedMachineId;

  try {
    if (process.platform === 'darwin') {
      _cachedMachineId = execSyncWithRetry(
        "system_profiler SPHardwareDataType | awk '/Hardware UUID/ {print $3}'",
        { timeout: 5000 }
      ).toString().trim();

    } else if (process.platform === 'win32') {
      // 1. Registry: fastest, non-deprecated, works even on VMs
      try {
        const regOut = execSyncWithRetry(
          'reg query HKEY_LOCAL_MACHINE\\SOFTWARE\\Microsoft\\Cryptography /v MachineGuid',
          { timeout: 2000 }
        ).toString();
        const parts = regOut.split('MachineGuid');
        if (parts.length > 1) {
          const valParts = parts[1].trim().split(/\s+/);
          if (valParts.length > 1) {
            _cachedMachineId = valParts[valParts.length - 1].trim();
          }
        }
      } catch (regErr) {
        console.warn('[getMachineId] Registry query failed:', regErr.message);
      }

      // 2. WMI fallback (deprecated but still present on most Windows versions)
      if (!_cachedMachineId) {
        try {
          _cachedMachineId = execSyncWithRetry('wmic csproduct get uuid', { timeout: 3000 })
            .toString().trim().split('\n').pop().trim();
        } catch (wmicErr) {
          console.warn('[getMachineId] wmic failed:', wmicErr.message);
        }
      }

      // 3. PowerShell CIM fallback
      if (!_cachedMachineId) {
        try {
          _cachedMachineId = execSyncWithRetry(
            'powershell -ExecutionPolicy Bypass -Command "[guid]((Get-CimInstance -ClassName Win32_ComputerSystemProduct).UUID)"',
            { timeout: 4000 }
          ).toString().trim();
        } catch (psErr) {
          console.warn('[getMachineId] PowerShell CIM failed:', psErr.message);
        }
      }

    } else {
      // Linux: /etc/machine-id is stable, requires root to change
      try {
        _cachedMachineId = fs.readFileSync('/etc/machine-id', 'utf8').trim();
      } catch {
        // Fallback to hostname if machine-id is unavailable (e.g., some containers)
        _cachedMachineId = os.hostname();
      }
    }
  } catch (e) {
    console.error('[getMachineId] Failed to retrieve machine ID:', e);
  }

  // Last resort: hostname + CPU model fragment
  if (!_cachedMachineId) {
    const cpuFragment =
      os.cpus() && os.cpus().length > 0
        ? os.cpus()[0].model.replace(/\s/g, '').slice(0, 8)
        : 'unknown';
    _cachedMachineId = `${os.hostname()}-${cpuFragment}`;
  }

  return _cachedMachineId;
}

module.exports = { getMachineId };
