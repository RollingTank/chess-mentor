"""Unit tests: pure functions and small helpers in chess_ops.py (no engine, no CLI)."""
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace as NS

import chess
import chess.engine
import chess.pgn
import pytest

from conftest import pgn_text, write_pgn


def pov(cp, color=chess.WHITE):
    return chess.engine.PovScore(chess.engine.Cp(cp), color)


# ------------------------------------------------------------------ scores and verdicts
class TestScores:
    def test_fmt_score_is_white_pov(self, ops):
        assert ops.fmt_score(pov(35)) == "+0.35"
        assert ops.fmt_score(pov(-120)) == "-1.20"
        assert ops.fmt_score(pov(0)) == "+0.00"

    def test_fmt_score_flips_black_pov(self, ops):
        assert ops.fmt_score(pov(35, chess.BLACK)) == "-0.35"

    def test_fmt_score_mate(self, ops):
        assert ops.fmt_score(chess.engine.PovScore(chess.engine.Mate(3), chess.WHITE)) == "#3"
        assert ops.fmt_score(chess.engine.PovScore(chess.engine.Mate(-2), chess.WHITE)) == "#-2"
        assert ops.fmt_score(chess.engine.PovScore(chess.engine.Mate(1), chess.BLACK)) == "#-1"

    def test_cp_respects_point_of_view(self, ops):
        info = {"score": pov(120)}
        assert ops.cp(info, chess.WHITE) == 120
        assert ops.cp(info, chess.BLACK) == -120

    def test_cp_maps_mate_to_large_score(self, ops):
        info = {"score": chess.engine.PovScore(chess.engine.Mate(2), chess.WHITE)}
        assert ops.cp(info, chess.WHITE) == 9998
        assert ops.cp(info, chess.BLACK) == -9998

    @pytest.mark.parametrize("loss,verdict", [
        (0, "excellent"), (10, "excellent"), (11, "good"), (49, "good"), (50, "inaccuracy"),
        (99, "inaccuracy"), (100, "mistake"), (199, "mistake"), (200, "blunder"), (9000, "blunder")])
    def test_classify_boundaries(self, ops, loss, verdict):
        assert ops.classify(loss) == verdict

    def test_limit_prefers_depth_over_time(self, ops):
        assert ops.limit(NS(depth=12, time=0.5)).depth == 12
        assert ops.limit(NS(depth=12, time=0.5)).time is None
        assert ops.limit(NS(depth=None, time=0.5)).time == 0.5

    def test_eval_position_terminal_positions_need_no_engine(self, ops):
        mated_white = chess.Board("rnb1kbnr/pppp1ppp/8/4p3/6Pq/5P2/PPPPP2P/RNBQKBNR w KQkq - 1 3")
        assert ops.eval_position(None, mated_white, None) == (-10000, "0-1", None)
        mated_black = chess.Board("R5k1/5ppp/8/8/8/8/8/6K1 b - - 0 1")
        assert ops.eval_position(None, mated_black, None) == (10000, "1-0", None)
        stalemate = chess.Board("7k/5Q2/6K1/8/8/8/8/8 b - - 0 1")
        assert ops.eval_position(None, stalemate, None) == (0, "draw", None)


