#!/usr/bin/env python3
"""Audit GitHub Pages after an account rename; apply reviewed URL-only repairs."""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import html.parser
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import tarfile
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

MAX_HTML = 2_000_000
UA = "PagesMigrationBot/1.0 (repository owner maintenance)"


def now():
    return datetime.now(timezone.utc).isoformat()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def owner_name(value):
    if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})", value):
        raise ValueError("Invalid GitHub account name")
    return value


def rewrite(text, old, new):
    """Change exact GitHub URL authorities/owner segments, never brand names."""
    owner_name(old)
    owner_name(new)
    patterns = [
        (rf"(?i)(https?://|//){re.escape(old)}\.github\.io(?=[/\s\"'<>?#)]|$)",
         lambda m: m[1] + new.lower() + ".github.io"),
        (rf"(?i)((?:https?://|//)(?:github\.com|raw\.githubusercontent\.com)/){re.escape(old)}(?=[/\s\"'<>?#)]|$)",
         lambda m: m[1] + new),
        (rf"(?i)((?:https?://|//)api\.github\.com/repos/){re.escape(old)}(?=/)",
         lambda m: m[1] + new),
    ]
    for pattern, replacement in patterns:
        text = re.sub(pattern, replacement, text)
    return text


class ApiRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urllib.parse.urlsplit(newurl).hostname != "api.github.com":
            raise ValueError("Refusing to forward GitHub API credentials to another host")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def github(path):
    headers = {"User-Agent": UA, "Accept": "application/vnd.github+json"}
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = "Bearer " + token
    request = urllib.request.Request("https://api.github.com" + path, headers=headers)
    with urllib.request.build_opener(ApiRedirect).open(request, timeout=30) as response:
        return json.load(response)


def repositories(owner):
    result = []
    page = 1
    while True:
        batch = github(f"/users/{owner_name(owner)}/repos?per_page=100&page={page}&type=owner")
        result.extend(batch)
        if len(batch) < 100:
            return result
        page += 1


def fetch(url, *, body=False):
    request = urllib.request.Request(url, headers={"User-Agent": UA}, method="GET" if body else "HEAD")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            content = response.read(MAX_HTML + 1) if body else b""
            result = {"url": url, "final_url": response.url, "status": response.status}
            if body:
                result.update(sha256=sha(content), truncated=len(content) > MAX_HTML)
            return result, content
    except urllib.error.HTTPError as error:
        return {"url": url, "status": error.code}, b""
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        return {"url": url, "status": None, "error": str(error)}, b""


class PageLinks(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = set()
        self.assets = set()

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        for key in ("href", "src", "poster"):
            if attrs.get(key):
                self.links.add(attrs[key])
        if tag in ("script", "img", "source") and attrs.get("src"):
            self.assets.add(attrs["src"])
        if tag == "link" and "stylesheet" in attrs.get("rel", "") and attrs.get("href"):
            self.assets.add(attrs["href"])


def site_url(owner, name):
    path = "" if name.lower() == owner.lower() + ".github.io" else urllib.parse.quote(name) + "/"
    return f"https://{owner.lower()}.github.io/{path}"


def audit_site(repo, owner, old, paths):
    base = site_url(owner, repo["name"])
    result = {"repository": repo["full_name"], "url": base,
              "homepage": repo.get("homepage"), "pages": [],
              "browser_security": "not_assessed: HTTP success does not establish browser safety"}
    homepage = repo.get("homepage") or ""
    corrected = rewrite(homepage, old, owner)
    if homepage != corrected:
        result["suggested_homepage"] = corrected
    allowed_hosts = {owner.lower() + ".github.io", old.lower() + ".github.io"}
    for path in paths:
        if path.startswith("/") or ".." in PurePosixPath(path).parts or ":" in path:
            raise ValueError("Audit paths must stay under the repository's Pages root")
        url = urllib.parse.urljoin(base, path)
        page, content = fetch(url, body=True)
        if page.get("status") == 200 and not page.get("truncated"):
            parser = PageLinks()
            parser.feed(content.decode("utf-8", errors="replace"))
            page["stale_links"] = sorted(x for x in parser.links if rewrite(x, old, owner) != x)
            assets = sorted({urllib.parse.urljoin(url, x) for x in parser.assets})
            assets = [x for x in assets if urllib.parse.urlsplit(x).hostname in allowed_hosts]
            page["assets_checked"] = min(len(assets), 64)
            page["assets_not_checked"] = max(0, len(assets) - 64)
            with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
                checks = list(executor.map(lambda x: fetch(x)[0], assets[:64]))
            page["failed_assets"] = [x for x in checks if x.get("status") != 200]
        result["pages"].append(page)
    return result


def audit(args):
    inventory = repositories(args.owner)
    routes = json.loads(Path(args.routes).read_text()) if args.routes else {}
    active = [r for r in inventory if r.get("has_pages")]
    results = []
    for repo in active:
        result = audit_site(repo, args.owner, args.previous_owner, routes.get(repo["name"], [""]))
        results.append(result)
        print(f"{repo['name']}: " + ", ".join(str(p.get("status")) for p in result["pages"]), flush=True)
    report = {"checked_at": now(), "owner": args.owner, "previous_owner": args.previous_owner,
              "inventory_scope": "Public repositories; private Pages require an authenticated inventory supplied separately",
              "public_repositories": len(inventory), "pages_repositories": len(active), "sites": results}
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n")
    lines = ["# GitHub Pages migration audit", "", f"Checked: {report['checked_at']}", "",
             "HTTP availability and browser security classifications are separate checks.", "",
             "| Repository | Page | HTTP | Stale links | Failed assets |", "|---|---|---:|---:|---:|"]
    for site in results:
        for page in site["pages"]:
            lines.append(f"| {site['repository']} | {page['url']} | {page.get('status')} | {len(page.get('stale_links', []))} | {len(page.get('failed_assets', []))} |")
    output.with_suffix(".md").write_text("\n".join(lines) + "\n")
    if args.fail_on_issues and any(
        site.get("suggested_homepage") or any(
            page.get("status") != 200 or page.get("stale_links") or page.get("failed_assets")
            for page in site["pages"]
        ) for site in results
    ):
        raise SystemExit(2)


def git(repo, *args, data=None):
    return subprocess.check_output(["git", "-C", str(repo), *args], input=data).decode().strip()


def safe_path(repo, relative):
    p = PurePosixPath(relative)
    if p.is_absolute() or not p.parts or ".." in p.parts or ".git" in p.parts:
        raise ValueError("Unsafe repair path")
    candidate = repo / relative
    if candidate.is_symlink() or not candidate.resolve().is_relative_to(repo.resolve()):
        raise ValueError("Repair paths cannot be symlinks or leave the checkout")
    if not candidate.is_file():
        raise ValueError("Repair path must be an existing regular file")
    return candidate


def require_clean(repo):
    if git(repo, "status", "--porcelain"):
        raise ValueError("Use a clean isolated checkout; concurrent changes will not be overwritten")


def plan(args):
    repo = Path(args.repo).resolve()
    require_clean(repo)
    head = git(repo, "rev-parse", "HEAD")
    changes = []
    for relative in dict.fromkeys(args.files):
        path = safe_path(repo, relative)
        git(repo, "ls-files", "--error-unmatch", "--", relative)
        before = path.read_bytes()
        if len(before) > 5_000_000 or b"\0" in before:
            raise ValueError("Repair supports small UTF-8 text files only")
        after = rewrite(before.decode("utf-8"), args.previous_owner, args.owner).encode("utf-8")
        if before != after:
            changes.append({"path": relative, "before_sha256": sha(before), "after_sha256": sha(after)})
    document = {"schema": 1, "created_at": now(), "head": head,
                "owner": args.owner, "previous_owner": args.previous_owner, "changes": changes}
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(document, indent=2) + "\n")
    print(f"Planned URL-only repairs in {len(changes)} explicitly selected files; nothing written to the checkout")


