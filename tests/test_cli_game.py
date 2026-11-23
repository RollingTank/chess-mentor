"""Component tests: the game commands, driven through the real CLI entry point with the stub engine."""
import re
from types import SimpleNamespace as NS

import chess
import chess.pgn
import pytest

from conftest import FOOLS_MATE_BLACK_TO_MATE, FOOLS_MATE_MOVES, HANGS_QUEEN_FEN, STALEMATE_FEN, play_moves


def image(m):
    return (m.DATA / "current_position.png").read_bytes()


def pgn_of(m):
    return (m.DATA / "game.pgn").read_text(encoding="utf-8")


def game_moves(m):
    with open(m.DATA / "game.pgn", encoding="utf-8") as f:
        g = chess.pgn.read_game(f)
    return g, [mv.uci() for mv in g.mainline_moves()]


# ------------------------------------------------------------------ new
class TestNew:
    def test_creates_game_pgn_and_image(self, scli, sops):
        r = scli("new", "--color", "white", "--elo", "1700")
        assert r.code == 0
        assert "New game. You play white." in r.out and "To move: White" in r.out and "Image:" in r.out
        assert image(sops)[:4] == b"\x89PNG"
        pgn = pgn_of(sops)
        assert '[UserColor "white"]' in pgn and '[EngineElo "1700"]' in pgn
        assert '[White "User"]' in pgn and '[Black "Stockfish"]' in pgn

    def test_black_headers_and_flipped_image(self, scli, sops):
        scli("new", "--color", "white")
        white_img = image(sops)
        r = scli("new", "--color", "black")
        assert '[White "Stockfish"]' in pgn_of(sops) and '[Black "User"]' in pgn_of(sops)
        assert image(sops) != white_img                      # board is shown from Black's side
        assert "Engine moves first" in r.out

    def test_white_user_is_not_told_the_engine_moves_first(self, scli):
        assert "Engine moves first" not in scli("new", "--color", "white").out

    def test_default_elo_comes_from_config(self, scli, sops):
        sops.save_config({"stockfish": None, "library": None, "elo": 1850})
        scli("new")
        assert '[EngineElo "1850"]' in pgn_of(sops)

    def test_random_colour_is_a_valid_colour(self, scli, sops):
        r = scli("new", "--color", "random")
        assert re.search(r"You play (white|black)\.", r.out)

    def test_custom_fen_and_source(self, scli, sops):
        fen = "4k3/8/8/8/8/8/4P3/4K3 w - - 0 1"
        scli("new", "--fen", fen, "--source", "Silman, ch. 3")
        pgn = pgn_of(sops)
        assert '[Source "Silman, ch. 3"]' in pgn and fen in pgn
        assert "FEN: " + fen in scli("show").out

    def test_invalid_fen_is_a_clean_error(self, scli, sops):
        r = scli("new", "--fen", "not a fen")
        assert r.code == 2 and "Invalid FEN" in r.err and "Traceback" not in r.text
        assert not (sops.DATA / "game.pgn").exists()

    def test_new_replaces_the_previous_game(self, scli, sops):
        scli("new")
        scli("move", "e4")
        scli("new")
        assert game_moves(sops)[1] == []


# ------------------------------------------------------------------ move
class TestMove:
    def test_move_updates_pgn_and_image(self, scli, sops):
        scli("new")
        before = image(sops)
        r = scli("move", "e4")
        assert r.code == 0 and "Played: e4" in r.out and "To move: Black" in r.out
        assert image(sops) != before
        assert game_moves(sops)[1] == ["e2e4"]

    @pytest.mark.parametrize("text", ["e4", "e2e4", "E2E4"])
    def test_accepts_san_and_uci(self, scli, sops, text):
        scli("new")
        assert scli("move", text).code == 0
        assert game_moves(sops)[1] == ["e2e4"]

    def test_illegal_move_changes_nothing(self, scli, sops):
        scli("new")
        scli("move", "e4")
        pgn_before, img_before = pgn_of(sops), image(sops)
        r = scli("move", "Qh7")
        assert r.code == 2 and "not a legal move" in r.err and "Legal moves:" in r.err
        assert pgn_of(sops) == pgn_before and image(sops) == img_before

    def test_move_without_a_game(self, scli):
        r = scli("move", "e4")
        assert r.code == 2 and "No game in progress" in r.err

    def test_move_with_empty_game_file_is_a_clean_error(self, scli, sops):
        sops.DATA.mkdir(parents=True)
        (sops.DATA / "game.pgn").write_text("", encoding="utf-8")
        r = scli("move", "e4")
        assert r.code == 2 and "Traceback" not in r.text

    def test_status_shows_recent_moves_in_numbered_pairs(self, scli):
        scli("new")
        r = play_moves(scli, "e4", "e5", "Nf3")
        assert "Moves: 1. e4 e5 2. Nf3" in r.out

    def test_status_for_black_to_move_from_a_fen(self, scli):
        scli("new", "--fen", "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 2")
        r = play_moves(scli, "Nc6")
        assert "Moves: 2... Nc6" in r.out

    def test_check_is_reported(self, scli):
        scli("new", "--fen", "4k3/8/8/8/8/8/8/R3K3 w - - 0 1")
        assert "CHECK" in scli("move", "Ra8").out

    def test_fools_mate_ends_the_game(self, scli, sops):
        scli("new")
        r = play_moves(scli, *FOOLS_MATE_MOVES)
        assert "GAME OVER: 0-1 (CHECKMATE)" in r.out and "CHECK" in r.out
        assert '[Result "0-1"]' in pgn_of(sops)
        again = scli("move", "a3")
        assert again.code == 2 and "Game is over" in again.err
        assert scli("engine").code == 2

    def test_stalemate_is_reported_as_a_draw(self, scli, sops):
        r = scli("new", "--fen", STALEMATE_FEN, "--color", "white")
        assert "GAME OVER: 1/2-1/2 (STALEMATE)" in r.out
        assert '[Result "1/2-1/2"]' in pgn_of(sops)

    def test_game_in_progress_has_unfinished_result(self, scli, sops):
        scli("new")
        scli("move", "e4")
        assert '[Result "*"]' in pgn_of(sops)


