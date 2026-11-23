"""Shared fixtures for the Chess Mentor test suite.

Every test runs against a throwaway data directory (CHESS_DATA_DIR in pytest's tmp_path), so no test can
read or write the user's own files. Engine-dependent behaviour is tested twice: deterministically with
StubEngine, and (marked `engine`) against a real Stockfish when one can be found.
"""
import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import chess
import chess.engine
import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "skills" / "chess-tutor" / "scripts" / "chess_ops.py"

# Well-known positions and games used across the tests.
START_FEN = chess.STARTING_FEN
FOOLS_MATE_MOVES = ["f3", "e5", "g4", "Qh4"]                      # 0-1, checkmate on move 2
FOOLS_MATE_BLACK_TO_MATE = "rnbqkbnr/pppp1ppp/8/4p3/6P1/5P2/PPPPP2P/RNBQKBNR b KQkq - 0 2"
STALEMATE_FEN = "7k/5Q2/6K1/8/8/8/8/8 b - - 0 1"                    # black to move, no legal moves
HANGS_QUEEN_FEN = "4k3/8/8/3q4/8/8/8/3QK3 w - - 0 1"                # Qd4?? loses the queen to ...Qxd4
BLUNDER_GAME = "1. e4 e5 2. Qh5 Nc6 3. Qxe5 Nxe5 4. d4 Nc6 *"       # 3.Qxe5?? hangs the queen
FRIED_LIVER = ("1. e4 e5 2. Nf3 Nc6 3. Bc4 Nf6 4. Ng5 d5 5. exd5 Nxd5 6. Nxf7 Kxf7 7. Qf3+ Ke6 8. Nc3 Nb4 "
               "9. O-O c6 10. d4 Kd7 11. Rd1 Nxc2 12. Bxd5 cxd5 13. Qxd5+ Ke8 *")
SHILLING = "1. e4 e5 2. Nf3 Nc6 3. Bc4 Nd4 4. Nxe5 Qg5 5. Nxf7 Qxg2 6. Rf1 Qxe4+ 7. Be2 Nf3# 0-1"


class Result:
    def __init__(self, code, out, err):
        self.code, self.out, self.err = code, out, err

    @property
    def text(self):
        return self.out + self.err

    def __repr__(self):
        return f"Result(code={self.code}, out={self.out!r}, err={self.err!r})"


class StubEngine:
    """Deterministic fake UCI engine: a 1-ply material search, with forced mates reported as mates.

    It is deliberately simple but behaves like an engine where the code under test cares: it scores
    from the side to move's point of view, returns the best move first in `pv`, supports multipv, and
    exposes `options`, `id` and `configure`.
    """
    VALUES = {chess.PAWN: 100, chess.KNIGHT: 300, chess.BISHOP: 300, chess.ROOK: 500, chess.QUEEN: 900}

    def __init__(self):
        self.id = {"name": "StubFish 1.0"}
        self.options = {"UCI_LimitStrength": SimpleNamespace(min=None, max=None),
                        "UCI_Elo": SimpleNamespace(min=1320, max=3190),
                        "Skill Level": SimpleNamespace(min=0, max=20)}
        self.configured = {}
        self.calls = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def configure(self, opts):
        self.configured.update(opts)

    def _material(self, board):
        return sum(self.VALUES.get(p.piece_type, 0) * (1 if p.color == chess.WHITE else -1)
                   for p in board.piece_map().values())

    def _ranked(self, board, root_moves=None):
        """[(score from side-to-move POV as chess.engine score, sort key, move)], best first."""
        out = []
        for mv in board.legal_moves:
            if root_moves is not None and mv not in root_moves:
                continue
            board.push(mv)
            if board.is_checkmate():
                mate_for_mover = True
                key = 10**6
                s = None
            else:
                mate_for_mover = False
                m = self._material(board)
                key = m if board.turn == chess.BLACK else -m      # after the push, turn flipped
                s = key
            board.pop()
            out.append((mate_for_mover, key, s, mv))
        out.sort(key=lambda t: -t[1])
        return out

    def analyse(self, board, limit, multipv=None, root_moves=None):
        self.calls += 1
        ranked = self._ranked(board, root_moves)
        infos = []
        for mate, key, s, mv in ranked[: (multipv or 1)]:
            score = chess.engine.Mate(1) if mate else chess.engine.Cp(s)
            infos.append({"score": chess.engine.PovScore(score, board.turn), "pv": [mv], "depth": 1})
        return infos if multipv else infos[0]

    def play(self, board, limit):
        self.calls += 1
        return SimpleNamespace(move=self._ranked(board)[0][3])


