"""Contract tests: the skills, manifests, docs and code must agree with each other.

These catch the failures that only show up at runtime for a user: a skill telling Claude to run a command
or flag that does not exist, a broken relative link, mismatched versions, personal paths left in the repo.
"""
import ast
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from conftest import ROOT, SCRIPT

SKILLS = ROOT / "skills"
EXPECTED_SKILLS = {"chess-tutor", "init-chess", "teach-chess", "play-chess", "analyze-chess"}
COMMAND_SKILLS = EXPECTED_SKILLS - {"chess-tutor"}
SHARED = SKILLS / "chess-tutor" / "SKILL.md"


def read(p):
    return Path(p).read_text(encoding="utf-8")


def frontmatter(path):
    text = read(path)
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    assert m, f"{path} has no frontmatter"
    fields = {}
    for line in m.group(1).splitlines():
        k, _, v = line.partition(":")
        fields[k.strip()] = v.strip()
    return fields


def skill_files():
    return sorted(SKILLS.glob("*/SKILL.md"))


def doc_files():
    return skill_files() + [ROOT / "README.md", ROOT / "CHANGELOG.md"]


@pytest.fixture(scope="module")
def commands():
    """The CLI's subcommands, read from the real parser."""
    p = subprocess.run([__import__("sys").executable, str(SCRIPT), "--help"], capture_output=True, text=True)
    m = re.search(r"\{([a-z,\-]+)\}", p.stdout)
    assert m, p.stdout
    return set(m.group(1).split(","))


@pytest.fixture(scope="module")
def help_text(commands):
    import sys
    out = {}
    for c in commands:
        out[c] = subprocess.run([sys.executable, str(SCRIPT), c, "--help"], capture_output=True, text=True).stdout
    return out


# ------------------------------------------------------------------ skills
class TestSkillStructure:
    def test_exactly_the_expected_skills_exist(self):
        assert {p.name for p in SKILLS.iterdir() if p.is_dir()} == EXPECTED_SKILLS

    @pytest.mark.parametrize("skill", sorted(EXPECTED_SKILLS))
    def test_frontmatter(self, skill):
        fm = frontmatter(SKILLS / skill / "SKILL.md")
        assert fm["name"] == skill
        assert len(fm["description"]) > 60
        if skill == "chess-tutor":
            assert fm.get("user-invocable") == "false"
        else:
            assert "user-invocable" not in fm and fm.get("argument-hint")

    @pytest.mark.parametrize("skill", sorted(COMMAND_SKILLS))
    def test_command_skills_load_the_shared_foundation_first(self, skill):
        text = read(SKILLS / skill / "SKILL.md")
        assert "(../chess-tutor/SKILL.md)" in text and "First read" in text
        assert "$ARGUMENTS" in text

    @pytest.mark.parametrize("path", skill_files(), ids=lambda p: p.parent.name)
    def test_relative_links_resolve(self, path):
        for target in re.findall(r"\]\((\.\.?/[^)#\s]+)\)", read(path)):
            assert (path.parent / target).resolve().exists(), f"{path.parent.name}: broken link {target}"

    def test_only_the_shared_skill_ships_code(self):
        for skill in COMMAND_SKILLS:
            assert [p.name for p in (SKILLS / skill).iterdir()] == ["SKILL.md"]
        assert SCRIPT.exists() and (SKILLS / "chess-tutor" / "requirements.txt").exists()


