import importlib.util
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('recipe', ROOT / 'scripts/build.py')
recipe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recipe)


class RecipeTests(unittest.TestCase):
    def test_version_mismatch_fails_before_patch_checks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'VERSION').write_text('different\n')
            (root / 'upstream.lock.json').write_text(json.dumps({'distribution_version': 'expected'}))
            with mock.patch.object(recipe, 'ROOT', root):
                with self.assertRaisesRegex(ValueError, 'VERSION must match'):
                    recipe.load_lock()

    def test_lock_checks_version_and_patch_integrity(self):
        original = recipe.ROOT
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'VERSION').write_text('1\n')
            (root / 'a.patch').write_text('changed bytes')
            (root / 'upstream.lock.json').write_text(json.dumps({
                'distribution_version': '1',
                'patches': [{'path': 'a.patch', 'sha256': '0' * 64}],
            }))
            try:
                recipe.ROOT = root
                with self.assertRaisesRegex(ValueError, 'digest mismatch'):
                    recipe.load_lock()
            finally:
                recipe.ROOT = original
        self.assertEqual(recipe.load_lock()['version'], '0.9.5')

    def test_launcher_handles_symlink_spaces_arguments_and_config_override(self):
        with tempfile.TemporaryDirectory(prefix='custom test ') as tmp:
            root = Path(tmp) / 'release'
            (root / 'bin').mkdir(parents=True)
            (root / 'libexec').mkdir()
            (root / 'config').mkdir()
            (root / 'VERSION').write_text('test.1\n')
            launcher = root / 'bin/herdr-custom'
            launcher.write_bytes((ROOT / 'scripts/herdr-custom').read_bytes())
            launcher.chmod(0o755)
            runtime = root / 'libexec/herdr'
            runtime.write_text('#!/bin/sh\nif [ "$1" = --version ]; then echo "herdr 0.9.5"; else printf "%s\\n" "$HERDR_CONFIG_PATH" "$@"; fi\n')
            runtime.chmod(0o755)
            link = Path(tmp) / 'custom'
            link.symlink_to(launcher)
            env = dict(os.environ)
            env.pop('HERDR_CONFIG_PATH', None)
            output = subprocess.check_output([str(link), '--session', 'space name'], env=env, text=True)
            self.assertEqual(output.splitlines(), [str(root / 'config/config.toml'), '--session', 'space name'])
            env['HERDR_CONFIG_PATH'] = '/explicit/config.toml'
            output = subprocess.check_output([str(link), '--session', 'test'], env=env, text=True)
            self.assertEqual(output.splitlines()[0], '/explicit/config.toml')
            version = subprocess.check_output([str(link), '--version'], env=env, text=True)
            self.assertEqual(version.strip(), 'herdr-custom test.1 (upstream herdr 0.9.5)')

    def test_runtime_environment_does_not_inherit_operator_session_or_home(self):
        with tempfile.TemporaryDirectory() as tmp:
            inherited = dict(os.environ, HERDR_SESSION='operator', HERDR_SOCKET_PATH='/live.sock',
                             HERDR_CLIENT_SOCKET_PATH='/live-client.sock', HERDR_BIN_PATH='/official/herdr',
                             HERDR_CONFIG_PATH='/live.toml', XDG_DATA_HOME='/live-data',
                             ENV='/live-shell', BASH_ENV='/live-bash', ZDOTDIR='/live-zsh')
            with mock.patch.dict(os.environ, inherited, clear=True):
                env = recipe.isolated_env(tmp)
            self.assertNotIn('HERDR_SESSION', env)
            self.assertNotIn('HERDR_CLIENT_SOCKET_PATH', env)
            self.assertNotIn('HERDR_BIN_PATH', env)
            self.assertTrue({'ENV', 'BASH_ENV', 'ZDOTDIR'}.isdisjoint(env))
            root = Path(tmp).resolve()
            for key in ['HOME', 'XDG_CONFIG_HOME', 'XDG_CACHE_HOME', 'XDG_DATA_HOME',
                        'XDG_STATE_HOME', 'XDG_RUNTIME_DIR', 'TMPDIR']:
                self.assertTrue(Path(env[key]).is_relative_to(root))
                self.assertTrue(Path(env[key]).is_dir())
            self.assertEqual(env['HERDR_SOCKET_PATH'], str(root / 'runtime/api.sock'))
            self.assertEqual(env['HERDR_CONFIG_PATH'], str(root / 'config.toml'))

    def test_runtime_guard_rejects_success_and_unrelated_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / 'runtime-validation-fixture'
            for body in ['exit 0', 'echo unrelated >&2; exit 1']:
                binary.write_text('#!/bin/sh\nif [ "$1" = --version ]; then echo "herdr 0.9.5"; else ' + body + '; fi\n')
                binary.chmod(0o755)
                with self.assertRaisesRegex(ValueError, 'Custom update guard failed'):
                    recipe.verify_runtime(binary, {'version': '0.9.5'})
            binary.write_text('#!/bin/sh\nif [ "$1" = --version ]; then echo "herdr 0.9.3"; else exit 1; fi\n')
            with self.assertRaisesRegex(ValueError, 'upstream version differs'):
                recipe.verify_runtime(binary, {'version': '0.9.5'})

    def test_clean_recipe_rejects_changed_commit_and_dirty_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            git(root, 'init', '-q')
            (root / 'input').write_text('original')
            git(root, 'add', '.')
            git(root, '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '-qm', 'fixture')
            with mock.patch.object(recipe, 'ROOT', root):
                commit = recipe.clean_recipe()
                with self.assertRaisesRegex(ValueError, 'commit changed'):
                    recipe.clean_recipe('0' * 40)
                (root / 'input').write_text('changed')
                with self.assertRaisesRegex(ValueError, 'must be clean'):
                    recipe.clean_recipe(commit)
                git(root, 'checkout', '--', 'input')
                (root / 'untracked-input').write_text('new')
                with self.assertRaisesRegex(ValueError, 'must be clean'):
                    recipe.clean_recipe(commit)


def git(root, *args):
    return subprocess.check_output(['git', *args], cwd=root, stderr=subprocess.STDOUT).decode().strip()


class PreparedSourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'recipe'
        self.root.mkdir()
        upstream = Path(self.tmp.name) / 'upstream'
        upstream.mkdir()
        git(upstream, 'init', '-q')
        (upstream / 'input').write_text('original\n')
        git(upstream, 'add', '.')
        git(upstream, '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '-qm', 'fixture')
        commit = git(upstream, 'rev-parse', 'HEAD')
        (upstream / 'input').write_text('patched\n')
        patch = git(upstream, 'diff') + '\n'
        git(upstream, 'checkout', '--', 'input')
        (self.root / 'change.patch').write_text(patch)
        self.lock = {'commit': commit, 'repository': 'https://example.invalid/upstream.git',
                     'patches': [{'path': 'change.patch', 'sha256': hashlib.sha256(patch.encode()).hexdigest()}]}
        (self.root / 'upstream.lock.json').write_text(json.dumps(self.lock))
        self.patch_root = mock.patch.object(recipe, 'ROOT', self.root)
        self.patch_root.start()
        self.addCleanup(self.patch_root.stop)
        self.source = recipe.prepare(self.lock, upstream)

    def test_unchanged_cache_can_be_reused(self):
        self.assertEqual(recipe.prepare(self.lock), self.source)
        self.assertEqual((self.source / 'input').read_text(), 'patched\n')

    def test_rewritten_stamp_cannot_hide_staged_tampering(self):
        (self.source / 'input').write_text('tampered\n')
        git(self.source, 'add', 'input')
        staged = subprocess.check_output(['git', 'diff', '--cached', '--binary'], cwd=self.source)
        (self.source / '.git/custom-patch-digest').write_text(hashlib.sha256(staged).hexdigest() + '\n')
        with self.assertRaisesRegex(ValueError, 'differs from the locked patches'):
            recipe.prepare(self.lock)

    def test_untracked_and_unstaged_inputs_are_rejected(self):
        (self.source / 'new-input').write_text('untracked')
        with self.assertRaisesRegex(ValueError, 'untracked inputs'):
            recipe.prepare(self.lock)
        (self.source / 'new-input').unlink()
        (self.source / 'input').write_text('unstaged\n')
        with self.assertRaisesRegex(ValueError, 'unstaged changes'):
            recipe.prepare(self.lock)

    def test_changed_upstream_head_is_rejected(self):
        git(self.source, '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '-qm', 'changed base')
        with self.assertRaisesRegex(ValueError, 'Upstream commit mismatch'):
            recipe.prepare(self.lock)


if __name__ == '__main__':
    unittest.main()