# ------------------------------------------------------------------ move parsing
class TestParseMove:
    def test_san_and_uci(self, ops):
        b = chess.Board()
        assert ops.parse_move(b, "Nf3") == chess.Move.from_uci("g1f3")
        assert ops.parse_move(b, "e2e4") == chess.Move.from_uci("e2e4")
        assert ops.parse_move(b, "  e4  ") == chess.Move.from_uci("e2e4")

    def test_sloppy_input(self, ops):
        b = chess.Board()
        assert ops.parse_move(b, "nf3") == chess.Move.from_uci("g1f3")       # lowercase piece letter
        assert ops.parse_move(b, "G1F3") == chess.Move.from_uci("g1f3")      # uppercase UCI
        assert ops.parse_move(b, "Nf3+") == chess.Move.from_uci("g1f3")      # superfluous check mark

    def test_castling_spellings(self, ops):
        b = chess.Board("r1bqkbnr/pppp1ppp/2n5/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 4 4")
        castle = chess.Move.from_uci("e1g1")
        for text in ("O-O", "0-0", "o-o"):
            assert ops.parse_move(b, text) == castle

    def test_pawn_move_beats_bishop_reading(self, ops):
        b = chess.Board("rnbqkbnr/ppp1pppp/8/3p4/2B1P3/8/PPPP1PPP/RNBQK1NR w KQkq - 0 3")
        assert ops.parse_move(b, "Bxd5") == chess.Move.from_uci("c4d5")
        assert ops.parse_move(b, "bxd5") == chess.Move.from_uci("c4d5")      # falls back to the bishop
        assert ops.parse_move(b, "exd5") == chess.Move.from_uci("e4d5")      # pawn capture wins

    @pytest.mark.parametrize("text", ["a8=Q", "a8Q", "a7a8q", "a8q"])
    def test_promotion_spellings(self, ops, text):
        b = chess.Board("4k3/P7/8/8/8/8/8/4K3 w - - 0 1")
        assert ops.parse_move(b, text) == chess.Move.from_uci("a7a8q")

    def test_illegal_move_exits_with_legal_moves(self, ops, capsys):
        with pytest.raises(SystemExit) as e:
            ops.parse_move(chess.Board(), "Qh7")
        assert e.value.code == 2
        err = capsys.readouterr().err
        assert "not a legal move" in err and "Nf3" in err and "e4" in err

    def test_ambiguous_move_is_rejected(self, ops, capsys):
        with pytest.raises(SystemExit):
            ops.parse_move(chess.Board("4k3/8/8/8/8/8/8/1N1NK3 w - - 0 1"), "Nc3")
        assert "Nbc3" in capsys.readouterr().err

    def test_prose_is_rejected(self, ops):
        with pytest.raises(SystemExit):
            ops.parse_move(chess.Board(), "knight to f3")


# ------------------------------------------------------------------ config, paths and files
class TestConfigAndPaths:
    def test_user_color(self, ops):
        assert ops.user_color({"UserColor": "black"}) == chess.BLACK
        assert ops.user_color({"UserColor": "white"}) == chess.WHITE
        assert ops.user_color({}) == chess.WHITE

    def test_out_path_bare_name_goes_to_data_dir(self, ops, tmp_path):
        assert ops.out_path("lesson.png") == ops.DATA / "lesson.png"
        assert ops.out_path(str(tmp_path / "x" / "lesson.png")) == tmp_path / "x" / "lesson.png"
        assert ops.out_path("sub/lesson.png") == Path("sub/lesson.png")

    def test_data_dir_comes_from_environment(self, ops, tmp_path):
        assert ops.DATA == tmp_path / "chess_data"
        assert ops.CONFIG.parent == ops.DATA

    def test_load_config_defaults(self, ops):
        assert ops.load_config() == {"stockfish": None, "library": None, "elo": 1500}

    def test_load_config_merges_file_and_env_override(self, ops, monkeypatch):
        ops.save_config({"stockfish": "/from/file", "library": "/lib", "elo": 1700})
        assert ops.load_config()["library"] == "/lib"
        assert ops.load_config()["stockfish"] == "/from/file"
        monkeypatch.setenv("STOCKFISH_PATH", "/from/env")
        assert ops.load_config()["stockfish"] == "/from/env"
        assert ops.load_config()["elo"] == 1700

    def test_find_stockfish_order(self, ops, tmp_path, monkeypatch):
        exe = tmp_path / "sf.exe"
        exe.write_text("x")
        on_path = tmp_path / "onpath" / "stockfish"
        monkeypatch.setattr(ops.shutil, "which", lambda name: str(on_path) if name == "stockfish" else None)
        assert ops.find_stockfish({"stockfish": str(exe)}) == str(exe)                 # configured path wins
        assert ops.find_stockfish({"stockfish": str(tmp_path / "missing")}) == str(on_path)   # then PATH
        assert ops.find_stockfish({}) == str(on_path)
        monkeypatch.setattr(ops.shutil, "which", lambda name: None)
        assert ops.find_stockfish({"stockfish": None}) is None

    def test_open_engine_without_stockfish_exits_helpfully(self, ops, monkeypatch, capsys):
        monkeypatch.setattr(ops.shutil, "which", lambda name: None)
        with pytest.raises(SystemExit) as e:
            ops.open_engine()
        assert e.value.code == 2
        assert "Stockfish not found" in capsys.readouterr().err

    def test_write_atomic_creates_parents(self, ops, tmp_path):
        target = tmp_path / "a" / "b" / "f.bin"
        ops.write_atomic(target, b"abc")
        assert target.read_bytes() == b"abc"
        assert not list(target.parent.glob("*.tmp"))

    def test_write_atomic_falls_back_when_replace_is_blocked(self, ops, tmp_path, monkeypatch):
        """Windows refuses os.replace while a viewer holds the image open."""
        target = tmp_path / "f.bin"

        def blocked(*a, **k):
            raise PermissionError("held open")
        monkeypatch.setattr(ops.os, "replace", blocked)
        ops.write_atomic(target, b"new")
        assert target.read_bytes() == b"new"
        assert not list(tmp_path.glob("*.tmp"))


