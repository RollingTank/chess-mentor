"""Component tests for /init-chess support: `discover` and `profile` (stub engine for the sample)."""
import json
import os
import re

import chess
import pytest

from conftest import pgn_text, write_pgn

E4_LINE = "1. e4 e5 2. Nf3 Nc6 3. Bc4 Bc5"
D4_LINE = "1. d4 d5 2. c4 e6 3. Nc3 Nf6"
C4_LINE = "1. c4 e5 2. Nc3 Nf6 3. g3 d5"
MATE_LOSS = "1. f3 e5 2. g4 Qh4# 0-1"


def game(moves=E4_LINE, white="Me", black="Opp", result="1-0", date="2026.01.01", opening=None, we=None, be=None,
         tc=None, term=None, **extra):
    h = {"White": white, "Black": black, "Result": result, "Date": date}
    if opening:
        h["Opening"] = opening
    if we:
        h["WhiteElo"] = str(we)
    if be:
        h["BlackElo"] = str(be)
    if tc:
        h["TimeControl"] = tc
    if term:
        h["Termination"] = term
    h.update(extra)
    return pgn_text(moves + " " + result, **h)


def profile_json(m):
    return json.loads(m.PROFILE.read_text(encoding="utf-8"))


# ------------------------------------------------------------------ discover
@pytest.fixture
def tree(tmp_path):
    root = tmp_path / "proj"
    write_pgn(root / "my games" / "a.pgn", *[game() for _ in range(3)])
    write_pgn(root / "study" / "masters.pgn", game(white="Kasparov", black="Karpov"), game(white="Fischer", black="Spassky"))
    (root / "study" / "tactics.epd").write_text("8/8/8/8/8/8/8/K6k w - - bm Ka2;\n")
    for name in ("Silman_Endgame_Course.pdf", "My_System.pdf"):
        (root / "books").mkdir(parents=True, exist_ok=True)
        (root / "books" / name).write_bytes(b"%PDF-" + b"x" * 2000)
    (root / "books" / "sub").mkdir()
    (root / "books" / "sub" / "Logical_Chess.epub").write_bytes(b"PK" + b"x" * 100)
    (root / "notes" / "chess notes").mkdir(parents=True)
    (root / "notes" / "chess notes" / "openings.md").write_text("# my openings")
    (root / "random").mkdir()
    (root / "random" / "readme.md").write_text("not chess")
    (root / "readme.md").write_text("project readme")
    for skipped in (".venv/lib", "node_modules/x", "chess_data", "stockfish", ".git/objects", ".claude/skills"):
        write_pgn(root / skipped / "ignored.pgn", game())
    write_pgn(root / "d1" / "d2" / "d3" / "d4" / "d5" / "d6" / "deep.pgn", game())
    return root


