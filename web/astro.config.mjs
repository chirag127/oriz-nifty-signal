// @ts-check
import { defineConfig } from 'astro/config';

// Static market-timing signal site for nifty-signal.oriz.in. Reads
// ../data/latest.json + history at build time (the scraper commits it daily;
// CF Pages rebuilds on push).
export default defineConfig({
  site: 'https://nifty-signal.oriz.in',
  output: 'static',
  trailingSlash: 'ignore',
});
