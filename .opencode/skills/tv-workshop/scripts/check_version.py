"""Check a workshop installation against published GitHub releases, without changing it."""

import json
from http.client import HTTPException
from pathlib import Path
import re
import sys
from urllib.request import Request, urlopen


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


def inspect_version(local):
    if not TAG.fullmatch(local):
        return "unknown", None
    rehearsal = "-rc." in local
    url = API + ("?per_page=100" if rehearsal else "/latest")
    try:
        request = Request(url, headers={"User-Agent": "tv-skill-workshop", "Accept": "application/vnd.github+json"})
        with urlopen(request, timeout=5) as response:
            data = json.load(response)
    except (OSError, ValueError, HTTPException):
        return "unknown", None
    rows = data if rehearsal else [data]
    if not isinstance(rows, list):
        return "unknown", None
    newest = max((r["tag_name"] for r in rows if available(r, rehearsal)), key=order, default=None)
    if newest is None or order(newest) < order(local):
        return "unknown", None
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
    return "Файлы на месте. Сверить версию с GitHub не удалось. Повторите проверку позже."


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
        print("Актуальность версии проверить не удалось. Можно продолжить с установленной копией.")
        print(f"{REPOSITORY}/releases")