class TestDiscover:
    def test_finds_game_folders_with_counts_and_hints(self, scli, tree):
        out = scli("discover", tree).out
        assert re.search(r"my games/\s+1 file\(s\)\s+3 game\(s\)\s+\[name suggests games\]", out)
        assert re.search(r"study/\s+1 file\(s\)\s+2 game\(s\)", out)
        assert "a.pgn (3 games)" in out

    def test_likely_player_games_are_listed_first(self, scli, tree):
        out = scli("discover", tree).out
        assert out.index("my games/") < out.index("study/")

    def test_finds_books_and_study_files(self, scli, tree):
        out = scli("discover", tree).out
        for name in ("Silman_Endgame_Course.pdf", "My_System.pdf", "Logical_Chess.epub", "tactics.epd", "openings.md"):
            assert name in out
        assert re.search(r"books/\s+2 file\(s\) \(pdf 2\)", out)

    def test_notes_only_count_in_chess_looking_folders(self, scli, tree):
        out = scli("discover", tree).out
        assert "readme.md" not in out

    @pytest.mark.parametrize("skipped", [".venv", "node_modules", "chess_data", "stockfish", ".git", ".claude"])
    def test_skips_tool_and_data_folders(self, scli, tree, skipped):
        out = scli("discover", tree).out
        assert f"{skipped}/" not in out

    def test_depth_limit(self, scli, tree):
        assert "deep.pgn" not in scli("discover", tree).out
        assert "deep.pgn" in scli("discover", tree, "--depth", "8").out

    def test_defaults_to_the_current_directory(self, scli, tree, monkeypatch):
        monkeypatch.chdir(tree)
        out = scli("discover").out
        assert "my games/" in out and "Searched" in out

    def test_never_leaves_the_directory_it_was_given(self, scli, tree, tmp_path):
        """Files next to (outside) the searched root must not appear."""
        write_pgn(tmp_path / "outside" / "outside_games.pgn", game())
        (tmp_path / "outside" / "Outside_Book.pdf").write_bytes(b"x")
        out = scli("discover", tree).out
        assert "outside_games" not in out and "Outside_Book" not in out

    def test_empty_directory(self, scli, tmp_path):
        (tmp_path / "empty").mkdir()
        out = scli("discover", tmp_path / "empty").out
        assert out.count("(none found)") == 2

    def test_not_a_directory(self, scli, tmp_path):
        r = scli("discover", tmp_path / "missing")
        assert r.code == 2 and "not a directory" in r.err

    def test_uppercase_extensions_are_found(self, scli, tmp_path):
        write_pgn(tmp_path / "g" / "UPPER.PGN", game())
        (tmp_path / "g" / "BOOK.PDF").write_bytes(b"x")
        out = scli("discover", tmp_path / "g").out
        assert "UPPER.PGN" in out and "BOOK.PDF" in out

    def test_long_resource_lists_are_truncated(self, scli, tmp_path):
        (tmp_path / "books").mkdir()
        for i in range(12):
            (tmp_path / "books" / f"b{i:02}.pdf").write_bytes(b"x")
        out = scli("discover", tmp_path, "--list", "3").out
        assert "and 9 more" in out

    def test_does_not_follow_symlinks_out_of_the_tree(self, scli, tmp_path):
        outside = tmp_path / "outside"
        write_pgn(outside / "secret.pgn", game())
        root = tmp_path / "root"
        root.mkdir()
        try:
            os.symlink(outside, root / "link", target_is_directory=True)
        except (OSError, NotImplementedError):
            pytest.skip("symlinks not permitted here")
        assert "secret.pgn" not in scli("discover", root).out


# ------------------------------------------------------------------ profile
@pytest.fixture
def games_dir(tmp_path):
    return tmp_path / "games"


def make_games(games_dir, *games, name="all.pgn"):
    return write_pgn(games_dir / name, *games)