# ------------------------------------------------------------------ rating maths
class TestRatingMaths:
    def test_elo_update_even_match(self, ops):
        assert ops.elo_update(1200, 0, 1200, True) == pytest.approx(1224)
        assert ops.elo_update(1200, 0, 1200, False) == pytest.approx(1176)

    def test_elo_update_difficulty_matters(self, ops):
        assert ops.elo_update(1000, 0, 1400, True) == pytest.approx(1043.64, abs=0.01)
        assert ops.elo_update(1400, 0, 1000, True) < ops.elo_update(1400, 0, 1400, True)
        assert ops.elo_update(1400, 0, 1000, False) < 1400 - 40       # losing to an easy puzzle costs a lot

    def test_k_factor_drops_after_ten_puzzles(self, ops):
        assert ops.elo_update(1200, 9, 1200, True) == pytest.approx(1224)
        assert ops.elo_update(1200, 10, 1200, True) == pytest.approx(1212)

    @pytest.mark.parametrize("n,label", [(0, "low"), (7, "low"), (8, "medium"), (19, "medium"), (20, "good")])
    def test_confidence(self, ops, n, label):
        assert ops.confidence(n) == label

    def test_delta_semantics(self, ops):
        assert ops.delta(5, 10) == "-5, better"
        assert ops.delta(10, 5) == "+5, worse"
        assert ops.delta(5, 5) == "same"
        assert ops.delta(10, 5, lower_is_better=False) == "+5, better"