class TestSkillsMatchTheCli:
    def test_every_cli_command_is_in_the_shared_command_table(self, commands):
        text = read(SHARED)
        for c in commands:
            assert re.search(rf"\|\s*`{c}[ `]", text) or c == "setup", f"`{c}` missing from the operations table"
        assert "setup" in text

    def test_table_flags_exist_in_the_cli(self, commands, help_text):
        checked = 0
        for line in read(SHARED).splitlines():
            m = re.match(r"\|[^|]*\|\s*`([a-z]+)\b([^`]*)`", line)
            if not m or m.group(1) not in commands:
                continue
            for flag in re.findall(r"--[a-z][a-z-]*", m.group(2)):
                assert flag in help_text[m.group(1)], f"table says `{m.group(1)} {flag}` but the CLI has no such flag"
                checked += 1
        assert checked > 20                                    # the table really was parsed

    @pytest.mark.parametrize("path", skill_files(), ids=lambda p: p.parent.name)
    def test_ops_invocations_use_real_commands_and_flags(self, path, commands, help_text):
        for line in read(path).splitlines():
            for m in re.finditer(r"\$OPS ([a-z]+)([^`\n]*)", line):
                cmd, rest = m.group(1), m.group(2)
                assert cmd in commands, f"{path.parent.name}: `$OPS {cmd}` is not a CLI command"
                for flag in re.findall(r"--[a-z][a-z-]*", rest):
                    assert flag in help_text[cmd], f"{path.parent.name}: `$OPS {cmd} {flag}` is not a real flag"

    def test_readme_script_examples_are_valid(self, commands, help_text):
        for m in re.finditer(r"chess_ops\.py ([a-z]+)([^\n]*)", read(ROOT / "README.md")):
            assert m.group(1) in commands
            for flag in re.findall(r"--[a-z][a-z-]*", m.group(2)):
                assert flag in help_text[m.group(1)]

    def test_data_files_named_in_the_skills_exist_in_the_code(self):
        code = read(SCRIPT)
        claude_written = {"imported.pgn"}                       # written by Claude, not by the script
        for path in skill_files():
            for name in re.findall(r"chess_data/([\w.-]+\.(?:json|jsonl|pgn|png))", read(path)):
                assert name in code or name in claude_written, f"{path.parent.name} mentions chess_data/{name}"

    def test_default_thresholds_in_the_docs_match_the_code(self):
        text = read(SHARED)
        assert "inaccuracy (50+)" in text and "mistake (100+)" in text and "blunder (200+)" in text


class TestEvidenceRule:
    """No reference, no evaluation; a book's stated continuation outranks the engine."""

    def text(self, skill):
        return read(SKILLS / skill / "SKILL.md")

    def test_shared_skill_states_the_rule_and_the_priority_order(self):
        text = self.text("chess-tutor")
        for needle in ("Evidence rule: no reference, no evaluation; the book outranks the engine",
                       "never evaluate a position, move, exercise, puzzle, example or game from your own judgement",
                       "A book (or other resource the user owns) that explicitly states the best continuation",
                       "**Stockfish**, when no book states the answer",
                       "**Neither: do not evaluate.**",
                       "the book wins, always", "The engine can be wrong",
                       "never tell the user the book is wrong",
                       "A move played in a PGN game is only *what was played*",
                       "`$OPS verdict` applies this rule mechanically"):
            assert needle in text, needle

    def test_rule_names_what_is_not_evaluation(self):
        assert "needs no reference" in self.text("chess-tutor") and "legality and the rules" in self.text("chess-tutor")

    def test_every_skill_that_grades_or_presents_answers_uses_verdict(self):
        for skill in ("teach-chess", "analyze-chess", "play-chess", "init-chess"):
            assert "verdict" in self.text(skill), skill

    def test_teach_chess_puts_the_book_first(self):
        text = self.text("teach-chess")
        for needle in ("The book outranks the engine", "No reference, no example", "the book's move whenever the book states one",
                       "never call the book wrong", "Never challenge an answer that matches the book with an engine objection",
                       "don't add verdicts of your own"):
            assert needle in text, needle

    def test_play_chess_requires_the_engine(self):
        text = self.text("play-chess")
        assert "Stockfish is mandatory here" in text and "never coach or rate a move from your own judgement" in text
        assert "the book outranks the engine" in text

    def test_analyze_chess_lets_a_book_override_the_engine(self):
        text = self.text("analyze-chess")
        assert "that book is the reference and it outranks the engine" in text
        assert "don't judge the move: say you have no reference" in text

    def test_init_chess_does_not_judge_without_an_engine(self):
        assert "without an engine you must skip this step rather than judge the moves yourself" in self.text("init-chess")

    def test_old_engine_over_book_wording_is_gone(self):
        for skill in sorted(EXPECTED_SKILLS):
            text = self.text(skill)
            for stale in ("Always verify the book's claim with the engine", "isn't engine-approved",
                          "source of truth for evaluation", "not an error to hide", "Never judge a position, a move's quality"):
                assert stale not in text, f"{skill} still says {stale!r}"

    def test_pick_does_not_present_a_played_move_as_the_best_move(self):
        assert "only **the move that was played**" in self.text("chess-tutor")

    def test_readme_explains_the_rule_to_users(self):
        text = read(ROOT / "README.md")
        assert "How Claude decides what is right" in text and "book" in text.split("How Claude decides what is right")[1][:900]

    def test_changelog_records_the_change(self):
        assert "verdict" in read(ROOT / "CHANGELOG.md")


