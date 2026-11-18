// Shows a row above the prompt when a self-hosted CI runner needs attention: a
// runner is stopped or offline, a job has waited too long for one, or a disk the
// runners write to is low. Nothing shows while all is well.
//
// Every 15 seconds the module reads this machine's runner services with systemctl
// and their disks with df. Every 2 minutes it asks GitHub, through gh, for the
// organization's runners and the queued jobs; the answer is kept in a file in the
// mods folder, so every open chat shares one call. switches.json in the mods folder
// turns the plugin off or hides the band.
//
// A reload of the module drops its timer; the next session start sets it again.

import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { ApiState, DiskFree, Health, HealthSwitches, LocalUnit, QueuedJob, Settings } from '../types'
import {
  API_MS,
  API_RETRY_MS,
  TICK_MS,
  assess,
  bandText,
  configDir,
  ghFailure,
  parseDf,
  parseJobs,
  parseRunIds,
  parseRunnerFile,
  parseRunners,
  parseSettings,
  parseSwitches,
  parseUnits,
  sameHealth,
} from './health'

const EMPTY: Health = { problems: [], note: null }
const health = atom({ plugin: 'runner-health', key: 'health' } as const, EMPTY)
const switches = atom({ plugin: 'runner-health', key: 'switches' } as const, { isOff: false, isHidden: false } as HealthSwitches)

// Each command gets this long before it counts as failed.
const RUN_MS = 15_000

type Timer = { cancel: () => void }
// Where a runner service keeps its files: its name and its work folder.
type Place = { name: string | null; work: string }

let folder: string | null = null
let timer: Timer | null = null
let isChecking = false
const places = new Map<string, Place>()
// When each local runner's service was first seen active, by runner name.
let activeSince: Record<string, number> = {}
let api: ApiState | null = null
let apiKey = ''
let apiDueAt = 0

async function configFolder($: EngineInterface): Promise<string> {
  folder ??= configDir(await $.env.get('HOME'), await $.env.get('CLAUDE_CONFIG_DIR'))
  return folder
}

async function readText($: EngineInterface, path: string): Promise<string | undefined> {
  return $.fs.read(path).then(
    value => (typeof value === 'string' ? value : undefined),
    () => undefined,
  )
}

async function run($: EngineInterface, argv: string[]): Promise<{ exitCode: number | null; stdout: string; stderr: string }> {
  try {
    const result = await $.process.run(argv, { timeoutMs: RUN_MS })
    return { exitCode: result.exitCode, stdout: result.stdout, stderr: result.stderr }
  } catch {
    // The command is not installed, or it ran past the timeout.
    return { exitCode: null, stdout: '', stderr: '' }
  }
}

async function readSwitches($: EngineInterface): Promise<HealthSwitches> {
  const value = parseSwitches(await readText($, `${await configFolder($)}/mods/switches.json`))
  const before = await read($, switches)
  if (before.isOff !== value.isOff || before.isHidden !== value.isHidden) {
    await update($, switches, () => value)
    $.ui.invalidate('ui.render')
  }
  return value
}

async function setHealth($: EngineInterface, value: Health) {
  if (sameHealth(await read($, health), value)) return
  await update($, health, () => value)
  $.ui.invalidate('ui.render')
}

// This machine's runner services and the disks they write to.
async function readLocal($: EngineInterface): Promise<{ units: LocalUnit[]; disks: DiskFree[]; note: string | null }> {
  const listed = await run($, ['systemctl', 'list-units', '--all', '--plain', '--no-legend', 'actions.runner.*.service'])
  if (listed.exitCode === null) return { units: [], disks: [], note: 'systemctl is not available' }
  if (listed.exitCode !== 0) return { units: [], disks: [], note: `systemctl exited with ${listed.exitCode}` }
  const units = parseUnits(listed.stdout)
  for (const unit of units) {
    if (!places.has(unit.unit)) {
      const shown = await run($, ['systemctl', 'show', '-p', 'WorkingDirectory', '--value', unit.unit])
      const dir = shown.exitCode === 0 ? shown.stdout.trim() : ''
      if (dir !== '') {
        const found = parseRunnerFile(await readText($, `${dir}/.runner`))
        const work = found.workFolder.startsWith('/') ? found.workFolder : `${dir}/${found.workFolder}`
        places.set(unit.unit, { name: found.name, work })
      }
    }
    unit.runner = places.get(unit.unit)?.name ?? unit.runner
  }
  // The work folders hold each job's checkout and temp folder; jobs also write to /tmp.
  const paths = [...new Set(units.flatMap(unit => places.get(unit.unit)?.work ?? []))]
  if (units.length > 0) paths.push('/tmp')
  const disks: DiskFree[] = []
  for (const path of paths) {
    const df = await run($, ['df', '-P', '-k', path])
    if (df.exitCode !== 0) continue
    for (const disk of parseDf(df.stdout, [path])) {
      const same = disks.find(one => one.mount === disk.mount)
      if (same === undefined) disks.push(disk)
      else same.paths.push(path)
    }
  }
  return { units, disks, note: null }
}

async function gh($: EngineInterface, path: string): Promise<{ text: string } | { note: string }> {
  const result = await run($, ['gh', 'api', path])
  if (result.exitCode === 0) return { text: result.stdout }
  return { note: ghFailure(result.exitCode, result.stderr) }
}

