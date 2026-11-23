"""The evidence rule: no reference, no evaluation; a book's stated continuation outranks the engine.

`verdict` is the mechanical form of that rule, so these tests pin down every branch of it.
"""
import chess
import pytest

from conftest import HANGS_QUEEN_FEN, START_FEN

CASTLING_FEN = "r1bqkbnr/pppp1ppp/2n5/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 4 4"


# ------------------------------------------------------------------ parsing a book line
class TestParseLine:
    def test_plain_san_line(self, ops):
        moves, err = ops.parse_line(chess.Board(), "e4 e5 Nf3 Nc6")
        assert err is None and [m.uci() for m in moves] == ["e2e4", "e7e5", "g1f3", "b8c6"]

    def test_move_numbers_and_glyphs_are_ignored(self, ops):
        moves, err = ops.parse_line(chess.Board(), "1.e4! e5?! 2.Nf3!! Nc6")
        assert err is None and len(moves) == 4

    def test_black_to_move_with_ellipsis(self, ops):
        b = chess.Board()
        b.push_san("e4")
        moves, err = ops.parse_line(b, "1...e5 2.Nf3")
        assert err is None and [m.uci() for m in moves] == ["e7e5", "g1f3"]

    def test_castling_spellings_and_result_tokens(self, ops):
        moves, err = ops.parse_line(chess.Board(CASTLING_FEN), "4.O-O Nf6 5.d3 1-0")
        assert err is None and moves[0].uci() == "e1g1" and len(moves) == 3

    def test_sloppy_typing_is_accepted_like_for_user_moves(self, ops):
        moves, err = ops.parse_line(chess.Board(), "e4 e5 nf3")
        assert err is None and moves[-1].uci() == "g1f3"

    def test_uci_moves(self, ops):
        moves, err = ops.parse_line(chess.Board(), "e2e4 e7e5")
        assert err is None and len(moves) == 2

    def test_illegal_move_is_an_error_naming_the_point_of_failure(self, ops):
        moves, err = ops.parse_line(chess.Board(), "1.e4 e5 2.Qh5 Nc6 3.Qxf7 Qh4")
        assert [m.uci() for m in moves] == ["e2e4", "e7e5", "d1h5", "b8c6", "h5f7"]
        assert "'Qh4' is not a legal move after e4 e5 Qh5 Nc6 Qxf7" in err

    def test_line_that_does_not_fit_the_position(self, ops):
        _, err = ops.parse_line(chess.Board(), "Nxe5")
        assert "not a legal move" in err

    @pytest.mark.parametrize("text", ["1.e4 (1.d4 d5) e5", "1.e4 {best by far} e5"])
    def test_variations_and_comments_are_rejected_not_guessed(self, ops, text):
        moves, err = ops.parse_line(chess.Board(), text)
        assert moves == [] and "not supported" in err

    @pytest.mark.parametrize("text", ["", "   ", "1-0", "1. ... "])
    def test_empty_line(self, ops, text):
        assert ops.parse_line(chess.Board(), text) == ([], "no moves found in the book line")

    def test_the_input_board_is_not_modified(self, ops):
        b = chess.Board()
        ops.parse_line(b, "e4 e5")
        assert b.fen() == START_FEN and not b.move_stack


class TestTryMove:
    def test_returns_none_instead_of_exiting(self, ops):
        assert ops.try_move(chess.Board(), "Qh7") is None
        assert ops.try_move(chess.Board(), "") is None
        assert ops.try_move(chess.Board(), "e4") == chess.Move.from_uci("e2e4")


