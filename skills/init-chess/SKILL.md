---
name: init-chess
description: Get started with the chess mentor by scanning the user's own files. Finds their games folder, reads every PGN to build a player profile (results, openings, ratings, time controls, plus a Stockfish sample of recent games), goes through their chess books and resources, and writes a personalised training plan. Use first, or when the user wants to build or refresh their profile, or asks for a training plan based on their games and books.
argument-hint: "[directory to search] [player name]"
---

# /init-chess: build the player profile and a training plan

First read [chess-tutor/SKILL.md](../chess-tutor/SKILL.md) for the hard rules, setup, the `chess_ops.py` reference and the `progress.md` format, and follow them. `$OPS` below is the helper command defined in its Setup section (Python plus the absolute path to `chess_ops.py`), written out in full each time.

This command is **read-only on the user's files**: it only reads their games and books, and writes everything it produces into the data directory (`chess_data/`). Never modify, move or delete their PGNs or books, and never copy them elsewhere.

**File scope (hard boundary).** Search only the directory the user named, or the session's current directory if they named none. If that finds no games or no books, **stop and ask them for the path**: never look through their home folder, Desktop or Documents, never run `find`/`ls` over parent directories, and never point `discover` at any other location on your own initiative, even if it seems likely that their files are somewhere else. If you cannot ask (a non-interactive run), finish with a short "nothing found in <directory>; tell me where your games and books are" report instead of improvising. Likewise never invent the user's goals or available time: if you couldn't ask and weren't told, write the plan with clearly marked assumptions.

Run `$OPS` from the session's working directory (do not `cd` to the plugin folder), so `chess_data/` is created in the user's project. Their content stays on their machine; paraphrase books and quote only short excerpts.

User request: $ARGUMENTS

You produce, in order: a **player profile** (from their games), a **resource catalog** (from their books and files), and a **training plan** built from both. Everything you tell the user must come from the data, not from a guess.

## 1. Check setup

Confirm Python, the dependencies and the engine as the shared Setup section describes. Stockfish is needed for the engine sample of recent games. If it isn't available, say the profile will be statistics-only (results, openings, ratings) and offer to continue anyway.

## 2. Find the files

```bash
$OPS discover [<directory from the request, default: the current directory>]
```

It searches the directory tree (read-only, skipping `.venv`, `.git`, `chess_data`, `stockfish` and similar) and lists:
- **PGN folders**, with file and game counts and a note when the folder name suggests the player's own games;
- **books and study resources** (PDF, EPUB, MOBI, DJVU, EPD, and notes in chess-looking folders).

Then decide which folder holds **the user's own games**:
- One clear candidate (a "games" folder, or the only PGN folder): use it and say so.
- Several candidates, or none with a name hint: **ask which folder is theirs.** A masters or opening-study PGN collection is *not* the player's own games, so don't mix them in.
- No PGN found at all: say so. Offer to continue with their books only (the plan will rest on a placement check instead of results), or ask them to export their games (Lichess: *Export games* on their profile; Chess.com: *Archive* then *Download*) and re-run. Don't search anywhere else unless they tell you where (see the file-scope rule above).

## 3. Build the profile from their games

```bash
$OPS profile "<games folder>" [--player "<name or comma-separated usernames>"] --engine-games 8 --depth 12
```

- It reads every PGN under the folder, de-duplicates games, and finds the player as the name that appears in most games. If it says it **can't tell which player is the user**, show the names it listed and ask for their username(s) (several accounts: comma-separate), then re-run with `--player`.
- Tell the user the engine sample takes a minute or two (it runs Stockfish over their most recent games). For a large archive use `--engine-games 12` or more if they're patient; `--engine-games 0` skips the engine.
- It writes `chess_data/profile.json` and prints a summary. It also records the sampled games in the analysis history, so a later `/analyze-chess` has a baseline to compare with. A previous profile is kept as `profile.prev.json`: on a refresh, compare the two and say what changed.

**Read `profile.json`** (the printed summary is only part of it) and extract the facts. Look for these patterns and report only those the numbers support, each with its numbers:

| Pattern | Evidence in `profile.json` |
|---|---|
| Colour gap | `as_white` vs `as_black` score differs by about 10+ points |
| Rating level and trend | `rating`: recent average vs previous average, peak, opponent average |
| Time-control mismatch | `time_controls`: a class with a much lower score or many games |
| Clock trouble | `endings.losses_on_time` as a share of `losses` (about 25%+ is notable) |
| Early collapse | `short_losses_under_25_moves`, and `engine_sample.avg_first_error_move` (low means opening gaps) |
| Repertoire | `openings`: scattered (the top opening covers well under a third of games) or concentrated; `weak_openings` (5+ games, under 40%) and `strong_openings` |
| Weakest phase | `engine_sample.phase_acpl`: the highest ACPL phase |
| Technique and resilience | `failed_conversions` (had +3 or better and didn't win) vs `escapes` (was -3 or worse and didn't lose) |
| Error load | `engine_sample.per_game_avg` blunders and mistakes per game |
| Form | `recent_20` vs `overall` |

**Be honest about sample size.** The statistics cover all N games; the engine findings cover only the sampled M games ("indicative, not conclusive"). The header rating is a *game rating from the PGNs*, not an official one; if the headers have no ratings, say it's unknown and ask the user for a rough estimate. Don't invent rating numbers.

