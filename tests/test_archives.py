import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from zipfile import ZipFile


ROOT = Path(__file__).resolve().parents[1]
PACKER = ROOT / ".opencode/skills/tv-skill-builder/scripts/pack_skill.py"


class ArchiveTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.project = Path(self.tmp.name) / "Учебная редакция"
        self.skill = self.project / ".opencode/skills/news-brief"
        self.skill.mkdir(parents=True)
        self.contents = {"SKILL.md": "---\nname: news-brief\ndescription: Выделить поручения\n---\nПокажи задачу и срок.",
                         "README.md": "Откройте пример и попросите выделить поручения.",
                         "example.md": "Учебный материал. Редактор проверит титры."}
        for name, content in self.contents.items():
            (self.skill / name).write_text(content, encoding="utf-8")
        (self.project / "opencode.jsonc").write_text("LOCAL-ONLY")
        self.archive = self.project / "Готовые скиллы/news-brief/news-brief.zip"

    def pack(self, *extra, skill_id="news-brief"):
        return subprocess.run([sys.executable, str(PACKER), skill_id, *extra],
                              cwd=self.project, capture_output=True, text=True)

    def test_zip_installs_in_clean_project_and_rebuild_replaces_previous_files(self):
        (self.skill / "private.md").write_text("LOCAL-ONLY")
        (self.skill / "assets").mkdir()
        (self.skill / "assets/table.md").write_text("Шаблон")
        result = self.pack("assets/table.md")
        self.assertEqual(result.returncode, 0, result.stderr)
        with ZipFile(self.archive) as z:
            expected = {f"news-brief/{p}" for p in [*self.contents, "assets/table.md"]}
            self.assertEqual(set(z.namelist()), expected)
            self.assertTrue(all(b"LOCAL-ONLY" not in z.read(p) for p in z.namelist()))
            clean = Path(self.tmp.name) / "Получатель/.opencode/skills"
            z.extractall(clean)
            self.assertEqual((clean / "news-brief/example.md").read_text(), self.contents["example.md"])
        revised = self.contents["SKILL.md"] + "\nЕсли срок не указан, напиши «уточнить»."
        (self.skill / "SKILL.md").write_text(revised)
        self.assertEqual(self.pack().returncode, 0)
        with ZipFile(self.archive) as z:
            self.assertEqual(z.read("news-brief/SKILL.md").decode(), revised)
            self.assertNotIn("news-brief/assets/table.md", z.namelist())

    def test_bad_resource_or_missing_file_preserves_previous_archive(self):
        self.assertEqual(self.pack().returncode, 0)
        previous = self.archive.read_bytes()
        for path in ["../opencode.jsonc", "assets/../../config.md", "assets/secret.env", "README.md", "assets/.private.md"]:
            with self.subTest(path=path):
                self.assertNotEqual(self.pack(path).returncode, 0)
        (self.skill / "example.md").unlink()
        self.assertNotEqual(self.pack().returncode, 0)
        self.assertEqual(previous, self.archive.read_bytes())

    def test_links_and_reserved_names_do_not_escape_team_folders(self):
        (self.skill / "assets").mkdir()
        private = self.project / "opencode.jsonc"
        (self.skill / "assets/link.md").symlink_to(private)
        os.link(private, self.skill / "assets/shared.md")
        for name in ["assets/link.md", "assets/shared.md"]:
            self.assertNotEqual(self.pack(name).returncode, 0)
        for skill_id in ["../news-brief", "tv-workshop", "tv-skill-builder", "con"]:
            self.assertNotEqual(self.pack(skill_id=skill_id).returncode, 0)
        (self.project / "Готовые скиллы").symlink_to(self.project, target_is_directory=True)
        self.assertNotEqual(self.pack().returncode, 0)
        self.assertFalse((self.project / "news-brief").exists())

    def test_damaged_skill_cannot_replace_openable_version(self):
        self.assertEqual(self.pack().returncode, 0)
        previous = self.archive.read_bytes()
        for text in ["Только ответ в чате", "---\nname: other\ndescription: Проверка\n---\nИнструкция",
                     "---\nname: news-brief\n---\nИнструкция"]:
            with self.subTest(text=text):
                (self.skill / "SKILL.md").write_text(text)
                self.assertNotEqual(self.pack().returncode, 0)
                self.assertEqual(self.archive.read_bytes(), previous)

    def test_release_from_commit_has_only_installer_materials(self):
        # Include a tracked machine setting and an untracked credential in a throwaway repository.
        repo = Path(self.tmp.name) / "release"
        shutil.copytree(ROOT, repo, ignore=shutil.ignore_patterns(".git", "__pycache__", ".ruff_cache"))
        def git(*args):
            subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)
        git("init", "-q")
        (repo / "opencode.jsonc").write_text("LOCAL-ONLY")
        git("add", ".")
        git("-c", "user.name=Test", "-c", "user.email=test@localhost", "commit", "-qm", "test")
        (repo / ".env").write_text("LOCAL-ONLY")
        archive = Path(self.tmp.name) / "release.zip"
        result = subprocess.run(["sh", str(repo / "tools/build-release.sh"), str(archive)],
                                cwd=repo, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        with ZipFile(archive) as z:
            files = {n.removeprefix("TV-Workshop/") for n in z.namelist() if not n.endswith("/")}
            self.assertEqual(files, {"README.md", "Начать практику.md", "AGENTS.md",
                ".opencode/skills/tv-workshop/VERSION",
                ".opencode/skills/tv-workshop/scripts/check_version.py",
                ".opencode/skills/tv-workshop/scripts/install_release.py",
                ".opencode/skills/tv-workshop/SKILL.md", ".opencode/skills/tv-skill-builder/SKILL.md",
                ".opencode/skills/tv-workshop/references/practice.md",
                ".opencode/skills/tv-workshop/references/clear-russian.md",
                ".opencode/skills/tv-skill-builder/references/native-pack.md",
                ".opencode/skills/tv-skill-builder/scripts/pack_skill.py"})
            self.assertTrue(all(b"LOCAL-ONLY" not in z.read(n) for n in z.namelist()))
