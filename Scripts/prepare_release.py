#!/usr/bin/env python
import argparse
import json
import re
import subprocess
import sys

from datetime import date
from pathlib import Path
from string import Template
from textwrap import indent, dedent
from urllib.request import Request, urlopen
from shlex import quote

from typing import Any, Callable, Optional, Tuple, TypeVar

class CannotReleaseError(Exception):
    pass

def progress(msg: str="", **kwargs) -> None:
    print(msg, **{"file": sys.stderr, "flush": True, **kwargs})

def git(cmd: str, *args: str, **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(["git", cmd, *args], # pylint: disable=subprocess-run-check
        **{"capture_output": True, "check": False, "encoding": "utf-8", **kwargs})

A = TypeVar(name="A")
def with_error(fn: Callable[[], A]) -> A:
    try:
        return fn()
    except Exception as e:
        progress(f"failed: {e}")
        if isinstance(e, subprocess.CalledProcessError):
            progress("Process output: ")
            progress(e.stdout)
            progress(e.stderr)
        raise CannotReleaseError() from e

def assert_one(msg: str, condition: Callable[[], Any]):
    assert msg.endswith("?")
    progress(msg + " ", end="")
    if not with_error(condition):
        progress("no, exiting.")
        raise CannotReleaseError()
    progress("yes.")

def run_one(msg: str, operation: Callable[[], None]):
    assert msg.endswith("...")
    progress(msg + " ", end="")
    with_error(operation)
    progress("done.")

def unwrap(opt: Optional[A]) -> A:
    assert opt
    return opt

class NewsFragments:
    IGNORED = {".gitignore"}
    KNOWN_EXTENSIONS = {".fix": "Bug fixes",
                        ".feat": "New features"}

    def __init__(self, path: str) -> None:
        self.path = Path(path)
        self.fragments = {}
        self.unrecognized = []
        self.collect()

    def collect(self) -> None:
        if self.path.exists():
            for f in self.path.iterdir():
                if f.suffix in self.KNOWN_EXTENSIONS:
                    self.fragments.setdefault(f.suffix, []).append(f)
                elif f.name not in self.IGNORED:
                    self.unrecognized.append(f.name)

    def check(self):
        if self.unrecognized:
            names = ', '.join(quote(name) for name in sorted(self.unrecognized))
            raise ValueError(f"Not sure what to do with {names}.")

    def render(self) -> str:
        rendered = ""
        for ext, title in self.KNOWN_EXTENSIONS.items():
            if ext not in self.fragments:
                continue
            rendered += f"## {title}\n\n"
            for pth in self.fragments[ext]:
                fr = pth.read_text(encoding="utf-8")
                rendered += "- " + indent(fr, "  ").lstrip() + "\n\n"
        return rendered

    def delete(self):
        for _, paths in self.fragments:
            for pth in paths:
                pth.delete()

class Release:
    def __init__(self, version: str) -> None:
        self.version = version
        self.remote = "origin"
        self.branch_name = f"release-{version}"
        self.branch_path = f"refs/heads/{self.branch_name}"
        self.master_branch = "refs/heads/master"
        self.tag = f"v{version}"
        self.version_cs_path = Path("Source/version.cs")
        self.release_notes_md_path = Path("RELEASE_NOTES.md")
        self.newsfragments = NewsFragments("docs/dev/newsfragments")

    @staticmethod
    def in_git_root() -> bool:
        return Path(".git").exists()

    def has_origin(self) -> bool:
        return git("remote", "url", self.remote).returncode == 0

    @staticmethod
    def has_git() -> bool:
        return git("rev-parse", "--verify", "HEAD").returncode == 0

    def has_news(self) -> bool:
        self.newsfragments.check()
        return bool(self.newsfragments.fragments)

    def version_file_exists(self) -> bool:
        return self.version_cs_path.is_file()

    def release_notes_file_exists(self) -> bool:
        return self.release_notes_md_path.is_file()

    RELEASE_NOTES_MARKER = "See [docs/devs/newsfragments/](docs/devs/newsfragments/)."
    def release_notes_have_header(self) -> bool:
        contents = self.release_notes_md_path.read_text(encoding="utf-8")
        return self.RELEASE_NOTES_MARKER in contents

    def version_number_is_fresh(self) -> bool:
        contents = self.release_notes_md_path.read_bytes()
        return b"# " + self.version.encode("utf-8") not in contents

    @staticmethod
    def get_branch(check: bool) -> str:
        return git("symbolic-ref", "--quiet", "HEAD", check=check).stdout.strip()

    VERNUM_RE = re.compile("^(?P<num>[0-9.]+)(?P<suffix>-.+)?$")
    def parse_vernum(self) -> Optional[Tuple[str, Optional[str]]]:
        if m := self.VERNUM_RE.match(self.version):
            num, suffix = m.group("num", "suffix")
            assert num
            return num, suffix or ""
        return None

    def is_release_branch(self) -> bool:
        return self.get_branch(check=False) in (self.master_branch, self.branch_path)

    @staticmethod
    def is_repo_clean() -> bool:
        return git("status", "--short").stdout.strip() == ""

    @classmethod
    def head_up_to_date(cls) -> bool:
        git("fetch")
        return "behind" not in git("status", "--short", "--branch").stdout

    @staticmethod
    def no_release_blocking_issues() -> bool:
        progress("Checking... ", end="")
        HEADERS = {"Accept": "application/vnd.github.v3+json"}
        ENDPOINT = 'https://api.github.com/repos/dafny-lang/dafny/issues?labels=severity%3A+release-blocker'
        with urlopen(Request(ENDPOINT, data=None, headers=HEADERS)) as fs:
            response = fs.read().decode("utf-8")
        return json.loads(response) == []

    def no_release_branch(self) -> bool:
        return git("rev-parse", "--quiet", "--verify", self.branch_path).returncode == 1

    def no_release_tag(self) -> bool:
        return git("tag", "--verify", self.tag).returncode == 1

    VERSION_FILE_TEMPLATE = Template(dedent("""\
    using System.Reflection;
    // Version $version, year 2018+$year_delta, month $month, day $day
    [assembly: AssemblyVersion("$version_prefix.$version_date$version_suffix")]
    [assembly: AssemblyFileVersion("$version_prefix.$version_date$version_suffix")]
    """))

    def update_version_file(self) -> None:
        today = date.today()
        version_prefix, version_suffix = unwrap(self.parse_vernum())
        year_delta, month, day = today.year - 2018, today.month, today.day
        contents = self.VERSION_FILE_TEMPLATE.substitute({
            "year_delta": year_delta, "month": month, "day": day,
            "version": self.version, "version_prefix": version_prefix,
            "version_suffix": version_suffix,
            "version_date": str((year_delta * 100 + month) * 100 + day),
        })
        self.version_cs_path.write_text(contents, encoding="utf-8")

    def create_release_branch(self):
        git("checkout", "-b", self.branch_path, check=True)

    def consolidate_news_fragments(self):
        news = NewsFragments("docs/dev/newsfragments/").render()
        new_section = f"\n\n# {self.version}\n\n{news.rstrip()}"
        contents = self.release_notes_md_path.read_text(encoding="utf-8")
        nl = "\r\n" if "\r\n" in contents else "\n"
        replacement = self.RELEASE_NOTES_MARKER + new_section.replace("\n", nl)
        contents = contents.replace(self.RELEASE_NOTES_MARKER, replacement)
        self.release_notes_md_path.write_text(contents, encoding="utf-8")

    def delete_news_fragments(self):
        self.newsfragments.delete()

    def commit_changes(self):
        git("commit", "--quiet", "--all",
            "--no-verify", "--no-post-rewrite",
            f"--message=Release Dafny {self.version}",
            check=True)

    # def set_upstream_of_release_branch(self):
    #     git("branch", f"--set-upstream-to={self.remote}/{self.upstream_branch}",
    #         self.branch_path, capture_output=False).check_returncode()

    def push_release_branch(self):
        return # FIXME
        git("push", "--force-with-lease", "--set-upstream",
            self.remote, f"{self.branch_path}:{self.branch_path}",
            check=True)

    # Still TODO:
    # - Run deep test as part of release workflow

    def prepare(self):
        assert_one("Can we run `git`?",
                   self.has_git)
        assert_one(f"Is {self.version} a valid version number?",
                   self.parse_vernum)
        assert_one("Are we running from the root of a git repo?",
                   self.in_git_root)
        assert_one("Can we find `Source/version.cs`?",
                   self.version_file_exists)
        assert_one("Can we find `RELEASE_NOTES.md`?",
                   self.release_notes_file_exists)
        assert_one("Does `RELEASE_NOTES.md` have a header?",
                   self.release_notes_have_header)
        assert_one(f"Can we create a section for `{self.version}` in `RELEASE_NOTES.md`?",
                   self.version_number_is_fresh)
        assert_one(f"Do we have news in {self.newsfragments.path}?",
                   self.has_news)
        assert_one(f"Is the current branch `master` or `{self.branch_name}`?",
                   self.is_release_branch)
        assert_one("Is repo clean (all changes committed)?",
                   self.is_repo_clean)
        assert_one("Is HEAD is up to date?",
                   self.head_up_to_date)
        assert_one("Are all release-blocking issues closed?",
                   self.no_release_blocking_issues)
        assert_one(f"Can we create release tag `{self.tag}`?",
                   self.no_release_tag)
        if self.get_branch(check=False) == self.master_branch:
            assert_one(f"Can we create release branch `{self.branch_name}`?",
                       self.no_release_branch)
            run_one(f"Creating release branch {self.branch_path}...",
                    self.create_release_branch)
        else:
            progress("Note: Release branch already checked out, so not creating it.")
        run_one("Updating `Source/version.cs`...",
                self.update_version_file)
        run_one("Updating `RELEASE_NOTES.md` from `docs/dev/newsfragments`...",
                self.consolidate_news_fragments)
        run_one("Creating commit...",
                self.commit_changes)
        # run_one("Setting upstream of branch `{self.branch_name}`...", # FIXME
        #         self.set_upstream_of_release_branch)
        run_one("Pushing release branch...",
                self.push_release_branch)
        run_one("Deleting news fragments...",
                self.delete_news_fragments)

        progress("Done!")
        progress()

        DEEPTESTS_URL = "https://github.com/dafny-lang/dafny/actions/workflows/deep-tests.yml"
        progress(f"Now, start a deep-tests workflow manually for branch {self.branch_name} at\n"
                 f"<{DEEPTESTS_URL}>.\n"
                 "Once it completes, re-run this script with argument `release`.")
        progress()

    def tag_release(self):
        git("tag", "--annotate", f"--message=Dafny {self.tag}",
            self.tag, self.branch_path, capture_output=False).check_returncode()

    def push_release_tag(self):
        git("push", self.remote, f"{self.tag}",
            capture_output=False).check_returncode()

    def release(self):
        run_one("Tagging release...",
                self.tag_release)
        run_one("Pushing tag...",
                self.push_release_tag)

        progress("Done!")
        progress()

        PR_URL = f"https://github.com/dafny-lang/dafny/pull/new/{self.branch_name}"
        progress("You can merge this branch by opening a PR at\n"
                 f"<{PR_URL}>.")


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Dafny release helper")
    parser.add_argument("version", help="Version number for this release (A.B.C-xyz)")
    parser.add_argument("action", help="Which part of the release process to run",
                        choices=["release", ""])
    return parser.parse_args()

def main() -> None:
    args = parse_arguments()
    try:
        Release(args.version).prepare()
    except CannotReleaseError:
        sys.exit(1)

if __name__ == "__main__":
    main()
