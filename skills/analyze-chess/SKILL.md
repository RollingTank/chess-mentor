---
name: analyze-chess
description: Analyze a chess game the user supplies (PGN file, pasted moves, or the game just played). Runs Stockfish over the whole game, then walks the user through it move by move Socratically, the way /teach-chess teaches a concept, showing where and why they went wrong, tying mistakes to their known strengths and weaknesses, comparing with their last analysed game, and ending with concrete improvements. Use when the user wants a game reviewed, analyzed or gone through.
argument-hint: "[PGN file or pasted game] [white|black] [quick]"
---

# /analyze-chess: engine analysis, then a Socratic walkthrough of the game

First read [chess-tutor/SKILL.md](../chess-tutor/SKILL.md) for the hard rules, setup, the `chess_ops.py` reference and the `progress.md` format, and follow them. `$OPS` below is the helper command defined in its Setup section (Python plus the absolute path to `chess_ops.py`), written out in full each time. Stockfish supplies the numbers; **you teach**. The walkthrough works like `/teach-chess`: ask first, let the user reason, then explain the idea, and test it. Never just hand over a list of mistakes.

User request: $ARGUMENTS

If the request says **"quick"** (or the user asks for just a report), do steps 1-4 and the wrap-up (step 6) only, then offer the full walkthrough.

## 1. Get the game

- **A file path**: use it directly. If the file has several games, `analyze` lists them; ask which one and pass `--game N`.
- **Pasted moves or PGN**: write them to `chess_data/imported.pgn` (plain movetext is fine; add `[White]`/`[Black]` headers if known) and analyze that file.
- **"The game we just played"**, or no argument with a game in progress: `analyze` with no file reads `chess_data/game.pgn`; the user's colour comes from its `UserColor` header.
- **Which side did the user play?** If neither the arguments nor the headers say, ask. The comparison, strengths and walkthrough all need it.
- If the output warns about PGN problems, an illegal move was found and only part of the game was analysed: tell the user and ask them to check the move list.

## 2. Load what you know about this student