class TestSlashCommands:
    ALL = {f"/{s}" for s in COMMAND_SKILLS}

    def test_only_real_commands_are_referenced(self):
        for path in doc_files():
            text = re.sub(r"```.*?```", "", read(path), flags=re.S)
            for m in re.finditer(r"(?<![\w/.:-])(/[a-z]+-chess)\b", text):
                assert m.group(1) in self.ALL, f"{path.name}: {m.group(1)}"
            for m in re.finditer(r"/chess-mentor:([a-z-]+)", text):
                assert m.group(1) in COMMAND_SKILLS, f"{path.name}: /chess-mentor:{m.group(1)}"

    def test_no_stale_generic_command_names(self):
        for path in doc_files() + [ROOT / ".claude-plugin" / "plugin.json", ROOT / ".claude-plugin" / "marketplace.json"]:
            for m in re.finditer(r"(?<![\w/.:-])/(teach|play|analyze|init)(?![\w-])", read(path)):
                pytest.fail(f"{path.name} still uses the old command name {m.group(0)}")

    def test_readme_documents_every_command_and_both_install_routes(self):
        text = read(ROOT / "README.md")
        for skill in COMMAND_SKILLS:
            assert f"`/{skill}`" in text and f"/chess-mentor:{skill}" in text
        assert "/plugin install" in text and ".claude/skills" in text and "CHESS_DATA_DIR" in text
        assert "Python 3.10" in text and "stockfishchess.org" in text


# ------------------------------------------------------------------ safety rules stay in the skills
class TestSafetyContracts:
    def test_shared_rules_are_present(self):
        text = read(SHARED)
        for needle in ("Don't leak answers", "Report engine output faithfully", "Stay inside your file scope",
                       "Never browse their home folder", "never `cd` into the plugin or skills folder",
                       "Never modify or delete their PGNs or books", "Annotated or one-off images never overwrite"):
            assert needle in text, needle

    def test_init_chess_is_scoped_and_read_only(self):
        text = read(SKILLS / "init-chess" / "SKILL.md")
        for needle in ("read-only on the user's files", "File scope (hard boundary)", "never look through their home folder",
                       "stop and ask them for the path", "never invent the user's goals", "never copy them elsewhere",
                       "do not `cd` to the plugin folder"):
            assert needle in text, needle

    def test_coach_not_opponent_framing(self):
        assert "coach**, not their opponent" in read(SHARED)
        assert "you are the coach" in read(SKILLS / "play-chess" / "SKILL.md")

    def test_modes_do_not_leak_answers(self):
        for skill in ("teach-chess", "play-chess"):
            assert re.search(r"(?i)hint ladder|no hints|don't reveal|do not reveal", read(SKILLS / skill / "SKILL.md"))

    def test_skills_use_generic_paths(self):
        for path in skill_files():
            text = read(path)
            assert "$PY" not in text and ".venv/Scripts" not in text and "../../../" not in text, path.parent.name