class TestProfileBasics:
    def test_auto_detects_the_player_and_counts_results(self, scli, sops, games_dir):
        make_games(games_dir,
                   game(white="Me", black="A", result="1-0", date="2026.01.01"),
                   game(white="B", black="Me", result="1-0", date="2026.01.02"),        # a loss as Black
                   game(white="Me", black="C", result="1/2-1/2", date="2026.01.03"),
                   game(white="D", black="Me", result="0-1", date="2026.01.04"))        # a win as Black
        r = scli("profile", games_dir, "--engine-games", "0")
        assert r.code == 0 and "Player identified as 'me' (4 of 4 games)" in r.out
        p = profile_json(sops)
        assert p["overall"] == {"games": 4, "wins": 2, "draws": 1, "losses": 1, "score_pct": 62.5}
        assert p["as_white"]["games"] == 2 and p["as_black"]["games"] == 2
        assert p["as_white"]["score_pct"] == 75.0 and p["as_black"]["score_pct"] == 50.0
        assert p["date_range"] == ["2026.01.01", "2026.01.04"]
        assert p["games_in_folder"] == 4 and p["games_used"] == 4 and p["player_names"] == ["me"]

    def test_schema(self, scli, sops, games_dir):
        make_games(games_dir, game(we=1500, be=1400, tc="180+0"), game(date="2026.01.02", we=1510, be=1400, tc="180+0"))
        scli("profile", games_dir, "--engine-games", "0")
        p = profile_json(sops)
        assert {"generated", "folder", "pgn_files", "games_in_folder", "games_used", "player_names", "skipped",
                "date_range", "overall", "as_white", "as_black", "recent_20", "time_controls", "rating", "openings",
                "weak_openings", "strong_openings", "endings", "engine_sample"} <= set(p)
        assert set(p["openings"]) == {"white", "black_vs_e4", "black_vs_d4", "black_vs_other"}

    def test_ambiguous_player_asks_for_a_name(self, scli, sops, games_dir):
        make_games(games_dir, *[game(white=f"P{i}", black=f"Q{i}") for i in range(6)])
        r = scli("profile", games_dir, "--engine-games", "0")
        assert r.code == 2 and "Cannot tell which player is you" in r.out and "--player" in r.err
        assert not sops.PROFILE.exists()

    def test_explicit_player_and_multiple_usernames(self, scli, sops, games_dir):
        make_games(games_dir, game(white="alice", black="X"), game(white="Y", black="Alice_alt"),
                   game(white="Z", black="W"), game(white="V", black="U"))
        scli("profile", games_dir, "--player", "alice, Alice_alt", "--engine-games", "0")
        p = profile_json(sops)
        assert p["games_used"] == 2 and p["player_names"] == ["alice", "alice_alt"]

    def test_player_names_match_case_insensitively(self, scli, sops, games_dir):
        make_games(games_dir, game(white="ME", black="x"))
        assert scli("profile", games_dir, "--player", "me", "--engine-games", "0").code == 0

    def test_partial_name_is_a_fallback(self, scli, sops, games_dir):
        make_games(games_dir, game(white="TestPlayer99", black="x"), game(white="y", black="TestPlayer99"))
        r = scli("profile", games_dir, "--player", "player99", "--engine-games", "0")
        assert r.code == 0 and profile_json(sops)["games_used"] == 2

    def test_unknown_player(self, scli, games_dir):
        make_games(games_dir, game())
        r = scli("profile", games_dir, "--player", "nobody", "--engine-games", "0")
        assert r.code == 2 and "No games found for player" in r.err

    def test_masters_collection_is_not_mistaken_for_the_user(self, scli, games_dir):
        make_games(games_dir, *[game(white=f"Master{i}", black=f"Rival{i}") for i in range(10)])
        assert scli("profile", games_dir, "--engine-games", "0").code == 2

    def test_missing_folder_and_empty_folder(self, scli, tmp_path):
        assert "not found" in scli("profile", tmp_path / "nope").err
        (tmp_path / "empty").mkdir()
        r = scli("profile", tmp_path / "empty")
        assert r.code == 2 and "No PGN games found" in r.err

    def test_accepts_a_single_pgn_file(self, scli, sops, games_dir):
        p = make_games(games_dir, game(), game(date="2026.01.02"))
        assert scli("profile", p, "--engine-games", "0").code == 0
        assert profile_json(sops)["games_used"] == 2

    def test_reads_pgns_in_subfolders(self, scli, sops, games_dir):
        make_games(games_dir, game(), name="2025/a.pgn")
        make_games(games_dir, game(date="2026.02.02"), name="2026/b.pgn")
        scli("profile", games_dir, "--engine-games", "0")
        p = profile_json(sops)
        assert p["pgn_files"] == 2 and p["games_used"] == 2


class TestProfileFiltering:
    def test_duplicates_across_files_are_counted_once(self, scli, sops, games_dir):
        g = game(date="2026.01.01")
        make_games(games_dir, g, name="a.pgn")
        make_games(games_dir, g, game(date="2026.01.05", moves=D4_LINE), name="b.pgn")
        r = scli("profile", games_dir, "--engine-games", "0")
        p = profile_json(sops)
        assert p["games_used"] == 2 and p["skipped"] == {"duplicate": 1}
        assert "Skipped: {'duplicate': 1}" in r.out

    def test_games_without_moves_are_skipped(self, scli, sops, games_dir):
        make_games(games_dir, game(), pgn_text("*", White="Me", Black="X", Result="*"))
        scli("profile", games_dir, "--engine-games", "0")
        p = profile_json(sops)
        assert p["games_used"] == 1 and p["skipped"] == {"no moves": 1}

    def test_folder_where_every_game_is_empty(self, scli, games_dir):
        make_games(games_dir, pgn_text("*", White="Me", Black="X"), pgn_text("*", White="Me", Black="Y"))
        r = scli("profile", games_dir, "--engine-games", "0")
        assert r.code == 2 and "No usable games" in r.err

    def test_unfinished_games_are_used_but_not_scored(self, scli, sops, games_dir):
        make_games(games_dir, game(result="1-0"), game(result="*", date="2026.01.02", moves=D4_LINE))
        scli("profile", games_dir, "--engine-games", "0")
        p = profile_json(sops)
        assert p["games_used"] == 2 and p["overall"]["games"] == 1

    def test_max_games_keeps_the_most_recent(self, scli, sops, games_dir):
        make_games(games_dir, *[game(date=f"2026.01.{d:02}", moves=E4_LINE) for d in range(1, 9)])
        r = scli("profile", games_dir, "--engine-games", "0", "--max-games", "3")
        assert "Using the 3 most recent of 8" in r.out
        p = profile_json(sops)
        assert p["games_used"] == 3 and p["date_range"] == ["2026.01.06", "2026.01.08"]


