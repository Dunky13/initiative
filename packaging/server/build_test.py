"""Focused input-integrity and listener tests; package lifecycle is smoke-test.sh."""

import base64
import hashlib
import importlib.util
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import build


class AssetIntegrityTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.assets = Path(self.temporary.name)
        for directory in ("browser", "editor", "ota"):
            (self.assets / directory).mkdir()
        (self.assets / "browser/index.html").write_text("browser")
        (self.assets / "browser/THIRD_PARTY_NOTICES.txt").write_text("licenses")
        (self.assets / "editor/editor.js").write_text("editor")
        with zipfile.ZipFile(self.assets / "ota/bundle.zip", "w") as archive:
            archive.writestr("index.html", "mobile")
        self.sign_statement("1.2.3")

    def sign_statement(self, version: str) -> None:
        digest = hashlib.sha256(
            (self.assets / "ota/bundle.zip").read_bytes()
        ).hexdigest()
        (self.assets / "ota/bundle.sha256").write_text(digest)
        (self.assets / "ota/statement.json").write_text(
            json.dumps(
                {
                    "v": 1,
                    "version": version,
                    "sha256": digest,
                    "minNativeVersion": "1.0.0",
                    "minDesktopVersion": "1.1.0",
                }
            )
        )
        # A structural test fixture, not a cryptographically verified signature.
        (self.assets / "ota/statement.sig").write_text(
            base64.b64encode(bytes(64)).decode()
        )

    def validate(self, channel: str = "release") -> None:
        build.validate_assets(self.assets, "1.2.3", "1.0.0", "1.1.0", channel)

    def test_preserves_matching_signed_assets(self) -> None:
        original = (self.assets / "ota/statement.json").read_bytes()
        self.validate()
        self.assertEqual((self.assets / "ota/statement.json").read_bytes(), original)

    def test_rejects_corrupt_bundle(self) -> None:
        (self.assets / "ota/bundle.zip").write_bytes(b"corrupted")
        with self.assertRaisesRegex(ValueError, "does not match"):
            self.validate()

    def test_rejects_mismatched_floor(self) -> None:
        with self.assertRaisesRegex(ValueError, "does not match"):
            build.validate_assets(self.assets, "1.2.3", "0.0.0", "1.1.0")

    def test_release_rejects_dev_assets(self) -> None:
        self.sign_statement("1.2.3-server-test-sha")
        with self.assertRaisesRegex(ValueError, "does not match"):
            self.validate()
        self.validate("dev")

    def test_dev_rejects_release_assets(self) -> None:
        with self.assertRaisesRegex(ValueError, "Dev assets"):
            self.validate("dev")

    def test_rejects_missing_signature(self) -> None:
        (self.assets / "ota/statement.sig").unlink()
        with self.assertRaisesRegex(ValueError, "Missing"):
            self.validate()

    def test_rejects_wrong_signature_format(self) -> None:
        (self.assets / "ota/statement.sig").write_text("not-a-signature")
        with self.assertRaises(ValueError):
            self.validate()

    def test_rejects_escape_via_symlink(self) -> None:
        (self.assets / "browser/outside").symlink_to("/etc/passwd")
        with self.assertRaisesRegex(ValueError, "symlinks"):
            self.validate()

    def test_rejects_zip_path_traversal(self) -> None:
        with zipfile.ZipFile(self.assets / "ota/bundle.zip", "a") as archive:
            archive.writestr("../escape", "bad")
        self.sign_statement("1.2.3")
        with self.assertRaisesRegex(ValueError, "Unsafe"):
            self.validate()

    def test_requires_licenses(self) -> None:
        (self.assets / "browser/THIRD_PARTY_NOTICES.txt").unlink()
        with self.assertRaisesRegex(ValueError, "THIRD_PARTY_NOTICES"):
            self.validate()


