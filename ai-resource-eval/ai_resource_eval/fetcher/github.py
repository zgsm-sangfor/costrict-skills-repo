"""GitHub README fetcher — fetch raw content from GitHub repositories.

Derives ``raw.githubusercontent.com`` URLs from ``source_url`` and tries each
path in ``content_paths`` in order until one succeeds (HTTP 200).  Returns
``(content, content_hash)`` or ``None`` when all paths 404.
"""

from __future__ import annotations

import hashlib
import re

import httpx

# Matches "https://github.com/owner/repo" with optional /tree|blob/ref/subpath.
_GITHUB_REPO_RE = re.compile(
    r"https://github\.com/([^/]+)/([^/]+)"
    r"(?:/(?:tree|blob)/([^/]+)(?:/(.+))?)?"
)

_RAW_BASE = "https://raw.githubusercontent.com"

_DEFAULT_CONTENT_PATHS = ["README.md"]

_TIMEOUT = 30.0  # seconds


class GitHubFetcher:
    """Fetch README content from a GitHub repository.

    Parameters
    ----------
    content_paths:
        Ordered list of file paths to try within the repository root.
        Defaults to ``["README.md"]``.
    """

    def __init__(self, content_paths: list[str] | None = None) -> None:
        self._content_paths = content_paths or list(_DEFAULT_CONTENT_PATHS)
        # In-memory cache of (source_url) → (content, content_hash) | None。
        # 同 fetcher 实例内，相同 source_url 不重复打 GitHub raw。这对
        # plugin 类型尤其关键：50+ 个 anthropic plugin 共享同一 marketplace
        # repo，没 cache 时每条都拉一次 README → 50× 浪费。
        # None 值标记"已尝试但 404"，避免 cache miss 回头重试浪费。
        # GIL 保证 dict[k]=v 原子，并发 set 最坏"最后一个赢"，无需 lock。
        self._url_cache: dict[str, tuple[str, str] | None] = {}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_owner_repo(
        source_url: str,
    ) -> tuple[str, str, str, str] | None:
        """Extract ``(owner, repo, ref, subpath)`` from a GitHub URL.

        Returns ``None`` for non-GitHub URLs.

        *ref* defaults to ``"HEAD"`` and *subpath* defaults to ``""`` when the
        URL does not contain ``/tree/<ref>/…`` or ``/blob/<ref>/…`` segments.
        """
        m = _GITHUB_REPO_RE.match(source_url)
        if m is None:
            return None
        owner = m.group(1)
        repo = m.group(2)
        # Strip trailing ".git" if present.
        if repo.endswith(".git"):
            repo = repo[: -len(".git")]
        ref = m.group(3) or "HEAD"
        subpath = (m.group(4) or "").rstrip("/")
        return owner, repo, ref, subpath

    @staticmethod
    def _content_hash(text: str) -> str:
        """Return the SHA-256 hex digest of *text*."""
        return hashlib.sha256(text.encode()).hexdigest()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fetch(self, source_url: str) -> tuple[str, str] | None:
        """Fetch content from a GitHub repository.

        Derives ``raw.githubusercontent.com`` URLs from *source_url* and tries
        each path in ``content_paths`` in order. Repeat calls for the same
        ``source_url`` are served from in-memory cache.

        Returns
        -------
        tuple[str, str] | None
            ``(content, content_hash)`` on success, or ``None`` when all paths
            return non-200 responses or the URL is not a GitHub URL.
        """
        # In-memory cache hit (含 None 表示"已尝试 404"，避免重试)
        if source_url in self._url_cache:
            return self._url_cache[source_url]

        parsed = self._extract_owner_repo(source_url)
        if parsed is None:
            self._url_cache[source_url] = None
            return None

        owner, repo, ref, subpath = parsed

        # Strip fragment from subpath (e.g. "PROMPTS.md#slug" → "PROMPTS.md")
        fragment = self._extract_fragment(source_url)
        if fragment and "#" in (subpath or ""):
            subpath = subpath.split("#")[0]

        prefix = f"{_RAW_BASE}/{owner}/{repo}/{ref}"

        # Detect blob URLs pointing to a specific file (subpath ends with
        # a file extension like .md, .txt, .csv).  In this case fetch the
        # file directly instead of appending content_paths.
        is_file = bool(
            subpath and re.search(r"\.\w+$", subpath)
        )

        if is_file:
            # Direct file fetch — don't iterate content_paths
            raw_url = f"{prefix}/{subpath}"
            try:
                with httpx.Client(timeout=_TIMEOUT) as client:
                    response = client.get(raw_url)
                    if response.status_code == 200:
                        content = response.text
                        if fragment:
                            section = self._extract_section(content, fragment)
                            if section:
                                content = section
                        result = content, self._content_hash(content)
                        self._url_cache[source_url] = result
                        return result
            except httpx.HTTPError:
                pass
            self._url_cache[source_url] = None
            return None

        if subpath:
            prefix = f"{prefix}/{subpath}"

        with httpx.Client(timeout=_TIMEOUT) as client:
            for path in self._content_paths:
                url = f"{prefix}/{path}"
                try:
                    response = client.get(url)
                except httpx.HTTPError:
                    continue

                if response.status_code == 200:
                    content = response.text
                    if fragment:
                        section = self._extract_section(content, fragment)
                        if section:
                            content = section
                    result = content, self._content_hash(content)
                    self._url_cache[source_url] = result
                    return result

        self._url_cache[source_url] = None
        return None

    # ------------------------------------------------------------------
    # Section extraction
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_fragment(url: str) -> str | None:
        """Extract the ``#fragment`` from a URL, or None."""
        idx = url.find("#")
        if idx < 0:
            return None
        return url[idx + 1 :]

    @staticmethod
    def _slugify_heading(heading: str) -> str:
        """Convert a Markdown heading line into a GitHub-compatible anchor slug.

        Mirrors jch/html-pipeline's TableOfContentsFilter (the algorithm GitHub
        actually uses for ``##`` heading anchors):

        1. Lowercase.
        2. Remove characters that are not word chars, dashes, or spaces
           (drops punctuation like ``&``, ``(``, ``)``, ``#``, ``:``, ...).
        3. Replace each space with a dash **per-character**, NOT collapsing
           consecutive dashes. ``Foo - Bar`` therefore becomes ``foo---bar``
           (3 dashes), matching the URL fragment GitHub actually emits.
        4. Strip leading dashes left over from the ``## `` prefix.

        Note: an earlier version collapsed runs of dashes with ``re.sub(r'-+',
        '-', ...)``, which lost information for headings containing punctuation
        or literal dashes (e.g. ``Foo & Bar``, ``Foo - Bar``). Real GitHub
        anchors preserve those extra dashes, so collapse-style slugifiers fail
        to match for ~10% of f/prompts.chat headings.
        """
        s = heading.lower()
        # ``\w`` is unicode-aware in Python 3 re by default; this keeps CJK and
        # other unicode word chars while dropping ASCII punctuation. We
        # explicitly keep ``-`` and `` `` so the per-space replacement below
        # can preserve dash multiplicity.
        s = re.sub(r"[^\w\- ]", "", s)
        s = s.replace(" ", "-")
        return s.lstrip("-")

    @staticmethod
    def _extract_section(text: str, slug: str) -> str | None:
        """Extract a Markdown section matching *slug* from *text*.

        Finds the ``## Title`` whose GitHub-style slug matches, then returns
        everything from that heading to the next ``##`` heading (exclusive).
        """
        for m in re.finditer(r"^(##\s+.+)$", text, re.MULTILINE):
            heading = m.group(1)
            if GitHubFetcher._slugify_heading(heading) == slug:
                start = m.start()
                # Find next ## heading
                rest = text[m.end() :]
                nxt = re.search(r"^## ", rest, re.MULTILINE)
                end = m.end() + nxt.start() if nxt else len(text)
                return text[start:end].strip()

        return None