# ------------------------------------------------------------------ undo
class TestUndo:
    def test_undo_one_and_many(self, scli, sops):
        scli("new")
        play_moves(scli, "e4", "e5", "Nf3")
        r = scli("undo")
        assert "Undid 1 half-move" in r.out and game_moves(sops)[1] == ["e2e4", "e7e5"]
        scli("undo", "5")                                    # more than exist: stops at the start
        assert game_moves(sops)[1] == []

    def test_undo_refreshes_the_image(self, scli, sops):
        scli("new")
        scli("move", "e4")
        after_move = image(sops)
        scli("undo")
        assert image(sops) != after_move

    def test_undo_after_game_over_reopens_the_game(self, scli, sops):
        scli("new")
        play_moves(scli, *FOOLS_MATE_MOVES)
        r = scli("undo")
        assert "GAME OVER" not in r.out and '[Result "*"]' in pgn_of(sops)

    @pytest.mark.parametrize("n", ["0", "-2"])
    def test_undo_rejects_non_positive_counts(self, scli, sops, n):
        scli("new")
        scli("move", "e4")
        r = scli("undo", n)
        assert r.code == 2 and game_moves(sops)[1] == ["e2e4"]

    def test_undo_without_game(self, scli):
        assert scli("undo").code == 2


# ------------------------------------------------------------------ show
class TestShow:
    def test_show_rerenders_the_live_game(self, scli, sops):
        scli("new")
        scli("move", "e4")
        (sops.DATA / "current_position.png").unlink()
        r = scli("show")
        assert r.code == 0 and "FEN: " in r.out and image(sops)[:4] == b"\x89PNG"

    def test_show_without_game(self, scli):
        assert "No game in progress" in scli("show").err

    def test_annotated_image_never_touches_current_position(self, scli, sops):
        scli("new")
        scli("move", "e4")
        before = image(sops)
        r = scli("show", "--arrows", "g1f3,b1c3", "--squares", "e4,d5", "--out", "analysis.png")
        assert r.code == 0 and image(sops) == before
        assert (sops.DATA / "analysis.png").read_bytes()[:4] == b"\x89PNG"

    def test_out_with_a_directory_part_is_respected(self, scli, tmp_path):
        scli("new")
        target = tmp_path / "elsewhere" / "pos.png"
        scli("show", "--out", str(target))
        assert target.exists()

    def test_fen_mode_is_state_free(self, scli, sops):
        r = scli("show", "--fen", "4k3/8/8/8/8/8/4P3/4K3 w - - 0 1", "--arrows", "e2e4")
        assert r.code == 0
        assert (sops.DATA / "analysis.png").exists()
        assert not (sops.DATA / "game.pgn").exists() and not (sops.DATA / "current_position.png").exists()

    def test_fen_mode_leaves_a_live_game_alone(self, scli, sops):
        scli("new")
        scli("move", "e4")
        before_img, before_pgn = image(sops), pgn_of(sops)
        scli("show", "--fen", "4k3/8/8/8/8/8/4P3/4K3 w - - 0 1")
        assert image(sops) == before_img and pgn_of(sops) == before_pgn

    def test_fen_mode_orientation(self, scli, sops):
        scli("show", "--fen", chess.STARTING_FEN, "--color", "white", "--out", "w.png")
        scli("show", "--fen", chess.STARTING_FEN, "--color", "black", "--out", "b.png")
        assert (sops.DATA / "w.png").read_bytes() != (sops.DATA / "b.png").read_bytes()

    def test_invalid_fen(self, scli):
        r = scli("show", "--fen", "garbage")
        assert r.code == 2 and "Invalid FEN" in r.err and "Traceback" not in r.text

    @pytest.mark.parametrize("flag,value", [("--arrows", "zz9"), ("--arrows", "e2"), ("--squares", "k9")])
    def test_invalid_squares_are_a_clean_error(self, scli, flag, value):
        scli("new")
        r = scli("show", flag, value)
        assert r.code == 2 and "Traceback" not in r.text