class TestProfileStatistics:
    def test_time_control_classes(self, scli, sops, games_dir):
        make_games(games_dir,
                   game(tc="60", result="1-0"), game(tc="180+0", result="0-1", date="2026.01.02"),
                   game(tc="600+0", result="1-0", date="2026.01.03"), game(tc="1800", result="1-0", date="2026.01.04"),
                   game(tc="1/86400", result="1/2-1/2", date="2026.01.05"), game(result="1-0", date="2026.01.06"))
        scli("profile", games_dir, "--engine-games", "0")
        tcs = profile_json(sops)["time_controls"]
        assert set(tcs) == {"bullet", "blitz", "rapid", "classical", "correspondence", "unknown"}
        assert tcs["blitz"]["score_pct"] == 0.0 and tcs["rapid"]["score_pct"] == 100.0

    def test_rating_summary_uses_the_most_played_time_control(self, scli, sops, games_dir):
        gs = [game(white="Me", black="O", we=1400 + 10 * i, be=1380, tc="180+0", date=f"2026.01.{i + 1:02}") for i in range(10)]
        gs.append(game(white="Me", black="O", we=2000, be=2000, tc="1800", date="2026.01.20"))       # one classical game
        make_games(games_dir, *gs)
        scli("profile", games_dir, "--engine-games", "0")
        r = profile_json(sops)["rating"]
        assert r["class"] == "blitz" and r["rated_games"] == 10
        assert (r["first"], r["last"], r["peak"]) == (1400, 1490, 1490)
        assert r["recent_avg"] == 1445 and r["previous_avg"] is None and r["avg_opponent"] == 1380

    def test_rating_trend_compares_recent_with_previous(self, scli, sops, games_dir):
        gs = [game(we=1000 + 20 * i, be=1000, tc="180+0", date=f"2026.{1 + i // 28:02}.{i % 28 + 1:02}") for i in range(40)]
        make_games(games_dir, *gs)
        scli("profile", games_dir, "--engine-games", "0")
        r = profile_json(sops)["rating"]
        assert r["recent_avg"] > r["previous_avg"]

    def test_no_ratings_in_the_headers(self, scli, sops, games_dir):
        make_games(games_dir, game(), game(date="2026.01.02"))
        r = scli("profile", games_dir, "--engine-games", "0")
        assert r.code == 0 and "rating" not in profile_json(sops) and "Header rating" not in r.out

    def test_non_numeric_ratings_are_ignored(self, scli, sops, games_dir):
        make_games(games_dir, game(we="?", be="?"), game(date="2026.01.02", WhiteElo="abc"))
        assert scli("profile", games_dir, "--engine-games", "0").code == 0

    def test_opening_tables_split_by_colour_and_first_move(self, scli, sops, games_dir):
        make_games(games_dir,
                   game(white="Me", black="A", opening="Italian Game: Classical", moves=E4_LINE, result="1-0"),
                   game(white="Me", black="B", opening="Italian Game", moves=E4_LINE, result="0-1", date="2026.01.02"),
                   game(white="C", black="Me", opening="Sicilian Defense: Najdorf", moves="1. e4 c5 2. Nf3 d6", result="0-1", date="2026.01.03"),
                   game(white="D", black="Me", opening="Queen's Gambit Declined", moves=D4_LINE, result="1/2-1/2", date="2026.01.04"),
                   game(white="E", black="Me", opening="English Opening", moves=C4_LINE, result="0-1", date="2026.01.05"))
        scli("profile", games_dir, "--engine-games", "0")
        o = profile_json(sops)["openings"]
        assert o["white"][0] == {"name": "Italian Game", "games": 2, "wins": 1, "draws": 0, "losses": 1, "score_pct": 50.0}
        assert [x["name"] for x in o["black_vs_e4"]] == ["Sicilian Defense"]
        assert [x["name"] for x in o["black_vs_d4"]] == ["Queen's Gambit Declined"]
        assert [x["name"] for x in o["black_vs_other"]] == ["English Opening"]

    def test_weak_and_strong_openings_need_five_games(self, scli, sops, games_dir):
        gs = ([game(opening="Scotch Game", result="0-1", date=f"2026.01.{i:02}") for i in range(1, 6)]            # 5 losses
              + [game(opening="Italian Game", result="1-0", date=f"2026.02.{i:02}") for i in range(1, 6)]         # 5 wins
              + [game(opening="Vienna Game", result="0-1", date=f"2026.03.{i:02}") for i in range(1, 5)])         # only 4
        make_games(games_dir, *gs)
        scli("profile", games_dir, "--engine-games", "0")
        p = profile_json(sops)
        assert [w["name"] for w in p["weak_openings"]] == ["Scotch Game"]
        assert p["weak_openings"][0]["side"] == "white" and p["weak_openings"][0]["score_pct"] == 0.0
        assert [w["name"] for w in p["strong_openings"]] == ["Italian Game"]

    def test_openings_fall_back_to_moves_without_a_name(self, scli, sops, games_dir):
        make_games(games_dir, game(moves="1. e4 e5 2. Nf3 Nc6 3. Bc4 Bc5"))
        scli("profile", games_dir, "--engine-games", "0")
        assert profile_json(sops)["openings"]["white"][0]["name"] == "e4 e5 Nf3 Nc6 Bc4"

    def test_chesscom_style_opening_from_url(self, scli, sops, games_dir):
        make_games(games_dir, game(ECOUrl="https://www.chess.com/openings/Italian-Game-Giuoco-Piano-4.c3-Nf6"))
        scli("profile", games_dir, "--engine-games", "0")
        assert profile_json(sops)["openings"]["white"][0]["name"] == "Italian Game"

    def test_how_games_end(self, scli, sops, games_dir):
        make_games(games_dir,
                   game(moves=MATE_LOSS, white="Me", black="A", result="0-1", date="2026.01.01"),               # mated in 2
                   game(white="B", black="Me", result="1-0", term="Time forfeit", date="2026.01.02"),         # lost on time
                   game(white="Me", black="C", result="0-1", term="Opp won on time", date="2026.01.03"),      # lost on time
                   game(white="Me", black="D", result="1-0", term="Time forfeit", date="2026.01.04"),         # won on time
                   game(white="Me", black="E", result="1-0", moves="1. e4 e5 2. Qh5 Nc6 3. Bc4 Nf6 4. Qxf7#", date="2026.01.05"))
        scli("profile", games_dir, "--engine-games", "0")
        e = profile_json(sops)["endings"]
        assert e["losses"] == 3 and e["losses_on_time"] == 2 and e["losses_by_checkmate"] == 1
        assert e["short_losses_under_25_moves"] == 3 and e["wins_by_checkmate"] == 1 and e["wins_on_time"] == 1

    def test_unknown_dates_do_not_crash(self, scli, sops, games_dir):
        make_games(games_dir, game(date="????.??.??"), game(date="????.??.??", moves=D4_LINE))
        r = scli("profile", games_dir, "--engine-games", "0")
        assert r.code == 0 and profile_json(sops)["date_range"] is None

    def test_lichess_utcdate_is_used_when_date_is_unknown(self, scli, sops, games_dir):
        make_games(games_dir, game(date="????.??.??", UTCDate="2025.05.05"))
        scli("profile", games_dir, "--engine-games", "0")
        assert profile_json(sops)["date_range"] == ["2025.05.05", "2025.05.05"]

    def test_recent_form_covers_the_last_twenty_games(self, scli, sops, games_dir):
        gs = [game(result="0-1", date=f"2025.01.{i + 1:02}") for i in range(10)]
        gs += [game(result="1-0", date=f"2026.01.{i + 1:02}") for i in range(20)]
        make_games(games_dir, *gs)
        scli("profile", games_dir, "--engine-games", "0")
        p = profile_json(sops)
        assert p["recent_20"]["score_pct"] == 100.0 and p["overall"]["score_pct"] < 100

    def test_console_summary_is_printed(self, scli, games_dir):
        make_games(games_dir, game(we=1500, be=1400, tc="180+0", opening="Italian Game"))
        out = scli("profile", games_dir, "--engine-games", "0").out
        for needle in ("PLAYER PROFILE", "Record: +1 =0 -0", "Header rating (blitz", "Time controls:", "White: Italian Game",
                       "Endings:", "profile.json"):
            assert needle in out


