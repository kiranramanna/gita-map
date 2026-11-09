#!/usr/bin/env node
// Serves site/dist under a sub-path (default /gita-map/) the way GitHub Pages serves a
// project site. Anything outside the sub-path returns 404, so absolute-path leaks show up.
// Usage: node site/scripts/serve-subpath.mjs [--port 4321] [--base /gita-map/] [--dir site/dist]
import http from 'node:http';
import { createReadStream, statSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const args = Object.fromEntries(
  process.argv.slice(2).reduce((acc, v, i, a) => (v.startsWith('--') ? [...acc, [v.slice(2), a[i + 1]]] : acc), []),
);
const port = Number(args.port || process.env.PORT || 4321);
let base = args.base || process.env.GITA_MAP_BASE || '/gita-map/';
if (!base.endsWith('/')) base += '/';
const dir = path.resolve(args.dir || path.join(here, '..', 'dist'));

const TYPES = {
  '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json',
  '.svg': 'image/svg+xml', '.png': 'image/png', '.ico': 'image/x-icon', '.woff2': 'font/woff2', '.txt': 'text/plain',
};

const server = http.createServer((req, res) => {
  const url = new URL(req.url, 'http://localhost');
  const log = (code) => process.env.QUIET || console.log(`${code} ${req.method} ${url.pathname}`);
  if (url.pathname === base.slice(0, -1)) {
    res.writeHead(301, { Location: base });
    log(301);
    return res.end();
  }
  if (!url.pathname.startsWith(base)) {
    res.writeHead(404, { 'content-type': 'text/plain' });
    log(404);
    return res.end('404: outside base path');
  }
  let rel = decodeURIComponent(url.pathname.slice(base.length));
  if (rel === '' || rel.endsWith('/')) rel += 'index.html';
  const file = path.resolve(dir, rel);
  if (!file.startsWith(dir + path.sep)) {
    res.writeHead(403);
    log(403);
    return res.end();
  }
  try {
    if (!statSync(file).isFile()) throw new Error('not a file');
  } catch {
    res.writeHead(404, { 'content-type': 'text/plain' });
    log(404);
    return res.end('404');
  }
  res.writeHead(200, { 'content-type': TYPES[path.extname(file)] || 'application/octet-stream' });
  log(200);
  createReadStream(file).pipe(res);
});

server.listen(port, '127.0.0.1', () => {
  console.log(`Serving ${dir} at http://127.0.0.1:${port}${base}`);
});
