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


def prepare(lock, cache=None):
    digest = hashlib.sha256((ROOT / 'upstream.lock.json').read_bytes()).hexdigest()[:16]
    source = ROOT / '.build' / digest
    stamp = source / '.git' / 'custom-patch-digest'
    if source.exists():
        if not stamp.exists():
            raise ValueError(f'Incomplete build directory; inspect and remove {source}')
        run('git', 'diff', '--exit-code', cwd=source)
        staged = run('git', 'diff', '--cached', '--binary', cwd=source, capture=True)
        if hashlib.sha256(staged.encode()).hexdigest() != stamp.read_text().strip():
            raise ValueError('Prepared source was modified; refusing to build')
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
    staged = run('git', 'diff', '--cached', '--binary', cwd=source, capture=True)
    stamp.write_text(hashlib.sha256(staged.encode()).hexdigest() + '\n')
    return source


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
    if target_args and 'statically linked' not in run('file', str(binary), capture=True):
        raise ValueError('Linux release must be statically linked')
    if run(str(binary), '--version', capture=True).strip() != 'herdr ' + lock['version']:
        raise ValueError('Built binary upstream version differs from the lock')
    with tempfile.TemporaryDirectory() as home:
        isolated = dict(env, HOME=home, XDG_CONFIG_HOME=home + '/config',
                        XDG_STATE_HOME=home + '/state', HERDR_CONFIG_PATH=home + '/config.toml')
        result = subprocess.run([str(binary), 'update'], env=isolated, capture_output=True, text=True)
        if result.returncode == 0 or 'self-update is disabled for herdr-custom' not in result.stdout + result.stderr:
            raise ValueError('Custom update guard failed')
    return binary


def package(binary, source, lock):
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
                          recipe_commit=run('git', 'rev-parse', 'HEAD', capture=True).strip(),
                          binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest())
        (stage / 'provenance.json').write_text(json.dumps(provenance, indent=2) + '\n')
        with tempfile.TemporaryDirectory() as home:
            isolated = dict(os.environ, HOME=home, XDG_CONFIG_HOME=home + '/config',
                            XDG_STATE_HOME=home + '/state')
            isolated.pop('HERDR_CONFIG_PATH', None)
            launcher = str(stage / 'bin/herdr-custom')
            run(launcher, '--version', env=isolated)
            run(launcher, 'config', 'check', env=isolated)
        archive = dist / (name + '.tar.gz')
        with tarfile.open(archive, 'w:gz') as tar:
            tar.add(stage, arcname=name)
        checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
        (dist / (archive.name + '.sha256')).write_text(checksum + '  ' + archive.name + '\n')
        print(archive)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-cache', help='Optional existing Git checkout containing the pinned commit')
    parser.add_argument('--prepare-only', action='store_true')
    args = parser.parse_args()
    lock = load_lock()
    source = prepare(lock, args.source_cache)
    if args.prepare_only:
        print(source)
        return
    binary = build(source, lock, test=True)
    package(binary, source, lock)


if __name__ == '__main__':
    main()
