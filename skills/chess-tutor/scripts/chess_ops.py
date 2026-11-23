#!/usr/bin/env python3
# Chess Mentor: chess_ops.py
# Copyright (C) 2026 Chess Mentor contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# This program is free software: you can redistribute it and/or modify it under the terms of
# the GNU General Public License as published by the Free Software Foundation, either version 3
# of the License, or (at your option) any later version. See the LICENSE file in the repository.
"""Chess tutor helper: one CLI around python-chess + Stockfish.

Every command that changes the position (new, move, engine, undo) re-renders
<data_dir>/current_position.png, so the image on disk always matches the game.

Run it with any Python 3.10+ that has the packages from ../requirements.txt, e.g.
    python3 chess_ops.py move e4
State lives in <data_dir> (default ./chess_data, or $CHESS_DATA_DIR): config.json,
game.pgn, current_position.png, progress.jsonl, last_analysis.json, analyses.jsonl.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import random
import re
import shutil
import sys
from collections import Counter
from pathlib import Path

try:
    import chess
    import chess.engine
    import chess.pgn
    import chess.svg
except ImportError:
    _req = Path(__file__).resolve().parent.parent / "requirements.txt"
    print(f"ERROR: python-chess is not installed for this Python ({sys.executable}).\n"
          f"Install the dependencies with:\n  \"{sys.executable}\" -m pip install -r \"{_req}\"\n"
          "If pip refuses because the environment is externally managed, create a virtual environment "
          "(python3 -m venv <dir>), install into it, and run this script with <dir>/bin/python "
          "(Windows: <dir>\\Scripts\\python.exe).", file=sys.stderr)
    sys.exit(3)

DATA = Path(os.environ.get("CHESS_DATA_DIR", "chess_data"))
CONFIG = DATA / "config.json"
GAME = DATA / "game.pgn"
IMAGE = DATA / "current_position.png"
PROGRESS = DATA / "progress.jsonl"
DEFAULTS = {"stockfish": None, "library": None, "elo": 1500}


# ---------------------------------------------------------------- config / io
def load_config(use_env=True):
    """Saved config plus defaults; $STOCKFISH_PATH overrides the engine path unless use_env=False."""
    cfg = dict(DEFAULTS)
    if CONFIG.exists():
        try:
            cfg.update(json.loads(CONFIG.read_text(encoding="utf-8")))
        except ValueError:
            die(f"{CONFIG} is not valid JSON. Delete it and re-run: chess_ops.py setup")
    if use_env and os.environ.get("STOCKFISH_PATH"):
        cfg["stockfish"] = os.environ["STOCKFISH_PATH"]
    return cfg


def save_config(cfg):
    DATA.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def die(msg, code=2):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def write_atomic(path, data: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    try:
        os.replace(tmp, path)
    except PermissionError:  # viewer holds the file open on Windows
        path.write_bytes(data)
        tmp.unlink(missing_ok=True)


def out_path(text):
    """A bare filename (analysis.png) goes into the data dir; anything with a directory part is used as given."""
    p = Path(text)
    return p if p.parent != Path(".") else DATA / p


def find_stockfish(cfg):
    """Configured path, else a `stockfish` executable on PATH (no disk searching), else None."""
    path = cfg.get("stockfish")
    if path and Path(path).exists():
        return path
    return shutil.which("stockfish")


def open_engine():
    path = find_stockfish(load_config())
    if not path:
        die("Stockfish not found. Install it (https://stockfishchess.org/download/) and run: "
            "chess_ops.py setup --stockfish <full path to the executable>")
    return chess.engine.SimpleEngine.popen_uci(path)


# ---------------------------------------------------------------- game state
def load_game():
    if not GAME.exists():
        die("No game in progress. Run: chess_ops.py new")
    with open(GAME, encoding="utf-8") as f:
        game = chess.pgn.read_game(f)
    if game is None:
        die(f"{GAME} is empty or unreadable. Start a new game with: chess_ops.py new")
    board = game.board()
    for mv in game.mainline_moves():
        board.push(mv)
    return game.headers, board


def parse_fen(text):
    """A Board from FEN, or a clean error instead of a traceback."""
    try:
        return chess.Board(text)
    except ValueError as e:
        die(f"Invalid FEN {text!r}: {e}")


def parse_sq(text):
    try:
        return chess.parse_square(text)
    except ValueError:
        die(f"Invalid square {text!r}; use names like e4")


def user_color(headers):
    return chess.BLACK if headers.get("UserColor", "white") == "black" else chess.WHITE


def render(board, flipped=False, path=IMAGE, arrows=(), squares=None, size=640):
    """Write a PNG of the board. Last move and check are highlighted."""
    svg = chess.svg.board(
        board,
        lastmove=board.peek() if board.move_stack else None,
        check=board.king(board.turn) if board.is_check() else None,
        flipped=flipped,
        arrows=list(arrows),
        fill=squares or {},
        size=size,
    )
    try:
        import resvg_py
    except ImportError:
        # Fallback keeps the game usable; tell the user to install resvg-py for PNG.
        svg_path = path.with_suffix(".svg")
        write_atomic(svg_path, svg.encode("utf-8"))
        print(f"WARNING: resvg-py missing, wrote SVG instead: {svg_path}", file=sys.stderr)
        return svg_path
    write_atomic(path, bytes(resvg_py.svg_to_bytes(svg_string=svg)))
    return path


def commit(headers, board, note=""):
    """Persist the game to PGN AND refresh current_position.png. Call after every change."""
    game = chess.pgn.Game.from_board(board)
    for k, v in headers.items():
        if k not in ("FEN", "SetUp"):  # from_board sets these itself
            game.headers[k] = v
    game.headers["Result"] = board.result(claim_draw=True) if board.is_game_over(claim_draw=True) else "*"
    GAME.parent.mkdir(parents=True, exist_ok=True)
    with open(GAME, "w", encoding="utf-8") as f:
        print(game, file=f, end="\n\n")
    img = render(board, flipped=user_color(headers) == chess.BLACK)
    status(board, img, note)


def status(board, img, note=""):
    if note:
        print(note)
    san_list = []
    replay = chess.Board(board.root().fen())
    for mv in board.move_stack:
        san_list.append(replay.san(mv))
        replay.push(mv)
    start = board.root().fullmove_number
    pairs, i = [], 0
    if board.root().turn == chess.BLACK and san_list:
        pairs.append(f"{start}... {san_list[0]}")
        i = 1
    n = start + (1 if board.root().turn == chess.BLACK else 0)
    while i < len(san_list):
        pairs.append(f"{n}. {san_list[i]}" + (f" {san_list[i+1]}" if i + 1 < len(san_list) else ""))
        i += 2
        n += 1
    print("Moves:", " ".join(pairs[-8:]) or "(none)")
    print("FEN:", board.fen())
    print("To move:", "White" if board.turn else "Black")
    if board.is_check():
        print("CHECK")
    if board.is_game_over(claim_draw=True):
        o = board.outcome(claim_draw=True)
        print(f"GAME OVER: {board.result(claim_draw=True)} ({o.termination.name})")
    print("Image:", img.resolve())


def parse_move(board, text):
    """Accept SAN, UCI, and sloppy typing: 0-0 / o-o, lowercase piece letters (nf3)."""
    text = text.strip()
    candidates = [text]
    if text.lower() in ("o-o", "0-0", "o-o-o", "0-0-0"):
        candidates.append(text.lower().replace("0", "O").replace("o", "O"))
    if text and text[0] in "nbrqk":  # tried after the literal text so pawn moves like bxc4 still win
        candidates.append(text[0].upper() + text[1:])
    for cand in candidates:
        try:
            return board.parse_san(cand)
        except ValueError:
            pass
    try:
        return board.parse_uci(text.lower())
    except ValueError:
        legal = ", ".join(board.san(m) for m in board.legal_moves)
        die(f"'{text}' is not a legal move here. Legal moves: {legal}")


# ---------------------------------------------------------------- evaluation
def fmt_score(score):
    s = score.white()
    if s.is_mate():
        return f"#{s.mate()}"
    return f"{s.score() / 100:+.2f}"


def cp(info, pov):
    return info["score"].pov(pov).score(mate_score=10000)


def limit(args):
    return chess.engine.Limit(depth=args.depth) if args.depth else chess.engine.Limit(time=args.time)


def classify(loss):
    if loss <= 10:
        return "excellent"
    if loss < 50:
        return "good"
    if loss < 100:
        return "inaccuracy"
    if loss < 200:
        return "mistake"
    return "blunder"


# ---------------------------------------------------------------- commands
def cmd_setup(a):
    cfg = load_config(use_env=False)          # a temporary $STOCKFISH_PATH must not be written into the saved config
    if a.stockfish:
        cfg["stockfish"] = a.stockfish
    if a.library:
        cfg["library"] = a.library
    if a.elo:
        cfg["elo"] = a.elo
    saved_ok = bool(cfg["stockfish"] and Path(cfg["stockfish"]).exists())
    if not saved_ok and not os.environ.get("STOCKFISH_PATH"):
        found = shutil.which("stockfish")
        if found:
            cfg["stockfish"] = found
            print("Found Stockfish on PATH:", found)
    save_config(cfg)
    cfg = load_config()                        # effective settings (env override applied) for the checks below
    print("Python", sys.version.split()[0], "| chess", chess.__version__)
    print("Data directory:", DATA.resolve())
    try:
        import resvg_py  # noqa: F401
        print("resvg-py OK (PNG rendering available)")
    except ImportError:
        print(f"resvg-py MISSING: \"{sys.executable}\" -m pip install resvg-py")
    if cfg["stockfish"] and Path(cfg["stockfish"]).exists():
        with open_engine() as eng:
            print("Engine OK:", eng.id.get("name"))
            for o in ("UCI_LimitStrength", "UCI_Elo", "Skill Level"):
                opt = eng.options.get(o)
                if opt:
                    rng = f" [{opt.min}-{opt.max}]" if opt.min is not None else ""
                    print(f"  option {o}{rng}")
    else:
        print("Engine NOT configured. Re-run with --stockfish <path>")
    print("Config:", json.dumps(cfg))


def cmd_new(a):
    cfg = load_config()
    board = parse_fen(a.fen) if a.fen else chess.Board()
    color = a.color if a.color != "random" else random.choice(["white", "black"])
    headers = chess.pgn.Headers()
    headers["Event"] = "Chess tutor game"
    headers["Date"] = dt.date.today().strftime("%Y.%m.%d")
    headers["UserColor"] = color
    headers["EngineElo"] = str(a.elo or cfg["elo"])
    headers["White"] = "User" if color == "white" else "Stockfish"
    headers["Black"] = "User" if color == "black" else "Stockfish"
    if a.source:
        headers["Source"] = a.source
    commit(headers, board, f"New game. You play {color}.")
    if board.turn != user_color(headers):
        print("Engine moves first: run `engine`.")


def cmd_move(a):
    headers, board = load_game()
    if board.is_game_over(claim_draw=True):
        die("Game is over. Start a new one.")
    mv = parse_move(board, a.move)
    san = board.san(mv)
    board.push(mv)
    commit(headers, board, f"Played: {san}")


def cmd_engine(a):
    headers, board = load_game()
    if board.is_game_over(claim_draw=True):
        die("Game is over.")
    elo = int(headers.get("EngineElo", load_config()["elo"]))
    with open_engine() as eng:
        opts = eng.options
        if "UCI_LimitStrength" in opts and "UCI_Elo" in opts and not a.full:
            lo, hi = opts["UCI_Elo"].min, opts["UCI_Elo"].max
            eng.configure({"UCI_LimitStrength": True, "UCI_Elo": max(lo, min(hi, elo))})
            if not lo <= elo <= hi:
                print(f"NOTE: engine Elo {elo} is outside this Stockfish's range {lo}-{hi}; playing at {max(lo, min(hi, elo))}.")
        elif "Skill Level" in opts and not a.full:
            eng.configure({"Skill Level": max(0, min(20, (elo - 800) // 100))})
        res = eng.play(board, limit(a))
    san = board.san(res.move)
    board.push(res.move)
    commit(headers, board, f"Engine plays: {san}")


def cmd_show(a):
    arrows = [(parse_sq(s[:2]), parse_sq(s[2:4])) for s in (a.arrows or "").split(",") if s]
    squares = {parse_sq(s): "#ff000080" for s in (a.squares or "").split(",") if s}
    if a.fen:
        # State-free render of any position (analysis, teaching). Never touches game.pgn
        # or current_position.png unless --out points there.
        board = parse_fen(a.fen)
        flipped = a.color == "black"
        out = out_path(a.out) if a.out else DATA / "analysis.png"
    else:
        headers, board = load_game()
        flipped = user_color(headers) == chess.BLACK
        out = out_path(a.out) if a.out else IMAGE
    img = render(board, flipped, out, arrows, squares)
    status(board, img)


def cmd_eval(a):
    board = parse_fen(a.fen) if a.fen else load_game()[1]
    with open_engine() as eng:
        infos = eng.analyse(board, limit(a), multipv=a.multipv)
    print("Eval is from White's point of view (+ = good for White).")
    for i, info in enumerate(infos, 1):
        pv = info.get("pv", [])
        line = board.variation_san(pv[:8]) if pv else ""
        print(f"{i}. {fmt_score(info['score'])}  depth {info.get('depth')}  {line}")


def cmd_review(a):
    """Rate the last move by centipawn loss vs the engine's best move."""
    headers, board = load_game()
    if not board.move_stack:
        die("No moves yet.")
    prev = board.copy()
    mv = prev.pop()
    mover = prev.turn
    with open_engine() as eng:
        best = eng.analyse(prev, limit(a))
        best_move = best["pv"][0]
        best_san = prev.san(best_move)
        best_line = prev.variation_san(best["pv"][:6])
        played_san = prev.san(mv)
        prev.push(mv)
        after = eng.analyse(prev, limit(a))
    loss = max(0, cp(best, mover) - cp(after, mover))
    label = "best" if mv == best_move else classify(loss)
    print(f"Move: {played_san}  verdict: {label}  (loss ~{loss} cp)")
    print(f"Best was: {best_san}   line: {best_line}   eval {fmt_score(best['score'])}")


