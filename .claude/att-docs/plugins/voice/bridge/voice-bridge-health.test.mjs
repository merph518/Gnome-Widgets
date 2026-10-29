// Run with: node --test plugins/voice/bridge/voice-bridge-health.test.mjs
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { after, test } from 'node:test';
import { checkOnce, healthPaths, probe } from './voice-bridge-health.mjs';

const CONFIG = {
  url: 'https://bridge.example.ts.net/health',
  notify: 'https://ntfy.example/topic',
};
const MINUTE = 60 * 1000;

// Every scratch folder the tests make, removed once the file's tests finish.
const tempDirs = [];
after(() => {
  for (const dir of tempDirs) fs.rmSync(dir, { recursive: true, force: true });
});

function stateFile() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'voice-bridge-health-'));
  tempDirs.push(dir);
  return path.join(dir, 'state', 'health.json');
}

// A fake fetch: the health URL answers with whatever bridge() returns, and every POST to the
// notify URL is recorded. notifyStatus sets what ntfy answers.
function fakeNet({ notifyStatus = 200 } = {}) {
  const sent = [];
  const net = { bridge: () => okResponse(), sent };
  net.fetch = async (url, init = {}) => {
    if (url === CONFIG.notify) {
      sent.push({ title: init.headers.Title, body: init.body });
      return new Response('', { status: notifyStatus });
    }
    return net.bridge();
  };
  return net;
}

function okResponse() {
  return new Response(JSON.stringify({ status: 'ok' }), { status: 200 });
}

function connectionRefused() {
  throw new TypeError('fetch failed', { cause: { code: 'ECONNREFUSED' } });
}

async function run(net, file, now) {
  return checkOnce({ config: CONFIG, stateFile: file, fetchImpl: net.fetch, now });
}

test('a healthy bridge sends nothing', async () => {
  const net = fakeNet();
  const file = stateFile();
  for (let i = 0; i < 3; i += 1) await run(net, file, i * 2 * MINUTE);
  assert.equal(net.sent.length, 0);
});

test('repeated failures send one alert, and recovery sends one notice', async () => {
  const net = fakeNet();
  const file = stateFile();
  await run(net, file, 0);
  net.bridge = connectionRefused;
  const first = await run(net, file, 2 * MINUTE);
  assert.equal(first.sent.title, 'Voice bridge down');
  await run(net, file, 4 * MINUTE);
  await run(net, file, 6 * MINUTE);
  assert.equal(net.sent.length, 1);
  assert.match(net.sent[0].body, /ECONNREFUSED/);
  assert.doesNotMatch(net.sent[0].body, /ts\.net/);

  net.bridge = okResponse;
  const back = await run(net, file, 8 * MINUTE);
  assert.equal(back.sent.title, 'Voice bridge back up');
  assert.match(back.sent.body, /after 6 minutes/);
  await run(net, file, 10 * MINUTE);
  assert.equal(net.sent.length, 2);
});

test('a down bridge on the first run alerts', async () => {
  const net = fakeNet();
  net.bridge = () => new Response('Bad Gateway', { status: 502 });
  const { sent } = await run(net, stateFile(), 0);
  assert.equal(sent.title, 'Voice bridge down');
  assert.match(sent.body, /HTTP 502/);
});

test('a failed notification leaves the state, so the next probe sends it', async () => {
  const net = fakeNet({ notifyStatus: 500 });
  const file = stateFile();
  net.bridge = connectionRefused;
  await assert.rejects(run(net, file, 0), /notification refused: HTTP 500/);
  assert.equal(fs.existsSync(file), false);

  const retry = fakeNet();
  retry.bridge = connectionRefused;
  const { sent } = await run(retry, file, 2 * MINUTE);
  assert.equal(sent.title, 'Voice bridge down');
});

test('probe reads a 200 with the wrong body as down', async () => {
  const fetchImpl = async () => new Response('<html>', { status: 200 });
  assert.deepEqual(await probe(CONFIG.url, fetchImpl), {
    up: false, detail: 'an unexpected body',
  });
});

test('probe names a timeout', async () => {
  const fetchImpl = async () => {
    throw new DOMException('timed out', 'TimeoutError');
  };
  const result = await probe(CONFIG.url, fetchImpl);
  assert.equal(result.up, false);
  assert.match(result.detail, /no answer within 10 seconds/);
});

test('probe gives the code from an AggregateError and never the URL', async () => {
  const several = async () => {
    const cause = new AggregateError([{ code: 'EHOSTUNREACH' }, { code: 'ECONNREFUSED' }]);
    throw new TypeError('fetch failed', { cause });
  };
  assert.equal((await probe(CONFIG.url, several)).detail, 'EHOSTUNREACH');
  const badUrl = async () => {
    throw new TypeError(`Failed to parse URL from ${CONFIG.url}`);
  };
  assert.equal((await probe(CONFIG.url, badUrl)).detail, 'TypeError');
});

test('health files sit beside the bridge config and state', () => {
  const paths = healthPaths({ XDG_CONFIG_HOME: '/c', XDG_STATE_HOME: '/s' });
  assert.deepEqual(paths, {
    configFile: '/c/voice-bridge/health.json',
    stateFile: '/s/voice-bridge/health.json',
  });
});
