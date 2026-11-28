// @ts-check
import { defineConfig } from 'astro/config';
import preact from '@astrojs/preact';

// Static screener site for nifty.oriz.in. Astro static shell + ONE Preact
// island (the screener grid). TanStack Table/Virtual import from 'react', so
// alias react -> preact/compat. Reads ../data/nifty_all_metrics.json at build
// time (scraper commits it daily; CF Pages rebuilds on the data push).
export default defineConfig({
  site: 'https://nifty.oriz.in',
  output: 'static',
  trailingSlash: 'ignore',
  integrations: [preact({ compat: true })],
});
