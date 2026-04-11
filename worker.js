/**
 * Cloudflare Worker for wetheagents.ai
 *
 * Proxies /btc and /btc/* to the local BTC dashboard exposed via
 * cloudflared tunnel at btc.wetheagents.ai.
 * All other requests are served from the static docs/ assets.
 */
export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (url.pathname === '/btc' || url.pathname.startsWith('/btc/')) {
      // Forward to the cloudflared tunnel subdomain, preserving path + query
      const target = new URL(request.url);
      target.hostname = 'btc.wetheagents.ai';
      // Clone the request with the new URL; strip CF-specific headers that
      // would cause a loop if forwarded back to Cloudflare's edge.
      const proxied = new Request(target.toString(), {
        method:  request.method,
        headers: request.headers,
        body:    ['GET', 'HEAD'].includes(request.method) ? undefined : request.body,
        redirect: 'follow',
      });
      return fetch(proxied);
    }

    // Serve static assets (existing docs/ site)
    return env.ASSETS.fetch(request);
  },
};
