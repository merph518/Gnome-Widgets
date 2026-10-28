// Probes the voice bridge's /health endpoint through its public Funnel address and sends a
// push notification to the phone when it stops answering, and one more when it answers again.
//
// Each run is one probe. The last state it saw sits in ~/.local/state/voice-bridge/health.json,
// so a bridge that stays down sends one alert however many probes fail, and a healthy bridge
// sends nothing. A notification that fails to send leaves the state alone, so the next probe
// tries it again. The first run assumes the bridge was up.
//
// Notifications go through ntfy: a POST to a topic URL, read on the phone by the ntfy app
// subscribed to the same topic. Anyone who knows a topic on the public server can read it, so
// the topic is a long random name and the message leaves out the bridge's address.
//
// The probe runs on the same machine as the bridge. It catches the bridge exiting and Funnel
// being switched off, but not a machine that is asleep, off, or offline: then nothing probes,
// and a probe that cannot reach the address cannot reach ntfy either.
//
// Setup, once, after the bridge itself (see the header of voice-bridge.mjs):
//   1. Install the ntfy app on the phone and subscribe to a new topic with a long random
//      name, such as the output of: openssl rand -hex 16
//   2. Write ~/.config/voice-bridge/health.json, readable by this user only:
//        { "url": "https://<machine>.<tailnet>.ts.net/health",
//          "notify": "https://ntfy.sh/<topic>" }
//      Try it once by hand: node plugins/voice/bridge/voice-bridge-health.mjs
//      A healthy probe prints nothing; a down one prints why, and each notification sent.
//   3. A systemd user timer runs the probe every two minutes. Link the service, then enable
//      the timer, both by full path:
//        systemctl --user link \
//          ~/Code/Overmind/plugins/voice/bridge/systemd/voice-bridge-health.service
//        systemctl --user enable --now \
//          ~/Code/Overmind/plugins/voice/bridge/systemd/voice-bridge-health.timer
//      Logs: journalctl --user -u voice-bridge-health.
//
// The bridge pushes each new permission prompt to the same topic, naming the session by its
// sidebar title and the tool it asks for (see the header of voice-bridge.mjs).
import { fileURLToPath } from 'node:url';
import {
  defaultPaths, notify, notifyFiles, readJson, spokenSpan, writePrivateJson,
} from './voice-bridge.mjs';

// Long enough for a slow Funnel round trip, well short of the timer's interval.
const PROBE_TIMEOUT_MS = 10 * 1000;

export function healthPaths(env = process.env) {
  const { healthConfig, healthState } = notifyFiles(defaultPaths(env));
  return { configFile: healthConfig, stateFile: healthState };
}

// Up only on a 200 whose body reads {"status":"ok"}. Anything else says what came back.
export async function probe(url, fetchImpl = fetch) {
  try {
    const res = await fetchImpl(url, { signal: AbortSignal.timeout(PROBE_TIMEOUT_MS) });
    if (res.status !== 200) return { up: false, detail: `HTTP ${res.status}` };
    const body = await res.json().catch(() => null);
    if (body?.status !== 'ok') return { up: false, detail: 'an unexpected body' };
    return { up: true, detail: 'ok' };
  } catch (err) {
    if (err?.name === 'TimeoutError') {
      return { up: false, detail: `no answer within ${PROBE_TIMEOUT_MS / 1000} seconds` };
    }
    return { up: false, detail: failureCode(err) };
  }
}

// The socket error's code, never the message: a URL that fails to parse is quoted in the
// message, and the detail goes to the topic. A connect that tried several addresses carries
// its codes on an AggregateError.
function failureCode(err) {
  const cause = err?.cause;
  return cause?.code ?? cause?.errors?.find(e => e?.code)?.code ?? err?.name ?? 'an error';
}

function spokenDuration(ms) {
  const seconds = Math.round(ms / 1000);
  return seconds < 60 ? 'under a minute' : spokenSpan(seconds);
}

export function message(result, previous, now) {
  if (!result.up) {
    return {
      title: 'Voice bridge down',
      body: `The health check stopped answering: ${result.detail}.`,
      priority: 'high',
    };
  }
  const downFor = previous.since ? ` after ${spokenDuration(now - previous.since)}` : '';
  return {
    title: 'Voice bridge back up',
    body: `The health check answers again${downFor}.`,
    priority: 'default',
  };
}

// One probe. Returns the probe's result and the notification sent, or null when the state
// did not change. Throws when a notification could not be sent, with the state unchanged.
export async function checkOnce({ config, stateFile, fetchImpl = fetch, now = Date.now() }) {
  const previous = readJson(stateFile, { status: 'up' });
  const result = await probe(config.url, fetchImpl);
  if (!result.up) console.log(`health probe: down (${result.detail})`);
  if (result.up === (previous.status === 'up')) return { result, sent: null };
  const note = message(result, previous, now);
  await notify(config.notify, note, fetchImpl);
  console.log(`health probe: sent "${note.title}"`);
  writePrivateJson(stateFile, { status: result.up ? 'up' : 'down', since: now });
  return { result, sent: note };
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const { configFile, stateFile } = healthPaths();
  const config = readJson(configFile, null);
  if (!config?.url || !config?.notify) {
    console.error(`health probe: ${configFile} needs "url" and "notify"`);
    process.exit(1);
  }
  try {
    await checkOnce({ config, stateFile });
  } catch (err) {
    console.error(`health probe: ${err.message}`);
    process.exit(1);
  }
}
