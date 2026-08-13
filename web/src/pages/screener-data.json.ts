import type { APIRoute } from 'astro';
import { loadMetrics } from '../lib/screener';

// Static endpoint: emits the whole screener universe as one fetchable JSON in
// dist/. The browser fetches this once, then filters/sorts/re-weights in-memory.
export const GET: APIRoute = () => {
  const payload = loadMetrics();
  return new Response(JSON.stringify(payload), {
    headers: {
      'content-type': 'application/json; charset=utf-8',
      'cache-control': 'public, max-age=1800',
    },
  });
};
