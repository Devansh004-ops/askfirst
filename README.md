# AskFirst

**Ask your SQLite database questions in plain English. When a question is vague, it asks you
what you meant, instead of silently guessing.**

> "Who is our top member?" Top by loans? By different books read? By recent activity? Each
> reading gives different, perfectly valid SQL, and no error message warns you which one you
> got. AskFirst notices the vague phrase, asks one short multiple-choice question, and tells the
> SQL writer exactly what you decided.

```text
$ askfirst ask "What is the most popular book?"

How should books be ranked?   [about: popular / best (books)]
  [1] Most loans (times borrowed)   (default)
  [2] Most different borrowers
  [3] Highest average rating
Pick a number, type your own meaning, or press Enter for the default: 3

"popular / best (books)" -> Highest average rating   (you chose)

SQL:
SELECT b.title FROM books b JOIN reviews r ON r.book_id = b.book_id GROUP BY b.book_id HAVING COUNT(*) >= 3 ORDER BY AVG(r.rating) DESC LIMIT 1

title
-----------------
The Hidden Voyage

[1 row(s), 0.00s]
```

That transcript is real output of the bundled demo (offline provider, library database).

## Why it is built the way it is

| Idea | What it means here |
| --- | --- |
| **Detect vagueness deterministically.** | Vague phrases are found by small, readable rules (`rules.json`), not by another model call. It is free, instant, explainable, and testable. A model can optionally flag terms the rules miss (`--probe`). |
| **Ask only when it matters.** | Each rule lists the words that already settle the meaning ("by number of loans", "last 14 days"), so those questions are never interrupted. |
| **Never ask twice.** | Resolution order: your saved choice, then the organisation **glossary**, then asking you, then a default that is **reported as an assumption**. Nothing is assumed silently. |
| **Pass decisions on as data.** | Your answer reaches the SQL writer as an explicit instruction, not text glued onto your question. |
| **Make the database the safety net.** | Model-written SQL runs in a sandbox where SQLite itself says what a statement does (see below), not one that scans for scary keywords. |
| **Measure, don't claim.** | A golden set scores whether the *result* is right, with and without asking. |

## Install and try it

```bash
pip install -e .            # standard library only; no dependencies for the core
askfirst ask "What is the most popular book?"     # creates a demo database on first use
askfirst ask --assume "Show me recent loans"      # never ask; report assumptions instead
askfirst repl                                      # interactive session
askfirst schema                                    # what the model is told about the database
askfirst eval                                      # the benchmark
```

Needs Python 3.10+ (tested on 3.11, 3.12 and 3.13). The default **offline provider** understands
only the bundled sample questions; it exists so the project runs, demos and tests with no API key.
For open-ended questions use a real model:

```bash
pip install -e ".[gemini]"
export GEMINI_API_KEY=...           # https://aistudio.google.com/apikey
askfirst ask --provider gemini --probe "Which authors are most borrowed?"
```

> The Gemini provider is unit-tested with a fake client but has **not** been run against the live
> API by the author. Treat it as a first implementation of a small interface (`providers/`) and
> report problems.

## Use it from Python

```python
from askfirst import Engine, ReadOnlyDB, load_domain
from askfirst.domains.library.seed import generate
from askfirst.providers import make_provider

generate("library.db")                                   # deterministic demo data
engine = Engine(load_domain("library"), ReadOnlyDB("library.db"), make_provider("offline"))

answer = engine.ask("What is the most popular book?", chooser=lambda rule: "rating")
print(answer.resolutions[0].interpretation.label, answer.rows)
```

`chooser` receives the vague rule and returns an option id, an option number, free text (used as a
custom meaning), or `None` to decline (the default is then used and flagged in `answer.assumptions`).

## How a question flows

```text
question
  |
  v
detect vague terms (rules.json)  --none-->  ...............................
  |                                                                       :
  v                                                                       :
resolve each: saved choice > glossary > ask the user > reported default   :
  |                                                                       :
  v                                                                       v
SQL provider  <-- schema, notes, today's date, your decisions ------------+
  |
  v
sandbox: read-only file, authorizer allowlist, timeout, row cap
  |        error the model can fix? -> one repair attempt with SQLite's message
  v        refused by the sandbox?  -> reported, never retried
rows + the interpretations that produced them
```

### Safety: what the sandbox does