def apply(args):
    repo = Path(args.repo).resolve()
    document = json.loads(Path(args.plan).read_text())
    if document.get("schema") != 1 or git(repo, "rev-parse", "HEAD") != document["head"]:
        raise ValueError("Plan is stale or unsupported; regenerate it against the current HEAD")
    require_clean(repo)
    prepared = []
    for change in document["changes"]:
        path = safe_path(repo, change["path"])
        before = path.read_bytes()
        after = rewrite(before.decode("utf-8"), document["previous_owner"], document["owner"]).encode("utf-8")
        if sha(before) != change["before_sha256"] or sha(after) != change["after_sha256"]:
            raise ValueError("Content differs from the reviewed plan")
        prepared.append((path, change["path"], before, after))
    backup = Path(args.backup).resolve()
    if backup.is_relative_to(repo):
        raise ValueError("Keep backups outside the checkout")
    backup.mkdir(parents=True, exist_ok=False)
    (backup / "plan.json").write_text(json.dumps(document, indent=2) + "\n")
    with tarfile.open(backup / "before.tar.gz", "w:gz") as archive:
        for path, relative, _, _ in prepared:
            archive.add(path, arcname=relative, recursive=False)
    with tarfile.open(backup / "before.tar.gz") as archive:
        for _, relative, before, _ in prepared:
            if archive.extractfile(relative).read() != before:
                raise ValueError("Backup verification failed")
    for path, _, _, after in prepared:
        path.write_bytes(after)
    git(repo, "diff", "--check")
    print(f"Applied {len(prepared)} URL-only repairs. Verified backup: {backup}")
    print("Run the repository's required checks, inspect git diff, then commit and push explicit paths.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    audit_parser = sub.add_parser("audit")
    audit_parser.add_argument("--owner", required=True, type=owner_name)
    audit_parser.add_argument("--previous-owner", required=True, type=owner_name)
    audit_parser.add_argument("--routes")
    audit_parser.add_argument("--output", required=True)
    audit_parser.add_argument("--fail-on-issues", action="store_true")
    audit_parser.set_defaults(func=audit)
    plan_parser = sub.add_parser("plan")
    plan_parser.add_argument("--repo", required=True)
    plan_parser.add_argument("--owner", required=True, type=owner_name)
    plan_parser.add_argument("--previous-owner", required=True, type=owner_name)
    plan_parser.add_argument("--files", nargs="+", required=True)
    plan_parser.add_argument("--output", required=True)
    plan_parser.set_defaults(func=plan)
    apply_parser = sub.add_parser("apply")
    apply_parser.add_argument("--repo", required=True)
    apply_parser.add_argument("--plan", required=True)
    apply_parser.add_argument("--backup", required=True)
    apply_parser.set_defaults(func=apply)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
