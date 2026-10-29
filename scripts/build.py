#!/usr/bin/env python3
"""Build the pinned upstream source with the reviewed patch set."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def run(*args, cwd=ROOT, capture=False, env=None):
    return subprocess.run(args, cwd=cwd, env=env, check=True, text=True,
                          stdout=subprocess.PIPE if capture else None).stdout


def load_lock():
    lock = json.loads((ROOT / 'upstream.lock.json').read_text())
    if (ROOT / 'VERSION').read_text().strip() != lock['distribution_version']:
        raise ValueError('VERSION must match the lock')
    for patch in lock['patches']:
        data = (ROOT / patch['path']).read_bytes()
        if hashlib.sha256(data).hexdigest() != patch['sha256']:
            raise ValueError(f"Patch digest mismatch: {patch['path']}")
    return lock


def clean_recipe(expected=None):
    commit = run('git', 'rev-parse', 'HEAD', cwd=ROOT, capture=True).strip()
    if expected is not None and commit != expected:
        raise ValueError('Recipe commit changed during the build')
    if run('git', 'status', '--porcelain', '--untracked-files=normal', cwd=ROOT, capture=True):
        raise ValueError('Recipe must be clean before building or packaging')
    return commit


def isolated_env(root):
    root = Path(root).resolve()
    env = {key: os.environ[key] for key in ['PATH', 'LANG', 'LC_ALL', 'LC_CTYPE', 'TERM', 'TZ']
           if key in os.environ}
    for key, directory in [('HOME', 'home'), ('XDG_CONFIG_HOME', 'config'),
                           ('XDG_CACHE_HOME', 'cache'), ('XDG_DATA_HOME', 'data'),
                           ('XDG_STATE_HOME', 'state'), ('XDG_RUNTIME_DIR', 'runtime'),
                           ('TMPDIR', 'tmp')]:
        path = root / directory
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        env[key] = str(path)
    env.update(SHELL='/bin/sh', HERDR_CONFIG_PATH=str(root / 'config.toml'),
               HERDR_SOCKET_PATH=str(root / 'runtime/api.sock'))
    return env


def verify_prepared(source, lock):
    if run('git', 'rev-parse', 'HEAD', cwd=source, capture=True).strip() != lock['commit']:
        raise ValueError('Upstream commit mismatch')
    if run('git', 'diff', '--name-only', cwd=source, capture=True):
        raise ValueError('Prepared source has unstaged changes')
    if run('git', 'ls-files', '--others', '--exclude-standard', cwd=source, capture=True):
        raise ValueError('Prepared source has untracked inputs')
    with tempfile.TemporaryDirectory(prefix='hc-index-') as tmp:
        env = dict(os.environ, GIT_INDEX_FILE=str(Path(tmp) / 'index'))
        run('git', 'read-tree', lock['commit'], cwd=source, env=env)
        for patch in lock['patches']:
            run('git', 'apply', '--cached', str(ROOT / patch['path']), cwd=source, env=env)
        expected = run('git', 'write-tree', cwd=source, capture=True, env=env).strip()
    actual = run('git', 'write-tree', cwd=source, capture=True).strip()
    if actual != expected:
        raise ValueError('Prepared source differs from the locked patches')


def prepare(lock, cache=None):
    digest = hashlib.sha256((ROOT / 'upstream.lock.json').read_bytes()).hexdigest()[:16]
    source = ROOT / '.build' / digest
    if source.exists():
        verify_prepared(source, lock)
        return source
    source.parent.mkdir(parents=True, exist_ok=True)
    if cache:
        run('git', 'clone', '--no-hardlinks', '--no-checkout', str(Path(cache).resolve()), str(source))
        run('git', 'remote', 'set-url', 'origin', lock['repository'], cwd=source)
    else:
        source.mkdir()
        run('git', 'init', str(source))
        run('git', 'remote', 'add', 'origin', lock['repository'], cwd=source)
        run('git', 'fetch', '--depth=1', 'origin', lock['commit'], cwd=source)
    run('git', 'checkout', '--detach', lock['commit'], cwd=source)
    if run('git', 'rev-parse', 'HEAD', cwd=source, capture=True).strip() != lock['commit']:
        raise ValueError('Upstream commit mismatch')
    for patch in lock['patches']:
        run('git', 'apply', '--check', str(ROOT / patch['path']), cwd=source)
        run('git', 'apply', '--index', str(ROOT / patch['path']), cwd=source)
    verify_prepared(source, lock)
    return source


def verify_runtime(binary, lock):
    with tempfile.TemporaryDirectory(prefix='hc-runtime-', dir='/tmp') as tmp:
        env = isolated_env(tmp)
        if run(str(binary), '--version', capture=True, env=env).strip() != 'herdr ' + lock['version']:
            raise ValueError('Built binary upstream version differs from the lock')
        result = subprocess.run([str(binary), 'update'], env=env, capture_output=True, text=True, timeout=30)
        if result.returncode == 0 or 'self-update is disabled for herdr-custom' not in result.stdout + result.stderr:
            raise ValueError('Custom update guard failed')


def build(source, lock, test):
    zig = os.environ.get('ZIG', 'zig')
    if run(zig, 'version', capture=True).strip() != lock['zig']:
        raise ValueError('Zig version differs from the lock')
    env = dict(os.environ, HERDR_CUSTOM_BUILD=lock['distribution_version'])
    cargo = ['cargo', '+' + lock['rust']]
    target_args = ['--target', 'x86_64-unknown-linux-musl'] if platform.system() == 'Linux' else []
    if test:
        run(*cargo, 'test', '--release', '--locked', '--bin', 'herdr',
            *target_args, 'client::shell::', '--', '--test-threads=4', cwd=source, env=env)
    run(*cargo, 'build', '--release', '--locked', *target_args, cwd=source, env=env)
    target = Path(env.get('CARGO_TARGET_DIR', source / 'target')).resolve()
    if target_args:
        target = target / target_args[1]
    binary = target / 'release' / 'herdr'
    if target_args:
        elf = run('readelf', '--program-headers', '--dynamic', str(binary), capture=True)
        if 'INTERP' in elf or '(NEEDED)' in elf:
            raise ValueError('Linux release must not require a loader or shared libraries')
    verify_runtime(binary, lock)
    return binary


def package(binary, source, lock, recipe_commit=None):
    recipe_commit = clean_recipe(recipe_commit)
    verify_prepared(source, lock)
    supported = {('Darwin', 'arm64'): 'macos-aarch64',
                 ('Linux', 'x86_64'): 'linux-x86_64'}
    platform_name = supported.get((platform.system(), platform.machine()))
    if platform_name is None:
        raise ValueError('Supported platforms: macOS Apple Silicon and Linux x86_64')
    name = 'herdr-custom-' + lock['distribution_version'] + '-' + platform_name
    dist = ROOT / 'dist'
    dist.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        stage = Path(tmp) / name
        (stage / 'bin').mkdir(parents=True)
        (stage / 'libexec').mkdir()
        (stage / 'config').mkdir()
        shutil.copy2(binary, stage / 'libexec/herdr')
        shutil.copy2(ROOT / 'scripts/herdr-custom', stage / 'bin/herdr-custom')
        shutil.copy2(ROOT / 'config/config.toml', stage / 'config/config.toml')
        for file in ['VERSION', 'LICENSE', 'NOTICE', 'README.md', 'upstream.lock.json']:
            shutil.copy2(ROOT / file, stage / file)
        if (source / 'NOTICE').exists():
            shutil.copy2(source / 'NOTICE', stage / 'UPSTREAM-NOTICE')
        shutil.copytree(ROOT / 'patches', stage / 'patches')
        provenance = dict(lock, platform=platform_name,
                          recipe_commit=recipe_commit,
                          binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest())
        (stage / 'provenance.json').write_text(json.dumps(provenance, indent=2) + '\n')
        with tempfile.TemporaryDirectory(prefix='hc-package-', dir='/tmp') as home:
            isolated = isolated_env(home)
            isolated.pop('HERDR_CONFIG_PATH', None)
            launcher = str(stage / 'bin/herdr-custom')
            run(launcher, '--version', env=isolated)
            run(launcher, 'config', 'check', env=isolated)
        archive = dist / (name + '.tar.gz')
        with tarfile.open(archive, 'w:gz') as tar:
            tar.add(stage, arcname=name)
        checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
        (dist / (archive.name + '.sha256')).write_text(checksum + '  ' + archive.name + '\n')
        clean_recipe(recipe_commit)
        run('python3', str(ROOT / 'scripts/verify_release.py'), '--recipe-commit', recipe_commit,
            '--platform', platform_name, str(dist))
        print(archive)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-cache', help='Optional existing Git checkout containing the pinned commit')
    parser.add_argument('--prepare-only', action='store_true')
    args = parser.parse_args()
    recipe_commit = None if args.prepare_only else clean_recipe()
    lock = load_lock()
    source = prepare(lock, args.source_cache)
    if args.prepare_only:
        print(source)
        return
    binary = build(source, lock, test=True)
    package(binary, source, lock, recipe_commit)


if __name__ == '__main__':
    main()
