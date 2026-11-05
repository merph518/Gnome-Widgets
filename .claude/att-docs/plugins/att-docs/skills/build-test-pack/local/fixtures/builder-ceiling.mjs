// A builder command that adds two checks to the stub: the most assumptions each
// overall confidence allows (High 3, Medium 10), and an Executive Summary confidence
// that starts with the overall one. A pack that breaks either is refused: every
// sheet is printed with its status, a failing one with its reason indented under
// it, and no workbook is written. Any other pack goes to the stub's command line.
//
//   node builder-ceiling.mjs <pack.json> --out <dir>

import fs from 'node:fs';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { buildPack } from './builder-stub.mjs';

const CEILINGS = { High: 3, Medium: 10 };

const pack = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const overall = pack.confidence?.overall;
const count = Array.isArray(pack.assumptions) ? pack.assumptions.length : 0;
const problems = {};
if (overall in CEILINGS && count > CEILINGS[overall]) {
  problems['Confidence Assessment'] = `overall confidence ${overall} is more than the pack supports:`
    + ` ${count} assumptions against a limit of ${CEILINGS[overall]}; rate it Low`;
}
const summary = String(pack.executiveSummary?.confidence ?? '');
if (overall && !summary.startsWith(overall)) {
  problems['Executive Summary'] = `confidence starts "${summary.split(/[.\s]/)[0]}", which does not`
    + ` match the overall confidence "${overall}"`;
}

if (!Object.keys(problems).length) {
  const stub = fileURLToPath(new URL('./builder-stub.mjs', import.meta.url));
  const result = spawnSync(process.execPath, [stub, ...process.argv.slice(2)], { encoding: 'utf8' });
  process.stdout.write(result.stdout);
  process.stderr.write(result.stderr);
  process.exit(result.status ?? 1);
}
for (const [sheet, , , status] of buildPack(pack).validation ?? []) {
  const failed = Boolean(problems[sheet]) || sheet === 'Workbook Validation';
  console.log(`${(failed ? 'FAIL' : status).padEnd(22)} ${sheet}`);
  if (problems[sheet]) console.log(`    ${problems[sheet]}`);
}
process.exit(1);
