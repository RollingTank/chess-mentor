"""Integration tests against a real Stockfish (skipped automatically when none is found).

Stockfish's moves differ between versions, so these assert properties that must hold for any engine:
legality, state consistency, mate detection, and clearly-decided evaluations.
"""
import json
import random
import re

import chess
import chess.pgn
import pytest

from conftest import BLUNDER_GAME, FOOLS_MATE_BLACK_TO_MATE, SHILLING, pgn_text, write_pgn

pytestmark = pytest.mark.engine


def saved_game(real):
    with open(real.data / "game.pgn", encoding="utf-8") as f:
        g = chess.pgn.read_game(f)
    return g, [m for m in g.mainline_moves()]


def assert_game_is_legal(real):
    g, moves = saved_game(real)
    board = g.board()
    for mv in moves:
        assert mv in board.legal_moves
        board.push(mv)
    return board, moves


class TestSetup:
    def test_setup_detects_the_engine_and_its_options(self, real):
        r = real("setup")
        assert r.code == 0, r
        assert "Engine OK: Stockfish" in r.out and "resvg-py OK" in r.out
        assert "option UCI_Elo [" in r.out and "option UCI_LimitStrength" in r.out

    def test_setup_saves_an_explicit_engine_path(self, real, stockfish_path):
        assert real("setup", "--stockfish", stockfish_path).code == 0
        assert json.loads((real.data / "config.json").read_text(encoding="utf-8"))["stockfish"] == stockfish_path


class TestPlayingAGame:
    def test_six_moves_against_the_engine_stay_consistent(self, real):
        real("new", "--color", "white", "--elo", "1500")
        rnd = random.Random(11)
        for _ in range(6):
            g, moves = saved_game(real)
            board = g.board()
            for mv in moves:
                board.push(mv)
            if board.is_game_over(claim_draw=True):
                break
            user_move = rnd.choice(list(board.legal_moves)).uci()
            r = real("move", user_move)
            assert r.code == 0, r
            if "GAME OVER" in r.out:
                break
            r = real("engine", "--time", "0.05")
            assert r.code == 0 and "Engine plays:" in r.out, r
            assert "Image:" in r.out
        board, moves = assert_game_is_legal(real)
        assert len(moves) >= 2
        assert (real.data / "current_position.png").read_bytes()[:4] == b"\x89PNG"
        assert board.fen() in real("show").out                       # the image/state is regenerated from the same game

    def test_engine_opens_for_white_when_the_user_is_black(self, real):
        real("new", "--color", "black")
        r = real("engine", "--depth", "6")
        assert r.code == 0 and "To move: Black" in r.out
        assert len(saved_game(real)[1]) == 1

    def test_engine_at_full_strength_and_fixed_depth(self, real):
        real("new", "--color", "black")
        assert real("engine", "--full", "--depth", "5").code == 0
        assert len(saved_game(real)[1]) == 1

    def test_engine_delivers_mate_in_one(self, real):
        real("new", "--fen", FOOLS_MATE_BLACK_TO_MATE, "--color", "white")
        r = real("engine", "--depth", "6", "--full")
        assert "Engine plays: Qh4#" in r.out and "GAME OVER: 0-1 (CHECKMATE)" in r.out
        assert real("engine").code == 2                              # nothing left to play

    def test_elo_below_the_engines_minimum_is_clamped_with_a_note(self, real):
        low = int(re.search(r"option UCI_Elo \[(\d+)-", real("setup").out).group(1))
        real("new", "--color", "black", "--elo", str(max(100, low - 300)))
        r = real("engine", "--time", "0.05")
        assert r.code == 0 and "NOTE" in r.out and str(low) in r.out

    def test_undo_after_an_engine_reply(self, real):
        real("new", "--color", "white")
        real("move", "e4")
        real("engine", "--time", "0.05")
        r = real("undo", "2")
        assert "Moves: (none)" in r.out and saved_game(real)[1] == []