# ------------------------------------------------------------------ engine
class TestEngine:
    def test_engine_plays_a_legal_move_and_updates_everything(self, scli, sops):
        scli("new")
        scli("move", "e4")
        before = image(sops)
        r = scli("engine")
        assert r.code == 0 and "Engine plays:" in r.out
        _, moves = game_moves(sops)
        assert len(moves) == 2 and image(sops) != before
        board = chess.Board()                                     # the whole game is legal
        for uci in moves:
            assert chess.Move.from_uci(uci) in board.legal_moves
            board.push_uci(uci)

    def test_engine_can_open_for_white(self, scli, sops):
        scli("new", "--color", "black")
        r = scli("engine")
        assert r.code == 0 and len(game_moves(sops)[1]) == 1

    def test_strength_limit_uses_uci_elo(self, scli, sops):
        scli("new", "--elo", "1500")
        scli("engine")
        assert sops.stub.configured == {"UCI_LimitStrength": True, "UCI_Elo": 1500}

    def test_elo_is_clamped_and_the_user_is_told(self, scli, sops):
        scli("new", "--elo", "1000")
        r = scli("engine")
        assert sops.stub.configured["UCI_Elo"] == 1320
        assert "NOTE" in r.out and "1320" in r.out
        scli("new", "--elo", "3500")
        assert "3190" in scli("engine").out

    def test_full_strength_ignores_the_limit(self, scli, sops):
        scli("new", "--elo", "1500")
        scli("engine", "--full")
        assert sops.stub.configured == {}

    @pytest.mark.parametrize("elo,level", [(800, 0), (1500, 7), (2800, 20), (3500, 20), (100, 0)])
    def test_skill_level_fallback(self, scli, sops, elo, level):
        sops.stub.options = {"Skill Level": NS(min=0, max=20)}
        scli("new", "--elo", str(elo))
        scli("engine")
        assert sops.stub.configured == {"Skill Level": level}

    def test_engine_without_a_game(self, scli):
        assert "No game in progress" in scli("engine").err

    def test_engine_missing_gives_install_hint(self, cli, ops, monkeypatch):
        monkeypatch.setattr(ops.shutil, "which", lambda name: None)
        cli("new")
        r = cli("engine")
        assert r.code == 2 and "Stockfish not found" in r.err and "stockfishchess.org" in r.err


# ------------------------------------------------------------------ eval
class TestEval:
    def test_eval_lists_ranked_lines(self, scli):
        scli("new")
        r = scli("eval", "--multipv", "3")
        assert r.code == 0 and "White's point of view" in r.out
        assert [l.split(".")[0] for l in r.out.splitlines()[1:]] == ["1", "2", "3"]

    def test_eval_does_not_change_the_game(self, scli, sops):
        scli("new")
        scli("move", "e4")
        before = pgn_of(sops)
        scli("eval")
        assert pgn_of(sops) == before

    def test_eval_fen_reports_mate_from_white_pov(self, scli):
        r = scli("eval", "--fen", FOOLS_MATE_BLACK_TO_MATE, "--multipv", "1")
        assert "#-1" in r.out and "Qh4#" in r.out

    def test_eval_fen_needs_no_game(self, scli, sops):
        assert scli("eval", "--fen", chess.STARTING_FEN).code == 0
        assert not (sops.DATA / "game.pgn").exists()

    def test_eval_without_game_or_fen(self, scli):
        assert scli("eval").code == 2

    def test_eval_invalid_fen(self, scli):
        r = scli("eval", "--fen", "zzz")
        assert r.code == 2 and "Invalid FEN" in r.err and "Traceback" not in r.text


# ------------------------------------------------------------------ review
class TestReview:
    def test_best_move_is_rated_best(self, scli):
        scli("new", "--fen", HANGS_QUEEN_FEN)
        scli("move", "Qxd5+")
        r = scli("review")
        assert r.code == 0 and "verdict: best" in r.out

    def test_hanging_the_queen_is_a_blunder(self, scli):
        scli("new", "--fen", HANGS_QUEEN_FEN)
        scli("move", "Qd4")
        r = scli("review")
        assert "verdict: blunder" in r.out and "Best was: Qxd5 " in r.out
        loss = int(re.search(r"loss ~(\d+) cp", r.out).group(1))
        assert loss >= 800

    def test_review_does_not_change_the_game(self, scli, sops):
        scli("new", "--fen", HANGS_QUEEN_FEN)
        scli("move", "Qd4")
        before = pgn_of(sops)
        scli("review")
        assert pgn_of(sops) == before

    def test_review_without_moves(self, scli):
        scli("new")
        r = scli("review")
        assert r.code == 2 and "No moves yet" in r.err

    def test_review_without_game(self, scli):
        assert "No game in progress" in scli("review").err
