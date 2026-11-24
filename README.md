# Chess Mentor for Claude Code

[![CI](https://github.com/RollingTank/chess-mentor/actions/workflows/ci.yml/badge.svg)](https://github.com/RollingTank/chess-mentor/actions/workflows/ci.yml)

A set of Claude Code skills that turn Claude into a chess **coach** (not your opponent). Stockfish does the
playing and the evaluating; Claude does the teaching.

| Command | What it does |
|---|---|
| `/init-chess` | **Start here.** Finds your games folder, reads every PGN to build your player profile (results, openings, ratings, time controls, plus a Stockfish sample of your recent games), goes through your chess books and resources, and writes a **personalised training plan** from all of it. |
| `/teach-chess` | Teaches what you want from the chess book (PDF, EPUB, PGN, EPD, notes) you choose. Each idea is explained, illustrated with 1-3 examples, then quizzed (4-8 puzzles), then you reflect. Later it **surprise re-quizzes** you to check you actually remember it. |
| `/play-chess` | An instructive game against Stockfish. Claude checks each of your moves, hints without giving the answer, offers take-backs, and reminds you of your recurring weaknesses as they come up. |
| `/analyze-chess` | Runs Stockfish over a game you give it, then walks you through it **move by move, Socratically**: what you were thinking, what you missed and why, how this compares with your last game, and what to work on. |

All four share a **progress record** (`progress.md`): your strengths, weaknesses, an estimated rating, a skill
map, and a personal pre-move checklist, so every session builds on the last. Positions are drawn as PNG
boards (`current_position.png`) that update after every move; keep the file open in VS Code and it refreshes.

## Requirements

- [Claude Code](https://claude.com/claude-code)
- **Python 3.10+** (tested on 3.11; the PNG renderer `resvg-py` does not support older versions)
- **Stockfish**, downloaded separately from <https://stockfishchess.org/download/>. It is not bundled.
- Optional: your own chess books and files for `/teach-chess`.

## Install

### Option A: Claude Code plugin

```text
/plugin marketplace add RollingTank/chess-mentor
/plugin install chess-mentor@chess-mentor
```

Plugin skills are namespaced, so the commands are `/chess-mentor:init-chess`, `/chess-mentor:teach-chess`,
`/chess-mentor:play-chess` and `/chess-mentor:analyze-chess`.

### Option B: copy the skills into your project

Copy the five folders inside [`skills/`](skills) into your project's `.claude/skills/` folder (or into
`~/.claude/skills/` to have them in every project):

```text
your-project/
└── .claude/
    └── skills/
        ├── chess-tutor/     <- shared foundation + the helper script (required by the other four)
        ├── init-chess/
        ├── teach-chess/
        ├── play-chess/
        └── analyze-chess/
```

The commands are then simply `/init-chess`, `/teach-chess`, `/play-chess` and `/analyze-chess`. **Keep all five folders
together**: the four commands load `chess-tutor/` as a sibling. If a command name collides with one of your own skills, rename that
mode's folder and the `name:` line in its `SKILL.md`.

### First-time setup (both options)

The first time you use any command, Claude walks you through setup. You can also do it yourself:

```bash
# 1. Install the two Python packages (versions pinned in skills/chess-tutor/requirements.txt)
python3 -m pip install -r skills/chess-tutor/requirements.txt
#    If pip says the environment is "externally managed", use a virtual environment:
#    python3 -m venv ~/.chess-mentor-venv && ~/.chess-mentor-venv/bin/python -m pip install -r skills/chess-tutor/requirements.txt

# 2. Tell it where Stockfish and your books are (Stockfish on your PATH is found automatically)
python3 skills/chess-tutor/scripts/chess_ops.py setup --stockfish "/path/to/stockfish" --library "/path/to/your/chess books"
```

On Windows use `py -3` (or your Python's full path) instead of `python3`. If you installed as a plugin, the
script is inside the plugin's install folder; simply ask Claude to run setup and it will find it.

## How to use it

Start Claude Code in the folder you want to keep your chess data in, then:

### `/init-chess`: build your profile and training plan (run this first)

```text
/init-chess                      # searches the current folder for your games and books
/init-chess ~/Documents/chess    # search somewhere else
/init-chess ~/chess MyUsername   # say which player in the PGNs is you
```

1. **Finds your files.** It searches the folder (read-only) for PGN folders and for books and study files. If
   it can't tell which folder holds *your own* games (as opposed to a masters collection), it asks.
2. **Builds your profile.** It reads every game, works out which player you are, and summarises your results by
   colour and time control, your rating from the PGN headers, your openings (with the ones that score badly),
   and how your games end (time losses, early collapses). It then runs Stockfish over your most recent games
   (8 by default, a minute or two) for your accuracy by game phase, your error rate, games you failed to
   convert and games you rescued, and your costliest mistakes, which it checks and sorts into themes.
3. **Goes through your books.** It opens the contents pages of the books it finds and writes a catalog
   (`resources.md`) of what each covers, at what level, and which chapters serve which weakness.
4. **Asks about your goal and the time you have**, then writes a **training plan** (`training_plan.md`):
   ranked priorities with the evidence and a measurable target for each, a four-week schedule of exact
   commands, a map of which of your books serves which priority, and what it couldn't tell.

It fills in your `progress.md` so the other commands start from your profile. Re-run it after about 20 new
games to refresh the profile and see what changed. To get your games: Lichess, *Export games* on your profile;
Chess.com, *Archive* then *Download*.

### `/teach-chess`: learn from your books

```text
/teach-chess                                   # Claude lists your library and asks what you want to learn
/teach-chess "Silman's Endgame Course" rook endgames
/teach-chess my_openings.pgn the Najdorf
```

Claude breaks the topic into subskills and runs the cycle for each: **explain**, **examples** (drawn as boards),
**quiz**, **reflect**. Answer in your own words; it asks one question at a time and won't hand you the answer.
Say *just tell me* to skip a question, *harder* / *easier* to adjust, *show progress* for your skill map.
Positions from books are only used when they can be reconstructed with certainty, and every claim is checked
with the engine (old analysis is sometimes wrong, and Claude will tell you when a book is).

### `/play-chess`: coached games

```text
/play-chess                 # Claude asks colour and strength
/play-chess black 1600      # you play Black against Stockfish at about 1600 Elo
```

You play moves in normal notation (`Nf3`, `e2e4`, `0-0`, `nf3` all work). After each move Claude rates it
before the engine replies; if it was a mistake it nudges you with a question and offers to let you retry.
It opens by naming the weaknesses it will watch for, based on your history.

### `/analyze-chess`: review a game

```text
/analyze-chess my_game.pgn black             # a PGN file, and the colour you played
/analyze-chess                               # the game you just played with /play-chess
/analyze-chess quick                         # the report only, without the walkthrough
```

You can also paste moves straight into the chat. Claude runs Stockfish, opens with your accuracy and how it
compares with last time, then goes through the game in order. At each key moment it shows the board and asks
what you were thinking *before* revealing what the engine saw. Say *skip*, *next* or *stop* any time. It ends
with what repeated from earlier games, what you fixed, and 2-3 concrete things to work on.

### How Claude decides what is right

Claude never judges a position, move, puzzle, example or game from its own opinion. Every verdict needs a
**reference**, in this order:

1. **Your book**, when it explicitly states the best continuation for that exact position (a printed solution, a
   stated best line, an EPD `bm`). Claude cites it.
2. **Stockfish**, when no book states the answer.
3. **Neither**: Claude says it has no reference and does not evaluate. It will not guess.

**If the book and the engine disagree, the book wins.** The engine can be wrong, so Claude uses the book's move as
the answer and grades you against it; at most it mentions once that Stockfish prefers something else. A move played
in a PGN game counts as "what was played", not as proof it was best. `chess_ops.py verdict` applies this rule
mechanically: it checks that the book's line is legal from the position, cross-checks it with the engine, and always
answers with the book's move when you supply one.

## Where your data lives

Everything is stored in one folder, `chess_data/`, in the directory where Claude is running (set the
`CHESS_DATA_DIR` environment variable to put it elsewhere).

| File | Contents |
|---|---|
| `progress.md` | Your readable record: player profile, rating estimate, strengths, weaknesses, skill map, review queue, checklist, history |
| `training_plan.md`, `resources.md` | Your personalised plan and the catalog of your books (from `/init-chess`) |
| `profile.json` | The numbers behind your profile (and `profile.prev.json`, the one before) |
| `current_position.png` | The live board, redrawn after every move |
| `game.pgn` | The game in progress |
| `progress.jsonl`, `analyses.jsonl` | Raw results behind `progress.md` and the game-to-game comparison |
| `config.json` | Your Stockfish and library paths |

Nothing leaves your machine except what you say to Claude. Add `chess_data/` to your project's `.gitignore`.

About **ratings**: the profile shows the *game rating from your PGN headers* (not an official rating). The `/teach-chess` quizzes add a *puzzle rating* estimated from your quiz results against the difficulty Claude
assigns each puzzle, so it is only as good as those estimates and says so (with a confidence level).

## Troubleshooting

| Symptom | Fix |
|---|---|
| `python-chess is not installed` | Run the `pip install` command the script prints, or use a virtual environment (see setup) |
| `Stockfish not found` | Install Stockfish, then re-run `setup --stockfish "<full path>"` |
| Board shows an `.svg` instead of a `.png` | `pip install resvg-py` into the Python the script uses |
| On Windows, `python` opens the Microsoft Store | Use `py -3` or a real interpreter path |
| The board image looks stale | Make sure you are viewing `chess_data/current_position.png`, not `analysis.png` |
| Opponent is stronger than the Elo you asked for | Stockfish cannot play below 1320; the script says when it clamps |

## Development

```text
.claude-plugin/        plugin.json, marketplace.json
skills/
  chess-tutor/         shared rules, command reference, scripts/chess_ops.py, requirements.txt
  init-chess/ teach-chess/ play-chess/ analyze-chess/   the four commands (SKILL.md each)
tests/                 pytest suite (see below)
```

- Try it locally without installing: `claude --plugin-dir .` from the repo root. Validate manifests with
  `claude plugin validate .`.
- `chess_ops.py` is stateless: each call replays `chess_data/game.pgn`. Anything that changes the position
  must go through `commit()` so the PNG stays in sync. The command table in `skills/chess-tutor/SKILL.md`
  must match the CLI exactly; update both together (the contract tests fail if they drift apart).
- The behavioural rules in `skills/chess-tutor/SKILL.md` (no answer leaks, never judge positions without the
  engine, short quotes only from books, stay inside the directory you were given) are contracts for Claude at
  runtime; keep them when editing a skill. The tests check that they are still present.
- See [CHANGELOG.md](CHANGELOG.md) for versions.

### Tests

```bash
python3 -m pip install -r requirements-dev.txt
pytest                  # everything; real-Stockfish tests are skipped if no Stockfish is found
pytest -m "not engine"  # fast (about 30 s): unit, component and contract tests only
pytest -m engine        # only the tests that run a real Stockfish (about 2 minutes)
```

| Layer | What it checks |
|---|---|
| Unit (`test_units.py`) | Pure functions: score formatting, move parsing, verdict thresholds, rating maths, profile helpers, rendering |
| Component (`test_cli_game.py`, `test_analyze.py`, `test_init.py`, `test_progress.py`) | Every CLI command end to end in a temporary data folder, with a deterministic stub engine: the board image always matches the game, rejected moves change nothing, `analyze`/`history` comparisons, `discover` and `profile` on realistic folders, `log`/`stats`, `setup` |
| Integration (`test_stockfish.py`) | The same flows against a real Stockfish: full games, mate detection, move review, `analyze`, `profile` with an engine sample. Stockfish is found through `STOCKFISH_PATH`, your `PATH`, or a `stockfish/` folder in the repo |
| Pipeline (`test_pipeline.py`) | The CI/CD workflows themselves (pinned actions, least-privilege permissions, no risky triggers, the Python/OS matrix) and the release script |
| Contract (`test_contract.py`) | Skills, manifests, docs and code agree: every `$OPS` command and flag a skill mentions exists, links resolve, versions match the changelog, the safety rules are still in the skills, no personal paths in the repo, Python 3.10-compatible syntax |

Tests run in pytest's temporary folders and never read or write your own `chess_data/`.

### CI/CD

GitHub Actions (`.github/workflows/`) runs on every push to the default branch and on every pull request:

| Job | What it does |
|---|---|
| Tests | `pytest -m "not engine"` on Ubuntu, Windows and macOS with Python 3.10 (the minimum) and 3.13 |
| Integration | `pytest -m engine` on Ubuntu with a real Stockfish installed from apt |
| Plugin | `claude plugin validate .` with a pinned Claude Code CLI |
| All checks passed | One status that depends on the others; use it as the required check for branch protection |

**Releasing** is driven by tags. To cut a release:

1. Bump `version` in `.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json`.
2. Move the notes in `CHANGELOG.md` under a `## [X.Y.Z] - date` heading.
3. Merge to the default branch, then `git tag vX.Y.Z && git push origin vX.Y.Z`.

The release workflow first checks that the tag is on the default branch, that the tag, both manifests and the
changelog agree (`python .github/scripts/release_notes.py vX.Y.Z` runs the same check locally), and that the
tests pass. Only then does it publish a GitHub Release with the changelog section as its notes and a
`chess-mentor-skills-X.Y.Z.zip` bundle of the `skills/` folders for people who copy them into `.claude/skills/`.
Dependabot opens weekly PRs for the workflow actions and the pinned Python dependencies; CI runs the full suite on each.

## License

[GPL-3.0-or-later](LICENSE). The helper script uses [python-chess](https://github.com/niklasf/python-chess)
(GPL-3.0+) and [resvg-py](https://pypi.org/project/resvg-py/) (MIT), installed separately by pip. Stockfish
(GPL-3.0) is not bundled; you install it yourself. Your chess books are only read locally, and Claude quotes
short excerpts at most.
