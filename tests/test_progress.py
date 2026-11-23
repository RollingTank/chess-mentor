"""Component tests: log/stats (progress record), pick, library, setup and the CLI shell itself."""
import json
import re
import subprocess
import sys

import chess
import pytest

from conftest import SCRIPT, pgn_text, write_pgn


def log_lines(m):
    return [json.loads(l) for l in m.PROGRESS.read_text(encoding="utf-8").splitlines() if l.strip()]


# ------------------------------------------------------------------ log
class TestLog:
    def test_appends_a_record_and_creates_the_data_dir(self, scli, sops):
        r = scli("log", "--topic", "forks", "--result", "correct", "--difficulty", "1300", "--source", "Silman p.12",
                 "--note", "found Nxe5")
        assert r.code == 0 and "logged" in r.out
        (rec,) = log_lines(sops)
        assert rec["topic"] == "forks" and rec["result"] == "correct" and rec["difficulty"] == 1300
        assert rec["source"] == "Silman p.12" and rec["note"] == "found Nxe5" and rec["review"] is False
        assert re.match(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d", rec["ts"])

    def test_review_flag_and_optional_fields(self, scli, sops):
        scli("log", "--topic", "pins", "--result", "wrong", "--review")
        scli("log", "--topic", "pins", "--result", "correct")
        a, b = log_lines(sops)
        assert a["review"] is True and a["difficulty"] is None and a["source"] == ""
        assert b["review"] is False

    def test_records_accumulate(self, scli, sops):
        for i in range(3):
            scli("log", "--topic", f"t{i}", "--result", "correct")
        assert len(log_lines(sops)) == 3

    def test_requires_topic_and_valid_result(self, scli):
        assert scli("log", "--result", "correct").code == 2
        assert scli("log", "--topic", "x", "--result", "maybe").code == 2


# ------------------------------------------------------------------ stats
class TestStats:
    def test_no_progress_yet(self, scli):
        assert "No progress yet" in scli("stats").out

    def test_weakest_topic_first_with_counts(self, scli):
        for res in ("correct", "correct", "wrong"):
            scli("log", "--topic", "forks", "--result", res)
        for res in ("wrong", "wrong"):
            scli("log", "--topic", "pins", "--result", res)
        scli("log", "--topic", "skewers", "--result", "correct")
        out = scli("stats").out
        assert out.index("pins") < out.index("forks") < out.index("skewers")
        assert re.search(r"forks\s+2/3", out) and re.search(r"pins\s+0/2", out)

    def test_recall_column(self, scli):
        scli("log", "--topic", "forks", "--result", "correct", "--review")
        scli("log", "--topic", "forks", "--result", "wrong", "--review")
        scli("log", "--topic", "forks", "--result", "correct")
        assert re.search(r"forks\s+2/3\s+1/2", scli("stats").out)

    def test_rating_matches_the_elo_update(self, scli, sops):
        scli("log", "--topic", "forks", "--result", "correct", "--difficulty", "1000")
        scli("log", "--topic", "forks", "--result", "wrong", "--difficulty", "1500")
        scli("log", "--topic", "pins", "--result", "correct", "--difficulty", "1300")
        r1 = sops.elo_update(1200.0, 0, 1000, True)
        r2 = sops.elo_update(r1, 1, 1500, False)
        r3 = sops.elo_update(r2, 2, 1300, True)
        out = scli("stats").out
        assert f"OVERALL puzzle rating: {r3:.0f}" in out and "n=3 rated puzzles" in out and "confidence: low" in out
        forks_t = sops.elo_update(sops.elo_update(1200.0, 0, 1000, True), 1, 1500, False)
        assert re.search(rf"forks\s+1/2\s+-\s+{forks_t:.0f} \(n=2\)", out)

    def test_prior_option(self, scli, sops):
        scli("log", "--topic", "forks", "--result", "correct", "--difficulty", "1000")
        assert f"{sops.elo_update(1500.0, 0, 1000, True):.0f}" in scli("stats", "--prior", "1500").out

    def test_unrated_results_do_not_move_the_rating(self, scli):
        scli("log", "--topic", "king safety", "--result", "wrong")
        out = scli("stats").out
        assert "king safety" in out and "No rated puzzles yet" in out and "OVERALL" not in out

    def test_unrated_entries_do_not_disturb_a_rating(self, scli):
        scli("log", "--topic", "forks", "--result", "correct", "--difficulty", "1000")
        before = re.search(r"OVERALL puzzle rating: (\d+)", scli("stats").out).group(1)
        scli("log", "--topic", "init mistakes", "--result", "wrong")
        assert re.search(r"OVERALL puzzle rating: (\d+)", scli("stats").out).group(1) == before

    def test_corrupt_and_blank_lines_are_ignored(self, scli, sops):
        scli("log", "--topic", "forks", "--result", "correct", "--difficulty", "1000")
        with open(sops.PROGRESS, "a", encoding="utf-8") as f:
            f.write("this is not json\n\n{\"topic\": \"x\"}\n")
        r = scli("stats")
        assert r.code == 0 and "forks" in r.out and "Traceback" not in r.text


# ------------------------------------------------------------------ pick
class TestPick:
    def test_epd_position_and_answer(self, scli, tmp_path):
        epd = tmp_path / "t.epd"
        epd.write_text('r1bqkbnr/pppp1ppp/2n5/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R b KQkq - bm Nf6; id "italian-1";\n')
        out = scli("pick", epd).out
        assert "FEN: r1bqkbnr/pppp1ppp/2n5/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R b KQkq - 0 1" in out
        assert "Side to move: Black" in out and "ANSWER (do not reveal yet): bm Nf6" in out and "italian-1" in out

    def test_epd_without_best_move_has_no_answer_line(self, scli, tmp_path):
        epd = tmp_path / "t.epd"
        epd.write_text("\n\n4k3/8/8/8/8/8/4P3/4K3 w - - id \"x\";\n\n")
        assert "ANSWER" not in scli("pick", epd).out

    def test_epd_with_several_best_moves(self, scli, tmp_path):
        epd = tmp_path / "t.epd"
        epd.write_text("4k3/8/8/8/8/8/8/R3K2R w - - bm Ra7 Rh7;\n")
        assert "bm Ra7 Rh7" in scli("pick", epd).out

    def test_pgn_position_is_valid_and_answer_is_legal(self, scli, tmp_path):
        p = write_pgn(tmp_path / "g.pgn", pgn_text("1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 4. Ba4 Nf6 5. O-O Be7 6. Re1 b5 7. Bb3 d6 8. c3 O-O *"))
        out = scli("pick", p, "--seed", "3", "--min-ply", "4").out
        fen = re.search(r"FEN: (.+)", out).group(1)
        answer = re.search(r"ANSWER \(game move, do not reveal yet\): (\S+)", out).group(1)
        board = chess.Board(fen)
        assert board.parse_san(answer) in board.legal_moves

    def test_pgn_pick_is_reproducible_with_a_seed(self, scli, tmp_path):
        p = write_pgn(tmp_path / "g.pgn", *[pgn_text("1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 4. Ba4 Nf6 5. O-O Be7 *", White=f"P{i}") for i in range(6)])
        assert scli("pick", p, "--seed", "5", "--min-ply", "3").out == scli("pick", p, "--seed", "5", "--min-ply", "3").out

    def test_short_game_falls_back_to_the_last_move(self, scli, tmp_path):
        p = write_pgn(tmp_path / "g.pgn", pgn_text("1. e4 e5 *"))
        assert "ANSWER" in scli("pick", p).out

    def test_game_too_short(self, scli, tmp_path):
        p = write_pgn(tmp_path / "g.pgn", pgn_text("1. e4 *"))
        assert scli("pick", p).code == 2

    def test_unsupported_and_missing_files(self, scli, tmp_path):
        pdf = tmp_path / "book.pdf"
        pdf.write_bytes(b"x")
        r = scli("pick", pdf)
        assert r.code == 2 and "pick supports .pgn and .epd" in r.err
        assert "not found" in scli("pick", tmp_path / "nope.epd").err

    def test_pgn_without_games(self, scli, tmp_path):
        p = tmp_path / "empty.pgn"
        p.write_text("")
        assert scli("pick", p).code == 2


# ------------------------------------------------------------------ library
class TestLibrary:
    def test_lists_study_files_only(self, scli, tmp_path):
        lib = tmp_path / "lib"
        (lib / "sub").mkdir(parents=True)
        (lib / "a.pdf").write_bytes(b"x" * 3000)
        (lib / "sub" / "b.PGN").write_text("[Event \"x\"]\n")
        (lib / "c.epub").write_bytes(b"x")
        (lib / "notes.txt").write_text("hi")
        (lib / "photo.jpg").write_bytes(b"x")
        (lib / "script.py").write_text("x")
        out = scli("library", lib).out
        for name in ("a.pdf", "b.PGN", "c.epub", "notes.txt"):
            assert name in out
        assert "photo.jpg" not in out and "script.py" not in out
        assert re.search(r"2 KB\s+.*a\.pdf", out)

    def test_uses_the_configured_library(self, scli, tmp_path):
        lib = tmp_path / "lib"
        lib.mkdir()
        (lib / "x.pdf").write_bytes(b"x")
        scli("setup", "--library", lib)
        assert "x.pdf" in scli("library").out

    def test_no_library_configured(self, scli):
        r = scli("library")
        assert r.code == 2 and "No library dir" in r.err


# ------------------------------------------------------------------ setup
class TestSetup:
    def test_reports_environment_and_saves_config(self, scli, sops, tmp_path):
        exe = tmp_path / "fake-stockfish"
        exe.write_text("x")
        r = scli("setup", "--stockfish", exe, "--library", tmp_path, "--elo", "1650")
        assert r.code == 0
        for needle in ("Python 3.", "chess 1.", "Data directory:", "resvg-py OK", "Engine OK: StubFish 1.0",
                       "option UCI_Elo [1320-3190]", "option Skill Level [0-20]"):
            assert needle in r.out
        cfg = json.loads(sops.CONFIG.read_text(encoding="utf-8"))
        assert cfg == {"stockfish": str(exe), "library": str(tmp_path), "elo": 1650}

    def test_finds_stockfish_on_path(self, scli, sops, tmp_path, monkeypatch):
        exe = tmp_path / "stockfish"
        exe.write_text("x")
        monkeypatch.setattr(sops.shutil, "which", lambda name: str(exe))
        r = scli("setup")
        assert f"Found Stockfish on PATH: {exe}" in r.out
        assert json.loads(sops.CONFIG.read_text(encoding="utf-8"))["stockfish"] == str(exe)

    def test_reports_a_missing_engine(self, cli, ops, monkeypatch):
        monkeypatch.setattr(ops.shutil, "which", lambda name: None)
        r = cli("setup")
        assert r.code == 0 and "Engine NOT configured" in r.out

    def test_environment_variable_overrides_config(self, scli, sops, tmp_path, monkeypatch):
        exe = tmp_path / "from-env"
        exe.write_text("x")
        monkeypatch.setenv("STOCKFISH_PATH", str(exe))
        r = scli("setup")
        assert "Engine OK" in r.out and "from-env" in r.out

    def test_temporary_environment_override_is_not_saved(self, scli, sops, tmp_path, monkeypatch):
        saved = tmp_path / "saved-engine"
        saved.write_text("x")
        scli("setup", "--stockfish", saved)
        env_exe = tmp_path / "env-engine"
        env_exe.write_text("x")
        monkeypatch.setenv("STOCKFISH_PATH", str(env_exe))
        scli("setup", "--elo", "1800")
        cfg = json.loads(sops.CONFIG.read_text(encoding="utf-8"))
        assert cfg["stockfish"] == str(saved) and cfg["elo"] == 1800

    def test_corrupt_config_is_a_clean_error(self, scli, sops):
        sops.DATA.mkdir(parents=True)
        sops.CONFIG.write_text("{not json", encoding="utf-8")
        r = scli("setup")
        assert r.code == 2 and "not valid JSON" in r.err and "Traceback" not in r.text

    def test_setup_is_incremental(self, scli, sops, tmp_path):
        exe = tmp_path / "sf"
        exe.write_text("x")
        scli("setup", "--stockfish", exe)
        scli("setup", "--elo", "1800")
        cfg = json.loads(sops.CONFIG.read_text(encoding="utf-8"))
        assert cfg["stockfish"] == str(exe) and cfg["elo"] == 1800

    def test_warns_when_png_rendering_is_unavailable(self, scli, monkeypatch):
        monkeypatch.setitem(sys.modules, "resvg_py", None)
        assert "resvg-py MISSING" in scli("setup").out


# ------------------------------------------------------------------ the CLI shell
COMMANDS = ["setup", "new", "move", "engine", "show", "eval", "review", "analyze", "history", "discover", "profile",
            "verdict", "undo", "pick", "library", "log", "stats"]


class TestCliShell:
    def test_help_lists_every_command(self, cli):
        r = cli("--help")
        assert r.code == 0
        for c in COMMANDS:
            assert c in r.out

    @pytest.mark.parametrize("command", COMMANDS)
    def test_every_command_has_help(self, cli, command):
        r = cli(command, "--help")
        assert r.code == 0 and "usage:" in r.out

    def test_missing_or_unknown_command_is_rejected(self, cli):
        assert cli().code == 2
        assert cli("frobnicate").code == 2

    def test_move_requires_an_argument(self, cli):
        assert cli("move").code == 2

    def test_runs_as_a_standalone_script(self, tmp_path):
        p = subprocess.run([sys.executable, str(SCRIPT), "--help"], capture_output=True, text=True,
                           env={"PATH": "", "SYSTEMROOT": "C:\\Windows", "CHESS_DATA_DIR": str(tmp_path)})
        assert p.returncode == 0 and "discover" in p.stdout

    def test_missing_dependency_gives_an_install_command(self, tmp_path):
        """Simulate python-chess not being installed and check the message tells the user what to do."""
        code = ("import sys, runpy; sys.modules['chess'] = None; sys.argv = ['chess_ops.py', 'stats'];"
                f"runpy.run_path({str(SCRIPT)!r}, run_name='__main__')")
        p = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                           env={"PATH": "", "SYSTEMROOT": "C:\\Windows", "CHESS_DATA_DIR": str(tmp_path)})
        assert p.returncode == 3
        assert "python-chess is not installed" in p.stderr and "-m pip install -r" in p.stderr
        assert "requirements.txt" in p.stderr and "externally managed" in p.stderr
        assert "Traceback" not in p.stderr

    def test_data_dir_is_created_lazily(self, scli, sops):
        assert not sops.DATA.exists()
        scli("new")
        assert sops.DATA.is_dir()

    def test_two_data_dirs_do_not_interfere(self, tmp_path, monkeypatch, capsys):
        from conftest import load_module, make_cli
        a = load_module(tmp_path / "a", monkeypatch, stub=True)
        run_a = make_cli(a, capsys, monkeypatch)
        run_a("new")
        run_a("move", "e4")
        b = load_module(tmp_path / "b", monkeypatch, stub=True)
        run_b = make_cli(b, capsys, monkeypatch)
        assert "No game in progress" in run_b("show").err
        assert (a.DATA / "game.pgn").exists() and not (b.DATA / "game.pgn").exists()