class TestEvaluation:
    def test_eval_start_position_is_roughly_equal(self, real):
        real("new")
        r = real("eval", "--multipv", "3", "--depth", "10")
        scores = [float(m) for m in re.findall(r"^\d\. ([+-]\d+\.\d+)", r.out, re.M)]
        assert len(scores) == 3 and all(abs(s) < 1.0 for s in scores)

    def test_eval_finds_forced_mate_from_whites_point_of_view(self, real):
        r = real("eval", "--fen", FOOLS_MATE_BLACK_TO_MATE, "--depth", "6", "--multipv", "1")
        assert "#-1" in r.out and "Qh4#" in r.out

    def test_review_calls_a_hung_queen_a_blunder(self, real):
        real("new", "--fen", "4k3/8/8/3q4/8/8/8/3QK3 w - - 0 1", "--color", "white")
        real("move", "Qd4")
        r = real("review", "--depth", "10")
        assert "verdict: blunder" in r.out and "Best was: Qxd5" in r.out

    def test_review_calls_the_best_move_best(self, real):
        real("new", "--fen", "4k3/8/8/3q4/8/8/8/3QK3 w - - 0 1", "--color", "white")
        real("move", "Qxd5")
        assert "verdict: best" in real("review", "--depth", "10").out

    def test_review_flags_a_real_opening_mistake(self, real):
        """1.d4 e5 2.e3 Qh4? (the queen sortie loses time and is punished): at least a mistake."""
        real("new", "--fen", "rnbqkbnr/pppp1ppp/8/4p3/3P4/4P3/PPP2PPP/RNBQKBNR b KQkq - 0 2", "--color", "black")
        real("move", "Qh4")
        r = real("review", "--depth", "12")
        loss = int(re.search(r"loss ~(\d+) cp", r.out).group(1))
        assert loss >= 100 and re.search(r"verdict: (mistake|blunder)", r.out)


class TestAnalyze:
    def test_flags_a_hung_queen_and_writes_the_details(self, real):
        p = write_pgn(real.tmp / "g.pgn", pgn_text(BLUNDER_GAME, White="Me", Black="Opp"))
        r = real("analyze", p, "--color", "white", "--depth", "10", "--save")
        assert r.code == 0, r
        assert re.search(r"3\.\s+Qxe5\+?\s+\S+\s+blunder", r.out)
        d = json.loads((real.data / "last_analysis.json").read_text(encoding="utf-8"))
        q = d["rows"][4]
        assert q["san"].startswith("Qxe5") and q["verdict"] == "blunder" and q["loss"] >= 500
        assert d["critical_plies"][0] == 5
        # every FEN and best move in the file is valid for the position it belongs to
        for row in d["rows"]:
            board = chess.Board(row["fen"])
            assert chess.Move.from_uci(row["uci"]) in board.legal_moves
            if row["best_uci"]:
                assert chess.Move.from_uci(row["best_uci"]) in board.legal_moves
        assert len((real.data / "analyses.jsonl").read_text(encoding="utf-8").splitlines()) == 1

    def test_game_ending_in_mate_is_handled(self, real):
        p = write_pgn(real.tmp / "s.pgn", pgn_text(SHILLING, White="Opp", Black="Me", Result="0-1"))
        r = real("analyze", p, "--color", "black", "--depth", "8")
        assert r.code == 0 and re.search(r"7\.\.\.\s+Nf3#\s+0-1", r.out)
        assert "STRENGTHS" in r.out

    def test_comparison_with_an_earlier_saved_game(self, real):
        first = write_pgn(real.tmp / "a.pgn", pgn_text(BLUNDER_GAME, White="Me", Black="X", Date="2026.01.01"))
        second = write_pgn(real.tmp / "b.pgn", pgn_text("1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 4. Ba4 Nf6 *", White="Me", Black="Y", Date="2026.02.02"))
        real("analyze", first, "--color", "white", "--depth", "8", "--save")
        out = real("analyze", second, "--color", "white", "--depth", "8").out
        assert "COMPARED WITH LAST ANALYSED GAME AS WHITE (2026.01.01" in out and "better" in out

    def test_analyzing_the_game_just_played(self, real):
        real("new", "--color", "white", "--elo", "1500")
        real("move", "e4")
        real("engine", "--time", "0.05")
        real("move", "Nf3")
        r = real("analyze", "--depth", "8")
        assert r.code == 0 and "User plays: white" in r.out and "SUMMARY" in r.out


