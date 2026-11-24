"""Check a workshop installation against published GitHub releases, without changing it."""

import json
from http.client import HTTPException
from pathlib import Path
import re
import sys
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen
from xml.etree import ElementTree


REPOSITORY = "https://github.com/Brain1917/tv-skill-workshop"
API = "https://api.github.com/repos/Brain1917/tv-skill-workshop/releases"
VERSION_FILE = Path(__file__).resolve().parents[1] / "VERSION"
SKILL_FILES = (
    "tv-workshop/VERSION", "tv-workshop/SKILL.md",
    "tv-workshop/scripts/check_version.py", "tv-workshop/references/practice.md",
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


def installation_status(version_file):
    root = version_file.parent.parent
    for name in SKILL_FILES:
        path = root / name
        try:
            present = path.is_file() and path.stat().st_size > 0
        except OSError:
            present = False
        if not present:
            return f"Не удалось найти или прочитать {name}. Распакуйте комплект целиком."
    status, latest = inspect_version(read_version(version_file))
    if status == "current":
        return "Всё установлено, можно использовать для воркшопа."
    if status == "update":
        return f"Обновите комплект до {latest} и повторите проверку: {REPOSITORY}/releases/tag/{latest}"
    return f"Файлы на месте. {latest} Сверьте версию на странице выпусков: {REPOSITORY}/releases"


if __name__ == "__main__":
    if sys.argv[1:] == ["--status"]:
        print(installation_status(VERSION_FILE))
        sys.exit(0)
    installed = read_version(VERSION_FILE)
    status, latest = inspect_version(installed)
    if status == "current":
        print(f"Установлена актуальная версия {installed}. Можно начинать практику.")
    elif status == "update":
        print(f"Установлена {installed}. Доступна {latest}. Попросите организатора обновить помощник.")
        print(f"{REPOSITORY}/releases/tag/{latest}")
    else:
        print(f"{latest} Можно продолжить с установленной копией.")
        print(f"{REPOSITORY}/releases")
