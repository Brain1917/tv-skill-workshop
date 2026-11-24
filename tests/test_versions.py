import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from io import BytesIO
from urllib.error import URLError

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".opencode/skills/tv-workshop/scripts/check_version.py"
spec = importlib.util.spec_from_file_location("workshop_check", SCRIPT)
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)


def release(tag, draft=False, asset="uploaded"):
    return {"tag_name": tag, "draft": draft, "prerelease": "-rc." in tag,
            "assets": [{"name": "tv-workshop.zip", "state": asset}]}


class VersionTest(unittest.TestCase):
    def test_greeting_requires_complete_skills_and_current_release(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            version = root / "tv-workshop/VERSION"
            for name in check.SKILL_FILES:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("v0.2.0-rc.3")
            ready = "Всё установлено, можно использовать для воркшопа."
            for status, latest in [("current", "v0.2.0-rc.3"), ("update", "v0.2.0"), ("unknown", None)]:
                with self.subTest(status=status), patch.object(check, "inspect_version", return_value=(status, latest)):
                    message = check.installation_status(version)
                    self.assertEqual(message == ready, status == "current")
                    if status == "update":
                        self.assertIn(latest, message)
            (root / "tv-skill-builder/scripts/pack_skill.py").unlink()
            with patch.object(check, "inspect_version", side_effect=AssertionError("unexpected network request")):
                self.assertIn("pack_skill.py", check.installation_status(version))

    def status(self, local, releases):
        with patch.object(check, "urlopen", return_value=BytesIO(json.dumps(releases).encode())) as get:
            result = check.inspect_version(local)
        return result, get.call_args.args[0].full_url

    def test_current_candidate_ignores_older_stable_draft_and_incomplete_assets(self):
        rows = [release("v0.1.0"), release("v0.2.0-rc.2"), release("v0.2.0-rc.3", draft=True),
                release("v0.3.0-rc.1", asset="starter")]
        result, url = self.status("v0.2.0-rc.2", rows)
        self.assertEqual(result, ("current", "v0.2.0-rc.2"))
        self.assertIn("/releases?", url)

    def test_newer_candidate_or_final_triggers_update(self):
        for tag in ("v0.2.0-rc.10", "v0.2.0"):
            with self.subTest(tag=tag):
                result, _ = self.status("v0.2.0-rc.2", [release(tag), release("v0.2.0-rc.2")])
                self.assertEqual(result, ("update", tag))

    def test_production_uses_github_latest_and_never_requests_downgrade(self):
        result, url = self.status("v0.2.0", release("v0.1.0"))
        self.assertEqual(result[0], "unknown")
        self.assertTrue(url.endswith("/latest"))
        self.assertEqual(self.status("v0.2.0", release("v0.2.1"))[0], ("update", "v0.2.1"))

    def test_offline_unknown_or_corrupt_response_never_claims_current(self):
        with patch.object(check, "urlopen", side_effect=URLError("offline")):
            self.assertEqual(check.inspect_version("v0.2.0-rc.2")[0], "unknown")
        for data in ([], {"message": "rate limited"}, [release("v0.1.0")], [release("not-a-version")]):
            self.assertEqual(self.status("v0.2.0-rc.2", data)[0][0], "unknown")
