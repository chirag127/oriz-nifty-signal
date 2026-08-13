import type { APIRoute } from 'astro';
import { loadMetrics } from '../lib/screener';

export const prerender = true;

// Emits dist/screener-data.json — the whole universe the island fetches once,
// client-side. Kept out of island props so ~7 MB isn't inlined into the HTML.
export const GET: APIRoute = () =>
  new Response(JSON.stringify(loadMetrics()), {
    headers: { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'public, max-age=1800' },
  });
