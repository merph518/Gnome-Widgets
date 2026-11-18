import type { EngineInterface } from 'claude-code'

// The shell jobs the plugin runs. It runs on Linux: /bin/sh, coreutils and xdg-open.

export async function removeFile($: EngineInterface, path: string) {
  await $.process.run(['/bin/rm', '-f', path])
}

// Opens a file in the desktop's default app for its type.
export async function openFile($: EngineInterface, path: string) {
  return $.process.run(['xdg-open', path], { timeoutMs: 10_000 })
}

// Appends text to a file, making its folder first. $.fs has no append, and a read and
// write could drop a line another plugin added in between.
export async function appendFile($: EngineInterface, path: string, text: string) {
  return $.process.run(['/bin/sh', '-c', 'mkdir -p "$(dirname "$1")" && cat >> "$1"', 'sh', path], {
    stdin: text,
    timeoutMs: 5000,
  })
}