def pgn_offsets(p):
    """[(file offset, headers)] for every game in a PGN file, without parsing the moves."""
    offs = []
    with open(p, encoding="utf-8", errors="replace") as f:
        while True:
            off = f.tell()
            h = chess.pgn.read_headers(f)
            if h is None:
                break
            offs.append((off, h))
    return offs


def eval_position(eng, board, lim):
    """(white-POV centipawns, display string, engine info or None). Mate = +-10000."""
    if board.is_game_over():
        o = board.outcome()
        if o.winner is None:
            return 0, "draw", None
        return (10000, "1-0", None) if o.winner == chess.WHITE else (-10000, "0-1", None)
    info = eng.analyse(board, lim)
    return info["score"].white().score(mate_score=10000), fmt_score(info["score"]), info


ANALYSES = DATA / "analyses.jsonl"
LAST_ANALYSIS = DATA / "last_analysis.json"
PHASES = (("opening", 1, 10), ("middlegame", 11, 25), ("late", 26, 999))
FLAGGED = ("inaccuracy", "mistake", "blunder")


def side_stats(rows, color):
    """ACPL, error counts and per-phase ACPL for one side, or None if it made no moves."""
    mine = [r for r in rows if r["mover"] == color]
    if not mine:
        return None
    def acpl(seg):
        return round(sum(min(r["loss"], 1000) for r in seg) / len(seg), 1)
    phases = {}
    for name, lo, hi in PHASES:
        seg = [r for r in mine if lo <= (r["ply"] + 1) // 2 <= hi]
        if seg:
            phases[name] = {"acpl": acpl(seg), "moves": len(seg)}
    return {"moves": len(mine), "acpl": acpl(mine),
            "inaccuracies": sum(1 for r in mine if r["verdict"] == "inaccuracy"),
            "mistakes": sum(1 for r in mine if r["verdict"] == "mistake"),
            "blunders": sum(1 for r in mine if r["verdict"] == "blunder"), "phases": phases}


def find_swings(rows, user):
    """Strengths (opponent errors punished, accurate streaks) and missed chances for the user."""
    punished, missed = [], []
    for prev, cur in zip(rows, rows[1:]):
        if prev["mover"] != user and prev["loss"] >= 100 and cur["mover"] == user:
            if cur["loss"] <= 25:
                punished.append((prev, cur))
            elif cur["loss"] >= 100:
                missed.append((prev, cur))
    best_run, run = [], []
    for r in rows:
        if r["mover"] != user:
            continue
        run = run + [r] if r["loss"] <= 25 else []
        if len(run) > len(best_run):
            best_run = run
    return punished, missed, best_run


def load_analyses():
    out = []
    if ANALYSES.exists():
        for line in ANALYSES.read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:
                pass  # skip a corrupt line rather than losing the whole history
    return out


def delta(cur, prev, lower_is_better=True):
    d = cur - prev
    if abs(d) < 0.05:
        return "same"
    better = (d < 0) == lower_is_better
    return f"{d:+.0f}, {'better' if better else 'worse'}"


def print_comparison(rec, prev):
    print(f"\nCOMPARED WITH LAST ANALYSED GAME AS {rec['color'].upper()} "
          f"({rec_date(prev)}, {prev.get('white', '?')} - {prev.get('black', '?')}):")
    print(f"  ACPL {rec['acpl']:.0f} vs {prev['acpl']:.0f} ({delta(rec['acpl'], prev['acpl'])})")
    for v in ("inaccuracies", "mistakes", "blunders"):
        print(f"  {v}: {rec[v]} vs {prev[v]} ({delta(rec[v], prev[v])})")
    for name, _, _ in PHASES:
        if name in rec["phases"] and name in prev.get("phases", {}):
            c, p = rec["phases"][name]["acpl"], prev["phases"][name]["acpl"]
            print(f"  {name} ACPL: {c:.0f} vs {p:.0f} ({delta(c, p)})")


def game_date(h):
    """PGN date, falling back to Lichess's UTCDate; '????.??.??' when unknown."""
    d = h.get("Date", "????.??.??")
    if "?" in d[:4]:
        d = h.get("UTCDate", d)
    return d


def date_key(d):
    return d.replace("?", "0")


def rec_date(r):
    d = r.get("date")
    return d if d and "?" not in d else r["ts"][:10]


def engine_pass(eng, game, lim):
    """Evaluate every position of a game; returns one row per move (see cmd_analyze for the fields)."""
    moves = list(game.mainline_moves())
    board = game.board()
    rows = []
    prev_cp, prev_disp, prev_info = eval_position(eng, board, lim)
    for mv in moves:
        mover = board.turn
        label_no = f"{board.fullmove_number}{'.' if mover == chess.WHITE else '...'}"
        fen_before = board.fen()
        san = board.san(mv)
        best_move = best_san = best_line = None
        if prev_info and prev_info.get("pv"):
            best_move = prev_info["pv"][0]
            best_san = board.san(best_move)
            best_line = board.variation_san(prev_info["pv"][:5])
        ply = len(board.move_stack) + 1
        board.push(mv)
        cur_cp, cur_disp, cur_info = eval_position(eng, board, lim)
        sign = 1 if mover == chess.WHITE else -1
        loss = 0 if mv == best_move else max(0, sign * (prev_cp - cur_cp))
        verdict = "best" if mv == best_move else classify(loss)
        rows.append(dict(ply=ply, no=label_no, san=san, uci=mv.uci(), mover=mover, eval=cur_disp, eval_cp=cur_cp,
                         prev_eval_cp=prev_cp, loss=loss, verdict=verdict, best=best_san,
                         best_uci=best_move.uci() if best_move else None, line=best_line,
                         fen=fen_before, fen_after=board.fen()))
        prev_cp, prev_info = cur_cp, cur_info
    return rows


def cmd_analyze(a):
    """Engine pass over a whole game: per-move verdicts, ACPL, critical moments, strengths,
    missed chances, comparison with the last analysed game. Details go to last_analysis.json."""
    path = Path(a.file) if a.file else GAME
    if not path.exists():
        die(f"{path} not found")
    offs = pgn_offsets(path)
    if not offs:
        die("No games found")
    if len(offs) > 1 and not a.game:
        for i, (_, h) in enumerate(offs[:30], 1):
            print(f"{i:>3}. {h.get('White', '?')} - {h.get('Black', '?')}  {h.get('Event', '')} {h.get('Date', '')} {h.get('Result', '')}")
        die("Several games in file; re-run with --game N")
    idx = (a.game or 1) - 1
    if not 0 <= idx < len(offs):
        die(f"--game must be 1..{len(offs)}")
    with open(path, encoding="utf-8", errors="replace") as f:
        f.seek(offs[idx][0])
        game = chess.pgn.read_game(f)
    moves = list(game.mainline_moves())
    if game.errors:
        print(f"WARNING: PGN problems ({game.errors[0]}); only the {len(moves)} moves before the problem are analysed. "
              "Check the move list with the user.", file=sys.stderr)
    if not moves:
        die("Game has no moves")
    color = a.color or game.headers.get("UserColor")
    user = {"white": chess.WHITE, "black": chess.BLACK}.get(color)
    lim = chess.engine.Limit(time=a.time) if a.time else chess.engine.Limit(depth=a.depth)
    white, black = game.headers.get("White", "?"), game.headers.get("Black", "?")

    board = game.board()
    print(f"{white} - {black}  {game.headers.get('Event', '')} {game.headers.get('Date', '')} {game.headers.get('Result', '')}")
    print(f"User plays: {color or 'unknown (both sides reported)'}   Evals are White's POV.   Engine limit: "
          f"{'%.1fs' % a.time if a.time else 'depth %d' % a.depth}")
    with open_engine() as eng:
        rows = engine_pass(eng, game, lim)

    for r in rows:
        mark = ""
        if r["verdict"] in FLAGGED:
            mark = f"  <-- {r['verdict']} (-{r['loss']}cp), best {r['best']}"
        print(f"{r['no']:<7}{r['san']:<8}{r['eval']:>7}  {r['verdict']}{mark}")

    stats_by = {"white": side_stats(rows, chess.WHITE), "black": side_stats(rows, chess.BLACK)}
    print("\nSUMMARY")
    for name in ("white", "black"):
        s = stats_by[name]
        if not s:
            continue
        print(f"{name.capitalize()}: ACPL {s['acpl']:.0f} | inaccuracies {s['inaccuracies']} "
              f"| mistakes {s['mistakes']} | blunders {s['blunders']}")
        for ph, v in s["phases"].items():
            print(f"    {ph}: ACPL {v['acpl']:.0f} over {v['moves']} moves")

    pool = [r for r in rows if r["verdict"] in FLAGGED and (user is None or r["mover"] == user)]
    pool.sort(key=lambda r: -r["loss"])
    if pool:
        print(f"\nCRITICAL MOMENTS ({'user' if user is not None else 'both sides'}, biggest loss first)")
        for r in pool[:a.top]:
            print(f"- {r['no']} {r['san']}: {r['verdict']}, -{r['loss']}cp. Best {r['best']}  line: {r['line']}")
            print(f"  FEN before: {r['fen']}")
    else:
        print("\nNo inaccuracies or worse found.")

    punished = missed = []
    best_run = []
    if user is not None:
        punished, missed, best_run = find_swings(rows, user)
        print("\nSTRENGTHS")
        shown = False
        for opp, mine in punished:
            print(f"- {mine['no']} {mine['san']}: punished the opponent's {opp['no']} {opp['san']} ({opp['verdict']}, -{opp['loss']}cp)")
            shown = True
        if len(best_run) >= 6:
            print(f"- {len(best_run)} accurate moves in a row ({best_run[0]['no']} to {best_run[-1]['no']})")
            shown = True
        if not shown:
            print("- (none detected automatically; look for good moves in the table)")
        if missed:
            print("\nMISSED CHANCES (opponent erred, user did not take advantage)")
            for opp, mine in missed:
                print(f"- Opponent's {opp['no']} {opp['san']} ({opp['verdict']}, -{opp['loss']}cp), but {mine['no']} {mine['san']} "
                      f"lost {mine['loss']}cp; best was {mine['best']}")

    # Comparison with the last analysed game as the same colour, and optional saving.
    rec = None
    if user is not None:
        s = stats_by[color]
        key = hashlib.sha1((" ".join(m.uci() for m in moves) + "|" + color).encode()).hexdigest()[:12]
        rec = {"ts": dt.datetime.now().isoformat(timespec="seconds"), "key": key, "date": game_date(game.headers), "source": str(path), "white": white,
               "black": black, "color": color, "plies": len(moves), "depth": None if a.time else a.depth,
               "result": game.headers.get("Result", "*"), "acpl": s["acpl"], "inaccuracies": s["inaccuracies"],
               "mistakes": s["mistakes"], "blunders": s["blunders"], "phases": s["phases"]}
        earlier = [r for r in load_analyses() if r.get("color") == color and r.get("key") != key]
        if earlier:
            print_comparison(rec, earlier[-1])
        else:
            print(f"\nNo earlier analysed game as {color} to compare with.")
        if a.save:
            DATA.mkdir(parents=True, exist_ok=True)
            kept = [r for r in load_analyses() if r.get("key") != key]
            ANALYSES.write_text("".join(json.dumps(r) + "\n" for r in kept + [rec]), encoding="utf-8")
            print(f"Saved to {ANALYSES.name} (history). Use `history` to see the trend.")
        else:
            print("(Not saved to history; re-run with --save for a finished game.)")
    elif a.save:
        print("Not saved: the user's colour is unknown (pass --color).")

    out = {"meta": {"white": white, "black": black, "result": game.headers.get("Result", "*"), "user_color": color,
                    "source": str(path), "limit": f"{a.time}s" if a.time else f"depth {a.depth}"},
           "summary": stats_by,
           "rows": [{**r, "mover": "white" if r["mover"] == chess.WHITE else "black"} for r in rows],
           "critical_plies": [r["ply"] for r in pool[:a.top]],
           "punished_plies": [m["ply"] for _, m in punished],
           "missed_plies": [m["ply"] for _, m in missed]}
    write_atomic(LAST_ANALYSIS, json.dumps(out, indent=1).encode("utf-8"))
    print(f"Details for every move (FENs, best lines, evals): {LAST_ANALYSIS.resolve()}")


def cmd_history(a):
    recs = load_analyses()
    if not recs:
        print("No saved analyses yet (run `analyze --save` on a finished game).")
        return
    print(f"{'date':<11}{'colour':<7}{'ACPL':>5} {'inacc':>5} {'mist':>5} {'blun':>5}  opponent / source")
    for r in recs:
        opp = r["black"] if r["color"] == "white" else r["white"]
        print(f"{rec_date(r):<11}{r['color']:<7}{r['acpl']:>5.0f} {r['inaccuracies']:>5} {r['mistakes']:>5} {r['blunders']:>5}  {opp}")
    for c in ("white", "black"):
        series = [r["acpl"] for r in recs if r["color"] == c]
        if len(series) >= 2:
            print(f"ACPL trend as {c}: " + " -> ".join(f"{x:.0f}" for x in series[-6:]))


# ---------------------------------------------------------------- init: discovery + player profile
PROFILE = DATA / "profile.json"
SKIP_DIRS = {".git", ".hg", ".svn", ".venv", "venv", "env", "node_modules", "__pycache__", "chess_data",
             "stockfish", ".claude", ".idea", ".vscode", "site-packages", "dist", "build"}
BOOK_EXTS = {".pdf", ".epub", ".mobi", ".azw3", ".djvu"}
NOTE_EXTS = {".txt", ".md", ".docx", ".rtf"}
STUDY_EXTS = {".epd", ".fen", ".cbh", ".cbv"}
GAMES_HINT = re.compile(r"game|pgn|match|tournament|lichess|chess[ ._-]?com|my[ ._-]?chess|archive", re.I)
BOOKS_HINT = re.compile(r"book|library|ebook|study|resource|course|opening|endgame|tactic|strateg|chess", re.I)


def count_games(p):
    n = 0
    try:
        with open(p, "rb") as f:
            for line in f:
                if line.lstrip(b"\xef\xbb\xbf").startswith(b"[Event "):
                    n += 1
    except OSError:
        return 0
    return n


def cmd_discover(a):
    """Search a directory tree for folders of PGN games and for chess books/resources (read-only)."""
    root = Path(a.root).resolve()
    if not root.is_dir():
        die(f"{root} is not a directory")
    dirs = {}
    base = len(root.parts)
    for dirpath, dirnames, filenames in os.walk(root):
        d = Path(dirpath)
        depth = len(d.parts) - base
        dirnames[:] = [x for x in dirnames if x not in SKIP_DIRS and not x.startswith(".")] if depth < a.depth else []
        for fn in filenames:
            ext = Path(fn).suffix.lower()
            b = dirs.setdefault(d, {"pgn": [], "books": [], "study": [], "notes": []})
            p = d / fn
            if ext == ".pgn":
                b["pgn"].append(p)
            elif ext in BOOK_EXTS:
                b["books"].append(p)
            elif ext in STUDY_EXTS:
                b["study"].append(p)
            elif ext in NOTE_EXTS and d != root and BOOKS_HINT.search(str(d.relative_to(root))):
                b["notes"].append(p)

    def rel(d):
        r = os.path.relpath(d, root)
        return "." if r == "." else r.replace("\\", "/") + "/"

    print(f"Searched {root} (max depth {a.depth}; skipped {', '.join(sorted(SKIP_DIRS)[:6])}, ...)")
    games = []
    for d, b in dirs.items():
        if b["pgn"]:
            games.append((d, len(b["pgn"]), sum(count_games(p) for p in b["pgn"])))
    games.sort(key=lambda g: (not GAMES_HINT.search(rel(g[0])), -g[2]))
    print("\nPGN FOLDERS (candidate game collections; a name hint means the folder name suggests the player's own games):")
    if not games:
        print("  (none found)")
    for d, nf, ng in games:
        hint = "  [name suggests games]" if GAMES_HINT.search(rel(d)) else ""
        print(f"  {rel(d):<40} {nf:>4} file(s) {ng:>7} game(s){hint}")
        for p in sorted(dirs[d]["pgn"])[:3]:
            print(f"       - {p.name} ({count_games(p)} games)")
    res = [(d, b) for d, b in dirs.items() if b["books"] or b["study"] or b["notes"]]
    print("\nBOOKS AND STUDY RESOURCES:")
    if not res:
        print("  (none found)")
    for d, b in sorted(res, key=lambda x: str(x[0])):
        types = Counter(p.suffix.lower().lstrip(".") for p in b["books"] + b["study"] + b["notes"])
        size = sum(p.stat().st_size for p in b["books"] + b["study"] + b["notes"]) / 1e6
        print(f"  {rel(d):<40} {sum(types.values()):>3} file(s) ({', '.join(f'{k} {v}' for k, v in types.items())}), {size:.1f} MB")
        for p in sorted(b["books"] + b["study"] + b["notes"])[:a.list]:
            print(f"       - {p.name}  ({p.stat().st_size / 1e6:.1f} MB)")
        extra = len(b["books"] + b["study"] + b["notes"]) - a.list
        if extra > 0:
            print(f"       ... and {extra} more")


def classify_tc(tc):
    if not tc or tc in ("-", "?"):
        return "unknown"
    if "/" in tc:
        return "correspondence"
    base, _, inc = tc.partition("+")
    try:
        est = int(base) + 40 * int(inc or 0)
    except ValueError:
        return "unknown"
    return "bullet" if est < 180 else "blitz" if est < 480 else "rapid" if est < 1500 else "classical"


def opening_family(h, sans):
    name = h.get("Opening", "")
    if name and name != "?":
        return name.split(":")[0].strip()
    url = h.get("ECOUrl", "")
    if url:
        words = []
        for w in url.rstrip("/").split("/")[-1].split("-"):
            if any(c.isdigit() for c in w) or "." in w:
                break
            words.append(w)
        if words:
            return " ".join(words[:2])
    return " ".join(sans[:5]) or "?"


def summarize(rs):
    n = len(rs)
    if not n:
        return {"games": 0}
    w = sum(1 for r in rs if r["score"] == 1)
    d = sum(1 for r in rs if r["score"] == 0.5)
    return {"games": n, "wins": w, "draws": d, "losses": n - w - d,
            "score_pct": round(100 * sum(r["score"] for r in rs) / n, 1)}


def opening_table(rs, top=8):
    groups = {}
    for r in rs:
        groups.setdefault(r["opening"], []).append(r)
    rows = [{"name": k, **summarize(v)} for k, v in groups.items()]
    rows.sort(key=lambda x: -x["games"])
    return rows[:top]


def cmd_profile(a):
    """Scan every PGN under a folder, identify the player, aggregate their results/openings/ratings, and
    optionally run the engine over a sample of recent games. Writes profile.json."""
    folder = Path(a.folder)
    if not folder.exists():
        die(f"{folder} not found")
    files = sorted(folder.rglob("*.pgn")) if folder.is_dir() else [folder]
    entries = []
    for p in files:
        for off, h in pgn_offsets(p):
            entries.append((p, off, h))
    if not entries:
        die(f"No PGN games found in {folder}")
    print(f"Found {len(entries)} game(s) in {len(files)} PGN file(s).")

    tokens = [t.strip().lower() for t in (a.player or "").split(",") if t.strip()]
    if not tokens:
        cnt = Counter()
        for _, _, h in entries:
            for k in ("White", "Black"):
                n = h.get(k, "?").strip().lower()
                if n and n not in ("?", "-", "stockfish"):
                    cnt[n] += 1
        top = cnt.most_common(8)
        if not top or top[0][1] < 0.5 * len(entries):
            print("Cannot tell which player is you; the most frequent names are:")
            for n, c in top:
                print(f"  {n}: {c} game(s)")
            die("Re-run with --player NAME (comma-separate several usernames).")
        tokens = [top[0][0]]
        print(f"Player identified as '{top[0][0]}' ({top[0][1]} of {len(entries)} games).")

    def side_of(h, loose=False):
        w, b = h.get("White", "").strip().lower(), h.get("Black", "").strip().lower()
        if loose:
            return chess.WHITE if any(t in w for t in tokens) else chess.BLACK if any(t in b for t in tokens) else None
        return chess.WHITE if w in tokens else chess.BLACK if b in tokens else None

    mine = [(p, off, h, side_of(h)) for p, off, h in entries]
    mine = [m for m in mine if m[3] is not None]
    if not mine and a.player:
        mine = [(p, off, h, side_of(h, True)) for p, off, h in entries]
        mine = [m for m in mine if m[3] is not None]
    if not mine:
        die(f"No games found for player {a.player!r}")
    if len(mine) > a.max_games:
        mine.sort(key=lambda e: date_key(game_date(e[2])))
        print(f"Using the {a.max_games} most recent of {len(mine)} games (--max-games).")
        mine = mine[-a.max_games:]

    games, seen, skipped = [], set(), Counter()
    by_file = {}
    for m in mine:
        by_file.setdefault(m[0], []).append(m)
    for p, ms in by_file.items():
        with open(p, encoding="utf-8", errors="replace") as f:
            for _, off, h, side in sorted(ms, key=lambda e: e[1]):
                f.seek(off)
                game = chess.pgn.read_game(f)
                moves = list(game.mainline_moves())
                if not moves:
                    skipped["no moves"] += 1
                    continue
                key = hashlib.sha1((" ".join(mv.uci() for mv in moves) + h.get("White", "") + h.get("Black", "")
                                    + game_date(h)).encode()).hexdigest()[:12]
                if key in seen:
                    skipped["duplicate"] += 1
                    continue
                seen.add(key)
                b = game.board()
                sans = []
                for i, mv in enumerate(moves):
                    if i < 6:
                        sans.append(b.san(mv))
                    b.push(mv)
                white = side == chess.WHITE
                pair = {"1-0": (1, 0), "0-1": (0, 1), "1/2-1/2": (0.5, 0.5)}.get(h.get("Result", "*"))
                def elo(k):
                    try:
                        return int(h.get(k, ""))
                    except ValueError:
                        return None
                games.append(dict(
                    path=str(p), off=off, date=game_date(h), white=white,
                    color="white" if white else "black",
                    opp=h.get("Black" if white else "White", "?"),
                    score=None if pair is None else pair[0 if white else 1],
                    elo=elo("WhiteElo" if white else "BlackElo"), opp_elo=elo("BlackElo" if white else "WhiteElo"),
                    tc=classify_tc(h.get("TimeControl")), termination=h.get("Termination", ""),
                    plies=len(moves), checkmate=b.is_checkmate(), first=sans[0] if sans else "?",
                    opening=opening_family(h, sans), result=h.get("Result", "*")))
    games.sort(key=lambda r: date_key(r["date"]))
    if not games:
        die("No usable games after filtering")
    done = [g for g in games if g["score"] is not None]
    print(f"Analysing {len(games)} game(s) for the player ({len(done)} with a result). Skipped: {dict(skipped) or 'none'}.")

    known = [g["date"] for g in games if "?" not in g["date"][:4]]
    prof = {"generated": dt.datetime.now().isoformat(timespec="seconds"), "folder": str(folder.resolve()),
            "pgn_files": len(files), "games_in_folder": len(entries), "games_used": len(games),
            "player_names": tokens, "skipped": dict(skipped),
            "date_range": [known[0], known[-1]] if known else None,
            "overall": summarize(done),
            "as_white": summarize([g for g in done if g["white"]]),
            "as_black": summarize([g for g in done if not g["white"]]),
            "recent_20": summarize(done[-20:]),
            "time_controls": {tc: summarize([g for g in done if g["tc"] == tc]) for tc in sorted({g["tc"] for g in done})}}

    # Header ratings: most-played time-control class that has ratings.
    rated = [g for g in games if g["elo"]]
    if rated:
        cls = Counter(g["tc"] for g in rated).most_common(1)[0][0]
        rs = [g for g in rated if g["tc"] == cls]
        recent, prior = rs[-20:], rs[-40:-20]
        prof["rating"] = {"class": cls, "rated_games": len(rs), "first": rs[0]["elo"], "last": rs[-1]["elo"],
                          "peak": max(g["elo"] for g in rs),
                          "recent_avg": round(sum(g["elo"] for g in recent) / len(recent)),
                          "previous_avg": round(sum(g["elo"] for g in prior) / len(prior)) if prior else None,
                          "avg_opponent": round(sum(g["opp_elo"] for g in rs[-50:] if g["opp_elo"]) /
                                                max(1, sum(1 for g in rs[-50:] if g["opp_elo"])))}
    prof["openings"] = {
        "white": opening_table([g for g in done if g["white"]]),
        "black_vs_e4": opening_table([g for g in done if not g["white"] and g["first"] == "e4"]),
        "black_vs_d4": opening_table([g for g in done if not g["white"] and g["first"] == "d4"]),
        "black_vs_other": opening_table([g for g in done if not g["white"] and g["first"] not in ("e4", "d4")])}
    groups = {}
    for g in done:
        groups.setdefault(("white" if g["white"] else "black vs 1." + g["first"], g["opening"]), []).append(g)
    prof["weak_openings"] = sorted([{"side": k[0], "name": k[1], **summarize(v)} for k, v in groups.items()
                                    if len(v) >= 5 and summarize(v)["score_pct"] < 40], key=lambda x: x["score_pct"])
    prof["strong_openings"] = sorted([{"side": k[0], "name": k[1], **summarize(v)} for k, v in groups.items()
                                      if len(v) >= 5 and summarize(v)["score_pct"] >= 60], key=lambda x: -x["score_pct"])
    losses = [g for g in done if g["score"] == 0]
    wins = [g for g in done if g["score"] == 1]
    prof["endings"] = {
        "avg_moves": round(sum(g["plies"] for g in games) / len(games) / 2, 1),
        "losses": len(losses),
        "losses_on_time": sum(1 for g in losses if "time" in g["termination"].lower()),
        "losses_by_checkmate": sum(1 for g in losses if g["checkmate"]),
        "short_losses_under_25_moves": sum(1 for g in losses if g["plies"] < 50),
        "wins_by_checkmate": sum(1 for g in wins if g["checkmate"]),
        "wins_on_time": sum(1 for g in wins if "time" in g["termination"].lower())}

    # Optional engine sample of the most recent games.
    sample = None
    if a.engine_games > 0:
        if not find_stockfish(load_config()):
            print("Engine not configured: skipping the engine sample (run `setup` to enable it).")
        else:
            elig = [g for g in games if g["plies"] >= a.min_ply][-a.engine_games:]
            lim = chess.engine.Limit(depth=a.depth)
            per_game, worst, failed, escapes, phase_losses, first_errors = [], [], [], [], {}, []
            recs = []
            print(f"Running Stockfish (depth {a.depth}) over {len(elig)} recent game(s)...", flush=True)
            with open_engine() as eng:
                for i, g in enumerate(elig, 1):
                    with open(g["path"], encoding="utf-8", errors="replace") as f:
                        f.seek(g["off"])
                        game = chess.pgn.read_game(f)
                    rows = engine_pass(eng, game, lim)
                    color = chess.WHITE if g["white"] else chess.BLACK
                    st = side_stats(rows, color)
                    mine_rows = [r for r in rows if r["mover"] == color]
                    sign = 1 if g["white"] else -1
                    peak = max([0] + [sign * r["eval_cp"] for r in rows])
                    trough = min([0] + [sign * r["eval_cp"] for r in rows])
                    fe = next((r for r in mine_rows if r["verdict"] in FLAGGED), None)
                    if fe:
                        first_errors.append((fe["ply"] + 1) // 2)
                    if g["score"] is not None and g["score"] < 1 and peak >= 300:
                        failed.append({"date": g["date"], "opp": g["opp"], "peak_cp": peak, "result": g["result"]})
                    if g["score"] is not None and g["score"] > 0 and trough <= -300:
                        escapes.append({"date": g["date"], "opp": g["opp"], "low_cp": trough, "result": g["result"]})
                    for r in mine_rows:
                        ph = next(n for n, lo, hi in PHASES if lo <= (r["ply"] + 1) // 2 <= hi)
                        phase_losses.setdefault(ph, []).append(min(r["loss"], 1000))
                        if r["loss"] >= 100:
                            worst.append({"date": g["date"], "opp": g["opp"], "color": g["color"], "no": r["no"],
                                          "san": r["san"], "best": r["best"], "line": r["line"], "loss": r["loss"],
                                          "verdict": r["verdict"], "fen": r["fen"], "result": g["result"]})
                    per_game.append({"date": g["date"], "opp": g["opp"], "color": g["color"], "result": g["result"],
                                     "acpl": st["acpl"], "inaccuracies": st["inaccuracies"],
                                     "mistakes": st["mistakes"], "blunders": st["blunders"], "plies": g["plies"]})
                    recs.append({"ts": dt.datetime.now().isoformat(timespec="seconds"),
                                 "key": hashlib.sha1((" ".join(r["uci"] for r in rows) + "|" + g["color"]).encode()).hexdigest()[:12],
                                 "source": g["path"], "date": g["date"],
                                 "white": game.headers.get("White", "?"), "black": game.headers.get("Black", "?"),
                                 "color": g["color"], "plies": len(rows), "depth": a.depth, "result": g["result"],
                                 "acpl": st["acpl"], "inaccuracies": st["inaccuracies"], "mistakes": st["mistakes"],
                                 "blunders": st["blunders"], "phases": st["phases"]})
                    print(f"  [{i}/{len(elig)}] {g['date']} vs {g['opp']}: ACPL {st['acpl']:.0f}", flush=True)
            worst.sort(key=lambda w: -w["loss"])
            n = len(per_game)
            sample = {"games": n, "depth": a.depth,
                      "acpl": round(sum(p["acpl"] for p in per_game) / n, 1) if n else None,
                      "phase_acpl": {k: round(sum(v) / len(v), 1) for k, v in phase_losses.items()},
                      "per_game_avg": {k: round(sum(p[k] for p in per_game) / n, 2)
                                       for k in ("inaccuracies", "mistakes", "blunders")} if n else {},
                      "avg_first_error_move": round(sum(first_errors) / len(first_errors), 1) if first_errors else None,
                      "failed_conversions": failed, "escapes": escapes, "worst_moments": worst[:15],
                      "per_game": per_game}
            if not a.no_history and recs:
                DATA.mkdir(parents=True, exist_ok=True)
                keys = {r["key"] for r in recs}
                kept = [r for r in load_analyses() if r.get("key") not in keys]
                ANALYSES.write_text("".join(json.dumps(r) + "\n" for r in kept + recs), encoding="utf-8")
                print(f"Saved {len(recs)} analysed game(s) to {ANALYSES.name} (baseline for /analyze-chess comparisons).")
    prof["engine_sample"] = sample
    if PROFILE.exists():  # keep the last profile so a re-run can show what changed
        shutil.copyfile(PROFILE, DATA / "profile.prev.json")
    write_atomic(PROFILE, json.dumps(prof, indent=1).encode("utf-8"))

    # Console summary
    o = prof["overall"]
    print("\nPLAYER PROFILE (from game files)")
    print(f"Games: {len(games)} used, {prof['date_range'][0] if prof['date_range'] else '?'} to "
          f"{prof['date_range'][1] if prof['date_range'] else '?'}")
    print(f"Record: +{o.get('wins', 0)} ={o.get('draws', 0)} -{o.get('losses', 0)}  score {o.get('score_pct')}%   "
          f"as White {prof['as_white'].get('score_pct')}%, as Black {prof['as_black'].get('score_pct')}%   "
          f"last 20: {prof['recent_20'].get('score_pct')}%")
    if "rating" in prof:
        r = prof["rating"]
        print(f"Header rating ({r['class']}, {r['rated_games']} rated games): last {r['last']}, recent avg {r['recent_avg']}, "
              f"peak {r['peak']}, avg opponent {r['avg_opponent']}")
    print("Time controls: " + ", ".join(f"{k} {v['games']}g {v.get('score_pct')}%" for k, v in prof["time_controls"].items()))
    for side, key in (("White", "white"), ("Black vs 1.e4", "black_vs_e4"), ("Black vs 1.d4", "black_vs_d4")):
        t = prof["openings"][key][:4]
        if t:
            print(f"{side}: " + "; ".join(f"{x['name']} ({x['games']}g, {x['score_pct']}%)" for x in t))
    for w in prof["weak_openings"][:3]:
        print(f"WEAK opening ({w['side']}): {w['name']}: {w['games']} games, {w['score_pct']}%")
    e = prof["endings"]
    print(f"Endings: avg {e['avg_moves']} moves; of {e['losses']} losses, {e['losses_on_time']} on time, "
          f"{e['losses_by_checkmate']} by checkmate, {e['short_losses_under_25_moves']} under 25 moves")
    if sample and sample["games"]:
        print(f"Engine sample ({sample['games']} recent games, depth {sample['depth']}): ACPL {sample['acpl']}; "
              f"by phase {sample['phase_acpl']}; per game {sample['per_game_avg']}; first error at move "
              f"{sample['avg_first_error_move']}; failed conversions {len(sample['failed_conversions'])}; "
              f"escapes {len(sample['escapes'])}")
    print(f"\nDetails written to {PROFILE.resolve()}")


def cmd_undo(a):
    if a.n < 1:
        die("undo needs a positive number of half-moves, e.g. `undo 2`")
    headers, board = load_game()
    for _ in range(min(a.n, len(board.move_stack))):
        board.pop()
    commit(headers, board, f"Undid {a.n} half-move(s).")


def cmd_pick(a):
    """Pick a random position from a PGN or EPD file in the library."""
    p = Path(a.file)
    if not p.exists():
        die(f"{p} not found")
    rnd = random.Random(a.seed)
    if p.suffix.lower() == ".epd":
        lines = [l for l in p.read_text(encoding="utf-8", errors="replace").splitlines() if l.strip()]
        line = rnd.choice(lines)
        board = chess.Board()
        ops = board.set_epd(line)
        bm = [board.san(m) for m in ops.get("bm", [])]
        print("FEN:", board.fen())
        print("Source:", p.name, "|", ops.get("id", ""))
        print("Side to move:", "White" if board.turn else "Black")
        if bm:
            print("ANSWER (do not reveal yet): bm", " ".join(bm))
    elif p.suffix.lower() == ".pgn":
        games = []
        with open(p, encoding="utf-8", errors="replace") as f:
            while True:
                off = f.tell()
                h = chess.pgn.read_headers(f)
                if h is None:
                    break
                games.append(off)
        if not games:
            die("No games found")
        with open(p, encoding="utf-8", errors="replace") as f:
            f.seek(rnd.choice(games))
            game = chess.pgn.read_game(f)
        nodes = list(game.mainline())
        if len(nodes) < 2:
            die("Game too short")
        node = nodes[rnd.randrange(max(1, a.min_ply), len(nodes))] if len(nodes) > a.min_ply else nodes[-2]
        board = node.parent.board()
        print("FEN:", board.fen())
        print("Source:", p.name, "|", game.headers.get("White"), "-", game.headers.get("Black"),
              game.headers.get("Event", ""), game.headers.get("Date", ""))
        print("Side to move:", "White" if board.turn else "Black")
        print("ANSWER (game move, do not reveal yet):", board.san(node.move))
    else:
        die("pick supports .pgn and .epd. For PDF/EPUB/text, extract positions manually then use `new --fen`.")


def cmd_library(a):
    lib = a.dir or load_config()["library"]
    if not lib:
        die("No library dir. Run: setup --library <dir>")
    exts = {".pgn", ".epd", ".fen", ".pdf", ".epub", ".txt", ".md", ".cbh"}
    for p in sorted(Path(lib).rglob("*")):
        if p.suffix.lower() in exts:
            print(f"{p.stat().st_size // 1024:>8} KB  {p}")


def cmd_log(a):
    DATA.mkdir(parents=True, exist_ok=True)
    rec = {"ts": dt.datetime.now().isoformat(timespec="seconds"), "topic": a.topic,
           "result": a.result, "source": a.source, "note": a.note,
           "difficulty": a.difficulty, "review": a.review}
    with open(PROGRESS, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")
    print("logged")


def elo_update(rating, n, difficulty, correct):
    """One Elo-style step of the user's puzzle rating against a puzzle of known difficulty."""
    expected = 1 / (1 + 10 ** ((difficulty - rating) / 400))
    k = 48 if n < 10 else 24  # move fast while we know little
    return rating + k * ((1.0 if correct else 0.0) - expected)


def confidence(n):
    return "low" if n < 8 else "medium" if n < 20 else "good"


def load_progress():
    """Valid records from progress.jsonl; corrupt or incomplete lines are skipped, not fatal."""
    out = []
    for line in PROGRESS.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if isinstance(r, dict) and r.get("topic") and r.get("result") in ("correct", "wrong"):
            out.append(r)
    return out


def cmd_stats(a):
    if not PROGRESS.exists():
        print("No progress yet.")
        return
    recs = load_progress()
    tally = {}
    overall = {"r": float(a.prior), "n": 0}
    for r in recs:
        t = tally.setdefault(r["topic"], {"correct": 0, "wrong": 0, "rc": 0, "rn": 0, "r": float(a.prior), "n": 0})
        ok = r["result"] == "correct"
        t["correct" if ok else "wrong"] += 1
        if r.get("review"):  # surprise re-quiz = unprompted recall
            t["rn"] += 1
            t["rc"] += ok
        if r.get("difficulty"):  # only puzzles with a difficulty feed the rating
            t["r"] = elo_update(t["r"], t["n"], r["difficulty"], ok)
            t["n"] += 1
            overall["r"] = elo_update(overall["r"], overall["n"], r["difficulty"], ok)
            overall["n"] += 1
    print(f"{'topic':<30} {'correct':>8} {'recall':>7}  puzzle rating")
    for topic, t in sorted(tally.items(), key=lambda kv: kv[1]["correct"] / max(1, kv[1]["correct"] + kv[1]["wrong"])):
        n = t["correct"] + t["wrong"]
        recall = f"{t['rc']}/{t['rn']}" if t["rn"] else "-"
        rating = f"{t['r']:.0f} (n={t['n']})" if t["n"] else "-"
        print(f"{topic:<30} {str(t['correct']) + '/' + str(n):>8} {recall:>7}  {rating}")
    if overall["n"]:
        print(f"\nOVERALL puzzle rating: {overall['r']:.0f}  (n={overall['n']} rated puzzles, confidence: {confidence(overall['n'])}; "
              f"prior {a.prior}). Relative to the difficulty values assigned when logging, not an official rating.")
    else:
        print("\nNo rated puzzles yet (log with --difficulty to get a puzzle rating).")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)

    def add(name, fn, **kw):
        p = sp.add_parser(name, **kw)
        p.set_defaults(fn=fn)
        return p

    def engine_limits(p):
        p.add_argument("--time", type=float, default=0.5, help="seconds (default 0.5)")
        p.add_argument("--depth", type=int, help="fixed depth; overrides --time")

    p = add("setup", cmd_setup, help="check install; save engine/library paths")
    p.add_argument("--stockfish"); p.add_argument("--library"); p.add_argument("--elo", type=int)

    p = add("new", cmd_new, help="start a game (optionally from a FEN)")
    p.add_argument("--color", choices=["white", "black", "random"], default="white")
    p.add_argument("--elo", type=int); p.add_argument("--fen"); p.add_argument("--source")

    p = add("move", cmd_move, help="play the user's move (SAN or UCI)"); p.add_argument("move")

    p = add("engine", cmd_engine, help="engine plays its move"); engine_limits(p)
    p.add_argument("--full", action="store_true", help="full strength, ignore Elo limit")

    p = add("show", cmd_show, help="re-render the position; optional arrows/squares")
    p.add_argument("--arrows", help="comma list like e2e4,g1f3"); p.add_argument("--squares", help="comma list like e4,d5")
    p.add_argument("--out", help="write here instead of current_position.png (use for explanations); a bare filename like analysis.png lands in the data dir")
    p.add_argument("--fen", help="render this position instead of the game (state-free; default out: chess_data/analysis.png)")
    p.add_argument("--color", choices=["white", "black"], default="white", help="orientation when --fen is used")

    p = add("eval", cmd_eval, help="engine evaluation + top lines (no state change)"); engine_limits(p)
    p.add_argument("--multipv", type=int, default=3)
    p.add_argument("--fen", help="evaluate this position instead of the current game")

    p = add("review", cmd_review, help="rate the last move vs the engine's best"); engine_limits(p)

    p = add("analyze", cmd_analyze, help="engine pass over a whole PGN game (default: the current game)")
    p.add_argument("file", nargs="?", help="PGN file; omit for chess_data/game.pgn")
    p.add_argument("--game", type=int, help="1-based game number when the file has several")
    p.add_argument("--color", choices=["white", "black"], help="side the user played (default: UserColor header)")
    p.add_argument("--depth", type=int, default=14, help="depth per position (default 14)")
    p.add_argument("--time", type=float, help="seconds per position; overrides --depth")
    p.add_argument("--top", type=int, default=5, help="critical moments to list (default 5)")
    p.add_argument("--save", action="store_true", help="record this game's results in analyses.jsonl (finished games only; powers the comparison next time)")

    add("history", cmd_history, help="saved analyses: ACPL and error trend over time")

    p = add("discover", cmd_discover, help="find folders of PGN games and chess books under a directory (read-only)")
    p.add_argument("root", nargs="?", default=".", help="directory to search (default: current directory)")
    p.add_argument("--depth", type=int, default=5, help="how many folder levels to descend (default 5)")
    p.add_argument("--list", type=int, default=8, help="files to list per resource folder (default 8)")

    p = add("profile", cmd_profile, help="scan all PGN games in a folder and build the player's profile (profile.json)")
    p.add_argument("folder", help="folder with the player's own games (searched recursively), or one PGN file")
    p.add_argument("--player", help="player name as it appears in the PGNs; comma-separate several usernames (default: auto-detect)")
    p.add_argument("--engine-games", type=int, default=8, help="most recent games to run Stockfish over (0 = skip; default 8)")
    p.add_argument("--depth", type=int, default=12, help="engine depth for the sample (default 12)")
    p.add_argument("--min-ply", type=int, default=20, help="ignore games shorter than this many plies for the sample")
    p.add_argument("--max-games", type=int, default=3000, help="cap on games read (most recent kept; default 3000)")
    p.add_argument("--no-history", action="store_true", help="don't record the sampled games in analyses.jsonl")

    p = add("undo", cmd_undo, help="take back half-moves"); p.add_argument("n", type=int, nargs="?", default=1)

    p = add("pick", cmd_pick, help="random position from a PGN/EPD file")
    p.add_argument("file"); p.add_argument("--seed", type=int); p.add_argument("--min-ply", type=int, default=10)

    p = add("library", cmd_library, help="list study files"); p.add_argument("dir", nargs="?")

    p = add("log", cmd_log, help="record a quiz result")
    p.add_argument("--topic", required=True); p.add_argument("--result", choices=["correct", "wrong"], required=True)
    p.add_argument("--source", default=""); p.add_argument("--note", default="")
    p.add_argument("--difficulty", type=int, help="estimated puzzle rating (e.g. 1300); feeds the rating estimate in `stats`")
    p.add_argument("--review", action="store_true", help="this was a surprise re-quiz (unprompted recall)")

    p = add("stats", cmd_stats, help="weakest topics first, recall results and estimated puzzle rating")
    p.add_argument("--prior", type=int, default=1200, help="starting puzzle rating before any data (default 1200)")

    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
