// Stands in for a repository's rule export: prints the synthetic master's
// export for one document, or for every document under a folder.
//
//   node export.mjs --doc <path>

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const master = JSON.parse(fs.readFileSync(path.join(here, 'master.json'), 'utf8'));
const doc = process.argv[process.argv.indexOf('--doc') + 1].replace(/\/$/, '');
const exports = master.exports.filter((row) => row.doc === doc || row.doc.startsWith(`${doc}/`));
process.stdout.write(`${JSON.stringify({ exports })}\n`);
