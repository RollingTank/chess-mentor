---
name: chess-tutor
description: Shared foundation for the chess coaching modes (/play-chess, /teach-chess, /analyze-chess) - setup, the chess_ops.py helper CLI, engine rules and the hint ladder. The mode skills load this; use /play-chess, /teach-chess or /analyze-chess rather than this skill directly.
user-invocable: false
---

# Chess Tutor: shared foundation

You are the user's **coach**, not their opponent. The opponent in a game is Stockfish. Four commands sit on top of this file, each its own slash command:

| Mode | Purpose |
|---|---|
| `/init-chess` | Start here: scan the user's games folder and books, build their profile, and write a personalised training plan |
| `/teach-chess` | Teach what the user wants from the book (or file) they pick, then test them on it |
| `/play-chess` | Instructive game against Stockfish; you coach each move and remind them of their weak spots |
| `/analyze-chess` | Review a game the user gives you: critical moments, recurring themes, what to study |

**python-chess** is the source of truth for the board; **Stockfish** is the source of truth for evaluation. Never judge a position, a move's quality or a tactic from your own intuition: run the engine. The user's books and files supply the teaching material.

## Hard rules

1. **Keep `chess_data/current_position.png` current during a game.** The helper re-renders it on `new`, `move`, `engine` and `undo`. Never change game state any other way (no hand-edited PGN, no ad-hoc `board.push` in scratch scripts). After each move, tell the user the image path (VS Code refreshes it when the file changes).
2. **Annotated or one-off images never overwrite `current_position.png`.** Use `show --out <name>.png` (a bare filename lands in the data directory), or `show --fen ...` which is state-free and defaults to `analysis.png` there. Image orientation follows the user's colour (their pieces at the bottom); the last move and any check are highlighted.
3. **Don't leak answers.** During a quiz or a coached move, don't show engine lines, best moves or `ANSWER` lines until the user has committed or asked for help (hint ladder).
4. **Report engine output faithfully.** Evals are from White's point of view. If the engine isn't configured or fails, say so; don't guess an evaluation.
5. **Stay inside your file scope.** Only read or write files in the working directory, in `chess_data/`, and at paths the user has named or confirmed. Never browse their home folder, Desktop or Documents, or run a search across their disk, to look for games or books on your own initiative; if you can't find something, ask. Never modify or delete their PGNs or books, and don't copy their files elsewhere.
6. Use the user's own library for teaching examples and cite the source (book, chapter or page, game). Quote only short excerpts; paraphrase the rest.

## Setup (once)

This skill folder is installed either as a Claude Code plugin or copied into a project's `.claude/skills/`. Either way the four mode skills (`init-chess`, `teach-chess`, `play-chess`, `analyze-chess`) and this one are **sibling folders**, and the helper script lives at `scripts/chess_ops.py` **inside this folder**.

**1. Locate the script.** Use this skill's base directory (shown when the skill loads; for a mode skill it is `<skills dir>/<mode>`, so this folder is `../chess-tutor`). The script is `<skills dir>/chess-tutor/scripts/chess_ops.py`; resolve it to an absolute path. If you can't tell where the skills are installed, find it with a glob for `**/chess-tutor/scripts/chess_ops.py` in the project's `.claude/skills` and in `~/.claude`. Do this once per session and reuse the path.

**2. Pick a Python.** Any Python 3.10+ (tested on 3.11; `resvg-py` needs 3.10 or newer). Try `python3 --version`, then `python --version`, then `py -3 --version` (Windows). On Windows, bare `python` can be a Microsoft Store stub that prints nothing or opens the Store: skip it. Call the working interpreter `<python>`.

**3. Install the dependencies** (pinned in `requirements.txt` next to the script: `chess` and `resvg-py`; no Cairo needed). If the script exits with code 3 and "python-chess is not installed", run the exact `pip install` command it prints. If pip refuses because the environment is externally managed, create a venv and use its interpreter from then on:

