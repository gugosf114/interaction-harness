import { DurableObject } from 'cloudflare:workers';

// Short-lived HTTP requests only. No phone data or keys are written to DO storage.
export class McpBridge extends DurableObject {
  constructor(ctx, env) {
    super(ctx, env);
    this.env = env;
    this.jobs = [];
    this.pending = new Map();
    this.polls = new Map();
  }
  authorized(request, key) {
    return request.headers.get('Authorization') === `Bearer ${key}`;
  }
  async fetch(request) {
    const url = new URL(request.url);
    const bridge = url.pathname.startsWith('/bridge/');
    if (!this.authorized(request, bridge ? this.env.BRIDGE_TOKEN : this.env.CLIENT_TOKEN)) {
      return new Response('Bearer token required.', {status: 401});
    }
    if (url.pathname === '/bridge/poll') {
      const client = url.searchParams.get('client');
      while (this.jobs.length) {
        const job = this.jobs.shift();
        if (this.pending.has(job.id)) return Response.json(job);
      }
      return await new Promise(resolve => {
        if (this.polls.has(client)) this.polls.get(client).finish(null);
        const finish = job => {
          clearTimeout(timer);
          this.polls.delete(client);
          resolve(job ? Response.json(job) : new Response(null, {status: 204}));
        };
        const timer = setTimeout(() => finish(null), 20000);
        this.polls.set(client, {finish});
      });
    }
    if (url.pathname === '/bridge/cancel') {
      this.polls.get(url.searchParams.get('client'))?.finish(null);
      return new Response(null, {status: 204});
    }
    if (url.pathname === '/bridge/result' && request.method === 'POST') {
      const result = await request.json();
      const pending = this.pending.get(result.id);
      if (!pending) return new Response(null, {status: 410});
      this.pending.delete(result.id); clearTimeout(pending.timer);
      const raw = atob(result.body || '');
      const bytes = Uint8Array.from(raw, x => x.charCodeAt(0));
      pending.finish(new Response(bytes.length ? bytes : null, {
        status: result.status, headers: result.headers || {'Content-Type': 'application/json'}
      }));
      return new Response(null, {status: 204});
    }
    if (url.pathname !== '/mcp' || !['POST', 'DELETE'].includes(request.method)) {
      return new Response('Use MCP POST.', {status: 405});
    }
    const bytes = new Uint8Array(await request.arrayBuffer());
    if (bytes.length > 1000000) return new Response('Request too large.', {status: 413});
    const id = crypto.randomUUID();
    const headers = {};
    for (const key of ['mcp-session-id', 'mcp-protocol-version', 'content-encoding']) {
      if (request.headers.has(key)) headers[key] = request.headers.get(key);
    }
    const body = btoa(Array.from(bytes, x => String.fromCharCode(x)).join(''));
    const job = {id, method: request.method, headers, body};
    return await new Promise(finish => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        this.jobs = this.jobs.filter(x => x.id !== id);
        finish(new Response('The phone bridge did not answer.', {status: 504}));
      }, 90000);
      this.pending.set(id, {finish, timer});
      const waiting = this.polls.values().next().value;
      if (waiting) waiting.finish(job);
      else this.jobs.push(job);
    });
  }
}

export default {
  async fetch(request, env) {
    const id = env.BRIDGE.idFromName('phone');
    return env.BRIDGE.get(id).fetch(request);
  }
};
