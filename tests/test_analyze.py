"""Component tests: analyze, history and the saved-analysis comparison (stub engine)."""
import json
import re

import chess
import pytest

from conftest import BLUNDER_GAME, FRIED_LIVER, SHILLING, pgn_text, play_moves, write_pgn


def last_analysis(m):
    return json.loads((m.LAST_ANALYSIS).read_text(encoding="utf-8"))


def records(m):
    return [json.loads(l) for l in m.ANALYSES.read_text(encoding="utf-8").splitlines() if l.strip()]


@pytest.fixture
def blunder_pgn(tmp_path):
    return write_pgn(tmp_path / "blunder.pgn", pgn_text(BLUNDER_GAME, White="Me", Black="Opp"))


@pytest.fixture
def shilling_pgn(tmp_path):
    return write_pgn(tmp_path / "shilling.pgn", pgn_text(SHILLING, White="Opp", Black="Me", Result="0-1"))


class TestAnalyzeReport:
    def test_flags_the_blunder_and_summarises(self, scli, blunder_pgn):
        r = scli("analyze", blunder_pgn, "--color", "white")
        assert r.code == 0
        assert re.search(r"3\.\s+Qxe5\+?\s+\S+\s+blunder\s+<-- blunder \(-\d+cp\)", r.out)
        assert "SUMMARY" in r.out and "ACPL" in r.out
        assert "CRITICAL MOMENTS (user" in r.out and "FEN before:" in r.out
        assert "User plays: white" in r.out

    def test_every_move_gets_a_verdict_line(self, scli, blunder_pgn):
        r = scli("analyze", blunder_pgn, "--color", "white")
        lines = [l for l in r.out.splitlines() if re.match(r"\d+\.", l)]
        assert len(lines) == 8                                    # 8 plies in the game

    def test_acpl_is_worse_for_the_side_that_blundered(self, scli, blunder_pgn):
        out = scli("analyze", blunder_pgn, "--color", "white").out
        white = float(re.search(r"White: ACPL (\d+)", out).group(1))
        black = float(re.search(r"Black: ACPL (\d+)", out).group(1))
        assert white > black

    def test_phase_breakdown_is_printed(self, scli, blunder_pgn):
        assert "opening: ACPL" in scli("analyze", blunder_pgn, "--color", "white").out

    def test_mate_loss_does_not_distort_acpl(self, scli, shilling_pgn):
        """7.Be2?? allows mate in one: that single move must be capped at 1000 in the average."""
        out = scli("analyze", shilling_pgn, "--color", "black").out
        white_acpl = float(re.search(r"White: ACPL (\d+)", out).group(1))
        assert white_acpl <= 1000

    def test_strengths_punished_opponent_errors(self, scli, blunder_pgn):
        """Black is the user: White's 3.Qxe5?? hangs the queen and 3...Nxe5 takes it."""
        out = scli("analyze", blunder_pgn, "--color", "black").out
        assert "STRENGTHS" in out
        assert re.search(r"3\.\.\. Nxe5: punished the opponent's 3\. Qxe5\+? \(blunder", out)
        assert "MISSED CHANCES" not in out

    def test_missed_chances_when_the_user_ignores_a_hanging_queen(self, scli, tmp_path):
        """Black hangs the queen with 2...Qh4?? and White (the user) plays 3.a3 instead of 3.Nxh4."""
        p = write_pgn(tmp_path / "miss.pgn", pgn_text("1. e4 e5 2. Nf3 Qh4 3. a3 Nc6 *", White="Me", Black="Opp"))
        out = scli("analyze", p, "--color", "white").out
        assert "MISSED CHANCES" in out
        assert re.search(r"Opponent's 2\.\.\. Qh4 \(blunder, -\d+cp\), but 3\. a3 lost \d+cp; best was Nxh4", out)

    def test_long_accurate_streak_is_a_strength(self, scli, tmp_path):
        """A quiet opening with nothing to capture: all six of White's moves are accurate."""
        p = write_pgn(tmp_path / "calm.pgn", pgn_text(
            "1. Nf3 Nf6 2. Nc3 Nc6 3. e3 e6 4. d3 d6 5. Be2 Be7 6. O-O O-O *", White="Me", Black="Opp"))
        out = scli("analyze", p, "--color", "white").out
        assert "- 6 accurate moves in a row (1. to 6.)" in out

    def test_time_limit_label(self, scli, blunder_pgn):
        assert "Engine limit: 0.1s" in scli("analyze", blunder_pgn, "--color", "white", "--time", "0.1").out
        assert "Engine limit: depth 9" in scli("analyze", blunder_pgn, "--color", "white", "--depth", "9").out

    def test_top_limits_critical_moments(self, scli, blunder_pgn):
        out = scli("analyze", blunder_pgn, "--color", "white", "--top", "1").out
        assert out.count("FEN before:") == 1

    def test_unknown_colour_reports_both_sides_and_skips_comparison(self, scli, blunder_pgn):
        r = scli("analyze", blunder_pgn)
        assert "unknown (both sides reported)" in r.out
        assert "CRITICAL MOMENTS (both sides" in r.out
        assert "COMPARED" not in r.out and "STRENGTHS" not in r.out

    def test_default_source_is_the_current_game(self, scli, sops):
        scli("new", "--color", "white")
        play_moves(scli, "e4", "e5", "Qh5", "Nc6", "Qxe5", "Nxe5")
        r = scli("analyze")
        assert r.code == 0 and "User plays: white" in r.out and "Qxe5" in r.out

    def test_start_position_from_fen_header(self, scli, tmp_path, sops):
        fen = "4k3/8/8/3q4/8/8/8/3QK3 w - - 0 1"
        p = write_pgn(tmp_path / "f.pgn", pgn_text("1. Qxd5+ Kd8 *", SetUp="1", FEN=fen))
        scli("analyze", p, "--color", "white")
        assert last_analysis(sops)["rows"][0]["fen"] == fen

    def test_pgn_with_an_illegal_move_warns_and_analyses_the_rest(self, scli, tmp_path):
        p = write_pgn(tmp_path / "bad.pgn", pgn_text("1. e4 e5 2. Qxh9 Nc6 *"))
        r = scli("analyze", p, "--color", "white")
        assert r.code == 0 and "PGN problems" in r.err and "2 moves" in r.err
        assert len([l for l in r.out.splitlines() if re.match(r"\d+\.", l)]) == 2


