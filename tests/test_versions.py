import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import sys
import unittest
from unittest.mock import patch
from io import BytesIO
from urllib.error import HTTPError, URLError

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".opencode/skills/tv-workshop/scripts/check_version.py"
sys.path.insert(0, str(SCRIPT.parent))
spec = importlib.util.spec_from_file_location("workshop_check", SCRIPT)
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)


def release(tag, draft=False, asset="uploaded"):
    return {"tag_name": tag, "draft": draft, "prerelease": "-rc." in tag,
            "assets": [{"name": "tv-workshop.zip", "state": asset}]}


def http_error(code, headers=None):
    return HTTPError(check.API, code, "", headers or {}, BytesIO(b""))


def feed(*tags):
    entries = "".join(f'<entry><link rel="alternate" href="{check.REPOSITORY}/releases/tag/{tag}"/></entry>'
                      for tag in tags)
    return BytesIO(f'<feed xmlns="http://www.w3.org/2005/Atom">{entries}</feed>'.encode())


class VersionTest(unittest.TestCase):
    def test_limited_api_uses_atom_and_only_offers_downloadable_release_in_channel(self):
        for local, assets, expected, probes in [
            ("v0.2.0-rc.2", [True], ("update", "v0.2.0-rc.10"), ["v0.2.0-rc.10"]),
            ("v0.2.0-rc.2", [False, True], ("current", "v0.2.0-rc.2"), ["v0.2.0-rc.10", "v0.2.0-rc.2"]),
            ("v0.1.0", [True], ("current", "v0.1.0"), ["v0.1.0"]),
        ]:
            with self.subTest(local=local, assets=assets), patch.object(check, "urlopen", side_effect=[
                http_error(403, {"X-RateLimit-Remaining":"0"}), feed("v0.1.0", "v0.2.0-rc.2", "v0.2.0-rc.10")
            ]) as get, patch.object(check, "asset_exists", side_effect=assets) as head:
                self.assertEqual(check.inspect_version(local), expected)
                self.assertTrue(get.call_args.args[0].full_url.endswith("/releases.atom"))
                self.assertEqual([call.args[0] for call in head.call_args_list], probes)

    def test_inaccessible_newer_archive_never_confirms_old_installation(self):
        with patch.object(check, "urlopen", side_effect=[
            http_error(429), feed("v0.2.0-rc.3", "v0.2.0-rc.4")
        ]), patch.object(check, "asset_exists", side_effect=http_error(503)):
            status, reason = check.inspect_version("v0.2.0-rc.3")
            self.assertEqual(status, "unknown")
            self.assertIn("503", reason)
            self.assertIn("лимит", reason.lower())

    def test_diagnostics_distinguish_rate_limit_network_proxy_and_missing_page(self):
        for error, phrase in [(http_error(403, {"X-RateLimit-Remaining":"0"}), "лимит"),
                              (URLError("offline"), "соединение"), (http_error(407), "прокси"),
                              (http_error(404), "404"), (http_error(403), "403")]:
            with self.subTest(phrase=phrase), patch.object(check, "urlopen", side_effect=error):
                status, reason = check.inspect_version("v0.2.0-rc.3")
                self.assertEqual(status, "unknown")
                self.assertIn(phrase, reason.lower())
                if phrase == "403":
                    self.assertNotIn("лимит", reason.lower())

    def test_greeting_requires_usable_skills_with_or_without_network(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            version = root / "tv-workshop/VERSION"
            for name in check.SKILL_FILES:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("v0.2.0-rc.3")
            ready = "Всё установлено, можно использовать для воркшопа."
            for status, latest in [("current", "v0.2.0-rc.3"), ("unknown", "offline")]:
                with self.subTest(status=status), patch.object(check, "inspect_version", return_value=(status, latest)):
                    self.assertEqual(check.installation_status(version), ready)
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
