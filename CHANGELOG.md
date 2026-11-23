# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-11-23

First release.

### Added
- **`/init-chess`**: scans a directory for the player's games folder and books (read-only), reads every PGN to
  build a player profile (results by colour and time control, header ratings, openings with weak and strong
  ones, how games end, plus a Stockfish sample of recent games: ACPL by phase, error rates, failed
  conversions, escapes, costliest mistakes), catalogues the player's books and resources with levels and
  chapters, and writes a personalised training plan with evidence-based priorities, measurable targets and a
  four-week schedule. Initialises `progress.md` and a baseline for game-to-game comparisons.
- **`/teach-chess`**: Socratic lessons from a book or study file the user picks. Each subskill runs as four
  phases (explain the concept, show 1-3 examples, quiz with 4-8 puzzles, reflect), then comes back
  later as an unannounced surprise re-quiz on a spaced schedule (1, 3, 7, 21 days). Includes a
  placement diagnostic for new topics and a 0-5 skill map with strictly earned levels.
- **`/play-chess`**: instructive game against Stockfish with Claude as the coach. Reviews every move before
  the engine replies, hints without giving the answer (hint ladder), offers take-backs, and reminds the
  user of their recurring weaknesses in context.
- **`/analyze-chess`**: Stockfish pass over a whole game (per-move verdicts, ACPL per side and phase, critical
  moments, strengths, missed chances, comparison with the last analysed game), followed by a Socratic
  move-by-move walkthrough that ties mistakes to the student's known strengths and weaknesses and ends
  with concrete improvements. A "quick" mode gives the report only.
- **`progress.md`**: a readable record of the student's strengths, weaknesses, estimated puzzle rating,
  skill map, review queue, personal pre-move checklist and history, shared by all four commands.
- **`chess_ops.py`**: single helper CLI (`setup new move engine show eval review analyze history discover
  profile undo pick library log stats`) around python-chess and Stockfish. Renders the board as a PNG after every
  move, rates moves by centipawn loss, and estimates a puzzle rating from logged results.
- Packaged both as a **Claude Code plugin** (`.claude-plugin/`) and as plain skill folders that can be
  copied into a project's `.claude/skills/`.
- Dependencies pinned: `chess==1.11.2`, `resvg-py==0.5.0`.
- Stockfish is found on `PATH` automatically; the script prints the exact install command when its
  Python packages are missing.
- Licensed under GPL-3.0-or-later.
- GitHub Actions CI (tests on Ubuntu, Windows and macOS with Python 3.10 and 3.13; real-Stockfish integration tests;
  plugin validation), a tag-driven release workflow that verifies tag, manifests and changelog before publishing a
  GitHub Release with a skills bundle, and Dependabot for actions and pinned dependencies.
- pytest suite of about 360 tests (unit, component with a stub engine, integration against a real Stockfish, and
  contract tests that keep the skills, manifests, README and CLI consistent); about 99% line coverage of
  `chess_ops.py` before counting the real-engine tests.

### Known limitations
- Requires Python 3.10 or newer (the pinned PNG renderer `resvg-py` does not support 3.9).
- Tested end to end on Windows with Stockfish 19. The skills' conversational flows (especially
  `/teach-chess` on a real book PDF) have had limited real-session testing.
- Stockfish's Elo limiter does not go below 1320.

[0.1.0]: https://github.com/RollingTank/chess-mentor/releases/tag/v0.1.0
