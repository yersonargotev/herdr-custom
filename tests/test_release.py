import hashlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import struct
import subprocess
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('release_verifier', ROOT / 'scripts/verify_release.py')
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'recipe'
        self.root.mkdir()
        for name in ['VERSION', 'LICENSE', 'NOTICE', 'README.md', 'upstream.lock.json',
                     'scripts/herdr-custom', 'config/config.toml']:
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / name, target)
        shutil.copytree(ROOT / 'patches', self.root / 'patches')
        self.git('init', '-q')
        self.git('add', '.')
        self.git('-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '-qm', 'fixture')
        self.commit = self.git('rev-parse', 'HEAD').strip()
        self.lock = json.loads((self.root / 'upstream.lock.json').read_text())
        self.dist = Path(self.tmp.name) / 'dist'
        self.dist.mkdir()

    def git(self, *args):
        return subprocess.check_output(['git', *args], cwd=self.root).decode()

    def archive(self, platform='macos-aarch64', changes=None, extra=None, mode=0o755, duplicate=None, omit=()):
        name = 'herdr-custom-' + self.lock['distribution_version'] + '-' + platform
        archive = self.dist / (name + '.tar.gz')
        binary = (struct.pack('<IIII', 0xfeedfacf, 0x0100000c, 0, 2) if platform == 'macos-aarch64'
                  else b'\x7fELF\x02\x01\x01' + b'\0' * 9 + struct.pack('<HH', 2, 62))
        files = {p: (self.root / p).read_bytes() for p in
                 ['VERSION', 'LICENSE', 'NOTICE', 'README.md', 'upstream.lock.json']}
        files.update({'bin/herdr-custom': (self.root / 'scripts/herdr-custom').read_bytes(),
                      'config/config.toml': (self.root / 'config/config.toml').read_bytes(),
                      'libexec/herdr': binary})
        files.update({p['path']: (self.root / p['path']).read_bytes() for p in self.lock['patches']})
        files['provenance.json'] = json.dumps(dict(self.lock, platform=platform, recipe_commit=self.commit,
                                                  binary_sha256=hashlib.sha256(binary).hexdigest())).encode()
        files.update(changes or {})
        for path in omit:
            del files[path]
        with tarfile.open(archive, 'w:gz') as tar:
            for path, data in files.items():
                member = tarfile.TarInfo(name + '/' + path)
                member.size = len(data)
                member.mode = mode if path in ('bin/herdr-custom', 'libexec/herdr') else 0o644
                tar.addfile(member, io.BytesIO(data))
            if extra:
                tar.addfile(extra)
            if duplicate:
                member = tarfile.TarInfo(name + '/' + duplicate)
                member.size = len(files[duplicate])
                tar.addfile(member, io.BytesIO(files[duplicate]))
        archive.with_name(archive.name + '.sha256').write_text(
            hashlib.sha256(archive.read_bytes()).hexdigest() + '  ' + archive.name + '\n')
        return archive

    def verify(self, platforms=('macos-aarch64',)):
        return verifier.verify_release(self.dist, self.root, self.commit, platforms)

    def test_complete_platform_pair_reports_measured_digests(self):
        for platform in verifier.PLATFORMS:
            self.archive(platform)
        reports = self.verify(verifier.PLATFORMS)
        self.assertEqual({report.platform for report in reports}, set(verifier.PLATFORMS))
        self.assertTrue(all(report.recipe_commit == self.commit for report in reports))
        for report in reports:
            self.assertEqual(report.archive_sha256, hashlib.sha256(Path(report.archive).read_bytes()).hexdigest())

    def test_missing_platform_and_stale_artifacts_are_rejected(self):
        self.archive()
        with self.assertRaisesRegex(ValueError, 'exactly the selected archives'):
            self.verify(verifier.PLATFORMS)
        (self.dist / 'stale.tar.gz').write_text('stale')
        with self.assertRaisesRegex(ValueError, 'exactly the selected archives'):
            self.verify()

    def test_expected_commit_must_be_full_current_and_clean(self):
        self.archive()
        for commit, message in [('short', 'full Git commit'), ('0' * 40, 'HEAD differs')]:
            with self.subTest(commit=commit), self.assertRaisesRegex(ValueError, message):
                verifier.verify_release(self.dist, self.root, commit, ('macos-aarch64',))
        (self.root / 'README.md').write_text('changed')
        with self.assertRaisesRegex(ValueError, 'must be clean'):
            self.verify()

    def test_payload_changes_fail_even_with_a_matching_outer_checksum(self):
        for path in ['VERSION', 'upstream.lock.json', 'patches/compact-ui.patch', 'config/config.toml',
                     'bin/herdr-custom', 'LICENSE', 'NOTICE', 'README.md']:
            with self.subTest(path=path):
                self.archive(changes={path: b'changed'})
                with self.assertRaisesRegex(ValueError, 'Packaged recipe differs'):
                    self.verify()

    def test_provenance_cannot_change_platform_commit_or_binary_digest(self):
        for key, value in [('platform', 'linux-x86_64'), ('recipe_commit', '0' * 40), ('binary_sha256', '0' * 64)]:
            with self.subTest(key=key):
                archive = self.archive()
                with tarfile.open(archive) as tar:
                    original = tar.extractfile(archive.name[:-7] + '/provenance.json').read()
                provenance = json.loads(original)
                provenance[key] = value
                self.archive(changes={'provenance.json': json.dumps(provenance).encode()})
                with self.assertRaisesRegex(ValueError, 'provenance differs'):
                    self.verify()
        self.archive(changes={'libexec/herdr': b'changed executable'})
        with self.assertRaisesRegex(ValueError, 'provenance differs'):
            self.verify()

    def test_missing_payload_members_are_rejected(self):
        for path in ['provenance.json', 'patches/compact-ui.patch']:
            with self.subTest(path=path):
                self.archive(omit=(path,))
                with self.assertRaisesRegex(ValueError, 'payload inventory mismatch'):
                    self.verify()

    def test_outer_checksum_must_include_actual_digest_and_filename(self):
        archive = self.archive()
        sidecar = archive.with_name(archive.name + '.sha256')
        sidecar.write_text('0' * 64 + '  ' + archive.name + '\n')
        with self.assertRaisesRegex(ValueError, 'checksum or checksum filename'):
            self.verify()
        sidecar.write_text(hashlib.sha256(archive.read_bytes()).hexdigest() + '  wrong.tar.gz\n')
        with self.assertRaisesRegex(ValueError, 'checksum or checksum filename'):
            self.verify()

    def test_archive_links_paths_duplicate_names_and_extra_files_are_rejected(self):
        root = 'herdr-custom-' + self.lock['distribution_version'] + '-macos-aarch64'
        for path in ['/absolute', root + '/../escape', root + '/./README.md', root + '/extra']:
            with self.subTest(path=path):
                self.archive(extra=tarfile.TarInfo(path))
                with self.assertRaises(ValueError):
                    self.verify()
        for kind in [tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.CHRTYPE]:
            with self.subTest(kind=kind):
                member = tarfile.TarInfo(root + '/extra')
                member.type = kind
                member.linkname = 'README.md'
                self.archive(extra=member)
                with self.assertRaisesRegex(ValueError, 'Unexpected archive member'):
                    self.verify()
        self.archive(duplicate='README.md')
        with self.assertRaisesRegex(ValueError, 'Duplicate archive member'):
            self.verify()

    def test_executables_require_native_header_and_execute_bits(self):
        self.archive(mode=0o644)
        with self.assertRaisesRegex(ValueError, 'not executable'):
            self.verify()
        binary = b'not a native executable'
        provenance = dict(self.lock, platform='macos-aarch64', recipe_commit=self.commit,
                          binary_sha256=hashlib.sha256(binary).hexdigest())
        self.archive(changes={'libexec/herdr': binary, 'provenance.json': json.dumps(provenance).encode()})
        with self.assertRaisesRegex(ValueError, 'format or architecture'):
            self.verify()


if __name__ == '__main__':
    unittest.main()
