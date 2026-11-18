// The parts of the handoff plugin that need no engine: removing secrets, building the
// draft, the write-up prompt, file names, the new-chat link, the clipboard commands and
// the switches file.

import type { SessionMessage } from 'claude-code'

import type { HandoffSwitches } from '../types'

export const SECRET = '<secret removed>'

// The context size, in tokens, at which the band is first offered, and how much more
// it takes before it is offered again once closed.
export const OFFER_AT = 250_000
export const SNOOZE = 100_000

// The five steps the band shows, in order.
export const STEPS = ['Read the chat', 'Save a draft', 'Write the handoff', 'Remove secrets', 'Save the handoff'] as const

// The longest `claude://code/new` link handed to xdg-open. The desktop app's own
// limit is not documented; 32,000 characters stays well under the 128 KiB a single
// command-line argument may hold on Linux.
export const MAX_LINK_CHARS = 32_000

const NEW_CHAT = 'claude://code/new?q='

// How much of each message the draft keeps.
const ASK_CHARS = 300
const REPLY_CHARS = 2000

// Each pattern is replaced in turn. Names that hold a secret keep their name, so the
// handoff still says which setting was there.
const PATTERNS: [RegExp, string][] = [
  // A private key block, whole.
  [/-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z0-9 ]*PRIVATE KEY-----/g, SECRET],
  // `Bearer <token>`, in a header or anywhere else.
  [/\b(Bearer\s+)[A-Za-z0-9\-._~+/]+=*/g, `$1${SECRET}`],
  // A quoted JSON or YAML key that names a secret: "client_secret": "value".
  [
    /("[\w.-]*(?:key|token|secret|password|passwd)[\w.-]*"\s*:\s*)"(?:[^"\\\n]|\\.)*"/gi,
    `$1"${SECRET}"`,
  ],
  // NAME=value where the name holds KEY, TOKEN, SECRET or PASSWORD (any case), the
  // value quoted or not. A value already removed is left alone, so scrubbing twice
  // gives the same text as scrubbing once.
  [
    /\b([A-Za-z0-9_.-]*(?:key|token|secret|password|passwd)[A-Za-z0-9_.-]*=)(?!<secret removed>)(?:"[^"\n]*"|'[^'\n]*'|[^\s"'`]+)/gi,
    `$1${SECRET}`,
  ],
  // Keys and tokens with a known shape.
  [/\bsk-(?:ant-)?[A-Za-z0-9_-]{16,}/g, SECRET],
  [/\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}/g, SECRET],
  [/\bgithub_pat_[A-Za-z0-9_]{20,}/g, SECRET],
  [/\b(?:AKIA|ASIA)[0-9A-Z]{16}\b/g, SECRET],
  [/\bxox[abposr]-[A-Za-z0-9-]{10,}/g, SECRET],
  [/\bAIza[0-9A-Za-z_-]{35}\b/g, SECRET],
  [/\bglpat-[A-Za-z0-9_-]{20,}/g, SECRET],
  // A JSON Web Token: three base64url parts, the first two starting `eyJ`.
  [/\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}/g, SECRET],
]

// Replaces text that looks like a secret with `<secret removed>`. The patterns catch
// the common shapes; a secret in an unusual shape can still get through.
export function scrub(text: string): string {
  return PATTERNS.reduce((out, [pattern, replacement]) => out.replace(pattern, replacement), text)
}

// Removes secrets before cutting, so a cut never leaves part of a secret too short for
// its pattern.
function clip(text: string, chars: number): string {
  const line = scrub(text).trim()
  return line.length > chars ? `${line.slice(0, chars - 1)}…` : line
}

function list(items: Iterable<string>): string {
  const lines = [...items].map(item => `- ${item}`)
  return lines.length === 0 ? '- none' : lines.join('\n')
}

const PATH_KEYS = ['file_path', 'notebook_path', 'path']

