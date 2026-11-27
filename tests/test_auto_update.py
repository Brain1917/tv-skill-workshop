import importlib
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / '.opencode/skills/tv-workshop/scripts'
sys.path.insert(0, str(SCRIPTS))
versions = importlib.import_module("check_version")
install = importlib.import_module("install_release")


class UpdateTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.project = Path(tmp.name)
        self.root = self.project / '.opencode/skills'
        shutil.copytree(ROOT / '.opencode/skills', self.root)
        self.version = self.root / 'tv-workshop/VERSION'
        self.version.write_text('v0.2.0-rc.5\n')
        self.new = 'v0.2.0-rc.6'
        self.extra = [self.project/'opencode.jsonc', self.root/'my-team/SKILL.md', self.project/'Готовые скиллы/мой.zip', self.project/'AGENTS.md']
        for path in self.extra:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'local only')

    def archive(self, extra=None, tag=None):
        buffer = BytesIO()
        with ZipFile(buffer, 'w') as z:
            for name in versions.SKILL_FILES:
                data = (ROOT / '.opencode/skills' / name).read_bytes()
                if name == 'tv-workshop/VERSION':
                    data = (tag or self.new).encode()
                if name == 'tv-workshop/SKILL.md':
                    data += b'\nupdated\n'
                z.writestr('TV-Workshop/.opencode/skills/' + name, data)
            if extra:
                z.writestr(extra, 'unexpected')
        return buffer.getvalue()

    def run_status(self, package):
        with patch.object(versions, 'inspect_version', return_value=('update', self.new)), patch.object(install, 'download', return_value=package):
            return versions.installation_status(self.version)

    def test_silent_upgrade_preserves_settings_team_files_and_returns_normal_greeting(self):
        self.assertEqual(self.run_status(self.archive()), versions.READY)
        self.assertEqual(self.version.read_text(), self.new)
        self.assertTrue((self.root/'tv-workshop/SKILL.md').read_bytes().endswith(b'updated\n'))
        for path in self.extra:
            self.assertEqual(path.read_bytes(), b'local only')
        with patch.object(versions, 'inspect_version', return_value=('current', self.new)), patch.object(install, 'download', side_effect=AssertionError('download')):
            self.assertEqual(versions.installation_status(self.version), versions.READY)

    def test_corrupt_wrong_version_and_unexpected_paths_leave_previous_installation_usable(self):
        for package in [b'broken', self.archive(tag='v0.2.0'), self.archive('TV-Workshop/opencode.jsonc'), self.archive('TV-Workshop/.opencode/skills/tv-workshop/../../bad')]:
            original = {name:(self.root/name).read_bytes() for name in versions.SKILL_FILES}
            self.assertEqual(self.run_status(package), versions.READY)
            self.assertEqual(original, {name:(self.root/name).read_bytes() for name in versions.SKILL_FILES})

    def test_interrupted_update_recovers_before_offline_start(self):
        original = {name:(self.root/name).read_bytes() for name in versions.SKILL_FILES}
        replace = os.replace
        def interrupt(src, dst):
            if Path(dst) == self.version:
                raise KeyboardInterrupt()
            return replace(src, dst)
        with patch.object(install.os, 'replace', side_effect=interrupt), self.assertRaises(KeyboardInterrupt):
            self.run_status(self.archive())
        with patch.object(versions, 'inspect_version', return_value=('unknown', 'offline')):
            self.assertEqual(versions.installation_status(self.version), versions.READY)
        self.assertEqual(original, {name:(self.root/name).read_bytes() for name in versions.SKILL_FILES})

    def test_linked_target_is_never_written(self):
        target = self.root/'tv-workshop/SKILL.md'
        target.unlink()
        target.symlink_to(self.extra[0])
        self.assertNotEqual(self.run_status(self.archive()), versions.READY)
        self.assertEqual(self.extra[0].read_bytes(), b'local only')

    def test_two_concurrent_starts_download_once(self):
        package = self.archive()
        def status(tag):
            return ('current' if tag == self.new else 'update', self.new)
        with patch.object(versions, 'inspect_version', side_effect=status), patch.object(install, 'download', return_value=package) as fetch:
            with ThreadPoolExecutor(max_workers=2) as workers:
                replies = list(workers.map(versions.installation_status, [self.version, self.version]))
        self.assertEqual(replies, [versions.READY, versions.READY])
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(self.version.read_text(), self.new)