class RuntimePayloadTest(unittest.TestCase):
    def test_staged_migrations_exclude_macos_resource_forks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary) / "source"
            root = Path(temporary) / "installed"
            for name in ("app", "alembic/versions", "vendor"):
                (repo / "backend" / name).mkdir(parents=True)
            (repo / "backend/alembic.ini").write_text("[alembic]\n")
            migrations = repo / "backend/alembic/versions"
            (migrations / "revision.py").write_text("revision = 'fixture'\n")
            (migrations / "._revision.py").write_bytes(b"\x00\x05\x16\x07Mac OS X")
            (migrations / ".DS_Store").write_bytes(b"metadata")
            with patch.object(build, "REPO", repo):
                build.stage_application_source(root)
            # Alembic discovers every .py file in versions, including dotfiles.
            staged = list((root / "alembic/versions").glob("*.py"))
            self.assertEqual([path.name for path in staged], ["revision.py"])
            for path in staged:
                compile(path.read_bytes(), str(path), "exec")
            self.assertFalse((root / "alembic/versions/.DS_Store").exists())

    def test_staged_source_loads_vendored_marketplace_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            build.stage_application_source(root)
            kit = root / "vendor/plugin-kit"
            for name in (
                "KIT_VERSION",
                "KIT_REVISION",
                "manifest.contract.json",
                "plugin-manifest.json",
                "plugin-api.json",
            ):
                self.assertTrue((kit / name).is_file(), name)
            spec = importlib.util.spec_from_file_location(
                "staged_contract", root / "app/services/marketplace/contract.py"
            )
            assert spec and spec.loader
            contract = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(contract)
            self.assertEqual(
                contract.KIT_VERSION, (kit / "KIT_VERSION").read_text().strip()
            )
            self.assertTrue(contract.manifest_schema())
            self.assertTrue((root / "app/assets/email-logo.png").is_file())
            self.assertTrue((root / "app/marketplace/root.json").is_file())
            self.assertFalse(list(root.rglob("*_test.py")))
            self.assertFalse(list(root.rglob(".env")))


class ListenerTest(unittest.TestCase):
    def setUp(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "native_launcher", build.HERE / "common/launch.py"
        )
        assert spec and spec.loader
        self.launch = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.launch)
        self.config = {
            "SECRET_KEY": "test-fixture",
            "DATABASE_URL": "test-fixture",
            "APP_URL": "test-fixture",
        }

    def test_requires_operator_configuration(self) -> None:
        with self.assertRaisesRegex(ValueError, "SECRET_KEY"):
            self.launch.command({})

    def test_listener_and_trusted_proxy_are_explicit(self) -> None:
        args = self.launch.command(self.config)
        self.assertEqual(args[args.index("--host") + 1], "127.0.0.1")
        self.assertIn("--no-proxy-headers", args)
        self.assertEqual(
            args[args.index("--forwarded-allow-ips") + 1], self.launch.LOCAL_NETWORKS
        )
        self.assertEqual(
            args[args.index("--env-file") + 1], "/etc/initiative/server.env"
        )

    def test_trusts_the_proxies_the_image_trusts(self) -> None:
        start = (build.REPO / "backend/start.sh").read_text()
        self.assertIn(f"FORWARDED_ALLOW_IPS:-{self.launch.LOCAL_NETWORKS}}}", start)

    def test_proxy_setting_and_shell_text_remain_single_argv_values(self) -> None:
        args = self.launch.command(
            {**self.config, "BEHIND_PROXY": "true", "FORWARDED_ALLOW_IPS": "$(false);*"}
        )
        self.assertIn("--proxy-headers", args)
        self.assertEqual(args[args.index("--forwarded-allow-ips") + 1], "$(false);*")

    def test_refuses_invalid_port_and_proxy(self) -> None:
        for override in (
            {"INITIATIVE_PORT": "0"},
            {"INITIATIVE_PORT": "65536"},
            {"BEHIND_PROXY": "yes"},
        ):
            with self.subTest(override=override), self.assertRaises(ValueError):
                self.launch.command({**self.config, **override})


if __name__ == "__main__":
    unittest.main()
