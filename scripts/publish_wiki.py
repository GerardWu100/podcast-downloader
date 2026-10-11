"""Publish ``docs/`` to the repository's GitHub wiki.

``docs/`` is the only place documentation is written. It is versioned with the
code, reviewed with it, and read by agents working in the checkout. The GitHub
wiki is a read-only copy for people browsing on GitHub, rebuilt from scratch by
this script, so an edit made in the wiki itself is lost on the next publish.

What changes on the way:

- Each page's front matter (``title:`` and ``sidebar_position:``) is removed.
  The title becomes the wiki page name, ``CLI and Config`` -> ``CLI-and-Config``;
  the page whose title is ``Home`` becomes the wiki's front page.
- The page's own ``# Heading`` is dropped, because the wiki prints the page
  name as the heading already.
- Links between docs pages, ``[x](cli-and-config.md#flags)``, become wiki links,
  ``[x](CLI-and-Config#flags)``. Any other relative link points at the file on
  GitHub, and images at their raw file, so nothing breaks.
- ``_Sidebar.md`` lists the pages in ``sidebar_position`` order, and
  ``_Footer.md`` says where to edit.

``GUIDE_*.md`` files are developer notes about the docs folder itself and are
not published.

Usage
-----
    uv run python scripts/publish_wiki.py                 # build and push
    uv run python scripts/publish_wiki.py --output wiki/  # build into a folder only

GitHub creates the wiki's git repository only after its first page is saved on
the website, so the first push fails until someone does that once.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = PROJECT_ROOT / "docs"
DEFAULT_BRANCH = "master"
HOME_TITLE = "Home"
# Docs-folder notes for developers, not documentation pages.
SKIPPED_FILE_PREFIX = "GUIDE_"

FRONT_MATTER = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)
FIRST_HEADING = re.compile(r"\A\s*# [^\n]*\n+")
# A Markdown link or image target: "](target)". Group 1 is the target.
LINK_TARGET = re.compile(r"\]\(([^)\s]+)\)")


@dataclass(frozen=True)
class DocPage:
    """One page of ``docs/`` ready to become a wiki page.

    Attributes
    ----------
    source_name:
        File name in ``docs/``, such as ``cli-and-config.md``.
    title:
        Front-matter ``title``, such as ``CLI and Config``.
    position:
        Front-matter ``sidebar_position``; lower comes first in the sidebar.
    body:
        Markdown after the front matter and the first heading.
    """

    source_name: str
    title: str
    position: int
    body: str

    @property
    def wiki_name(self) -> str:
        """Wiki page name: the title with spaces as hyphens."""
        return self.title.replace(" ", "-")


def run_git(*arguments: str, cwd: Path) -> str:
    """Run one git command and return its standard output."""
    result = subprocess.run(
        ["git", *arguments], cwd=cwd, check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


def github_repository_url() -> str:
    """Return ``https://github.com/<owner>/<repo>`` from the ``origin`` remote."""
    remote = run_git("remote", "get-url", "origin", cwd=PROJECT_ROOT)
    # Before: https://github.com/Owner/repo.git or git@github.com:Owner/repo.git
    # After:  https://github.com/Owner/repo
    match = re.search(r"github\.com[:/](.+?)(?:\.git)?$", remote)
    if not match:
        raise SystemExit(f"origin is not a GitHub remote: {remote}")
    return f"https://github.com/{match.group(1)}"


def read_doc_pages(docs_dir: Path) -> list[DocPage]:
    """Read every publishable page in ``docs_dir``, in sidebar order.

    Raises
    ------
    SystemExit
        When a page has no front matter, no title, or no exactly one ``Home``.
    """
    pages: list[DocPage] = []
    for source_file in sorted(docs_dir.glob("*.md")):
        if source_file.name.startswith(SKIPPED_FILE_PREFIX):
            continue
        text = source_file.read_text(encoding="utf-8")
        front_matter = FRONT_MATTER.match(text)
        if not front_matter:
            raise SystemExit(f"{source_file.name} has no front matter with a title.")
        # "title: CLI and Config\nsidebar_position: 3" -> {"title": ..., ...}
        fields = dict(
            line.split(":", 1)
            for line in front_matter.group(1).splitlines()
            if ":" in line
        )
        title = fields.get("title", "").strip()
        if not title:
            raise SystemExit(f"{source_file.name} has no title in its front matter.")
        body = FIRST_HEADING.sub("", text[front_matter.end() :], count=1)
        pages.append(
            DocPage(
                source_name=source_file.name,
                title=title,
                position=int(fields.get("sidebar_position", "99")),
                body=body,
            )
        )

    if [page.title for page in pages].count(HOME_TITLE) != 1:
        raise SystemExit(f'Exactly one docs page must have "title: {HOME_TITLE}".')
    return sorted(pages, key=lambda page: (page.position, page.title))


