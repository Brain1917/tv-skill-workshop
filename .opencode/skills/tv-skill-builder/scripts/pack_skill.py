"""Build and read back one team's reviewed skill, without archiving the project."""

import argparse
import os
from pathlib import Path
import re
import stat
import tempfile
from zipfile import ZIP_DEFLATED, ZipFile


BASE_FILES = ("SKILL.md", "README.md", "example.md")
RESERVED = {"tv-workshop", "tv-skill-builder", "con", "prn", "aux", "nul"}


def plain_path(path):
    # Reject directory links too. On Windows resolve also follows junctions.
    if path.resolve() != path:
        raise ValueError(f"Нужен обычный путь без ссылок: {path.name}")


def check_skill_header(text, skill_id):
    lines = text.splitlines()
    if not lines or lines[0] != "---" or "---" not in lines[1:]:
        raise ValueError("В SKILL.md нужны имя и описание между строками ---.")
    end = lines.index("---", 1)
    fields = {}
    for line in lines[1:end]:
        key, sep, value = line.partition(":")
        if sep and key in ("name", "description"):
            if key in fields:
                raise ValueError(f"Повтор поля {key} в SKILL.md.")
            fields[key] = value.strip().strip("\"'")
    if fields.get("name") != skill_id or not fields.get("description"):
        raise ValueError("Проверьте имя папки и описание в заголовке SKILL.md.")
    if not any(line.strip() for line in lines[end + 1:]):
        raise ValueError("После заголовка SKILL.md нужна инструкция.")


def build(project, skill_id, resources):
    if (len(skill_id) > 64 or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", skill_id)
            or skill_id in RESERVED or re.fullmatch(r"(?:com|lpt)[0-9]", skill_id)):
        raise ValueError("Выберите свободное имя скилла из строчных латинских букв, цифр и дефисов.")
    files = list(BASE_FILES)
    for resource in resources:
        if not re.fullmatch(r"assets/[a-z0-9][a-z0-9_-]*\.(md|txt|csv)", resource) or resource in files:
            raise ValueError("Ресурс должен быть отдельным текстовым файлом в assets/ с простым именем.")
        files.append(resource)

    skill = project / ".opencode" / "skills" / skill_id
    entries = {}
    for filename in files:
        path = skill / filename
        plain_path(path)
        info = path.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError(f"Проверьте исходный файл: {filename}")
        content = path.read_bytes()
        text = content.decode("utf-8-sig")
        if not text.strip() or b"\0" in content:
            raise ValueError(f"Ожидается непустой текст UTF-8: {filename}")
        if filename == "SKILL.md":
            check_skill_header(text, skill_id)
        entries[f"{skill_id}/{filename}"] = content

    target = project / "Готовые скиллы" / skill_id / f"{skill_id}.zip"
    plain_path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=target.parent, suffix=".zip", delete=False) as handle:
        temp = Path(handle.name)
    try:
        with ZipFile(temp, "w", ZIP_DEFLATED) as archive:
            for name, content in entries.items():
                archive.writestr(name, content)
        with ZipFile(temp) as archive:
            if archive.namelist() != list(entries) or any(archive.read(n) != b for n, b in entries.items()):
                raise ValueError("Содержимое ZIP отличается от исходных файлов.")
        os.replace(temp, target)
    finally:
        if temp.exists():
            temp.unlink()
    return target, list(entries)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("skill_id")
    parser.add_argument("resources", nargs="*")
    args = parser.parse_args()
    try:
        output, names = build(Path.cwd().resolve(), args.skill_id, args.resources)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"Архив не собран. {exc}\n")
    print(str(output), *names, sep="\n")