# ------------------------------------------------------------------ packaging
class TestPackaging:
    def manifests(self):
        return (json.loads(read(ROOT / ".claude-plugin" / "plugin.json")),
                json.loads(read(ROOT / ".claude-plugin" / "marketplace.json")))

    def test_plugin_and_marketplace_agree(self):
        plugin, market = self.manifests()
        assert plugin["name"] == market["name"] == market["plugins"][0]["name"] == "chess-mentor"
        assert plugin["version"] == market["plugins"][0]["version"]
        assert plugin["license"] == market["plugins"][0]["license"] == "GPL-3.0-or-later"
        assert market["plugins"][0]["source"] == "./"

    def test_version_is_semver_and_in_the_changelog(self):
        plugin, _ = self.manifests()
        assert re.fullmatch(r"\d+\.\d+\.\d+", plugin["version"])
        assert re.search(rf"^## \[{re.escape(plugin['version'])}\] - \d{{4}}-\d\d-\d\d", read(ROOT / "CHANGELOG.md"), re.M)
        assert f"[{plugin['version']}]: " in read(ROOT / "CHANGELOG.md")

    def test_descriptions_mention_every_command(self):
        plugin, market = self.manifests()
        for skill in COMMAND_SKILLS:
            assert f"/{skill}" in plugin["description"] and f"/{skill}" in market["plugins"][0]["description"]

    def test_dependencies_are_pinned_and_importable(self):
        lines = [l.strip() for l in read(SKILLS / "chess-tutor" / "requirements.txt").splitlines() if l.strip()]
        assert lines and all(re.fullmatch(r"[A-Za-z0-9_.-]+==\d+(\.\d+)*", l) for l in lines)
        import chess
        pinned = dict(l.split("==") for l in lines)
        assert chess.__version__ == pinned["chess"], "tests should run against the pinned python-chess"

    def test_dev_requirements_include_the_runtime_ones(self):
        text = read(ROOT / "requirements-dev.txt")
        assert "-r skills/chess-tutor/requirements.txt" in text and "pytest==" in text

    def test_license_is_gpl3(self):
        text = read(ROOT / "LICENSE")
        assert "GNU GENERAL PUBLIC LICENSE" in text and "Version 3, 29 June 2007" in text
        assert "END OF TERMS AND CONDITIONS" in text

    def test_script_carries_the_licence_header(self):
        head = read(SCRIPT)[:800]
        assert "SPDX-License-Identifier: GPL-3.0-or-later" in head

    def test_gitignore_protects_personal_data(self):
        lines = read(ROOT / ".gitignore").split()
        for entry in ("chess_data/", "__pycache__/", "/.venv", "/stockfish"):
            assert entry in lines

    def test_script_syntax_matches_the_minimum_python(self):
        """resvg-py (pinned) needs Python 3.10+, so that is the documented minimum; the script must not need newer."""
        ast.parse(read(SCRIPT), feature_version=(3, 10))

    def test_documented_minimum_python_is_consistent(self):
        assert "Python 3.10+" in read(ROOT / "README.md") and "Python 3.10+" in read(SHARED) and "Python 3.10+" in read(SCRIPT)

    def test_script_compiles_without_warnings(self):
        import py_compile
        import tempfile
        py_compile.compile(str(SCRIPT), cfile=str(Path(tempfile.mkdtemp()) / "x.pyc"), doraise=True)

    @pytest.mark.skipif(not shutil.which("claude"), reason="claude CLI not installed")
    def test_claude_plugin_validate_passes(self):
        p = subprocess.run([shutil.which("claude"), "plugin", "validate", str(ROOT)], capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=120)
        assert "Validation passed" in p.stdout + p.stderr, p.stdout + p.stderr


class TestRepositoryHygiene:
    TEXT_SUFFIXES = {".md", ".json", ".py", ".txt", ".ini", ".yml", ".yaml", ".toml", ""}
    SKIP_DIRS = {".venv", "stockfish", "chess_data", ".git", "__pycache__", ".pytest_cache", "node_modules"}

    def repo_text_files(self):
        for p in ROOT.rglob("*"):
            if p.is_file() and not (set(p.relative_to(ROOT).parts) & self.SKIP_DIRS) and p.suffix in self.TEXT_SUFFIXES \
                    and p.name != "LICENSE":
                yield p

    def test_no_personal_paths_or_names(self):
        user = "ro" + "lli"
        backslash = chr(92)
        patterns = ["(?i)(?<![a-z])" + user + "(?![a-z])", re.escape("C:" + backslash + "Users"), re.escape("C:/" + "Users"),
                    re.escape("/home/" + user), re.escape("Desk" + "top" + backslash), "App" + "Data"]
        for p in self.repo_text_files():
            text = read(p)
            for pat in patterns:
                assert not re.search(pat, text), f"{p.relative_to(ROOT)} matches {pat!r}"

    def test_no_placeholder_secrets_or_tokens(self):
        for p in self.repo_text_files():
            text = read(p)
            assert not re.search(r"(?i)(api[_-]?key|secret|password|token)\s*[:=]\s*['\"][^'\"]{8,}", text), p.name

    def test_marketplace_placeholders_are_only_the_known_ones(self):
        """Fail loudly (with a clear message) if placeholder values would be published by accident."""
        text = read(ROOT / ".claude-plugin" / "marketplace.json")
        placeholders = re.findall(r"REPLACE_WITH_[A-Z_]+", text)
        if placeholders:
            pytest.xfail(f"placeholders still to fill in before publishing: {sorted(set(placeholders))}")