def rewrite_links(body: str, wiki_name_for_file: dict[str, str], repo_url: str) -> str:
    """Point every relative link in ``body`` at its wiki page or GitHub file.

    Parameters
    ----------
    body:
        Page Markdown with links relative to ``docs/``.
    wiki_name_for_file:
        ``docs/`` file name -> wiki page name, such as
        ``{"cli-and-config.md": "CLI-and-Config"}``.
    repo_url:
        ``https://github.com/<owner>/<repo>``.
    """
    docs_blob_url = f"{repo_url}/blob/{DEFAULT_BRANCH}/docs/"
    docs_raw_url = (
        repo_url.replace("https://github.com/", "https://raw.githubusercontent.com/")
        + f"/{DEFAULT_BRANCH}/docs/"
    )

    def replace_target(match: re.Match[str]) -> str:
        target = match.group(1)
        if re.match(r"[a-z]+:|#", target):
            return match.group(0)  # absolute URL, mailto:, or in-page anchor
        path, _, anchor = target.partition("#")
        anchor = f"#{anchor}" if anchor else ""
        file_name = path.removeprefix("./")
        if file_name in wiki_name_for_file:
            return f"]({wiki_name_for_file[file_name]}{anchor})"
        if re.search(r"\.(png|jpe?g|gif|svg|webp)$", path, re.IGNORECASE):
            return f"]({urljoin(docs_raw_url, path)})"
        return f"]({urljoin(docs_blob_url, path)}{anchor})"

    return LINK_TARGET.sub(replace_target, body)


def build_wiki_pages(pages: list[DocPage], repo_url: str) -> dict[str, str]:
    """Return the wiki's files as ``{file name: Markdown}``."""
    wiki_name_for_file = {page.source_name: page.wiki_name for page in pages}
    wiki_files = {
        f"{page.wiki_name}.md": rewrite_links(page.body, wiki_name_for_file, repo_url)
        for page in pages
    }
    wiki_files["_Sidebar.md"] = "\n".join(
        f"- [{page.title}]({page.wiki_name})" for page in pages
    ) + f"\n\n[README and install]({repo_url}#readme)\n"
    wiki_files["_Footer.md"] = (
        f"Built from [`docs/`]({repo_url}/tree/{DEFAULT_BRANCH}/docs) by "
        "`scripts/publish_wiki.py`. Edit there; changes made here are overwritten.\n"
    )
    return wiki_files


def write_wiki_files(wiki_files: dict[str, str], target_dir: Path) -> None:
    """Replace every Markdown file in ``target_dir`` with ``wiki_files``."""
    target_dir.mkdir(parents=True, exist_ok=True)
    # Remove first, so a page deleted from docs/ also leaves the wiki.
    for old_page in target_dir.glob("*.md"):
        old_page.unlink()
    for file_name, text in wiki_files.items():
        (target_dir / file_name).write_text(text, encoding="utf-8")


def publish(wiki_files: dict[str, str], repo_url: str) -> None:
    """Clone the wiki, replace its pages, and push if anything changed."""
    source_commit = run_git("rev-parse", "--short", "HEAD", cwd=PROJECT_ROOT)
    with tempfile.TemporaryDirectory() as temporary_dir:
        wiki_dir = Path(temporary_dir) / "wiki"
        try:
            subprocess.run(
                ["git", "clone", "--quiet", f"{repo_url}.wiki.git", str(wiki_dir)],
                check=True,
            )
        except subprocess.CalledProcessError:
            raise SystemExit(
                f"Could not clone the wiki. Open {repo_url}/wiki, create the first "
                "page once on the website, then run this again."
            ) from None
        write_wiki_files(wiki_files, wiki_dir)
        run_git("add", "--all", cwd=wiki_dir)
        if not run_git("status", "--porcelain", cwd=wiki_dir):
            print("Wiki already matches docs/; nothing to publish.")
            return
        run_git("commit", "--quiet", "-m", f"Publish docs/ at {source_commit}", cwd=wiki_dir)
        run_git("push", "--quiet", cwd=wiki_dir)
    print(f"Published {len(wiki_files)} files to {repo_url}/wiki")


def main() -> int:
    """Build the wiki from ``docs/`` and publish it, or write it to a folder."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--output",
        type=Path,
        help="Write the wiki files into this folder instead of pushing them.",
    )
    args = parser.parse_args()

    repo_url = github_repository_url()
    wiki_files = build_wiki_pages(read_doc_pages(DOCS_DIR), repo_url)
    if args.output:
        write_wiki_files(wiki_files, args.output)
        print(f"Wrote {len(wiki_files)} files to {args.output}")
        return 0
    publish(wiki_files, repo_url)
    return 0


if __name__ == "__main__":
    sys.exit(main())
