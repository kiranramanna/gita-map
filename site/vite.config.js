// Vite config for the Gita Map static site.
// The public base path defaults to /gita-map/ (GitHub Pages project site).
// Override with GITA_MAP_BASE, e.g. GITA_MAP_BASE=/ npm run build.
import { defineConfig } from 'vite';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const here = path.dirname(fileURLToPath(import.meta.url));

function normaliseBase(value) {
  let base = value && value.trim() ? value.trim() : '/gita-map/';
  if (!base.startsWith('/')) base = '/' + base;
  if (!base.endsWith('/')) base += '/';
  return base;
}

export default defineConfig({
  root: here,
  base: normaliseBase(process.env.GITA_MAP_BASE),
  publicDir: path.join(here, 'public'),
  build: {
    outDir: path.join(here, 'dist'),
    emptyOutDir: true,
    chunkSizeWarningLimit: 2500,
  },
  server: { port: 5173 },
  preview: { port: 4173 },
});