# ------------------------------------------------------------------ the rule, with an engine
class TestBookOutranksEngine:
    def test_agreement(self, scli):
        r = scli("verdict", "--fen", HANGS_QUEEN_FEN, "--book", "1.Qxd5+ Ke7", "--source", "Test Book p.7")
        assert r.code == 0
        assert "REFERENCE: BOOK (Test Book p.7)" in r.out and "BOOK LINE: 1. Qxd5 Ke7" in r.out
        assert "ENGINE vs BOOK: AGREE" in r.out and "CONFLICT" not in r.out
        assert "ANSWER (reference: BOOK Test Book p.7): Qxd5" in r.out

    def test_conflict_the_book_stands(self, scli):
        """The book recommends a move that loses the queen. The engine knows better, but the book wins."""
        r = scli("verdict", "--fen", HANGS_QUEEN_FEN, "--book", "1.Qd4", "--source", "Old Book p.1")
        assert r.code == 0
        assert "ENGINE vs BOOK: CONFLICT" in r.out and "THE BOOK STANDS" in r.out
        assert "The engine prefers Qxd5 (+9.00)" in r.out
        assert "do not call the book wrong" in r.out
        answer = [l for l in r.out.splitlines() if l.startswith("ANSWER")]
        assert answer == ["ANSWER (reference: BOOK Old Book p.1): Qd4   line: 1. Qd4"]

    def test_close_call_counts_as_agreement(self, scli):
        # In the start position every move is equal for the stub engine, so any book move is at least "close".
        r = scli("verdict", "--fen", START_FEN, "--book", "1.h4")
        assert "ENGINE vs BOOK: AGREE" in r.out and "ANSWER (reference: BOOK): h4" in r.out

    def test_engine_lines_are_still_shown_for_information(self, scli):
        r = scli("verdict", "--fen", HANGS_QUEEN_FEN, "--book", "1.Qd4", "--multipv", "2")
        assert "ENGINE (evals are from White's point of view):" in r.out and "  1. " in r.out and "  2. " in r.out

    def test_user_matching_the_book_is_right_even_when_the_engine_disagrees(self, scli):
        r = scli("verdict", "--fen", HANGS_QUEEN_FEN, "--book", "1.Qd4", "--user", "Qd4")
        assert "USER: Qd4 MATCHES the book's move. Graded against the book." in r.out
        assert "For information only: Stockfish rates Qd4" in r.out and "cp below its best" in r.out

    def test_user_playing_the_engines_move_instead_of_the_book_differs(self, scli):
        r = scli("verdict", "--fen", HANGS_QUEEN_FEN, "--book", "1.Qd4", "--user", "Qxd5+")
        assert "USER: Qxd5 DIFFERS from the book's move Qd4. Grade against the book." in r.out
        assert "For information only: Stockfish rates Qxd5 as its best move." in r.out

    def test_only_the_first_book_move_is_graded(self, scli):
        r = scli("verdict", "--fen", HANGS_QUEEN_FEN, "--book", "1.Qxd5+ Ke7", "--user", "Qxd5+")
        assert "MATCHES the book's move" in r.out

    def test_annotated_book_line_with_numbers_and_glyphs(self, scli):
        r = scli("verdict", "--fen", HANGS_QUEEN_FEN, "--book", "1.Qxd5+! Ke7 2.Qd7+?!")
        assert r.code == 0 and "BOOK LINE: 1. Qxd5 Ke7 2. Qd7+" in r.out

    def test_book_for_black_to_move(self, scli):
        r = scli("verdict", "--fen", "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1", "--book", "1...c5 2.Nf3")
        assert r.code == 0 and "(Black to move)" in r.out and "ANSWER (reference: BOOK): c5" in r.out

    def test_uses_the_current_game_when_no_fen_is_given(self, scli):
        scli("new", "--fen", HANGS_QUEEN_FEN)
        r = scli("verdict", "--book", "1.Qd4")
        assert HANGS_QUEEN_FEN.split()[0] in r.out and "ANSWER (reference: BOOK): Qd4" in r.out

    def test_does_not_change_the_game(self, scli, sops):
        scli("new", "--fen", HANGS_QUEEN_FEN)
        before = (sops.DATA / "game.pgn").read_text(encoding="utf-8")
        scli("verdict", "--book", "1.Qd4", "--user", "Qxd5+")
        assert (sops.DATA / "game.pgn").read_text(encoding="utf-8") == before


# ------------------------------------------------------------------ no book: the engine decides
class TestEngineWhenNoBook:
    def test_engine_is_the_reference(self, scli):
        r = scli("verdict", "--fen", HANGS_QUEEN_FEN, "--depth", "10")
        assert r.code == 0 and "REFERENCE: ENGINE (Stockfish, depth 10); no book line was given" in r.out
        assert "ANSWER (reference: ENGINE, depth 10): Qxd5" in r.out and "BOOK" not in r.out

    def test_time_limit_label(self, scli):
        assert "ENGINE, 0.2s" in scli("verdict", "--fen", HANGS_QUEEN_FEN, "--time", "0.2").out

    def test_user_matching_the_engine(self, scli):
        assert "USER: Qxd5 MATCHES the engine's best move." in scli("verdict", "--fen", HANGS_QUEEN_FEN, "--user", "Qxd5").out

    def test_user_blunder_is_graded_by_the_engine(self, scli):
        r = scli("verdict", "--fen", HANGS_QUEEN_FEN, "--user", "Qd4")
        assert "USER: Qd4 is blunder (-" in r.out and "vs the engine's Qxd5)" in r.out


