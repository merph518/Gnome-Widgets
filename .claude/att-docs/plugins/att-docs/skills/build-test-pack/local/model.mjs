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

  // Every read of the server's status goes through here: GET only, no redirects,
  // a short time-out, and a URL that localEndpoint already held to loopback.
  async function getJson(url) {
    const reply = await fetchImpl(url, { redirect: 'error', signal: AbortSignal.timeout(5000) });
    if (reply.ok === false) throw new Error(`${url} answered ${reply.status}`);
    return reply.json();
  }

  // Lemonade reports the llama.cpp server each loaded model runs on, and the
  // options it loaded with. Null when the model is not loaded. A reply that is
  // not ok, or that has no list of loaded models, throws: it says nothing about
  // what is loaded.
  async function loadedEntry() {
    const body = await getJson(`${base}/health`);
    if (!Array.isArray(body?.all_models_loaded)) throw new Error('health lists no loaded models');
    return body.all_models_loaded.find((m) => m.model_name === name) ?? null;
  }

  const backendOf = (loaded) => localEndpoint(loaded.backend_url.replace(/\/v1\/?$/, ''));

  async function backendTokenizer() {
    if (tokenizeUrl !== undefined) return tokenizeUrl;
    tokenizeUrl = null;
    try {
      const loaded = await loadedEntry();
      if (loaded?.backend_url) tokenizeUrl = `${backendOf(loaded)}/tokenize`;
    } catch {
      tokenizeUrl = null;
    }
    return tokenizeUrl;
  }

  const positive = (n) => (Number.isInteger(n) && n > 0 ? n : null);

  // The per-slot window from recipe options: `ctx_size` divided by the slot
  // count in `llamacpp_args` (`-np N` or `--parallel N`, one when absent).
  const perSlot = (options) => {
    const total = positive(options?.ctx_size);
    if (!total) return null;
    const match = /(?:^|\s)(?:-np|--parallel)(?:\s+|=)(\d+)(?=\s|$)/.exec(String(options.llamacpp_args ?? ''));
    const slots = match && Number(match[1]) > 0 ? Number(match[1]) : 1;
    return positive(Math.floor(total / slots));
  };

  /**
   * The context size the server runs this model with, as `{ size, guess }`, or
   * null when it cannot be read. Asked fresh each time, so a reload at a new
   * size shows. The loaded backend's own figure comes first, then the options
   * the model loaded with; both are sure (`guess: false`). When the model is
   * listed as not loaded, the options saved for it are the size the server
   * loads it at next, and are sure. When the health check fails, or answers
   * without a list of loaded models, a model may already run at a size other
   * than the saved one, so the saved size is a guess (`guess: true`). A loaded
   * model whose size cannot be read gives null.
   */
  async function contextWindow() {
    let loaded;
    let guess = false;
    try {
      loaded = await loadedEntry();
    } catch {
      guess = true;
    }
    if (loaded?.backend_url) {
      try {
        const props = await getJson(`${backendOf(loaded)}/props`);
        const found = positive(props.default_generation_settings?.n_ctx);
        if (found) return { size: found, guess: false };
      } catch {
        // Fall through to the options Lemonade reports.
      }
    }
    // `ctx_size` is the server's total window across its slots, so it is divided
    // by the slot count in the same options. The backend's own /props, read
    // first, already reports the per-slot figure.
    const fromLoaded = perSlot(loaded?.recipe_options);
    if (fromLoaded) return { size: fromLoaded, guess: false };
    if (loaded) return null;
    try {
      const saved = await getJson(`${base}/models/${encodeURIComponent(name)}`);
      const size = perSlot(saved.recipe_options);
      return size ? { size, guess } : null;
    } catch {
      return null;
    }
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

  return { json, countTokens, contextWindow };
}
