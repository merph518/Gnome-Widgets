// The one network client the local pipeline has: an OpenAI-compatible chat
// endpoint on this machine. Every call asks for JSON against a schema, so the
// reply always has the shape the phase writes into the pack.

import http from 'node:http';
import https from 'node:https';

/** Hosts a model endpoint may name. Anything else could be a cloud API. */
export const LOOPBACK_HOSTS = ['localhost', '127.0.0.1', '[::1]', '::1'];

/** The endpoint's URL, or an error when it is not on this machine. */
export function localEndpoint(endpoint) {
  let url;
  try {
    url = new URL(endpoint);
  } catch {
    throw new Error(`model endpoint "${endpoint}" is not a URL`);
  }
  if (!['http:', 'https:'].includes(url.protocol) || !LOOPBACK_HOSTS.includes(url.hostname)) {
    throw new Error('model endpoint must be a loopback address (localhost, 127.0.0.1 or ::1)');
  }
  return url.href.replace(/\/$/, '');
}

/**
 * A rough token count, kept high on purpose: about three characters a token
 * for English prose, so a prompt it passes fits when the server counts.
 */
export const estimateTokens = (text) => Math.ceil(String(text).length / 3);

export class ModelError extends Error {
  constructor(code, message) {
    super(message);
    this.code = code;
  }
}

/**
 * A fetch-shaped request over node:http. Node's own fetch gives up when no
 * response headers arrive within five minutes, and a local server answering
 * one request at a time can hold a call longer than that before it starts. A
 * redirect is never followed: it comes back as a response that is not ok.
 */
export function localFetch(url, { method = 'GET', headers = {}, body, signal } = {}) {
  return new Promise((resolve, reject) => {
    const target = new URL(url);
    const request = (target.protocol === 'https:' ? https : http).request(target,
      { method, headers, signal }, (response) => {
        const chunks = [];
        response.on('data', (chunk) => chunks.push(chunk));
        response.on('error', reject);
        response.on('end', () => {
          const text = Buffer.concat(chunks).toString('utf8');
          resolve({ ok: response.statusCode >= 200 && response.statusCode < 300,
            status: response.statusCode, json: async () => JSON.parse(text) });
        });
      });
    request.on('error', reject);
    request.end(body);
  });
}

/**
 * A client for one model on one endpoint. `fetchImpl` stands in for fetch in
 * tests. `tokenize` asks the loaded llama.cpp backend for an exact count and
 * falls back to the estimate when the server offers none.
 */
export function modelClient({ endpoint, name, temperature = 0.1, timeoutMinutes = 150,
  fetchImpl = localFetch }) {
  const base = localEndpoint(endpoint);
  let tokenizeUrl;

  async function backendTokenizer() {
    if (tokenizeUrl !== undefined) return tokenizeUrl;
    tokenizeUrl = null;
    try {
      // Lemonade reports the llama.cpp server each loaded model runs on.
      const health = await fetchImpl(`${base}/health`, { redirect: 'error', signal: AbortSignal.timeout(5000) });
      const body = await health.json();
      const loaded = (body.all_models_loaded ?? []).find((m) => m.model_name === name);
      if (loaded?.backend_url) {
        const backend = localEndpoint(loaded.backend_url.replace(/\/v1\/?$/, ''));
        tokenizeUrl = `${backend}/tokenize`;
      }
    } catch {
      tokenizeUrl = null;
    }
    return tokenizeUrl;
  }

  async function countTokens(text) {
    const url = await backendTokenizer();
    if (!url) return estimateTokens(text);
    try {
      const reply = await fetchImpl(url, {
        method: 'POST', headers: { 'content-type': 'application/json' }, redirect: 'error',
        body: JSON.stringify({ content: String(text) }), signal: AbortSignal.timeout(60000),
      });
      const { tokens } = await reply.json();
      if (Array.isArray(tokens)) return tokens.length;
    } catch {
      // The backend can move when the model reloads; ask Lemonade again next time.
      tokenizeUrl = undefined;
    }
    return estimateTokens(text);
  }

  /**
   * One chat call. Returns the parsed JSON object and the call's timings. A
   * reply cut off at maxTokens, or one that does not parse, is a ModelError
   * whose message carries no reply text.
   */
  async function json({ system, user, schema, schemaName, reasoning, maxTokens }) {
    const started = Date.now();
    let reply;
    try {
      reply = await fetchImpl(`${base}/chat/completions`, {
        method: 'POST',
        // A redirect could hand the prompt to another host.
        redirect: 'error',
        headers: { 'content-type': 'application/json' },
        signal: AbortSignal.timeout(timeoutMinutes * 60000),
        body: JSON.stringify({
          model: name,
          temperature,
          max_tokens: maxTokens,
          messages: [{ role: 'system', content: system }, { role: 'user', content: user }],
          chat_template_kwargs: { enable_thinking: Boolean(reasoning) },
          response_format: {
            type: 'json_schema',
            json_schema: { name: schemaName, strict: true, schema },
          },
        }),
      });
    } catch {
      // The cause can quote the request, so only the code goes on.
      throw new ModelError('network', 'model endpoint could not be reached');
    }
    if (!reply.ok) throw new ModelError('http', `model endpoint answered HTTP ${reply.status}`);
    let body;
    try {
      body = await reply.json();
    } catch {
      // A server that gives up on a request, such as at its own time-out, can end
      // a 2xx reply with no body. The parse error quotes the body, so only the
      // code goes on.
      throw Object.assign(new ModelError('no-reply', 'model endpoint answered with no JSON'),
        { usage: { promptTokens: 0, outputTokens: 0, ms: Date.now() - started } });
    }
    const choice = body.choices?.[0];
    const usage = {
      promptTokens: body.usage?.prompt_tokens ?? 0,
      outputTokens: body.usage?.completion_tokens ?? 0,
      ms: Date.now() - started,
    };
    if (choice?.finish_reason === 'length') {
      throw Object.assign(new ModelError('length', 'model output reached max_tokens'), { usage });
    }
    try {
      return { value: JSON.parse(choice?.message?.content ?? ''), usage };
    } catch {
      throw Object.assign(new ModelError('parse', 'model output is not JSON'), { usage });
    }
  }

  return { json, countTokens };
}