Instead of searching the SQL text for forbidden words (which a parser and an attacker can disagree
about), the sandbox registers an **authorizer** with SQLite. SQLite reports every action a
statement performs while compiling it, and the sandbox approves only: `SELECT`, reading columns of
allowlisted tables, and calling allowlisted functions. Everything else (writes, DDL, `PRAGMA`,
`ATTACH`, `load_extension`, `random()`, reading `sqlite_master` or the internal metadata table)
is refused by the engine whatever the SQL looks like.

Layers beneath it: the file is opened `mode=ro`; `PRAGMA query_only` is on; a progress handler
enforces a wall-clock timeout; rows are capped and truncation is reported; SQLite rejects a second
statement. The tests attack each layer, and check the database file's hash is unchanged afterwards.

## Domain packs: point it at your own database

A pack is a folder:

```text
mypack/
  domain.json    {"name": "...", "notes": ["facts the SQL writer needs"], "as_of_query": "SELECT ..."}
  schema.sql     CREATE TABLE statements
  rules.json     vague phrases and their possible meanings
  glossary.json  optional {"rule_id": "option_id"} agreed definitions (no more asking)
  golden.json    optional benchmark questions
```

A rule:

```json
{
  "id": "recent_window", "term": "recent", "question": "How far back is \"recent\"?",
  "when_all": ["\\b(recent|recently|lately)\\b"],
  "unless":   ["\\b(last|past)\\s+\\d+\\s+days?\\b", "\\b(this|last)\\s+(week|month|year)\\b"],
  "options": [
    {"id": "7d",  "label": "The last 7 days",  "hint": "Treat \"recent\" as date >= date(TODAY, '-7 day')."},
    {"id": "30d", "label": "The last 30 days", "default": true, "hint": "..."}
  ]
}
```

Then `askfirst ask --domain mypack --db my.db --provider gemini "..."`. Packs are validated on load
(at least two options, one default at most, glossary entries must exist). `askfirst schema` shows
exactly what the model will be told. Relative dates are measured from `as_of_query` (or `--today`),
never the wall clock, so a snapshot database stays answerable.

## Evaluation

`askfirst eval` runs the domain's golden questions twice through the real engine:

* **guess**: nothing is asked; defaults are assumed (a system with no clarification step);
* **ask**: a scripted user answers with the intended meaning.

A case is correct only if the **result set** equals the expected query's result (column names and,
by default, row order ignored; extra columns allowed). Reported: accuracy overall / on ambiguous /
on clear questions, detection recall, false-alarm rate, repairs, latency, and a count of cases whose
expected result is empty (an empty-vs-empty match proves nothing).

With the bundled data the demo set includes planted facts so each reading of "most popular" has a
*different, unique* winner. **With the offline provider the benchmark shows the harness and the
effect of the clarification step (guessing: 0% on ambiguous questions; asking: 100%). It says nothing
about how well any language model writes SQL.** To measure a real model, run
`askfirst eval --provider gemini` and quote those numbers, with the model name and date.

## Project layout

```text
src/askfirst/
  engine.py      pipeline: detect -> resolve -> write SQL -> run -> repair
  detect.py      rule matching                resolve.py    saved choice > glossary > ask > assume
  sandbox.py     SQLite authorizer sandbox    domain.py     pack loader and validation
  scoring.py     result equivalence           evaluate.py   golden-set runner
  prompt.py      prompts for model providers  cli.py        command-line interface
  providers/     offline.py (demo), gemini.py (real model)
  domains/library/   schema, rules, seed generator, golden questions
tests/           150+ tests (sandbox attacks, rules, resolution, engine, scoring, CLI, benchmark)
```

Run the tests with `pip install -e ".[dev]" && pytest`.

## Limitations

* SQLite only. The sandbox idea (let the engine's authorizer decide) does not transfer directly to other databases.
* Rules are regular expressions: they are precise and cheap but only cover phrases someone wrote down. `--probe` is the stopgap for the rest.
* One clarification round per question; no conversation memory beyond saved preferences.
* The offline provider is a demo. The Gemini provider is untested against the live service.
* The benchmark is small and its demo data is synthetic.

## Background and license

Asking before guessing is a general idea in the text-to-SQL literature and in several open-source
projects; this implementation, its design, data and tests are original to this repository.
MIT licensed (see `LICENSE`).
