#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Release helper used by .github/workflows/release.yml (and runnable locally).

    python .github/scripts/release_notes.py v0.1.0

Checks that the git tag, .claude-plugin/plugin.json, .claude-plugin/marketplace.json and CHANGELOG.md all name
the same version, then prints that version's CHANGELOG section (the GitHub release notes) to stdout.
Exits with status 1 and a message on stderr if anything disagrees, so a bad tag never becomes a release.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
TAG_RE = re.compile(r"v(\d+\.\d+\.\d+(?:-[0-9A-Za-z.]+)?)")


class ReleaseError(Exception):
    pass


def version_from_tag(tag):
    m = TAG_RE.fullmatch(tag.strip())
    if not m:
        raise ReleaseError(f"tag {tag!r} is not of the form vMAJOR.MINOR.PATCH (optionally -prerelease)")
    return m.group(1)


def manifest_versions(root):
    plugin = json.loads((Path(root) / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    market = json.loads((Path(root) / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
    return {"plugin.json": plugin.get("version"), "marketplace.json": market["plugins"][0].get("version")}


def changelog_section(text, version):
    """The body of '## [version] - date' up to the next version heading or the link footer."""
    heading = re.search(rf"^## \[{re.escape(version)}\][^\n]*\n", text, re.M)
    if not heading:
        raise ReleaseError(f"CHANGELOG.md has no '## [{version}]' section")
    rest = text[heading.end():]
    end = re.search(r"^(?:## \[|\[[^\]]+\]: )", rest, re.M)
    body = (rest[:end.start()] if end else rest).strip()
    if not body:
        raise ReleaseError(f"the CHANGELOG.md section for {version} is empty")
    return body


def release_notes(tag, root=ROOT):
    version = version_from_tag(tag)
    for name, found in manifest_versions(root).items():
        if found != version:
            raise ReleaseError(f"{name} says version {found!r} but the tag is {tag} ({version}); bump it before tagging")
    return changelog_section((Path(root) / "CHANGELOG.md").read_text(encoding="utf-8"), version)


def main(argv):
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    try:
        print(release_notes(argv[1]))
    except (ReleaseError, OSError, ValueError, KeyError) as e:
        print(f"release check failed: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
