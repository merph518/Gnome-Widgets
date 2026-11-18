# model-router

Picks the model each subagent runs on. Before a subagent starts, Haiku reads its task and
answers in JSON:

```json
{"tier": "fast", "confidence": 0.86, "effort": 1, "effort_confidence": 0.7, "risky": 0.02}
```

| Tier | Default model | For |
|---|---|---|
| `fast` | `claude-haiku-5-5` | Mechanical and local work: read or summarize a file, run one command, rename a symbol. |
| `balanced` | `claude-sonnet-5-5` | Ordinary engineering: a well-specified change across a few files, tests, a clearly described bug. |
| `deep` | `claude-opus-5-5` | Hard or high-stakes work: design, unknown failures, security, migrations, concurrency. |

The judge call goes through the engine's own model call with `model: "haiku"`. The plugin
makes no other network call and needs no API key. It runs on Linux, in the terminal and in
the desktop app.

Install it from this marketplace:

```
claude plugin install model-router@att-docs --scope user
```

## A named model is judged too

Every spawn except a fork or a resume is judged, **including one whose caller named a
model**. A skill or agent that asks for Opus can run on Haiku when Haiku is at least 0.6
sure the task is simple. When a skill needs the model it names, turn routing off with
`routeSubagentModel: false`, or turn the plugin off in `/mods`.

## How a pick is made

- **Moving down needs 0.6.** A task moves to a cheaper model only when Haiku's confidence
  is at least `minDowngradeConfidence` (0.6). It moves to a dearer model at
  `minUpgradeConfidence` (0.3) or more.
- **The starting point.** A move is measured from the model the caller named, or from the
  parent's model when it named none.
- **Fail-open.** A judge call that errors, runs past `timeoutMs`, or answers with no
  readable tier keeps the model as it is. A confidence that is not a number from 0 to 1
  counts as none: it can never move a task down.
- **Risk forces the deep tier.** `risky` above 0.7 sends the task to `deep`, whatever the
  tier said. A task already on the deep tier keeps its exact id (`claude-opus-5-5[1m]`
  stays as it is).
- **Task text is cut** at 12,000 characters before it goes to the judge, and sits inside
  `<task>` tags that the judge is told to treat as data.
- **Forks and resumes are skipped.** A fork runs on its parent's model; a resume keeps its
  own.
- **The main chat's model is never changed.** A model change mid-chat throws the whole
  prompt cache away.
- **Main chat effort is off by default.** With `routeMainEffort` on, Haiku also reads each
  typed prompt and the main chat's effort moves by the same bars.

Haiku's confidence is its own estimate. It is not calibrated.

## The /mods switch

`"model-router": false` in `~/.claude/mods/switches.json` turns every hook into a
pass-through. `"model-router:hidden": true` stops the pane opening by itself; the routing
goes on. The file is read at session start and every 3 seconds. `~/.claude` is
`CLAUDE_CONFIG_DIR` when that is set.

## Savings ledger

When a picked subagent's run ends, one line goes to `~/.claude/mods-logs/savings.jsonl`
with `"mod":"model-router"`:

- `model`: the model it ran on. `replaced`: the model it would have run on. `changed`: true
  or false.
- `cost_usd`: `before`, `after` and `saved`, the run's real token counts priced at list
  price on both models (prices from 2026-10-06).
- `before` and `after` are the same token count: a model swap saves dollars, not tokens.
- `helper`: `{"model":"claude-haiku-5-5","in":…,"out":…}`, the judge call's token counts.
- `detail`: a short file in `~/.claude/mods-logs/model-router/` with the decision and the
  cost math.
- No ledger line when the judge gave no decision.

When the Agent call names no model, the "replaced" model is the parent's. An agent type
whose definition sets its own model is not seen here, so its saving can be overstated.

## The pane: Subagent Model Selector

- It opens by itself when a subagent starts. Once you close it, it stays closed until you
  ask for it.
- Open it with `/model-router pane` (or `/model-router`), or with Open in `/mods`.
- One card for each subagent: the task, Haiku's tier and confidence, the model it ran on,
  the model it would have run on, and one sentence on why. A kept model gets a card too,
  for example "Kept Opus: confidence 0.45 under the 0.6 bar."
- When the run ends, the card shows the dollars saved, or the extra cost.
- Details shows Haiku's whole answer, the time it took, the rule, the risk score, the list
  prices, the task and the detail file. Open detail file opens it with `xdg-open`.
- Tiles on top: subagents, how many moved, dollars saved.

## Reading the log

`~/.claude/mods-logs/model-router.log` holds the setup line, the first time each hook
fires, every spawn, every judge answer and every ledger line:

```
ready on the Haiku judge (claude-haiku-5-5, 8000ms limit); routing subagent model
judge (general-purpose "List files"): tier fast (0.86) · effort 1.0 → medium (0.70) · risky 0.02 · 1240ms
general-purpose "List files": claude-opus-5-5 -> claude-haiku-5-5: fast (confidence 0.86)
judge (general-purpose "Fix the parser"): tier fast (0.45) · risky 0.01 · 1180ms
general-purpose "Fix the parser": kept claude-opus-5-5: kept claude-opus-5-5, wanted claude-haiku-5-5 (confidence 0.45)
```

- `judge (...)` is what Haiku answered, before the bars.
- `kept ..., wanted ...` means a bar stopped the move.
- `judge gave no answer (...)`, `judge answer unreadable` or `judge call refused` means the
  model was kept and no ledger line is written.

## Options

```
fastModel:              string  default claude-haiku-5-5
balancedModel:          string  default claude-sonnet-5-5
deepModel:              string  default claude-opus-5-5
minUpgradeConfidence:   number  default 0.3
minDowngradeConfidence: number  default 0.6
routeSubagentModel:     boolean default true
routeMainEffort:        boolean default false
timeoutMs:              number  default 8000 (Haiku takes about 1.3 s)
logDecisions:           boolean default true
```

## Privacy

The subagent's prompt (cut to 12,000 characters), its description and its agent type go to
Haiku through the engine's own model call. Nothing else leaves the machine.

## Credit

This plugin is a modified copy of `cli-tool/components/mods/productivity/jev-model-router`
from [davila7/claude-code-templates](https://github.com/davila7/claude-code-templates),
by Daniel (San) Ávila, under the MIT license, by way of BenAI's modified copy. `LICENSE`
holds the license and each modification note.

## Tests

```
claude plugin test plugins/model-router
```
