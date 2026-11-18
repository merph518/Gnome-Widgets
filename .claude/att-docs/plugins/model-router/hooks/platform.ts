import type { EngineInterface } from 'claude-code'

// The shell job the plugin runs. It runs on Linux: /bin/sh and coreutils.

// Appends text to a file, making its folder first. $.fs has no append, and a read and
// write could drop a line another plugin added in between.
export async function appendFile($: EngineInterface, path: string, text: string) {
  return $.process.run(['/bin/sh', '-c', 'mkdir -p "$(dirname "$1")" && cat >> "$1"', 'sh', path], {
    stdin: text,
    timeoutMs: 5000,
  })
}
