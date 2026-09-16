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
 * Converts a local:// protocol URL into a clean, canonical filesystem path.
 * Handles Windows drive letters (C:\...), Chromium URL normalization (stripped colons, localhost host),
 * URI encoding, query parameters, and hashes.
 *
 * @param {string} rawUrl
 * @returns {string}
 */
function urlToFilePath(rawUrl) {
  if (!rawUrl || typeof rawUrl !== 'string') return '';

  // 1. Strip query string and fragment
  let cleanUrl = rawUrl.split('?')[0].split('#')[0];

  // 2. Strip scheme prefix: local://, local:///, local:/
  let pathPart = cleanUrl.replace(/^local:\/{1,3}/i, '');

  // 3. URI decode (%20, non-ASCII chars)
  try {
    pathPart = decodeURIComponent(pathPart);
  } catch {
    // Keep raw string if URI decoding encounters invalid escapes
  }

  // 4. Strip localhost if injected as hostname by Chromium
  pathPart = pathPart.replace(/^localhost[\\/]/i, '');

  if (process.platform === 'win32') {
    // Strip leading slashes: /C:/foo or ///C:/foo -> C:/foo
    pathPart = pathPart.replace(/^[\\/]+/, '');

    // Normalize Windows drive letter:
    // Case 1: C:/path or C:\path
    // Case 2: C/path (Chromium stripped colon when parsing as host)
    // Case 3: C:path
    const driveMatch = pathPart.match(/^([a-zA-Z])(?::[\\/]|[\\/]|:)(.*)/);
    if (driveMatch) {
      const driveLetter = driveMatch[1].toUpperCase();
      const restOfPath = driveMatch[2].replace(/^[\\/]+/, '');
      pathPart = `${driveLetter}:\\${restOfPath.replace(/\//g, '\\')}`;
    } else {
      pathPart = pathPart.replace(/\//g, '\\');
    }
  } else {
    // POSIX (macOS, Linux): Must start with single /
    pathPart = pathPart.replace(/^[\\/]+/, '/');
    if (!pathPart.startsWith('/')) {
      pathPart = '/' + pathPart;
    }
  }

  return pathPart;
}

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
      const decodedPath = urlToFilePath(request.url);
      if (!decodedPath) {
        console.warn('[Local Protocol] Bad request URL:', request.url);
        return new Response('Bad Request', { status: 400 });
      }

      // Resolve to an absolute path and resolve symlinks to prevent traversal via symlinks
      let resolvedPath;
      try {
        resolvedPath = fs.realpathSync(decodedPath);
      } catch (err) {
        // Fallback for non-existent files to check whitelist
        resolvedPath = path.resolve(decodedPath);
      }

      // Strip Windows extended path prefix (\\?\) so comparisons and APIs work cleanly
      resolvedPath = resolvedPath.replace(/^\\\\\?\\/, '');

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

module.exports = { registerLocalProtocol, urlToFilePath };