# ------------------------------------------------------------------ profile helpers
class TestProfileHelpers:
    @pytest.mark.parametrize("tc,cls", [
        ("60", "bullet"), ("120+1", "bullet"), ("180+0", "blitz"), ("180+2", "blitz"), ("15+10", "blitz"),
        ("300+5", "rapid"), ("600+0", "rapid"), ("900+10", "rapid"), ("1800", "classical"),
        ("1/86400", "correspondence"), ("-", "unknown"), ("?", "unknown"), (None, "unknown"), ("", "unknown"),
        ("abc", "unknown")])
    def test_classify_tc(self, ops, tc, cls):
        assert ops.classify_tc(tc) == cls

    def test_opening_family_from_lichess_header(self, ops):
        assert ops.opening_family({"Opening": "Sicilian Defense: Najdorf Variation"}, ["e4"]) == "Sicilian Defense"

    def test_opening_family_from_chesscom_url(self, ops):
        h = {"ECOUrl": "https://www.chess.com/openings/Sicilian-Defense-Open-Najdorf-Variation-6.Be3-e5"}
        assert ops.opening_family(h, ["e4", "c5"]) == "Sicilian Defense"

    def test_opening_family_falls_back_to_first_moves(self, ops):
        assert ops.opening_family({}, ["e4", "e5", "Nf3", "Nc6", "Bc4", "Bc5", "c3"]) == "e4 e5 Nf3 Nc6 Bc4"
        assert ops.opening_family({"Opening": "?"}, ["d4", "d5"]) == "d4 d5"
        assert ops.opening_family({}, []) == "?"

    def test_summarize(self, ops):
        rs = [{"score": 1}, {"score": 1}, {"score": 0.5}, {"score": 0}]
        s = ops.summarize(rs)
        assert (s["games"], s["wins"], s["draws"], s["losses"], s["score_pct"]) == (4, 2, 1, 1, 62.5)
        assert ops.summarize([]) == {"games": 0}

    def test_opening_table_groups_sorts_and_limits(self, ops):
        rs = ([{"opening": "A", "score": 1}] * 3 + [{"opening": "B", "score": 0}] * 5 + [{"opening": "C", "score": 0.5}])
        table = ops.opening_table(rs, top=2)
        assert [t["name"] for t in table] == ["B", "A"]
        assert table[0]["games"] == 5 and table[0]["score_pct"] == 0

    def test_dates(self, ops):
        assert ops.game_date({"Date": "2026.03.04"}) == "2026.03.04"
        assert ops.game_date({"Date": "????.??.??", "UTCDate": "2025.01.02"}) == "2025.01.02"
        assert ops.game_date({}) == "????.??.??"
        assert ops.date_key("2026.??.??") == "2026.00.00"
        assert ops.rec_date({"date": "2026.01.02", "ts": "2030-01-01T00:00:00"}) == "2026.01.02"
        assert ops.rec_date({"date": "2026.??.??", "ts": "2030-01-01T00:00:00"}) == "2030-01-01"
        assert ops.rec_date({"ts": "2030-01-01T00:00:00"}) == "2030-01-01"

    def test_count_games_handles_bom_and_missing_file(self, ops, tmp_path):
        p = tmp_path / "g.pgn"
        p.write_bytes(b"\xef\xbb\xbf" + (pgn_text("1. e4 *") * 3).encode())
        assert ops.count_games(p) == 3
        assert ops.count_games(tmp_path / "nope.pgn") == 0

    def test_pgn_offsets_allow_random_access(self, ops, tmp_path):
        p = write_pgn(tmp_path / "g.pgn", pgn_text("1. e4 e5 *", White="One"), pgn_text("1. d4 d5 *", White="Two"),
                      pgn_text("1. c4 c5 *", White="Three"))
        offs = ops.pgn_offsets(p)
        assert [h["White"] for _, h in offs] == ["One", "Two", "Three"]
        with open(p, encoding="utf-8") as f:
            f.seek(offs[1][0])
            game = chess.pgn.read_game(f)
        assert game.headers["White"] == "Two"
        assert game.next().san() == "d4"


# ------------------------------------------------------------------ analysis helpers
def row(ply, loss, verdict=None, san="x"):
    mover = chess.WHITE if ply % 2 == 1 else chess.BLACK
    return {"ply": ply, "mover": mover, "loss": loss, "verdict": verdict or ("best" if loss == 0 else "good"),
            "san": san, "no": f"{(ply + 1) // 2}{'.' if mover else '...'}", "best": "e4"}