class TestAnalyzeInputs:
    def test_missing_file(self, scli, tmp_path):
        r = scli("analyze", tmp_path / "nope.pgn")
        assert r.code == 2 and "not found" in r.err

    def test_file_without_games(self, scli, tmp_path):
        p = tmp_path / "empty.pgn"
        p.write_text("this is not a pgn\n", encoding="utf-8")
        r = scli("analyze", p)
        assert r.code == 2 and re.search("No games found|no moves", r.err)

    def test_zero_byte_file(self, scli, tmp_path):
        p = tmp_path / "zero.pgn"
        p.write_bytes(b"")
        r = scli("analyze", p)
        assert r.code == 2 and "No games found" in r.err

    def test_game_without_moves(self, scli, tmp_path):
        p = write_pgn(tmp_path / "nomoves.pgn", pgn_text("*"))
        r = scli("analyze", p, "--color", "white")
        assert r.code == 2 and "no moves" in r.err

    def test_several_games_need_a_choice(self, scli, tmp_path):
        p = write_pgn(tmp_path / "two.pgn", pgn_text("1. e4 e5 *", White="One"), pgn_text("1. d4 d5 *", White="Two"))
        r = scli("analyze", p, "--color", "white")
        assert r.code == 2 and "Several games" in r.err
        assert "1. One" in r.out and "2. Two" in r.out          # the choices are listed

    def test_game_selection(self, scli, tmp_path, sops):
        p = write_pgn(tmp_path / "two.pgn", pgn_text("1. e4 e5 *", White="One"), pgn_text("1. d4 d5 *", White="Two"))
        r = scli("analyze", p, "--game", "2", "--color", "white")
        assert r.code == 0 and "Two -" in r.out
        assert last_analysis(sops)["rows"][0]["san"] == "d4"
        assert scli("analyze", p, "--game", "3", "--color", "white").code == 2
        assert scli("analyze", p, "--game", "0", "--color", "white").code in (0, 2)   # 0 means "not given"


class TestDetailsFile:
    def test_schema(self, scli, sops, blunder_pgn):
        scli("analyze", blunder_pgn, "--color", "white")
        d = last_analysis(sops)
        assert set(d) == {"meta", "summary", "rows", "critical_plies", "punished_plies", "missed_plies"}
        assert d["meta"]["user_color"] == "white" and d["meta"]["white"] == "Me"
        assert len(d["rows"]) == 8
        row = d["rows"][4]
        assert {"ply", "no", "san", "uci", "mover", "eval", "eval_cp", "prev_eval_cp", "loss", "verdict", "best",
                "best_uci", "line", "fen", "fen_after"} <= set(row)
        assert row["san"].startswith("Qxe5") and row["mover"] == "white" and row["ply"] == 5
        assert row["verdict"] == "blunder" and row["loss"] >= 500

    def test_fens_chain_together(self, scli, sops, blunder_pgn):
        scli("analyze", blunder_pgn, "--color", "white")
        rows = last_analysis(sops)["rows"]
        assert rows[0]["fen"] == chess.STARTING_FEN
        for a, b in zip(rows, rows[1:]):
            assert a["fen_after"] == b["fen"]
        board = chess.Board(rows[4]["fen"])
        assert chess.Move.from_uci(rows[4]["uci"]) in board.legal_moves
        assert chess.Move.from_uci(rows[4]["best_uci"]) in board.legal_moves

    def test_critical_plies_point_at_the_users_worst_moves(self, scli, sops, blunder_pgn):
        scli("analyze", blunder_pgn, "--color", "white")
        d = last_analysis(sops)
        assert d["critical_plies"][0] == 5                          # the queen blunder comes first (biggest loss)
        assert all(d["rows"][p - 1]["mover"] == "white" for p in d["critical_plies"])

    def test_is_rewritten_by_each_analysis(self, scli, sops, blunder_pgn, shilling_pgn):
        scli("analyze", blunder_pgn, "--color", "white")
        scli("analyze", shilling_pgn, "--color", "black")
        assert last_analysis(sops)["meta"]["white"] == "Opp"