// A plain record of the chat, built without a model: what was asked, the files,
// skills and tools used, the links, and the last reply. It is saved first, so a
// write-up that fails still leaves something to start from.
export function draftFrom(messages: readonly SessionMessage[]): string {
  const asks: string[] = []
  const files = new Set<string>()
  const skills = new Set<string>()
  const tools = new Map<string, number>()
  const links = new Set<string>()
  let lastReply = ''
  for (const message of messages) {
    for (const url of scrub(message.text).match(/https?:\/\/[^\s)>\]"'`]+/g) ?? []) links.add(url)
    if (message.role === 'user') {
      if (message.text.trim() !== '') asks.push(clip(message.text, ASK_CHARS))
      continue
    }
    if (message.text.trim() !== '') lastReply = message.text
    for (const use of message.toolUses) {
      tools.set(use.tool, (tools.get(use.tool) ?? 0) + 1)
      for (const key of PATH_KEYS) {
        const value = use.input[key]
        if (typeof value === 'string' && value !== '') files.add(value)
      }
      if (use.tool === 'Skill' && typeof use.input.skill === 'string') skills.add(use.input.skill)
    }
  }
  return [
    '# Handoff draft',
    '',
    'A plain record of the chat, saved before the full handoff was written.',
    '',
    '## Asked',
    list(asks),
    '',
    '## Files',
    list(files),
    '',
    '## Skills',
    list(skills),
    '',
    '## Tools',
    list([...tools].map(([tool, count]) => `${tool} (${count})`)),
    '',
    '## Links',
    list(links),
    '',
    '## Last reply',
    lastReply === '' ? 'none' : clip(lastReply, REPLY_CHARS),
    '',
  ].join('\n')
}

// What the fork of the chat is asked to write.
export const WRITE_UP = `Write a handoff of this whole conversation so a new chat, with none of this context, can pick up the work. Do not call any tools; answer with the handoff alone, in Markdown, under these headings:

# Handoff

## Asked
What the user asked for, in their terms, including changes of direction.

## Done
What was done, and where it stands now.

## Decided
Decisions made and why, and what was ruled out.

## Files
The files read, changed or created, with full paths, and what each one is for.

## Skills
The skills used and what for.

## Tools
The tools and commands that mattered, and anything learned about them.

## Links
URLs, issues, pull requests and documents referenced.

## Next steps
What is left, in order, with anything the next chat must check first.

Leave out passwords, API keys, tokens and other secrets. Be specific and brief.`

// The moment as `YYYYMMDD-HHMMSS`, in UTC, for file names.
export function stamp(ms: number): string {
  return new Date(ms).toISOString().replace(/\.\d+Z$/, '').replace(/[-:]/g, '').replace('T', '-')
}

// The link that opens a new chat filled in with `text`. When the encoded handoff is
// too long for the link, the chat is filled in with a line naming the saved file.
export function newChatLink(text: string, path: string): string {
  const full = `${NEW_CHAT}${encodeURIComponent(text)}`
  if (full.length <= MAX_LINK_CHARS) return full
  return `${NEW_CHAT}${encodeURIComponent(`Read the handoff saved at ${path} and continue the work it describes.`)}`
}

export type ClipboardCommand = { argv: string[]; apt: string }

const WL_COPY: ClipboardCommand = { argv: ['wl-copy'], apt: 'wl-clipboard' }
const XCLIP: ClipboardCommand = { argv: ['xclip', '-selection', 'clipboard'], apt: 'xclip' }

// The clipboard commands to try, in order. A Wayland session tries wl-copy first, then
// xclip through XWayland when there is an X display; an X11 session tries xclip alone.
export function clipboardCommands(env: Readonly<Record<string, string | undefined>>): ClipboardCommand[] {
  const type = (env.XDG_SESSION_TYPE ?? '').toLowerCase()
  const isWayland = (env.WAYLAND_DISPLAY ?? '') !== '' || type === 'wayland'
  const isX = (env.DISPLAY ?? '') !== '' || type === 'x11'
  return [...(isWayland ? [WL_COPY] : []), ...(isX ? [XCLIP] : [])]
}

// Runs `argv` with its output thrown away, so a command that leaves a process behind
// (wl-copy and xclip keep one to serve the clipboard) does not hold the call open.
// The shell exits 127 when the command is not installed.
export function detached(argv: readonly string[]): string[] {
  return ['sh', '-c', 'exec "$@" >/dev/null 2>&1', 'sh', ...argv]
}

// switches.json is a JSON object of on and off values that a switchboard plugin
// writes. A missing or unreadable file leaves this plugin on and its band shown.
export function parseSwitches(text: string | undefined): HandoffSwitches {
  const on: HandoffSwitches = { isOff: false, isHidden: false }
  if (text === undefined) return on
  let value: unknown
  try {
    value = JSON.parse(text)
  } catch {
    return on
  }
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return on
  const record = value as Record<string, unknown>
  return { isOff: record.handoff === false, isHidden: record['handoff:hidden'] === true }
}

// Claude Code's configuration folder: CLAUDE_CONFIG_DIR when set, else ~/.claude.
export function configDir(home: string | undefined, configured: string | undefined): string {
  const dir = configured?.trim()
  if (dir) return dir.replace(/\/+$/, '')
  return `${home ?? ''}/.claude`
}
