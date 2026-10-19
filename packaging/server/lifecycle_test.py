"""Exercise Debian service cleanup with the installed helper in an isolated root."""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import build

HERE = Path(__file__).resolve().parent
HELPER = shutil.which("deb-systemd-helper")


@unittest.skipUnless(HELPER, "requires Debian's installed deb-systemd-helper")
class DebianServiceLifecycleTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="initiative-helper-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.env = {
            **os.environ,
            "DPKG_ROOT": str(self.root),
            "DPKG_MAINTSCRIPT_PACKAGE": "initiative-server",
        }
        self.unit = self.root / "usr/lib/systemd/system/initiative-server.service"
        self.unit.parent.mkdir(parents=True)
        shutil.copyfile(HERE / "debian/initiative-server.service", self.unit)
        self.link = (
            self.root
            / "etc/systemd/system/multi-user.target.wants/initiative-server.service"
        )
        self.link.parent.mkdir(parents=True)
        assert HELPER
        subprocess.run(
            [HELPER, "update-state", "initiative-server.service"],
            env=self.env,
            check=True,
        )

    def postrm(self, action: str) -> None:
        subprocess.run(
            ["/bin/sh", str(HERE / "debian/postrm"), action], env=self.env, check=True
        )

    def test_upgrade_and_remove_preserve_enabled_link_then_purge_cleans_it_offline(
        self,
    ) -> None:
        self.assertFalse(
            self.link.is_symlink(), "recording state must not enable the service"
        )
        self.link.symlink_to("/usr/lib/systemd/system/initiative-server.service")
        self.postrm("upgrade")
        self.assertTrue(self.link.is_symlink())
        # Removal has already deleted the package's unit before postrm executes.
        self.unit.unlink()
        self.postrm("remove")
        self.assertTrue(self.link.is_symlink())
        # Hide systemctl entirely: helper cleanup must work without systemd.
        tools = self.root / "test-tools"
        tools.mkdir()
        assert HELPER
        (tools / "deb-systemd-helper").symlink_to(HELPER)
        self.env["PATH"] = str(tools)
        self.postrm("purge")
        self.assertFalse(
            self.link.is_symlink(), "purge left a dangling enabled service link"
        )
        self.assertFalse(
            (
                self.root
                / "var/lib/systemd/deb-systemd-helper-enabled/initiative-server.service.dsh-also"
            ).exists()
        )
        self.postrm("purge")

    def test_purge_never_enables_an_unconfigured_service(self) -> None:
        self.assertFalse(self.link.is_symlink())
        self.unit.unlink()
        self.postrm("purge")
        self.assertFalse(self.link.is_symlink())


@unittest.skipUnless(
    shutil.which("abuild") and shutil.which("apk"),
    "requires Alpine's installed abuild and apk tools",
)
class StandaloneApkTest(unittest.TestCase):
    def test_signed_package_build_needs_no_global_trust_or_repository_index(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="initiative-apk-test-") as temporary:
            root = Path(temporary)
            stage, work, output = root / "payload", root / "work", root / "output"
            (stage / "usr/lib/initiative").mkdir(parents=True)
            (stage / "etc/initiative").mkdir(parents=True)
            (stage / "usr/lib/initiative/test-payload.txt").write_text(
                "standalone package fixture\n"
            )
            (stage / "etc/initiative/server.env").write_text("SECRET_KEY=\n")
            work.mkdir()
            output.mkdir()
            key = root / "fixture.rsa"
            subprocess.run(
                ["openssl", "genrsa", "-out", str(key), "2048"],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            keys = Path("/etc/apk/keys")
            trusted_before = {
                path.name: path.read_bytes()
                for path in keys.iterdir()
                if path.is_file()
            }
            with patch.dict(os.environ, {"APK_SIGNING_KEY": str(key)}):
                build.apk_package(stage, output, "1.2.3", 1, work)
            packages = list(output.glob("*.apk"))
            self.assertEqual(len(packages), 1)
            self.assertFalse(list(work.rglob("APKINDEX.tar.gz")))
            self.assertFalse(list(work.rglob("Packages.adb")))
            self.assertEqual(
                trusted_before,
                {
                    path.name: path.read_bytes()
                    for path in keys.iterdir()
                    if path.is_file()
                },
            )
            # A package signed with a new fixture key is rejected by default.
            rejected = subprocess.run(
                ["apk", "verify", str(packages[0])], capture_output=True
            )
            self.assertNotEqual(rejected.returncode, 0)
            # Trust only this invocation's fixture key, without --allow-untrusted.
            trust = root / "isolated-trust"
            trust.mkdir()
            public = output / "initiative-server.rsa.pub"
            shutil.copyfile(public, trust / public.name)
            subprocess.run(
                ["apk", "verify", "--keys-dir", str(trust), str(packages[0])],
                check=True,
            )


if __name__ == "__main__":
    unittest.main()