class TestSaveAndCompare:
    def test_nothing_is_saved_without_the_flag(self, scli, sops, blunder_pgn):
        r = scli("analyze", blunder_pgn, "--color", "white")
        assert "Not saved" in r.out and not sops.ANALYSES.exists()

    def test_save_records_the_game(self, scli, sops, blunder_pgn):
        r = scli("analyze", blunder_pgn, "--color", "white", "--save")
        assert "Saved to analyses.jsonl" in r.out
        (rec,) = records(sops)
        assert rec["color"] == "white" and rec["white"] == "Me" and rec["date"] == "2026.01.01"
        assert rec["blunders"] >= 1 and rec["acpl"] > 0 and "opening" in rec["phases"]

    def test_resaving_the_same_game_replaces_its_record(self, scli, sops, blunder_pgn):
        scli("analyze", blunder_pgn, "--color", "white", "--save")
        scli("analyze", blunder_pgn, "--color", "white", "--save")
        assert len(records(sops)) == 1

    def test_same_moves_as_other_colour_is_a_different_record(self, scli, sops, blunder_pgn):
        scli("analyze", blunder_pgn, "--color", "white", "--save")
        scli("analyze", blunder_pgn, "--color", "black", "--save")
        assert len(records(sops)) == 2

    def test_first_game_has_nothing_to_compare_with(self, scli, blunder_pgn):
        assert "No earlier analysed game as white" in scli("analyze", blunder_pgn, "--color", "white").out

    def test_a_game_is_not_compared_with_itself(self, scli, blunder_pgn):
        scli("analyze", blunder_pgn, "--color", "white", "--save")
        assert "No earlier analysed game" in scli("analyze", blunder_pgn, "--color", "white").out

    def test_comparison_with_the_previous_game_as_the_same_colour(self, scli, sops, blunder_pgn, tmp_path):
        scli("analyze", blunder_pgn, "--color", "white", "--save")
        clean = write_pgn(tmp_path / "clean.pgn", pgn_text("1. e4 e5 2. Nf3 Nc6 3. Bc4 Bc5 *", White="Me", Black="Opp2",
                                                           Date="2026.02.02"))
        out = scli("analyze", clean, "--color", "white").out
        assert "COMPARED WITH LAST ANALYSED GAME AS WHITE (2026.01.01, Me - Opp)" in out
        assert re.search(r"ACPL \d+ vs \d+ \(-\d+, better\)", out)
        assert re.search(r"blunders: 0 vs 1 \(-1, better\)", out)

    def test_comparison_ignores_games_as_the_other_colour(self, scli, blunder_pgn, shilling_pgn):
        scli("analyze", shilling_pgn, "--color", "black", "--save")
        assert "No earlier analysed game as white" in scli("analyze", blunder_pgn, "--color", "white").out

    def test_unknown_colour_cannot_be_saved(self, scli, sops, blunder_pgn):
        r = scli("analyze", blunder_pgn, "--save")
        assert "Not saved: the user's colour is unknown" in r.out and not sops.ANALYSES.exists()

    def test_corrupt_history_lines_are_ignored(self, scli, sops, blunder_pgn):
        scli("analyze", blunder_pgn, "--color", "white", "--save")
        with open(sops.ANALYSES, "a", encoding="utf-8") as f:
            f.write("garbage line\n")
        r = scli("analyze", blunder_pgn, "--color", "white", "--save")
        assert r.code == 0 and len(records(sops)) == 1


class TestHistory:
    def test_empty(self, scli):
        assert "No saved analyses yet" in scli("history").out

    def test_table_and_trend(self, scli, blunder_pgn, shilling_pgn, tmp_path):
        scli("analyze", blunder_pgn, "--color", "white", "--save")
        scli("analyze", shilling_pgn, "--color", "black", "--save")
        clean = write_pgn(tmp_path / "clean.pgn", pgn_text("1. e4 e5 2. Nf3 Nc6 *", White="Me", Black="X", Date="2026.03.03"))
        scli("analyze", clean, "--color", "white", "--save")
        out = scli("history").out
        assert "2026.01.01" in out and "2026.03.03" in out and "Opp" in out
        assert re.search(r"ACPL trend as white: \d+ -> \d+", out)
        assert "trend as black" not in out                           # only one black game

    def test_corrupt_lines_do_not_break_history(self, scli, sops, blunder_pgn):
        scli("analyze", blunder_pgn, "--color", "white", "--save")
        with open(sops.ANALYSES, "a", encoding="utf-8") as f:
            f.write("{broken\n")
        assert scli("history").code == 0