class TestAnalysisHelpers:
    def test_side_stats_acpl_counts_and_phases(self, ops):
        rows = [row(1, 0), row(2, 60, "inaccuracy"), row(3, 120, "mistake"), row(4, 300, "blunder"),
                row(5, 0), row(6, 5000, "blunder")]
        white = ops.side_stats(rows, chess.WHITE)
        black = ops.side_stats(rows, chess.BLACK)
        assert white["moves"] == 3 and white["acpl"] == 40.0
        assert (white["inaccuracies"], white["mistakes"], white["blunders"]) == (0, 1, 0)
        assert black["acpl"] == pytest.approx((60 + 300 + 1000) / 3, abs=0.1)        # 5000 is capped at 1000
        assert black["blunders"] == 2 and black["inaccuracies"] == 1
        assert set(white["phases"]) == {"opening"}
        assert white["phases"]["opening"]["moves"] == 3

    def test_side_stats_splits_phases_by_move_number(self, ops):
        rows = [row(p, 10) for p in (1, 21, 41, 61)]        # moves 1, 11, 21, 31 for white
        phases = ops.side_stats(rows, chess.WHITE)["phases"]
        assert set(phases) == {"opening", "middlegame", "late"}

    def test_side_stats_none_when_side_has_no_moves(self, ops):
        assert ops.side_stats([row(1, 0)], chess.BLACK) is None

    def test_find_swings(self, ops):
        rows = [row(1, 0), row(2, 300, "blunder"),                 # opponent (black) blunders
                row(3, 10),                                        # user (white) punishes it
                row(4, 150, "mistake"),                            # opponent errs again
                row(5, 250, "blunder"),                            # user misses the chance
                row(6, 0), row(7, 0), row(8, 0), row(9, 20), row(10, 0), row(11, 0)]
        punished, missed, run = ops.find_swings(rows, chess.WHITE)
        assert [(o["ply"], m["ply"]) for o, m in punished] == [(2, 3)]
        assert [(o["ply"], m["ply"]) for o, m in missed] == [(4, 5)]
        assert [r["ply"] for r in run] == [7, 9, 11]                # longest accurate streak of the user's moves

    def test_load_analyses_skips_corrupt_lines(self, ops):
        ops.DATA.mkdir(parents=True)
        ops.ANALYSES.write_text('{"key": "a"}\nnot json\n\n{"key": "b"}\n', encoding="utf-8")
        assert [r["key"] for r in ops.load_analyses()] == ["a", "b"]


# ------------------------------------------------------------------ rendering
class TestRender:
    def test_png_is_written(self, ops, tmp_path):
        out = ops.render(chess.Board(), path=tmp_path / "b.png")
        assert out.read_bytes()[:4] == b"\x89PNG"

    def test_orientation_changes_the_image(self, ops, tmp_path):
        a = ops.render(chess.Board(), flipped=False, path=tmp_path / "a.png").read_bytes()
        b = ops.render(chess.Board(), flipped=True, path=tmp_path / "b.png").read_bytes()
        assert a != b

    def test_last_move_and_check_are_highlighted(self, ops, tmp_path):
        played = chess.Board()
        played.push_san("e4")
        fresh = chess.Board(played.fen())                   # same position, no move history
        assert ops.render(played, path=tmp_path / "a.png").read_bytes() != \
            ops.render(fresh, path=tmp_path / "b.png").read_bytes()
        in_check = chess.Board("4k3/8/8/8/8/8/4R3/4K3 b - - 0 1")
        quiet = chess.Board("4k3/8/8/8/8/8/3R4/4K3 b - - 0 1")
        assert ops.render(in_check, path=tmp_path / "c.png").read_bytes() != \
            ops.render(quiet, path=tmp_path / "d.png").read_bytes()

    def test_arrows_and_squares_change_the_image(self, ops, tmp_path):
        plain = ops.render(chess.Board(), path=tmp_path / "a.png").read_bytes()
        arrow = ops.render(chess.Board(), arrows=[(chess.E2, chess.E4)], path=tmp_path / "b.png").read_bytes()
        square = ops.render(chess.Board(), squares={chess.E4: "#ff000080"}, path=tmp_path / "c.png").read_bytes()
        assert len({plain, arrow, square}) == 3

    def test_falls_back_to_svg_when_resvg_is_missing(self, ops, tmp_path, monkeypatch, capsys):
        monkeypatch.setitem(sys.modules, "resvg_py", None)
        out = ops.render(chess.Board(), path=tmp_path / "b.png")
        assert out.suffix == ".svg" and out.read_text(encoding="utf-8").startswith("<svg")
        assert "resvg-py missing" in capsys.readouterr().err