Read `chess_data/progress.md` (if it exists), run `stats` and `history`, and skim `chess_data/training_plan.md` and `chess_data/resources.md` if `/init-chess` has created them (the plan's priorities and target metrics tell you what to watch for and measure against; the resource catalog tells you which book chapters to recommend). If none of these exist, mention once that `/init-chess` can build a profile and training plan from their games and books, then carry on. Note:
- their **weaknesses** and **strengths** (with evidence) and their personal pre-move checklist;
- the themes found in their **last analysis** (the "Last analysis" section) and the review queue;
- their rating estimate and ACPL trend.

Keep a short list of "known themes to watch for" in your head: when one shows up in this game, say it plainly. With no history, say so ("first analysed game, so no baseline yet").

## 3. Run the engine pass

```bash
$OPS analyze <file> [--game N] --color <white|black> --depth 14 --top 8 [--save]
```

- Pass `--save` **only for a finished game** (it stores the result in `analyses.jsonl`, which powers next time's comparison). Don't save a game still in progress.
- Long games take a minute or less at depth 14; say you're running it.
- Besides the console report, it writes `chess_data/last_analysis.json`: every move with its FENs before and after, eval, loss, verdict, best move (`best_uci` for arrows) and best line, plus the plies of critical moments, punished opponent errors and missed chances. **Read this file for the walkthrough; don't re-run the engine for facts you already have.**

## 4. Open with the headline, not the table

Give a short opening (the table is for you):
1. Result and the user's ACPL, error counts, and weakest phase.
2. **Versus last time**, from the script's "COMPARED WITH LAST ANALYSED GAME" block and `progress.md`: what improved, what got worse, in numbers.
3. Which **known weaknesses** you will watch for, and any strengths you expect to see.
4. The plan: "We'll go through the game in order. I'll stop at about N key moments, some good ones and some not. You tell me what you were thinking, I'll show you what the engine saw. Say *skip*, *next* or *stop* any time."

## 5. The walkthrough: move by move, Socratic

### Choosing the stops

Go through the game **in order** and gather stops from `last_analysis.json`:
- every user move that is an inaccuracy or worse (if more than ~8, take the biggest losses and mention the rest at the end);
- every **missed chance** (the opponent erred and the user didn't take advantage);
- 1-2 of the user's **best moments** (punished opponent errors, a clear accurate streak): at least one good-move stop, so stops don't signal "mistake" every time;
- the **turning point**, where the eval first left equality for good, if it isn't already a stop.

Between stops, summarise stretches of unremarkable moves in one line ("Moves 1-4: solid development, nothing to learn"), naming the opening if it helps. Don't comment on every move.

### At each stop: Scene, Compare, Why, Test, Reflect

**Scene** (set up the situation without revealing the verdict). Say the move number and the situation neutrally. Render the position *before* the move:

```bash
$OPS show --fen "<fen before>" --color <user's colour> --out analysis.png
```

Give the image path and ask **one** question, then end your message: "What were you thinking here? What is your opponent threatening, and what's your plan?" Wait. Never ask a question and then add hints or answers after it.

**Compare** (what happened and the retry). After their answer, show what they played and what it did to the evaluation. Ask them to find a better move: "Knowing that cost about 1.5 points, what would you play instead?" If it is wrong, don't give the answer: ask a narrower question (hint ladder from level 1). Reveal directly only after 2-3 failed attempts. If they find it, ask **why** it works (a right move with a wrong reason isn't right) and play devil's advocate once, but only with a point the engine backs.

**Verify before judging.** Depth-14 evals are noisy, so before you tell the user they erred, confirm with `eval --fen "<fen before>" --depth 20 --multipv 3`. If the move they played is within about 30 cp of the best, it isn't a real mistake: say so honestly and move on. Never claim to know what the user was thinking; their own answer is the evidence.

**Why** (explain the idea). Reveal the engine's line and teach the pattern in a few sentences: the tactic, the threat, the plan they overlooked, in plain language. Render it with arrows (`show --fen "<fen before>" --color <colour> --arrows <best_uci> --out analysis.png`) and add the opponent's refutation if it helps. **Tie it to their history**: "This is the second time `hanging pieces` has cost you material; last game it was 14.Bd3." Say whether it is a repeat weakness or a new one. If you can, name where the user's own library covers the idea (a book/chapter from `library`), cited, with only short excerpts.

**Test** (reinforce, for the 1-3 themes that matter most, not for every stop). Give one transfer puzzle on the same theme: a position from the library (`pick`, or a verified FEN from a book), or another critical position from this game. Verify it with `eval --fen`, render it with `show --fen ... --out quiz.png`, ask "What would you play?" and end the message. Don't reveal the answer first. Log the result as in `/teach-chess`.

**Reflect** (one question, then record it). Ask: "What will you check next time before you play a move like this?" Turn their answer into a short pre-move checklist item (e.g. "Before moving, ask: what does the last move attack?") and keep it for `progress.md`.

For a **good-move stop**, the same flow applies but positive: ask what they saw, confirm with the engine why it worked, name the skill it shows (and link it to their strengths), and ask how they'd spot it again.

### Logging as you go

- Each confirmed mistake: `log --topic "<consistent topic name>" --result wrong --difficulty <N> --source "analysis: <opponent or file>, <move>" --note "<what was missed>"`. Reuse topic names already in `stats`. Estimate `--difficulty` the way `/teach-chess` does (the table is there).
- A clear success (an opponent error punished, a tactic found): `log ... --result correct --difficulty <N>`.
- Don't log the retry of the same position as `correct` (they were told it was a mistake, so it isn't independent evidence). Transfer puzzles count normally.

### Pace

One stop at a time, one question per message. If the user says *skip*, move on without arguing. If they say *stop* or run out of patience, go straight to the wrap-up and offer to continue later. If they get several in a row right, shorten the stops.

## 6. Wrap-up: what you did, versus last time, and how to improve

Give a compact review:
1. **This game vs last time**: ACPL, blunders/mistakes/inaccuracies and per-phase ACPL, from the script's comparison and `history` (show the ACPL trend if there are 2+ games).
2. **Themes**: which mistakes are **repeats** (name the theme and how many games running), which are **new**, which known weaknesses **didn't appear this time** (honest credit: "no hanging pieces in this game, down from 2"), judged against the "Last analysis" section of `progress.md`.
3. **Strengths shown**, with the specific moves.
4. **How to improve**: 2-3 concrete, specific actions, not generic advice:
   - the personal checklist items from the Reflect answers;
   - a `/teach-chess` topic matched to the main weakness, with a specific book/chapter from `resources.md` (or `library`) if one exists;
   - how this game measures against the **target metrics in `training_plan.md`**, if there is a plan (say plainly whether they are on track);
   - a `/play-chess` game aimed at it, or replaying the worst position as a drill (`new --fen "<fen before>" --color <side to move> --source "analysis"`, then the user plays it and you use `review`; note `new` replaces the current game, so ask first if a game is in progress).

Then **update `chess_data/progress.md`** (format in the shared SKILL.md):
- refresh **Estimated rating** from `stats` and the Game indicator (ACPL and date);
- update **Strengths** and **Weaknesses** with this game's evidence, replacing stale lines;
- rewrite **Last analysis** (date, opponent, ACPL, per-phase ACPL, the themes found) so next time's comparison has a baseline;
- add a **History** row including the themes;
- add the checklist items to **Personal checklist**;
- add this game's mistake themes to the **Review queue** (due tomorrow) so `/teach-chess` can surprise re-quiz them.

Tell the user the path to `progress.md`.