# ------------------------------------------------------------------ no engine
class TestNoEngine:
    @pytest.fixture(autouse=True)
    def no_stockfish(self, ops, monkeypatch):
        monkeypatch.setattr(ops.shutil, "which", lambda name: None)

    def test_no_book_and_no_engine_refuses_to_evaluate(self, cli):
        r = cli("verdict", "--fen", HANGS_QUEEN_FEN)
        assert r.code == 2 and "NO REFERENCE" in r.err and "do not judge it yourself" in r.err
        assert "ANSWER" not in r.out and "Traceback" not in r.text

    def test_user_move_cannot_be_graded_without_a_reference(self, cli):
        r = cli("verdict", "--fen", HANGS_QUEEN_FEN, "--user", "Qd4")
        assert r.code == 2 and "NO REFERENCE" in r.err and "USER" not in r.out

    def test_the_book_stands_alone_without_an_engine(self, cli):
        r = cli("verdict", "--fen", HANGS_QUEEN_FEN, "--book", "1.Qd4", "--source", "Old Book p.1")
        assert r.code == 0
        assert "engine unavailable, so the book stands on its own (cite it)" in r.out
        assert "ANSWER (reference: BOOK Old Book p.1): Qd4" in r.out
        assert "ENGINE (" not in r.out

    def test_user_is_graded_against_the_book_alone(self, cli):
        r = cli("verdict", "--fen", HANGS_QUEEN_FEN, "--book", "1.Qd4", "--user", "Qd4")
        assert "MATCHES the book's move" in r.out and "For information only" not in r.out
        r = cli("verdict", "--fen", HANGS_QUEEN_FEN, "--book", "1.Qd4", "--user", "Qxd5")
        assert "DIFFERS from the book's move Qd4" in r.out

    def test_an_illegal_book_line_is_still_rejected_without_an_engine(self, cli):
        r = cli("verdict", "--fen", HANGS_QUEEN_FEN, "--book", "1.Qh8")
        assert r.code == 2 and "not legal from this position" in r.err


# ------------------------------------------------------------------ bad input is refused, never guessed
class TestBadInput:
    def test_illegal_book_line_is_refused(self, scli):
        r = scli("verdict", "--fen", START_FEN, "--book", "1.e4 e5 2.Qh5 Nc6 3.Qxf7 Qh4")
        assert r.code == 2 and "not legal from this position" in r.err
        assert "'Qh4' is not a legal move after" in r.err and "do not use this line" in r.err
        assert "ANSWER" not in r.out

    def test_book_line_for_the_wrong_position(self, scli):
        r = scli("verdict", "--fen", HANGS_QUEEN_FEN, "--book", "1.e4 e5")
        assert r.code == 2 and "not legal from this position" in r.err

    def test_variations_are_refused(self, scli):
        r = scli("verdict", "--fen", START_FEN, "--book", "1.e4 (1.d4) e5")
        assert r.code == 2 and "variations and comments are not supported" in r.err

    def test_empty_book_line(self, scli):
        r = scli("verdict", "--fen", START_FEN, "--book", "1-0")
        assert r.code == 2 and "no moves found" in r.err

    def test_illegal_user_move(self, scli):
        r = scli("verdict", "--fen", START_FEN, "--book", "1.e4", "--user", "Qh7")
        assert r.code == 2 and "not legal here" in r.err

    def test_invalid_fen(self, scli):
        r = scli("verdict", "--fen", "garbage", "--book", "1.e4")
        assert r.code == 2 and "Invalid FEN" in r.err and "Traceback" not in r.text

    def test_no_game_and_no_fen(self, scli):
        assert "No game in progress" in scli("verdict", "--book", "1.e4").err

    @pytest.mark.parametrize("fen", ["rnb1kbnr/pppp1ppp/8/4p3/6Pq/5P2/PPPPP2P/RNBQKBNR w KQkq - 1 3",     # checkmate
                                     "7k/5Q2/6K1/8/8/8/8/8 b - - 0 1"])                                    # stalemate
    def test_finished_positions_have_nothing_to_evaluate(self, scli, fen):
        r = scli("verdict", "--fen", fen, "--book", "1.e4")
        assert r.code == 2 and "already over" in r.err and "Traceback" not in r.text

