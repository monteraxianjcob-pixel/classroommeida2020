import { defineConfig } from 'astro/config';

// Netlify serves from the root of a subdomain, so base MUST be '/'.
// (A repo subpath such as '/classroom-press' would 404 every asset.)
export default defineConfig({
  site: 'https://classroom-press.netlify.app',
  base: '/',
  output: 'static',
});