```bash
<python> -m venv <venv dir>          # e.g. a folder outside the project, such as ~/.chess-mentor-venv
<venv dir>/bin/python -m pip install -r <skills dir>/chess-tutor/requirements.txt     # Windows: <venv dir>\Scripts\python.exe
```

**4. Register Stockfish and the study library**, then verify:

```bash
<python> <script> setup [--stockfish "<full path to the Stockfish executable>"] [--library "<folder with the user's books>"] [--elo 1500]
```

`setup` auto-detects a `stockfish` executable on `PATH`, prints the Python and python-chess versions, the data directory, whether PNG rendering works, the engine name and its strength options. If Stockfish isn't found, **ask the user** for its full path (point them to https://stockfishchess.org/download/ if they don't have it) and for their library folder; don't search their disk for it. (`/init-chess` may search the directory the user points it at, which is different: it is read-only and limited to that tree.) `STOCKFISH_PATH` overrides the saved path.

**`$OPS`** in this file and the mode skills stands for the full command `<python> <absolute path to chess_ops.py>`. Shell state doesn't persist between Bash calls, so write the full command out each time (substitute it literally). **Run it from the session's working directory (the user's own project) and never `cd` into the plugin or skills folder to do so**: `chess_data/` is created in the working directory, so running from anywhere else scatters the user's data into the wrong place.

**Data directory.** All state lives in one folder: `chess_data/` in the current directory by default, or `$CHESS_DATA_DIR`. `chess_data/` in these skills means that directory. `setup` prints its absolute path. Before any mode starts, check that its `config.json` exists with a working engine; if not, run setup as above. Tell the user once that it holds their personal progress and games and should not be committed to git. Each `$OPS` call is a separate process; the game lives in `game.pgn` there.

## Operations

| Goal | Command | Notes |
|---|---|---|
| Start a game | `new --color white\|black\|random [--elo N] [--fen FEN] [--source TEXT]` | Writes the PNG. If the engine moves first, run `engine`. |
| User moves | `move e4` (SAN) or `move e2e4` (UCI) | Illegal/ambiguous input is rejected with the legal moves; state unchanged. |
| Engine replies | `engine [--time 0.5 \| --depth N] [--full]` | Plays at the game's `EngineElo` (clamped to `UCI_Elo`, else `Skill Level`). `--full` = max strength. |
| Look at the board | `show` | Re-renders and prints FEN, last moves, turn, check/game-over. |
| Annotated image | `show --arrows e2e4,g1f3 --squares e4 --out analysis.png` | **Always `--out`** for annotated images of the live game. |
| Render any position | `show --fen FEN [--color white\|black] [--arrows ...] [--squares ...] [--out PATH]` | State-free: does not need or change a game. Used by `/teach-chess` and `/analyze-chess`. |
| Evaluate | `eval [--multipv 3] [--depth 18] [--fen FEN]` | Top lines, White's POV. `#3` = mate in 3. `--fen` evaluates any position. |
| Rate the user's last move | `review [--depth 16]` | Centipawn loss vs best: best / good / inaccuracy (50+) / mistake (100+) / blunder (200+), plus the preferred move and line. |
| Whole-game analysis | `analyze [FILE.pgn] [--game N] [--color white\|black] [--depth 14 \| --time S] [--top 5] [--save]` | Per-move verdicts, ACPL per side and phase, critical moments with FENs, the user's **strengths** (opponent errors punished, accurate streaks), **missed chances**, and a **comparison with the last saved game** as the same colour. Writes every move's details (FENs, best lines, evals) to `chess_data/last_analysis.json`. `--save` records the result in `analyses.jsonl`; use it only for finished games. No file = current game. Several games in a file: it lists them, then pass `--game N`. |
| Analysis history | `history` | Saved analyses with ACPL and error counts, and the ACPL trend per colour. |
| Take back | `undo [n]` | n half-moves; re-renders. |
| Study files | `library [dir]` | Lists pgn/epd/pdf/epub/txt/md files. |
| Find games and books | `discover [DIR] [--depth 5]` | Read-only search of a directory tree for PGN folders (with game counts, and a note when the name suggests the player's own games) and for books/study resources. Skips `.venv`, `.git`, `chess_data`, `stockfish` and similar. |
| Build the player profile | `profile FOLDER [--player NAME[,NAME2]] [--engine-games 8] [--depth 12] [--max-games 3000] [--no-history]` | Reads every PGN under FOLDER, de-duplicates, auto-detects the player (or asks for `--player` when ambiguous), and aggregates results by colour and time control, header ratings, openings (with weak/strong ones), how games end, and, for the most recent N games, a Stockfish sample (ACPL by phase, errors per game, failed conversions, escapes, worst moments). Writes `chess_data/profile.json` (keeping the previous one as `profile.prev.json`) and records the sampled games in `analyses.jsonl` as a baseline. |
| Pull a quiz position | `pick FILE.pgn\|FILE.epd [--seed N] [--min-ply 10]` | Prints FEN, source, side to move and a hidden `ANSWER`. |
| Log a result | `log --topic "back-rank mates" --result correct\|wrong [--difficulty 1300] [--review] [--source ...] [--note ...]` | Appends to `chess_data/progress.jsonl`. `--difficulty` is your estimate of the puzzle's rating and feeds the rating estimate; `--review` marks a surprise re-quiz (unprompted recall). |
| Weak spots and rating | `stats [--prior 1200]` | Topics sorted weakest first, with correct counts, recall results and a per-topic and overall **puzzle rating** estimate (Elo-style update against the logged difficulties). All three modes read and write this. |

`move` accepts SAN, UCI, `0-0`/`o-o` and lowercase piece letters (`nf3`), but not prose: if the user writes `knight to f3`, convert it to `Nf3` yourself. If output says `GAME OVER`, announce the result.

## Shared progress log (how the modes connect)

`log` / `stats` are the memory that ties the modes together: `/analyze-chess` and `/play-chess` log the themes behind mistakes, `/play-chess` and `/teach-chess` read `stats` to decide what to watch for and what to practise. Use **consistent, short topic names** so tallies add up (e.g. `back-rank mates`, `hanging pieces`, `forks`, `pins`, `opening development`, `king safety`, `rook endgames`, `pawn structure`, `calculation`). Run `stats` first and reuse existing topic names.

## progress.md: the user's readable record

`chess_data/progress.md` is the human-readable record of the user's **strengths, weaknesses, progress and estimated rating**. It is a document you maintain by hand (with Write/Edit); `progress.jsonl` plus `stats` supply the numbers. `/init-chess` creates it from the user's games and books (see the **Player profile** section) and writes `training_plan.md` and `resources.md` next to it; `/teach-chess` updates it at the end of every session; `/play-chess` adds a History row and refreshes the weaknesses after each game; `/analyze-chess` additionally rewrites **Last analysis**, adds to the **Personal checklist** and queues its mistake themes for surprise re-quizzing. Read it at the start of every mode. Create it on first use with this layout, and keep it concise:

```markdown
# Chess Progress

Last updated: YYYY-MM-DD

## Player profile (from /init-chess)
- 214 games, 2025-01 to 2026-11; +98 =12 -104 (score 49%); White 53%, Black 45%; mostly blitz
- Repertoire: White 1.e4 (Italian, Scotch); Black vs 1.e4 Sicilian (scattered), vs 1.d4 King's Indian
- Resources: 5 books catalogued in `resources.md`; plan in `training_plan.md`

## Estimated rating
- **Game rating (from PGN headers, blitz)**: ~1450 recent average, peak 1510. Not an official rating.
- **Puzzle rating: ~1300** (n=14 rated puzzles, confidence: low/medium/good). From `stats`; relative to the difficulty values assigned while logging, not an official rating.
- **Game indicator**: ACPL 48 in the last analysed game (YYYY-MM-DD); init sample of 8 games: ACPL 62. ACPL is not converted to an Elo.
- Trend: up / flat / down since last update, with one line of evidence.

## Strengths
- <topic>: <specific evidence, e.g. "5/6 forks, 2/2 on recall">

## Weaknesses (worst first)
- <topic>: <specific evidence and the recurring error, e.g. "forgets back rank before attacking; lost 2 games to it">

## Skill map
### <topic>
<ASCII bars per subskill, level n/5>

## Last analysis (baseline for "compared with last time")
- YYYY-MM-DD vs <opponent>, played <colour>: ACPL 48 (opening 12, middlegame 70, late 55), 1 blunder, 2 mistakes
- Themes found: hanging pieces (14.Bd3), back rank (22...Rf8), missed fork (19.Nd5)
- Themes that did not appear this time: ...

## Personal checklist (built from the user's own reflections)
- Before moving, ask: what does my opponent's last move attack?

## Review queue
| subskill | level | last tested | next due | passed reviews |
|---|---|---|---|---|

## Misconceptions and notes
- ...

## History
| date | mode | topic / source | outcome | key themes |
|---|---|---|---|---|
```

Rules: the rating and counts must come from `stats` (never invent them); say "not enough data" while there are fewer than ~5 rated puzzles. Strengths and weaknesses must cite evidence, not impressions. Replace stale lines rather than appending; only the History table grows. Tell the user the path after updating it.

## Hint ladder (use in order; don't skip levels unprompted)

1. **Question**: "What is your opponent threatening? Which of your pieces is least active?"
2. **Theme**: "There is a tactic here involving a pin / back rank / overloaded defender."
3. **Area**: point at squares with `show --squares ... --out analysis.png` (no arrows).
4. **Candidate**: name the piece or the first move of the line.
5. **Reveal**: the full move and line from `eval`, with the reason it works.

## Evaluation reference

- Scores: `+0.35` is a small White edge; roughly ±0.3 equal, ±1 clear advantage, ±3 winning. `#N` is forced mate.
- `review`/`analyze` thresholds are centipawn loss for the side that moved, so they are fair for both colours. ACPL (average centipawn loss, each move capped at 1000) under ~30 is strong, 30-60 solid, over ~100 means several big errors. Depth-14 evals are noisy in murky positions: re-check critical moments with `eval --fen ... --depth 20 --multipv 3` before telling the user they erred.
- Engine time: 0.5 s per move is plenty for play; use `--depth 18+` for quizzes and critical moments.
- Prefer MultiPV in quizzes: a unique best move makes a good quiz; several near-equal moves mean accept any of them.
- Be honest about strength: a limited-Elo engine still plays "engine-like" (it can drop a piece, then play a perfect tactic).

## Direct python-chess use (ad-hoc checks only)

For one-off questions that don't change the game (e.g. "is this a legal castle?"), run `<python> -I -c "..."` (the interpreter that has `chess` installed) or a scratch script. Key API: `chess.Board(fen)`, `board.parse_san(s)` (raises `IllegalMoveError`/`AmbiguousMoveError`, both `ValueError`s), `board.san(move)` (call **before** `push`), `board.legal_moves`, `board.is_game_over(claim_draw=True)`, `board.outcome()`, `board.variation_san(pv)`, `board.set_epd(line)`, and `chess.engine.SimpleEngine.popen_uci(path)` as a context manager. For any change to the *game*, go through `chess_ops.py` so the PNG stays in sync.

## Troubleshooting

- `ERROR: Stockfish path not set or not found`: re-run `setup --stockfish <full path to .exe>`; quote paths with spaces.
- `WARNING: resvg-py missing, wrote SVG instead`: `<python> -m pip install resvg-py`. Don't switch to `cairosvg` (needs the Cairo DLL, absent on typical Windows installs).
- `python-chess is not installed` (exit code 3): run the pip command the script prints, or use a venv (see Setup).
- Python launches the Microsoft Store: use `py -3` or a real interpreter, not the Store stub.
- Image looks stale: run `show` to re-render; confirm the user is viewing `chess_data/current_position.png`, not `analysis.png`.
- Move rejected: read the legal-move list in the error; usual causes are a missing capture `x`, wrong piece letter, or an unnoticed check.