class TestProfile:
    GAMES = [
        "1. e4 e5 2. Nf3 Nc6 3. Bc4 Bc5 4. c3 Nf6 5. d3 d6 6. O-O O-O 7. Re1 a6 8. Bb3 Ba7 9. Nbd2 h6 10. Nf1 Re8 *",
        "1. d4 d5 2. c4 e6 3. Nc3 Nf6 4. Bg5 Be7 5. e3 O-O 6. Nf3 h6 7. Bh4 b6 8. cxd5 exd5 9. Bd3 Bb7 *",
        "1. e4 c5 2. Nf3 d6 3. d4 cxd4 4. Nxd4 Nf6 5. Nc3 a6 6. Be3 e5 7. Nb3 Be6 8. f3 Be7 9. Qd2 O-O *",
    ]

    def test_profile_with_a_real_engine_sample(self, real):
        gs = [pgn_text(m, White="Me", Black=f"Opp{i}", Result=r, Date=f"2026.01.0{i + 1}", WhiteElo="1500", BlackElo="1450",
                       TimeControl="180+0", Opening=o)
              for i, (m, r, o) in enumerate(zip(self.GAMES, ("1-0", "1/2-1/2", "0-1"), ("Italian Game", "Queen's Pawn Game", "Sicilian Defense")))]
        write_pgn(real.tmp / "games" / "me.pgn", *gs)
        r = real("profile", real.tmp / "games", "--engine-games", "2", "--depth", "6", "--min-ply", "10")
        assert r.code == 0, r
        assert "Player identified as 'me'" in r.out and "Engine sample (2 recent games" in r.out
        p = json.loads((real.data / "profile.json").read_text(encoding="utf-8"))
        assert p["overall"]["games"] == 3 and p["engine_sample"]["games"] == 2
        assert p["engine_sample"]["acpl"] is not None and p["rating"]["class"] == "blitz"
        assert len((real.data / "analyses.jsonl").read_text(encoding="utf-8").splitlines()) == 2
        assert "2026.01.03" in real("history").out

    def test_discover_then_profile_workflow(self, real):
        write_pgn(real.tmp / "proj" / "my games" / "a.pgn", *[pgn_text(m, White="Me", Black="Z") for m in self.GAMES[:2]])
        (real.tmp / "proj" / "books").mkdir()
        (real.tmp / "proj" / "books" / "Endgames.pdf").write_bytes(b"%PDF-1.4")
        out = real("discover", real.tmp / "proj").out
        assert "my games/" in out and "Endgames.pdf" in out
        assert real("profile", real.tmp / "proj" / "my games", "--engine-games", "0").code == 0


class TestVerdictWithRealEngine:
    HANGS = "4k3/8/8/3q4/8/8/8/3QK3 w - - 0 1"

    def test_book_stands_even_when_stockfish_strongly_disagrees(self, real):
        """The 'book' recommends Qd4, which hangs the queen. Stockfish knows better; the book still wins."""
        r = real("verdict", "--fen", self.HANGS, "--book", "1.Qd4", "--source", "Old Book p.1", "--depth", "10", "--user", "Qxd5")
        assert r.code == 0, r
        assert "ENGINE vs BOOK: CONFLICT" in r.out and "THE BOOK STANDS" in r.out
        assert "ANSWER (reference: BOOK Old Book p.1): Qd4" in r.out
        assert "DIFFERS from the book's move Qd4" in r.out and "Stockfish rates Qxd5 as its best move" in r.out

    def test_agreement_between_book_and_engine(self, real):
        r = real("verdict", "--fen", self.HANGS, "--book", "1.Qxd5", "--depth", "10")
        assert "ENGINE vs BOOK: AGREE" in r.out and "ANSWER (reference: BOOK): Qxd5" in r.out

    def test_engine_decides_only_when_there_is_no_book_line(self, real):
        r = real("verdict", "--fen", self.HANGS, "--depth", "10", "--user", "Qd4")
        assert "REFERENCE: ENGINE" in r.out and "ANSWER (reference: ENGINE, depth 10): Qxd5" in r.out
        assert "USER: Qd4 is blunder" in r.out

    def test_a_dubious_opening_book_line_is_still_the_answer(self, real):
        r = real("verdict", "--fen", chess.STARTING_FEN, "--book", "1.g4 d5 2.Bg2", "--depth", "10")
        assert r.code == 0 and "ANSWER (reference: BOOK): g4" in r.out

