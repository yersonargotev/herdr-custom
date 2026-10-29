#!/usr/bin/env python3
"""Inspect release archives against an independently selected recipe commit."""
import argparse
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import struct
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[1]
PLATFORMS = ('macos-aarch64', 'linux-x86_64')


@dataclass(frozen=True)
class ReleaseIdentity:
    recipe_commit: str
    lock: dict
    packaged_inputs: dict


@dataclass(frozen=True)
class ArchiveReport:
    archive: str
    platform: str
    recipe_commit: str
    archive_sha256: str
    binary_sha256: str


def git(root, *args):
    return subprocess.check_output(['git', *args], cwd=root)


def read_expected(root, commit):
    if not re.fullmatch(r'[0-9a-f]{40}', commit):
        raise ValueError('Recipe commit must be a full Git commit')
    if git(root, 'rev-parse', 'HEAD').decode().strip() != commit:
        raise ValueError('Recipe HEAD differs from the selected commit')
    if git(root, 'status', '--porcelain', '--untracked-files=normal'):
        raise ValueError('Recipe checkout must be clean')
    read = lambda path: git(root, 'show', commit + ':' + path)
    lock = json.loads(read('upstream.lock.json'))
    if read('VERSION').decode().strip() != lock['distribution_version']:
        raise ValueError('VERSION differs from the committed lock')
    files = {path: read(path) for path in ['VERSION', 'LICENSE', 'NOTICE', 'README.md', 'upstream.lock.json']}
    files.update({'bin/herdr-custom': read('scripts/herdr-custom'),
                  'config/config.toml': read('config/config.toml')})
    patch_paths = []
    for patch in lock['patches']:
        path = PurePosixPath(patch['path'])
        if path.parts != ('patches', path.name) or path.suffix != '.patch':
            raise ValueError('Invalid committed patch path')
        data = read(str(path))
        if hashlib.sha256(data).hexdigest() != patch['sha256']:
            raise ValueError('Committed patch digest mismatch')
        files[str(path)] = data
        patch_paths.append(str(path))
    tracked = git(root, 'ls-tree', '-r', '--name-only', commit, '--', 'patches').decode().splitlines()
    if sorted(patch_paths) != sorted(tracked):
        raise ValueError('Committed patches differ from the lock inventory')
    return ReleaseIdentity(commit, lock, files)


def verify_executable(data, platform):
    if platform == 'macos-aarch64':
        valid = (len(data) >= 16 and data[:4] == b'\xcf\xfa\xed\xfe'
                 and struct.unpack_from('<I', data, 4)[0] == 0x0100000c
                 and struct.unpack_from('<I', data, 12)[0] == 2)
    else:
        valid = (len(data) >= 20 and data[:7] == b'\x7fELF\x02\x01\x01'
                 and struct.unpack_from('<H', data, 18)[0] == 62
                 and struct.unpack_from('<H', data, 16)[0] in (2, 3))
    if not valid:
        raise ValueError('Executable format or architecture differs from the platform')


def inspect_archive(archive, expected, platform):
    name = 'herdr-custom-' + expected.lock['distribution_version'] + '-' + platform
    if archive.name != name + '.tar.gz':
        raise ValueError('Archive filename differs from the release identity')
    archive_sha256 = hashlib.sha256(archive.read_bytes()).hexdigest()
    checksum = archive.with_name(archive.name + '.sha256').read_text()
    if checksum != archive_sha256 + '  ' + archive.name + '\n':
        raise ValueError('Archive checksum or checksum filename mismatch')
    expected_files = set(expected.packaged_inputs) | {'libexec/herdr', 'provenance.json'}
    expected_dirs = {name}
    for path in expected_files:
        expected_dirs.update(str(p) for p in (PurePosixPath(name) / path).parents if str(p) != '.')
    files = {}
    seen = set()
    with tarfile.open(archive, 'r:gz') as tar:
        for member in tar:
            path = PurePosixPath(member.name)
            if (path.is_absolute() or '..' in path.parts or not path.parts
                    or path.parts[0] != name or str(path) != member.name.rstrip('/')):
                raise ValueError('Unsafe archive member path')
            if str(path) in seen:
                raise ValueError('Duplicate archive member')
            seen.add(str(path))
            if member.mode & 0o7000:
                raise ValueError('Unexpected archive member mode')
            if member.isdir() and str(path) in expected_dirs:
                continue
            relative = str(path.relative_to(name))
            if not member.isfile() or relative not in expected_files:
                raise ValueError('Unexpected archive member or file type')
            if relative in ('bin/herdr-custom', 'libexec/herdr') and member.mode & 0o111 != 0o111:
                raise ValueError('Packaged executable is not executable')
            files[relative] = tar.extractfile(member).read()
    if set(files) != expected_files:
        raise ValueError('Archive payload inventory mismatch')
    for path, data in expected.packaged_inputs.items():
        if files[path] != data:
            raise ValueError('Packaged recipe differs from the selected commit: ' + path)
    binary_sha256 = hashlib.sha256(files['libexec/herdr']).hexdigest()
    provenance = json.loads(files['provenance.json'])
    if provenance != dict(expected.lock, platform=platform, recipe_commit=expected.recipe_commit,
                          binary_sha256=binary_sha256):
        raise ValueError('Packaged provenance differs from the release identity or executable')
    verify_executable(files['libexec/herdr'], platform)
    return ArchiveReport(str(archive), platform, expected.recipe_commit, archive_sha256, binary_sha256)


def verify_release(directory, recipe_root, recipe_commit, platforms):
    if not platforms or len(set(platforms)) != len(platforms) or set(platforms) - set(PLATFORMS):
        raise ValueError('Select supported platforms without duplicates')
    expected = read_expected(recipe_root, recipe_commit)
    archives = [Path(directory) / ('herdr-custom-' + expected.lock['distribution_version']
                                  + '-' + platform + '.tar.gz') for platform in platforms]
    inventory = {path.name for path in archives} | {path.name + '.sha256' for path in archives}
    if {path.name for path in Path(directory).iterdir()} != inventory:
        raise ValueError('Release directory must contain exactly the selected archives and checksums')
    return tuple(inspect_archive(archive, expected, platform) for archive, platform in zip(archives, platforms))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--recipe-commit', required=True)
    parser.add_argument('--platform', choices=('all', *PLATFORMS), required=True)
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    platforms = PLATFORMS if args.platform == 'all' else (args.platform,)
    try:
        reports = verify_release(args.directory, ROOT, args.recipe_commit, platforms)
    except (ValueError, KeyError, TypeError, OSError, subprocess.CalledProcessError, tarfile.TarError) as error:
        parser.exit(1, 'Release verification failed: ' + str(error) + '\n')
    print(json.dumps([vars(report) for report in reports], indent=2))


if __name__ == '__main__':
    main()
