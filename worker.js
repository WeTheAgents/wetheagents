/** Cloudflare Worker for WEA static documentation assets. */
export default {
  async fetch(request, env) {
    return env.ASSETS.fetch(request);
  },
};