class TestProfileEngineSample:
    def long_game(self, date, white="Me", black="Opp", result="1-0", opening="Italian Game"):
        moves = "1. e4 e5 2. Nf3 Nc6 3. Bc4 Bc5 4. c3 Nf6 5. d3 d6 6. O-O O-O 7. Re1 a6 8. Bb3 Ba7 9. Nbd2 h6 10. Nf1 Re8 11. Ng3 Be6 12. Bxe6 *"
        return game(moves=moves, white=white, black=black, result=result, date=date, opening=opening)

    def test_samples_the_most_recent_games_and_aggregates(self, scli, sops, games_dir):
        make_games(games_dir, *[self.long_game(f"2026.01.{d:02}") for d in range(1, 7)])
        r = scli("profile", games_dir, "--engine-games", "3", "--depth", "8")
        assert r.code == 0 and "Running Stockfish (depth 8) over 3 recent game(s)" in r.out
        s = profile_json(sops)["engine_sample"]
        assert s["games"] == 3 and s["depth"] == 8 and len(s["per_game"]) == 3
        assert [g["date"] for g in s["per_game"]] == ["2026.01.04", "2026.01.05", "2026.01.06"]
        assert s["acpl"] is not None and set(s["per_game_avg"]) == {"inaccuracies", "mistakes", "blunders"}
        assert "Engine sample (3 recent games" in r.out

    def test_sampled_games_become_the_history_baseline(self, scli, sops, games_dir):
        make_games(games_dir, *[self.long_game(f"2026.01.{d:02}") for d in range(1, 4)])
        scli("profile", games_dir, "--engine-games", "3", "--depth", "6")
        recs = [json.loads(l) for l in sops.ANALYSES.read_text(encoding="utf-8").splitlines()]
        assert [r["date"] for r in recs] == ["2026.01.01", "2026.01.02", "2026.01.03"]
        assert all(r["color"] == "white" and r["depth"] == 6 and "phases" in r for r in recs)
        assert "2026.01.03" in scli("history").out                 # history shows game dates, not today's date

    def test_baseline_feeds_the_analyze_comparison(self, scli, sops, games_dir, tmp_path):
        make_games(games_dir, *[self.long_game(f"2026.01.{d:02}") for d in range(1, 3)])
        scli("profile", games_dir, "--engine-games", "2", "--depth", "6")
        different = ("1. d4 d5 2. c4 e6 3. Nc3 Nf6 4. Bg5 Be7 5. e3 O-O 6. Nf3 h6 7. Bh4 b6 8. cxd5 exd5 *")   # not a sampled game
        new_game = write_pgn(tmp_path / "new.pgn", game(moves=different, black="Newcomer", date="2026.05.05"))
        out = scli("analyze", new_game, "--color", "white", "--depth", "6").out
        assert "COMPARED WITH LAST ANALYSED GAME AS WHITE (2026.01.02, Me - Opp)" in out

    def test_resampling_does_not_duplicate_history(self, scli, sops, games_dir):
        make_games(games_dir, *[self.long_game(f"2026.01.{d:02}") for d in range(1, 3)])
        scli("profile", games_dir, "--engine-games", "2", "--depth", "6")
        scli("profile", games_dir, "--engine-games", "2", "--depth", "6")
        assert len(sops.ANALYSES.read_text(encoding="utf-8").splitlines()) == 2

    def test_no_history_flag(self, scli, sops, games_dir):
        make_games(games_dir, self.long_game("2026.01.01"))
        scli("profile", games_dir, "--engine-games", "1", "--depth", "6", "--no-history")
        assert not sops.ANALYSES.exists() and profile_json(sops)["engine_sample"]["games"] == 1

    def test_engine_games_zero_skips_the_engine(self, scli, sops, games_dir):
        make_games(games_dir, self.long_game("2026.01.01"))
        scli("profile", games_dir, "--engine-games", "0")
        assert profile_json(sops)["engine_sample"] is None and sops.stub.calls == 0

    def test_short_games_are_not_sampled(self, scli, sops, games_dir):
        make_games(games_dir, game(), game(date="2026.01.02"))                  # 6 plies each
        r = scli("profile", games_dir, "--engine-games", "5", "--depth", "6")
        assert r.code == 0 and profile_json(sops)["engine_sample"]["games"] == 0
        assert "Engine sample" not in r.out
        r = scli("profile", games_dir, "--engine-games", "5", "--depth", "6", "--min-ply", "4")
        assert profile_json(sops)["engine_sample"]["games"] == 2

    def test_missing_engine_is_not_fatal(self, cli, ops, games_dir, monkeypatch):
        monkeypatch.setattr(ops.shutil, "which", lambda name: None)
        make_games(games_dir, self.long_game("2026.01.01"))
        r = cli("profile", games_dir, "--engine-games", "3")
        assert r.code == 0 and "Engine not configured: skipping the engine sample" in r.out
        assert json.loads(ops.PROFILE.read_text(encoding="utf-8"))["engine_sample"] is None

    def test_black_games_are_analysed_from_blacks_point_of_view(self, scli, sops, games_dir):
        make_games(games_dir, self.long_game("2026.01.01", white="Opp", black="Me", result="0-1"))
        scli("profile", games_dir, "--player", "Me", "--engine-games", "1", "--depth", "6")
        assert profile_json(sops)["engine_sample"]["per_game"][0]["color"] == "black"

    def test_worst_moments_and_conversion_stats(self, scli, sops, games_dir):
        """The user (White) drops the queen on move 3 of an otherwise long game and then loses."""
        moves = BLUNDER_LONG = ("1. e4 e5 2. Qh5 Nc6 3. Qxe5 Nxe5 4. d4 Ng6 5. Nf3 Nf6 6. Bd3 d5 7. e5 Ne4 8. O-O Be7 "
                                "9. c4 O-O 10. cxd5 Qxd5 *")
        make_games(games_dir, game(moves=moves, result="0-1", date="2026.01.01"))
        scli("profile", games_dir, "--engine-games", "1", "--depth", "6")
        s = profile_json(sops)["engine_sample"]
        worst = s["worst_moments"][0]
        assert worst["san"].startswith("Qxe5") and worst["verdict"] == "blunder" and worst["loss"] >= 500
        assert chess.Board(worst["fen"]).is_valid() and worst["opp"] == "Opp"
        assert s["avg_first_error_move"] is not None and s["avg_first_error_move"] <= 3

    def test_failed_conversions_and_escapes_are_detected(self, scli, sops, games_dir):
        """Game 1: White wins Black's queen but only draws. Game 2: White hangs the queen but still draws."""
        make_games(games_dir,
                   game(moves="1. e4 e5 2. Nf3 Qh4 3. Nxh4 Nc6", result="1/2-1/2", date="2026.01.01"),
                   game(moves="1. e4 e5 2. Qh5 Nc6 3. Qxe5 Nxe5", result="1/2-1/2", date="2026.01.02"))
        r = scli("profile", games_dir, "--engine-games", "2", "--depth", "6", "--min-ply", "4")
        s = profile_json(sops)["engine_sample"]
        assert [f["date"] for f in s["failed_conversions"]] == ["2026.01.01"] and s["failed_conversions"][0]["peak_cp"] >= 300
        assert [e["date"] for e in s["escapes"]] == ["2026.01.02"] and s["escapes"][0]["low_cp"] <= -300
        assert "failed conversions 1; escapes 1" in r.out

    def test_won_and_lost_games_are_not_conversion_failures(self, scli, sops, games_dir):
        make_games(games_dir,
                   game(moves="1. e4 e5 2. Nf3 Qh4 3. Nxh4 Nc6", result="1-0", date="2026.01.01"),               # converted
                   game(moves="1. e4 e5 2. Qh5 Nc6 3. Qxe5 Nxe5", result="0-1", date="2026.01.02"))              # lost
        scli("profile", games_dir, "--engine-games", "2", "--depth", "6", "--min-ply", "4")
        s = profile_json(sops)["engine_sample"]
        assert s["failed_conversions"] == [] and s["escapes"] == []

    def test_rerun_keeps_the_previous_profile(self, scli, sops, games_dir):
        make_games(games_dir, game())
        scli("profile", games_dir, "--engine-games", "0")
        assert not (sops.DATA / "profile.prev.json").exists()
        make_games(games_dir, game(), game(date="2026.01.02", moves=D4_LINE))
        scli("profile", games_dir, "--engine-games", "0")
        prev = json.loads((sops.DATA / "profile.prev.json").read_text(encoding="utf-8"))
        assert prev["games_used"] == 1 and profile_json(sops)["games_used"] == 2
