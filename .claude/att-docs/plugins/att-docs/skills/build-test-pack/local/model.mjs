// The pipeline's model client: an OpenAI-compatible chat endpoint on this
// machine, and the only network client that sends document or rule text. Every
// call asks for JSON against a schema, so the reply always has the shape the
// phase writes into the pack. The one other network call is the build
// supervisor's waiting notice, a content-free line (supervisor.mjs).
//
// Each chat call streams its reply. Lemonade stops generating a streamed reply
// when the connection closes, so a stop or a time-out frees the model at once.
// An unstreamed reply runs to its end on the server even after the connection
// closes, and an unload asked for in the meantime waits for it.

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

/** The run was told to stop. Not a ModelError, so no phase retries it. */
export class Cancelled extends Error {
  constructor() {
    super('the run was cancelled');
    this.name = 'Cancelled';
  }
}

/**
 * A fetch-shaped request over node:http. Node's own fetch gives up when no
 * response headers arrive within five minutes, and a local server answering
 * one request at a time can hold a call longer than that before it starts. A
 * redirect is never followed: it comes back as a response that is not ok. The
 * whole body is read before the promise settles, so an abort, a time-out or a
 * reset partway through the body rejects it and closes the connection.
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
            status: response.statusCode, text: async () => text, json: async () => JSON.parse(text) });
        });
      });
    request.on('error', reject);
    request.end(body);
  });
}

/**
 * The reply of a streamed chat call, from its server-sent events: the content
 * deltas joined, the finish reason and the usage the last chunks carry. The
 * thinking deltas (`reasoning_content`) are left out. Null when the stream did
 * not end with `[DONE]`, or holds an event that is not JSON or is an error:
 * Lemonade answers a request its backend refuses with a 200 whose body is a
 * bare error object.
 */
function readStream(text) {
  let content = '';
  let finish = null;
  let usage = null;
  for (const event of text.split(/\r?\n\r?\n/)) {
    const lines = event.split(/\r?\n/).filter((line) => line.startsWith('data:'));
    if (!lines.length) continue;
    const data = lines.map((line) => line.slice(5).replace(/^ /, '')).join('\n');
    if (data === '[DONE]') return { content, finish, usage };
    let chunk;
    try {
      chunk = JSON.parse(data);
    } catch {
      return null;
    }
    if (!chunk || typeof chunk !== 'object' || chunk.error) return null;
    const choice = chunk.choices?.[0];
    if (typeof choice?.delta?.content === 'string') content += choice.delta.content;
    if (choice?.finish_reason) finish = choice.finish_reason;
    if (chunk.usage) usage = chunk.usage;
  }
  return null;
}

/**
 * The sampling settings a call goes out with when the pipeline config sets none.
 * Temperature 0 picks the likeliest token each time, and the fixed seed takes the
 * place of the server's random one (llama.cpp's default). With one server slot,
 * the same prompt then gets the same reply on the same server, model and load
 * options; llama.cpp does not promise that across batch sizes.
 */
export const DEFAULT_TEMPERATURE = 0;
export const DEFAULT_SEED = 42;

/**
 * A client for one model on one endpoint. `fetchImpl` stands in for fetch in
 * tests. `signal` stops a call in flight; the call then throws Cancelled, and
 * the closed connection stops the server generating its reply.
 * `tokenize` asks the loaded llama.cpp backend for an exact count and falls
 * back to the estimate when the server offers none. Every call is sent with
 * `temperature` and `seed`; `json` returns the seed, and a ModelError it throws
 * carries it, so the call record can say what the call was sent with.
 */
export function modelClient({ endpoint, name, temperature = DEFAULT_TEMPERATURE, seed = DEFAULT_SEED,
  timeoutMinutes = 150, fetchImpl = localFetch, signal: stop = null }) {
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
   * One chat call. Returns the parsed JSON object, the call's timings and the
   * seed it was sent with. A reply cut off at maxTokens, or one that does not
   * parse, is a ModelError whose message carries no reply text.
   */
  async function json(request) {
    try {
      return { ...await send(request), seed };
    } catch (error) {
      if (error instanceof ModelError) error.seed = seed;
      throw error;
    }
  }

  async function send({ system, user, schema, schemaName, reasoning, maxTokens }) {
    const started = Date.now();
    let reply;
    let text;
    try {
      reply = await fetchImpl(`${base}/chat/completions`, {
        method: 'POST',
        // A redirect could hand the prompt to another host.
        redirect: 'error',
        headers: { 'content-type': 'application/json' },
        signal: stop ? AbortSignal.any([stop, AbortSignal.timeout(timeoutMinutes * 60000)])
          : AbortSignal.timeout(timeoutMinutes * 60000),
        body: JSON.stringify({
          model: name,
          temperature,
          seed,
          max_tokens: maxTokens,
          // The usage comes in a last chunk of its own, and only when asked for.
          stream: true,
          stream_options: { include_usage: true },
          messages: [{ role: 'system', content: system }, { role: 'user', content: user }],
          chat_template_kwargs: { enable_thinking: Boolean(reasoning) },
          response_format: {
            type: 'json_schema',
            json_schema: { name: schemaName, strict: true, schema },
          },
        }),
      });
      if (reply.ok) text = await reply.text();
    } catch {
      if (stop?.aborted) throw new Cancelled();
      // The cause can quote the request, so only the code goes on.
      throw new ModelError('network', 'the connection to the model endpoint failed');
    }
    if (!reply.ok) throw new ModelError('http', `model endpoint answered HTTP ${reply.status}`);
    const parsed = readStream(text);
    if (!parsed) {
      // A server that gives up on a request, such as at its own time-out, or refuses
      // it, can end a 2xx reply without its last event. The body can quote the
      // request, so only the code goes on.
      throw Object.assign(new ModelError('no-reply', 'model endpoint ended the reply early'),
        { usage: { promptTokens: 0, outputTokens: 0, ms: Date.now() - started } });
    }
    const usage = {
      promptTokens: parsed.usage?.prompt_tokens ?? 0,
      outputTokens: parsed.usage?.completion_tokens ?? 0,
      ms: Date.now() - started,
    };
    if (parsed.finish === 'length') {
      throw Object.assign(new ModelError('length', 'model output reached max_tokens'), { usage });
    }
    try {
      return { value: JSON.parse(parsed.content), usage };
    } catch {
      throw Object.assign(new ModelError('parse', 'model output is not JSON'), { usage });
    }
  }

  return { json, countTokens, contextWindow };
}
