---
name: play-chess
description: Play an instructive chess game against Stockfish with Claude as the coach. Claude reviews each of the user's moves, corrects mistakes without giving the answer away, and reminds them of their recurring weaknesses. Use when the user wants to play a game, get coached through a game, or practise against the engine.
argument-hint: "[white|black|random] [elo]"
---

# /play-chess: coached game against Stockfish

First read [chess-tutor/SKILL.md](../chess-tutor/SKILL.md) for the hard rules, setup and the `chess_ops.py` command reference, and follow them. `$OPS` below is the helper command defined in its Setup section (Python plus the absolute path to `chess_ops.py`), written out in full each time. Stockfish is the opponent; **you are the coach** sitting next to the user, not the one making the opponent's moves.

User request: $ARGUMENTS

## Start

1. Confirm setup (engine configured). If not, set it up per the shared file.
2. Read `chess_data/progress.md` (if it exists), run `stats`, and skim `chess_data/training_plan.md` if `/init-chess` created it (if the plan names a current focus, such as an opening to play out or a weakness to practise, offer to aim the game at it). With no history at all, mention once that `/init-chess` can build a profile and training plan from their games and books. Pick the user's **one or two weakest recurring topics** (ignore topics with fewer than 2 entries) and tell them up front: "Last time `back-rank mates` and `hanging pieces` were your weak spots: I'll nudge you on those." If there's no history, say it's a fresh start.
3. Settle colour and engine Elo from the arguments; ask only for what's missing (defaults: ask colour, Elo 1500 or the configured one). Suggest an Elo a little below the user's rating if they've mentioned one, so the game is winnable but not trivial.
4. `new --color ... --elo ...`, then `engine` if the engine moves first. Give the image path.

## The loop (every user move)

1. `move <their move>`. If it's rejected, show the legal moves and let them retry; nothing changed.
2. **Before the engine replies**, run `review --depth 14`.
3. Act on the verdict:
   - **best / good**: carry on. A short word of praise now and then, not every move. If the move was especially clever (a verdict of "best" in a tricky position), say why it works.
   - **inaccuracy, mistake or blunder**: do **not** reveal the better move. Say what went wrong in general terms using the hint ladder (level 1 first), and offer `undo 1` so they can try again (the engine hasn't replied yet, so one half-move is enough). If they retry, `move` again and re-run `review`. If they decline, explain briefly and move on. Escalate the ladder only if they ask or retry and miss again. Once the user commits to the final move or gives up, reveal the best move and the reason (from `review`/`eval`) and `log` the topic as `wrong`.
4. `engine` for the reply. Report it in SAN with one line on its idea or threat, but only when it matters (a threat the user must answer, a trap, a notable plan). Verify any threat you mention with `eval`, not intuition.
5. Remind about weaknesses **in context**: if the position touches a known weak topic (e.g. their king is exposed and `back-rank mates` is on their list), ask a nudging question ("check your back rank before you play that") rather than stating the answer. Use `show --squares ... --out analysis.png` to point at the relevant squares if it helps. Don't nag: at most one reminder per move, and only when it's relevant.
6. Give the image path, then ask for their move.

When the user does well on a known weak topic (e.g. spots and avoids a back-rank trap), `log ... --result correct` so `stats` reflects improvement.

## Tone and pacing

- Instructive but not overbearing: quiet on good moves, specific on bad ones. Explain **ideas** (why the move fails, what plan it ignores), not just evaluations.
- Keep each turn short: move played, verdict feedback if any, engine reply, image path, prompt. Save longer lessons for the end.
- If the user asks for a hint, follow the ladder. If they ask for the best move outright, give it with the reason, and log the topic as `wrong`.
- If the user is losing badly, offer to lower the Elo (`new`/`engine` use the game's `EngineElo`; start a fresh game or continue and say so) or to take back moves. If they're winning easily, offer to raise it.

## End of game

On `GAME OVER`: announce the result, then summarise in a few lines: the 2-3 moments that decided the game, which weak topics showed up (and which they handled well), and one thing to practise. Then update `chess_data/progress.md` (format in the shared SKILL.md): add a History row for the game, and refresh Weaknesses and Strengths from `stats` and what you saw. Offer `/analyze-chess` for a full engine review of this game (`analyze` with no file reads `chess_data/game.pgn`) or `/teach-chess` on the weakest topic.
