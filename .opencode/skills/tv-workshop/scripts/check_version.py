"""Check a workshop installation and quietly install new GitHub releases."""

import json
from http.client import HTTPException
from pathlib import Path
import re
from zipfile import BadZipFile
from zlib import error as ZlibError
import install_release
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen
from xml.etree import ElementTree


REPOSITORY = "https://github.com/Brain1917/tv-skill-workshop"
API = "https://api.github.com/repos/Brain1917/tv-skill-workshop/releases"
VERSION_FILE = Path(__file__).absolute().parents[1] / "VERSION"
SKILL_FILES = (
    "tv-workshop/VERSION", "tv-workshop/SKILL.md",
    "tv-workshop/scripts/check_version.py", "tv-workshop/scripts/install_release.py", "tv-workshop/references/practice.md",
    "tv-workshop/references/clear-russian.md", "tv-skill-builder/SKILL.md",
    "tv-skill-builder/references/native-pack.md", "tv-skill-builder/scripts/pack_skill.py",
)
TAG = re.compile(r"v(\d{1,9})\.(\d{1,9})\.(\d{1,9})(?:-rc\.(\d{1,9}))?")
ATOM = "{http://www.w3.org/2005/Atom}"
FAILURES = (OSError, ValueError, HTTPException, ElementTree.ParseError)


def order(tag):
    major, minor, patch, rc = TAG.fullmatch(tag).groups()
    return (int(major), int(minor), int(patch), rc is None, int(rc or 0))


def available(row, rehearsal):
    if not isinstance(row, dict) or row.get("draft") is not False:
        return False
    tag = row.get("tag_name")
    if not isinstance(tag, str) or not TAG.fullmatch(tag):
        return False
    trial = "-rc." in tag
    if row.get("prerelease") is not trial or (trial and not rehearsal):
        return False
    assets = row.get("assets")
    return isinstance(assets, list) and any(
        isinstance(a, dict) and a.get("name") == "tv-workshop.zip" and a.get("state") == "uploaded"
        for a in assets
    )


def latest_from_api(rehearsal):
    url = API + ("?per_page=100" if rehearsal else "/latest")
    request = Request(url, headers={"User-Agent": "tv-skill-workshop", "Accept": "application/vnd.github+json"})
    with urlopen(request, timeout=5) as response:
        data = json.load(response)
    rows = data if rehearsal else [data]
    if not isinstance(rows, list):
        raise ValueError("release list")
    return max((r["tag_name"] for r in rows if available(r, rehearsal)), key=order, default=None)


class KeepHead(HTTPRedirectHandler):
    # urllib follows a 302 after HEAD with GET by default; only the archive headers are needed.
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        redirect = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirect is not None and req.get_method() == "HEAD":
            redirect.method = "HEAD"
        return redirect


def asset_exists(tag):
    request = Request(f"{REPOSITORY}/releases/download/{tag}/tv-workshop.zip", method="HEAD")
    try:
        with build_opener(KeepHead()).open(request, timeout=5) as response:
            if response.status != 200 or response.headers.get_content_type() == "text/html":
                raise ValueError("archive response")
            return True
    except HTTPError as error:
        if error.code != 404:
            raise
        error.close()
        return False


def latest_from_feed(local):
    request = Request(f"{REPOSITORY}/releases.atom", headers={"User-Agent": "tv-skill-workshop"})
    with urlopen(request, timeout=5) as response:
        root = ElementTree.parse(response).getroot()
    if root.tag != ATOM + "feed":
        raise ValueError("release feed")
    prefix = f"{REPOSITORY}/releases/tag/"
    tags = set()
    for link in root.findall(f"{ATOM}entry/{ATOM}link"):
        url = link.get("href", "")
        if link.get("rel", "alternate") == "alternate" and url.startswith(prefix):
            tag = url[len(prefix):]
            if TAG.fullmatch(tag) and ("-rc." in local or "-rc." not in tag) and order(tag) >= order(local):
                tags.add(tag)
    return next((tag for tag in sorted(tags, key=order, reverse=True) if asset_exists(tag)), None)


def diagnostic(error):
    if isinstance(error, HTTPError):
        code, headers = error.code, error.headers or {}
        error.close()
        if code == 429 or (code == 403 and (headers.get("X-RateLimit-Remaining") == "0" or headers.get("Retry-After"))):
            return "исчерпан лимит запросов"
        if code == 404:
            return "страница не найдена (HTTP 404), проверьте адрес и доступ к репозиторию"
        if code == 407:
            return "прокси требует авторизации (HTTP 407)"
        return f"сервер вернул HTTP {code}"
    if isinstance(error, (OSError, HTTPException)):
        return "не удалось установить соединение с GitHub"
    return "не удалось прочитать ответ GitHub"


def inspect_version(local):
    if not TAG.fullmatch(local):
        return "unknown", "Не удалось прочитать номер установленной версии в VERSION."
    try:
        newest = latest_from_api("-rc." in local)
    except FAILURES as api_error:
        api_reason = diagnostic(api_error)
        try:
            newest = latest_from_feed(local)
        except FAILURES as fallback_error:
            return "unknown", f"GitHub API: {api_reason}. Резервная проверка: {diagnostic(fallback_error)}."
        if newest is None:
            return "unknown", f"GitHub API: {api_reason}. В ленте не найден подходящий выпуск с архивом."
    if newest is None or order(newest) < order(local):
        return "unknown", "На GitHub не найден подходящий опубликованный выпуск с архивом."
    return ("current" if newest == local else "update"), newest


def read_version(path):
    try:
        return path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return ""


READY = "Всё установлено, можно использовать для воркшопа."
HELP = "Позовите технического помощника к вашему столу."
INSTALL_ERRORS = (*FAILURES, BadZipFile, RuntimeError, EOFError, ZlibError)


def installation_status(version_file):
    root = version_file.parent.parent
    try:
        install_release.validate_tree(root, SKILL_FILES)
        with install_release.locked(root):
            install_release.recover(root, SKILL_FILES)
            local = read_version(version_file)
            if not TAG.fullmatch(local):
                return HELP
            status, latest = inspect_version(local)
            if status == "update":
                try:
                    install_release.install(root, latest, SKILL_FILES, REPOSITORY)
                except INSTALL_ERRORS:
                    install_release.recover(root, SKILL_FILES)
            return READY
    except FileNotFoundError as exc:
        name = Path(exc.filename).name if exc.filename else ""
        if name and name in {Path(path).name for path in SKILL_FILES}:
            return f"Не найден {name}. {HELP}"
        return HELP
    except INSTALL_ERRORS:
        return HELP


if __name__ == "__main__":
    print(installation_status(VERSION_FILE))