**Turn the engine sample into weakness themes.** Take up to 8 of `engine_sample.worst_moments` from different games. For each: confirm it with `$OPS eval --fen "<fen>" --depth 18 --multipv 2` (drop it if the played move is within about 30 cp of the best), look at the position (`show --fen ... --out init.png` if you need to see it), and name the theme with a **consistent short topic name** (reuse names from `stats`; otherwise e.g. `hanging pieces`, `missed tactics`, `back-rank mates`, `king safety`, `opening development`, `endgame technique`, `calculation`, `pawn structure`). Log each:

```bash
$OPS log --topic "<topic>" --result wrong --source "init: <date> vs <opponent>, <move>" --note "<what was missed>"
```

Do **not** pass `--difficulty` for these (they aren't puzzles, so they must not move the puzzle rating). Count the themes: the most frequent ones are the profile's headline weaknesses.

Also record **strengths**, with evidence: openings scoring 60%+ over 5+ games, the best colour, phases with the lowest ACPL, escapes, strong recent form.

## 4. Go through their books and resources

Build a catalog of what the user has, from the `discover` output. Be efficient: tell the user you're going through the books and how many.

- **PDF**: Read the first pages (`pages: "1-6"`) for the title, author and table of contents. Don't read whole books. If a PDF has no extractable text (scanned images), note it as "scanned: limited use" and move on.
- **EPUB / TXT / MD**: read the title and contents/headings with text tools.
- **PGN study files** (not the player's games): count games and note the `Event`/`White` headers to see what they cover (an opening, annotated games, endgame studies). **EPD files**: count the positions and sample a few to see the theme.
- Go in depth on up to about 10 resources, prioritised by relevance to the top weaknesses (judge from filenames first). List the rest by filename and say they weren't opened.

For each resource, record: title (and author if visible), path, type, **estimated level** (beginner / intermediate / advanced, labelled as your judgement from its contents), the topics it covers, **chapters with page numbers when you saw them in the contents page** (never guess page numbers or chapter titles), and which of the player's weaknesses or goals it addresses. Write this to **`chess_data/resources.md`** (a table or short entries). `/teach-chess` and `/analyze-chess` use it to point at specific chapters.

## 5. Ask about goals and time

If the request didn't already say, ask **briefly** (ideally one question prompt with 2-3 questions): their **goal** (a rating target, fixing a weakness, learning an opening system, general improvement), **time per week** (about 2 hours or less, 3-5 hours, 6 or more), and **what they enjoy** (more lessons from books, more games, more game reviews). If the headers had no rating, ask for a rough one. Their answers shape the plan; don't skip this.

## 6. Write the training plan

Write **`chess_data/training_plan.md`**. Base every recommendation on the profile, `stats`, and the catalog. Structure:

1. **Snapshot**: 4-6 lines of the key facts (games analysed and date range, record, rating, repertoire, weakest phase), with the sample-size caveat.
2. **Priorities** (3-5, ranked): for each, the **evidence** (the numbers), **why it matters** to their results, and a **target metric** that can be measured later (for example "middlegame ACPL from 74 to under 60 over the next 10 games", "score as Black from 38% to 50%", "no losses on time in the next 20 games").
3. **Four-week schedule**, shaped by their available time and preferences. Each session names the exact command and focus:
   - `/teach-chess "<book>" <topic or chapter>` (only chapters you saw in the catalog);
   - `/play-chess <colour> <elo>` with the weakness to practise, or a specific opening position to play out;
   - `/analyze-chess <file>` on their newest games (aim for about one per week).
   Keep the load realistic for the hours they gave, and put the highest-impact priority first.
4. **Repertoire advice** (only if the data shows a repertoire problem): which openings to keep, which to drop or fix, with their scores.
5. **Resource map**: which of their books serves which priority, with chapters/pages from the catalog. If they have nothing for a priority, say so plainly and describe what kind of material would help (clearly marked as *not in your library*; don't present a guessed chapter as if it were in a book they own).
6. **Checkpoints**: when to measure progress (after about 20 new games, or four weeks): `history` and `/analyze-chess` give ACPL and error trends; re-running `/init-chess` refreshes the profile and compares with this one.
7. **What I couldn't tell**: gaps in the data (no games as Black, no ratings in the headers, scanned books, a small engine sample).

Keep it practical and short enough to follow: a plan the user will read beats a thorough one they won't.

## 7. Initialise `progress.md`

Create or update `chess_data/progress.md` in the format from the shared SKILL.md, so every other mode starts from this profile:
- **Player profile**: games analysed, date range, record, colour split, time controls, repertoire summary, the header rating (labelled as such).
- **Estimated rating**: the game rating from the headers; the puzzle rating says "not enough data yet" (it fills in as they do quizzes).
- **Game indicator**: the sample's ACPL (with its phase split and the number of games).
- **Strengths** and **Weaknesses (worst first)**, each with its evidence.
- **Last analysis**: the baseline from this scan (what it covered, ACPL, themes found).
- **History**: a row for this scan.

If `progress.md` already exists (a refresh), **merge**: keep the skill map, review queue and personal checklist, and update the profile, rating, strengths and weaknesses, replacing stale lines.

## 8. Wrap up

Reply with a short summary (not the documents): the 3-5 findings that matter most, the top priorities, and the **one command to run first** (for example `/teach-chess "<book>" <topic>`). Give the paths to `training_plan.md`, `resources.md` and `progress.md`, and remind them `chess_data/` holds their personal data and shouldn't be committed to git. Offer to adjust the plan if their goals or time change.
