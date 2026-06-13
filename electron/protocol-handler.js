// =============================================================
// GLIO-CARTOGRAPHY — local:// Protocol Handler
// =============================================================
// Security Fix: Path traversal protection via whitelist.
// Requests to paths outside allowedBaseDirs return 403 Forbidden.
// =============================================================
'use strict';

const path = require('path');
const fs = require('fs');
const os = require('os');

const MIME_TYPES = {
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.gif': 'image/gif',
  '.svg': 'image/svg+xml',
  '.webp': 'image/webp',
  '.html': 'text/html',
  '.css': 'text/css',
  '.js': 'application/javascript',
  '.json': 'application/json',
  '.pdf': 'application/pdf'
};

/**
 * Registers the local:// protocol handler with path traversal protection.
 * Only files within the allowed base directories can be served.
 *
 * @param {Electron.Protocol} protocol
 * @param {Electron.App}      app
 */
function registerLocalProtocol(protocol, app) {
  const { isPathAllowed } = require('./utils');

  protocol.handle('local', async (request) => {
    try {
      let urlPath = request.url;
      if (urlPath.startsWith('local://')) urlPath = urlPath.slice(8);

      // Strip query string and fragment
      urlPath = urlPath.split('?')[0].split('#')[0];
      let decodedPath = decodeURIComponent(urlPath);

      // Normalize platform paths
      if (process.platform !== 'win32') {
        if (!decodedPath.startsWith('/')) decodedPath = '/' + decodedPath;
      } else {
        // Handle /C:/foo/bar → C:/foo/bar on Windows
        if (decodedPath.startsWith('/') && decodedPath.charCodeAt(2) === 58) {
          decodedPath = decodedPath.slice(1);
        }
      }

      // Resolve to an absolute path and resolve symlinks to prevent traversal via symlinks
      let resolvedPath;
      try {
        resolvedPath = fs.realpathSync(decodedPath);
      } catch (err) {
        // Fallback for non-existent files to check whitelist
        resolvedPath = path.resolve(decodedPath);
      }

      // ── Path traversal protection ───────────────────────────
      if (!isPathAllowed(resolvedPath)) {
        console.warn('[Local Protocol] Access denied — path outside allowed dirs:', resolvedPath);
        return new Response('Forbidden', { status: 403 });
      }
      // ────────────────────────────────────────────────────────

      if (!fs.existsSync(resolvedPath)) {
        console.error('[Local Protocol] File not found:', resolvedPath);
        return new Response('File Not Found', { status: 404 });
      }

      const ext = path.extname(resolvedPath).toLowerCase();
      const contentType = MIME_TYPES[ext] || 'application/octet-stream';
      const fileBuffer = await fs.promises.readFile(resolvedPath);

      return new Response(fileBuffer, {
        headers: { 'content-type': contentType }
      });
    } catch (err) {
      console.error('[Local Protocol] Error:', err);
      return new Response('Error loading local resource', { status: 500 });
    }
  });
}

module.exports = { registerLocalProtocol };