async function fetchApi($: EngineInterface, settings: Settings): Promise<ApiState> {
  const answer = await gh($, `orgs/${settings.org}/actions/runners?per_page=100`)
  if ('note' in answer) return { runners: null, jobs: null, note: answer.note }
  const runners = parseRunners(answer.text, settings.label)
  if (runners === null) return { runners: null, jobs: null, note: 'GitHub did not send a runners list' }
  const jobs: QueuedJob[] = []
  for (const repo of settings.repos) {
    // A run already in progress can still hold a job that waits for a runner.
    for (const status of ['queued', 'in_progress']) {
      const runs = await gh($, `repos/${repo}/actions/runs?status=${status}&per_page=100`)
      const ids = 'note' in runs ? null : parseRunIds(runs.text)
      if (ids === null) return { runners, jobs: null, note: 'note' in runs ? runs.note : 'GitHub did not send a runs list' }
      for (const id of ids) {
        const listed = await gh($, `repos/${repo}/actions/runs/${id}/jobs?per_page=100`)
        const found = 'note' in listed ? null : parseJobs(listed.text, repo, settings.label)
        if (found === null) return { runners, jobs: null, note: 'note' in listed ? listed.note : 'GitHub did not send a jobs list' }
        jobs.push(...found)
      }
    }
  }
  return { runners, jobs, note: null }
}

function isApiState(value: unknown): value is ApiState {
  if (typeof value !== 'object' || value === null) return false
  const record = value as Record<string, unknown>
  return (
    (record['runners'] === null || Array.isArray(record['runners'])) &&
    (record['jobs'] === null || Array.isArray(record['jobs'])) &&
    (record['note'] === null || typeof record['note'] === 'string')
  )
}

// GitHub's side, asked at most once an interval across every open chat. A failed
// call waits longer before the next try.
async function readApi($: EngineInterface, settings: Settings, now: number): Promise<ApiState> {
  const key = JSON.stringify([settings.org, settings.repos, settings.label])
  if (api !== null && apiKey === key && now < apiDueAt) return api
  const path = `${await configFolder($)}/mods/.runner-health.json`
  let shared: Record<string, unknown> | null = null
  try {
    const value: unknown = JSON.parse((await readText($, path)) ?? '')
    if (typeof value === 'object' && value !== null) shared = value as Record<string, unknown>
  } catch {
    shared = null
  }
  const fetchedAt = shared?.['fetchedAt']
  const sharedApi = shared?.['api']
  if (shared?.['key'] === key && typeof fetchedAt === 'number' && fetchedAt <= now && isApiState(sharedApi)) {
    const dueAt = fetchedAt + (sharedApi.note === null ? API_MS : API_RETRY_MS)
    if (now < dueAt) {
      api = sharedApi
      apiKey = key
      apiDueAt = dueAt
      return sharedApi
    }
  }
  const fresh = await fetchApi($, settings)
  api = fresh
  apiKey = key
  apiDueAt = now + (fresh.note === null ? API_MS : API_RETRY_MS)
  await $.fs.write(path, `${JSON.stringify({ key, fetchedAt: now, api: fresh })}\n`).catch(() => undefined)
  return fresh
}

async function check($: EngineInterface) {
  // A check that runs long is not stacked on by the next tick.
  if (isChecking) return
  isChecking = true
  try {
    if ((await readSwitches($)).isOff) return await setHealth($, EMPTY)
    const settings = parseSettings(await readText($, `${await configFolder($)}/mods/runner-health.json`))
    const local = await readLocal($)
    const now = await $.clock.now()
    const next: Record<string, number> = {}
    for (const unit of local.units) {
      if (unit.isActive) next[unit.runner] = activeSince[unit.runner] ?? now
    }
    activeSince = next
    const state = await readApi($, settings, now)
    await setHealth(
      $,
      assess({
        units: local.units,
        activeSince,
        runners: state.runners,
        jobs: state.jobs,
        disks: local.disks,
        apiNote: state.note,
        localNote: local.note,
        now,
        settings,
      }),
    )
  } finally {
    isChecking = false
  }
}

function stopTimer() {
  timer?.cancel()
  timer = null
}

export const register: Register = on => {
  folder = null
  isChecking = false
  places.clear()
  activeSince = {}
  api = null
  apiKey = ''
  apiDueAt = 0
  stopTimer()

  on('session.start', async ($, e, next) => {
    const result = await next(e)
    stopTimer()
    await check($).catch(() => undefined)
    timer = $.clock.every(TICK_MS, () => check($).catch(() => undefined))
    return result
  })

  on('session.end', async ($, e, next) => {
    stopTimer()
    return next(e)
  })

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    const flags = await read($, switches)
    if (e.props.hasSurvey || flags.isOff || flags.isHidden) return next(e)
    const state = await read($, health)
    const text = bandText(state, e.props.bodyColumns)
    if (text === null) return next(e)
    const { Box, Text } = $.ui.resolve(e)
    const isQuiet = state.problems.every(problem => problem.kind === 'unreadable')
    return (
      <Box>
        {isQuiet ? <Text dimColor>{text}</Text> : <Text color="yellow">{text}</Text>}
      </Box>
    )
  })
}
