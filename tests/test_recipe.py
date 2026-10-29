import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('recipe', ROOT / 'scripts/build.py')
recipe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recipe)


class RecipeTests(unittest.TestCase):
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


if __name__ == '__main__':
    unittest.main()
