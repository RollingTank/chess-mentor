"""Tests for the CI/CD pipeline: workflow structure and safety rules, dependabot, and the release helper script."""
import functools
import importlib.util
import json
import re
import subprocess
import sys

import pytest
import yaml

from conftest import ROOT

WORKFLOW_DIR = ROOT / ".github" / "workflows"
WORKFLOWS = sorted(WORKFLOW_DIR.glob("*.yml"))
RELEASE_SCRIPT = ROOT / ".github" / "scripts" / "release_notes.py"


def load(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def triggers(wf):
    return wf.get("on", wf.get(True))            # YAML 1.1 parses a bare `on:` key as the boolean True


def steps_text(job):
    return "\n".join(str(s.get("run", "")) + " " + str(s.get("uses", "")) for s in job["steps"])


@functools.lru_cache(maxsize=None)
def release_module():
    spec = importlib.util.spec_from_file_location("release_notes_under_test", RELEASE_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ------------------------------------------------------------------ every workflow
class TestWorkflowSafety:
    def test_expected_workflows_exist(self):
        assert {p.name for p in WORKFLOWS} == {"ci.yml", "release.yml"}

    @pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
    def test_shape(self, path):
        wf = load(path)
        assert wf["name"] and triggers(wf) and wf["jobs"]
        for name, job in wf["jobs"].items():
            assert "runs-on" in job and job["steps"], name
            assert "timeout-minutes" in job, f"{path.name}:{name} has no timeout"

    @pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
    def test_default_permissions_are_read_only(self, path):
        assert load(path)["permissions"] == {"contents": "read"}

    @pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
    def test_actions_are_pinned_to_a_version(self, path):
        for job in load(path)["jobs"].values():
            for step in job["steps"]:
                if "uses" in step:
                    assert re.fullmatch(r"[\w./-]+@(v\d+(\.\d+)*|[0-9a-f]{40})", step["uses"]), step["uses"]

    @pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
    def test_no_dangerous_triggers_or_secret_echoing(self, path):
        text = path.read_text(encoding="utf-8")
        assert "pull_request_target" not in text and "workflow_run" not in text
        assert not re.search(r"echo[^\n]*secrets\.", text)
        assert "${{ github.event.pull_request.title" not in text and "github.head_ref" not in text   # script injection vectors

    @pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
    def test_referenced_files_exist(self, path):
        text = path.read_text(encoding="utf-8")
        for ref in set(re.findall(r"\.github/scripts/[\w./-]+|requirements-dev\.txt|skills/chess-tutor/requirements\.txt", text)):
            assert (ROOT / ref).exists(), f"{path.name} references missing {ref}"

    @pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
    def test_pytest_markers_are_defined(self, path):
        defined = set(re.findall(r"^\s*(\w+):", (ROOT / "pytest.ini").read_text(encoding="utf-8").split("markers =")[1], re.M))
        for expr in re.findall(r'pytest[^\n]*-m\s+"?([^"\n]+)"?', path.read_text(encoding="utf-8")):
            for word in re.findall(r"[a-z_]+", expr):
                if word not in ("not", "and", "or"):
                    assert word in defined, f"{path.name}: unknown marker {word!r}"


# ------------------------------------------------------------------ ci.yml
class TestCiWorkflow:
    wf = load(WORKFLOW_DIR / "ci.yml")

    def test_runs_on_pushes_and_pull_requests(self):
        t = triggers(self.wf)
        assert "pull_request" in t and "push" in t and "master" in t["push"]["branches"]

    def test_matrix_covers_all_platforms_and_the_documented_minimum_python(self):
        m = self.wf["jobs"]["test"]["strategy"]["matrix"]
        assert set(m["os"]) == {"ubuntu-latest", "windows-latest", "macos-latest"}
        assert "3.10" in m["python"], "the documented minimum Python must be tested"
        assert all(tuple(map(int, v.split("."))) >= (3, 10) for v in m["python"]), "resvg-py needs Python 3.10+"
        assert self.wf["jobs"]["test"]["strategy"]["fail-fast"] is False

    def test_stub_engine_tests_run_everywhere_and_real_engine_tests_run_with_stockfish(self):
        assert '-m "not engine"' in steps_text(self.wf["jobs"]["test"])
        engine = steps_text(self.wf["jobs"]["engine"])
        assert "apt-get install -y stockfish" in engine and "pytest -m engine" in engine
        assert any("STOCKFISH_PATH" in str(s.get("run", "")) for s in self.wf["jobs"]["engine"]["steps"])

    def test_plugin_validation_pins_the_cli(self):
        text = steps_text(self.wf["jobs"]["plugin"])
        assert re.search(r"@anthropic-ai/claude-code@\d+\.\d+\.\d+", text) and "claude plugin validate" in text

    def test_gate_job_depends_on_every_other_job(self):
        jobs = self.wf["jobs"]
        assert set(jobs["all-green"]["needs"]) == set(jobs) - {"all-green"}
        assert jobs["all-green"]["if"] == "always()"

    def test_runs_are_cancelled_when_superseded(self):
        assert self.wf["concurrency"]["cancel-in-progress"] is True


# ------------------------------------------------------------------ release.yml
class TestReleaseWorkflow:
    wf = load(WORKFLOW_DIR / "release.yml")

    def test_triggers_only_on_version_tags(self):
        t = triggers(self.wf)
        assert set(t) == {"push"} and set(t["push"]) == {"tags"}

    def glob_to_regex(self, pattern):
        # GitHub filter globs: '+' = one or more of the preceding token, '*' = anything but '/', '.' is literal
        out = ""
        for part in re.findall(r"\[[^\]]+\]\+?|\*|\.|[^\[\]*.]+", pattern):
            out += "[^/]*" if part == "*" else (r"\." if part == "." else part)
        return re.compile(out)

    @pytest.mark.parametrize("tag,ok", [("v0.1.0", True), ("v10.20.30", True), ("v0.2.0-rc.1", True),
                                        ("v1", False), ("v1.2", False), ("release-1", False), ("0.1.0", False)])
    def test_tag_pattern(self, tag, ok):
        (pattern,) = triggers(self.wf)["push"]["tags"]
        assert bool(self.glob_to_regex(pattern).fullmatch(tag)) is ok

    def test_publish_is_the_only_job_that_can_write_and_it_waits_for_verification(self):
        jobs = self.wf["jobs"]
        assert jobs["publish"]["permissions"] == {"contents": "write"} and jobs["publish"]["needs"] == "verify"
        assert "permissions" not in jobs["verify"]

    def test_verification_gates_the_release(self):
        text = steps_text(self.wf["jobs"]["verify"])
        assert "release_notes.py" in text and "pytest" in text and "merge-base --is-ancestor" in text

    def test_release_is_created_from_the_changelog_with_a_bundle(self):
        text = steps_text(self.wf["jobs"]["publish"])
        assert "gh release create" in text and "--notes-file" in text and "--verify-tag" in text
        assert "git archive" in text and "skills LICENSE" in text


# ------------------------------------------------------------------ dependabot
class TestDependabot:
    cfg = yaml.safe_load((ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8"))

    def test_covers_actions_and_both_requirement_files(self):
        entries = {(u["package-ecosystem"], u["directory"]) for u in self.cfg["updates"]}
        assert entries == {("github-actions", "/"), ("pip", "/skills/chess-tutor"), ("pip", "/")}

    def test_directories_contain_what_dependabot_reads(self):
        assert (ROOT / "skills" / "chess-tutor" / "requirements.txt").exists() and (ROOT / "requirements-dev.txt").exists()

    def test_dev_requirements_include_pyyaml_for_these_tests(self):
        assert re.search(r"^PyYAML==", (ROOT / "requirements-dev.txt").read_text(encoding="utf-8"), re.M)


# ------------------------------------------------------------------ release helper
CHANGELOG = """# Changelog

## [Unreleased]
- nothing yet

## [0.2.0-rc.1] - 2026-12-01
### Added
- the release candidate

## [0.1.0] - 2026-11-23

First release.

### Added
- thing one
- thing two

### Known limitations
- something

[0.2.0-rc.1]: https://example.com/rc
[0.1.0]: https://example.com/0.1.0
"""


def make_root(tmp_path, plugin="0.1.0", market="0.1.0", changelog=CHANGELOG):
    (tmp_path / ".claude-plugin").mkdir(parents=True)
    (tmp_path / ".claude-plugin" / "plugin.json").write_text(json.dumps({"name": "x", "version": plugin}), encoding="utf-8")
    (tmp_path / ".claude-plugin" / "marketplace.json").write_text(json.dumps({"plugins": [{"name": "x", "version": market}]}), encoding="utf-8")
    (tmp_path / "CHANGELOG.md").write_text(changelog, encoding="utf-8")
    return tmp_path


class TestReleaseNotesScript:
    @pytest.mark.parametrize("tag,version", [("v0.1.0", "0.1.0"), ("v10.2.33", "10.2.33"), ("v1.0.0-rc.1", "1.0.0-rc.1")])
    def test_valid_tags(self, tag, version):
        assert release_module().version_from_tag(tag) == version

    @pytest.mark.parametrize("tag", ["0.1.0", "v1", "v1.2", "release-1", "v1.2.3.4", "vx.y.z", "", "v1.2.3 "[:-1] + ";rm"])
    def test_invalid_tags(self, tag):
        with pytest.raises(release_module().ReleaseError):
            release_module().version_from_tag(tag)

    def test_extracts_exactly_one_version_section(self):
        notes = release_module().changelog_section(CHANGELOG, "0.1.0")
        assert notes.startswith("First release.") and "- thing two" in notes and "### Known limitations" in notes
        assert "release candidate" not in notes and "https://example.com" not in notes     # next version and footer links excluded

    def test_prerelease_section(self):
        assert release_module().changelog_section(CHANGELOG, "0.2.0-rc.1") == "### Added\n- the release candidate"

    def test_last_section_without_footer(self):
        assert release_module().changelog_section("## [1.0.0] - 2026-01-01\n- only entry\n", "1.0.0") == "- only entry"

    def test_missing_and_empty_sections(self):
        mod = release_module()
        with pytest.raises(mod.ReleaseError, match="no '## \\[9.9.9\\]' section"):
            mod.changelog_section(CHANGELOG, "9.9.9")
        with pytest.raises(mod.ReleaseError, match="empty"):
            mod.changelog_section("## [1.0.0] - x\n\n## [0.9.0] - y\n- a\n", "1.0.0")

    def test_version_prefix_is_not_confused_with_longer_versions(self):
        text = "## [0.1.10] - x\n- ten\n\n## [0.1.1] - y\n- one\n"
        assert release_module().changelog_section(text, "0.1.1") == "- one"

    def test_consistent_repo_produces_notes(self, tmp_path):
        assert "thing one" in release_module().release_notes("v0.1.0", make_root(tmp_path))

    @pytest.mark.parametrize("plugin,market,which", [("0.1.1", "0.1.0", "plugin.json"), ("0.1.0", "0.0.9", "marketplace.json")])
    def test_manifest_version_mismatch_blocks_the_release(self, tmp_path, plugin, market, which):
        mod = release_module()
        with pytest.raises(mod.ReleaseError, match=which):
            mod.release_notes("v0.1.0", make_root(tmp_path, plugin=plugin, market=market))

    def test_tag_without_changelog_entry_blocks_the_release(self, tmp_path):
        mod = release_module()
        with pytest.raises(mod.ReleaseError, match="CHANGELOG"):
            mod.release_notes("v0.3.0", make_root(tmp_path, plugin="0.3.0", market="0.3.0"))

    def test_the_repository_itself_is_releasable_at_its_current_version(self):
        """Tagging the version in plugin.json must always work; otherwise the release workflow would fail late."""
        version = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))["version"]
        notes = release_module().release_notes(f"v{version}")
        assert "### Added" in notes and len(notes) > 200

    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(RELEASE_SCRIPT), *args], capture_output=True, text=True, encoding="utf-8")

    def test_cli_success(self):
        version = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))["version"]
        r = self.run_cli(f"v{version}")
        assert r.returncode == 0 and "### Added" in r.stdout and r.stderr == ""

    def test_cli_failure_modes(self):
        bad = self.run_cli("v9.9.9")
        assert bad.returncode == 1 and "release check failed" in bad.stderr and bad.stdout == ""
        assert self.run_cli("not-a-tag").returncode == 1
        assert self.run_cli().returncode == 2
