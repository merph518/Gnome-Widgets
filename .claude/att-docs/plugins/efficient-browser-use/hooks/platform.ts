import type { EngineInterface } from 'claude-code'

// The shell jobs the plugin runs. It runs on Linux: /bin/sh, GNU coreutils, and
// ImageMagick from the imagemagick apt package for the pictures.

/** Runs scripts/imagetool.sh with a picture's base64 on stdin. */
export async function imageTool($: EngineInterface, args: readonly string[], base64: string) {
  return $.process.run(['/bin/sh', `${$.plugin.root}/scripts/imagetool.sh`, ...args], {
    stdin: base64,
    timeoutMs: 20_000,
  })
}

/** Writes a picture's base64 out as a file, making its folder first. */
export async function writePicture($: EngineInterface, path: string, base64: string) {
  return $.process.run(['/bin/sh', '-c', 'mkdir -p "$(dirname "$1")" && base64 -d > "$1"', 'sh', path], {
    stdin: base64,
    timeoutMs: 10_000,
  })
}

export async function removeFile($: EngineInterface, path: string) {
  await $.process.run(['/bin/rm', '-f', path])
}

// Appends text to a file, making its folder first. $.fs has no append, and a read and
// write could drop a line another plugin added in between.
export async function appendFile($: EngineInterface, path: string, text: string) {
  return $.process.run(['/bin/sh', '-c', 'mkdir -p "$(dirname "$1")" && cat >> "$1"', 'sh', path], {
    stdin: text,
    timeoutMs: 5000,
  })
}