def load_module(tmp_path, monkeypatch, stub):
    """A fresh import of chess_ops.py bound to tmp_path/chess_data (module constants read the env at import)."""
    monkeypatch.setenv("CHESS_DATA_DIR", str(tmp_path / "chess_data"))
    monkeypatch.delenv("STOCKFISH_PATH", raising=False)
    spec = importlib.util.spec_from_file_location("chess_ops_under_test", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if stub:
        mod.stub = StubEngine()
        monkeypatch.setattr(mod, "open_engine", lambda: mod.stub)
        monkeypatch.setattr(mod, "find_stockfish", lambda cfg: "stub-engine")
    return mod


def make_cli(mod, capsys, monkeypatch):
    def run(*args):
        monkeypatch.setattr(sys, "argv", ["chess_ops.py", *map(str, args)])
        capsys.readouterr()
        try:
            mod.main()
            code = 0
        except SystemExit as e:
            code = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
        out, err = capsys.readouterr()
        return Result(code, out, err)
    return run


@pytest.fixture
def ops(tmp_path, monkeypatch):
    """The real module (no engine patches), data dir in tmp_path."""
    return load_module(tmp_path, monkeypatch, stub=False)


@pytest.fixture
def cli(ops, capsys, monkeypatch):
    return make_cli(ops, capsys, monkeypatch)


@pytest.fixture
def sops(tmp_path, monkeypatch):
    """The module with the stub engine patched in (`sops.stub`)."""
    return load_module(tmp_path, monkeypatch, stub=True)


@pytest.fixture
def scli(sops, capsys, monkeypatch):
    return make_cli(sops, capsys, monkeypatch)


# ------------------------------------------------------------------ PGN helpers
def pgn_text(moves="1. e4 e5 *", **headers):
    h = {"Event": "Test", "Site": "?", "Date": "2026.01.01", "Round": "-", "White": "A", "Black": "B", "Result": "*"}
    h.update(headers)
    return "\n".join(f'[{k} "{v}"]' for k, v in h.items()) + "\n\n" + moves + "\n\n"


def write_pgn(path, *games):
    """games: strings from pgn_text()."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(games), encoding="utf-8")
    return path


def play_moves(cli, *sans):
    for san in sans:
        r = cli("move", san)
        assert r.code == 0, r
    return r


# ------------------------------------------------------------------ real Stockfish
def find_real_stockfish():
    env = os.environ.get("STOCKFISH_PATH")
    if env and Path(env).is_file():
        return env
    found = shutil.which("stockfish")
    if found:
        return found
    d = ROOT / "stockfish"
    if d.is_dir():
        for p in sorted(d.glob("stockfish*")):
            if p.is_file() and (p.suffix.lower() == ".exe" or os.access(p, os.X_OK)):
                return str(p)
    return None


@pytest.fixture(scope="session")
def stockfish_path():
    path = find_real_stockfish()
    if not path:
        pytest.skip("no Stockfish found (set STOCKFISH_PATH, put it on PATH, or place it in ./stockfish)")
    return path


@pytest.fixture
def real(tmp_path, stockfish_path):
    """Runs the script as a subprocess against the real Stockfish in an isolated data dir."""
    data = tmp_path / "chess_data"
    env = dict(os.environ, CHESS_DATA_DIR=str(data), STOCKFISH_PATH=stockfish_path, PYTHONUTF8="1")

    def run(*args, timeout=180):
        p = subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], env=env, capture_output=True,
                           text=True, encoding="utf-8", timeout=timeout, cwd=str(tmp_path))
        return Result(p.returncode, p.stdout, p.stderr)
    run.data = data
    run.tmp = tmp_path
    return run
