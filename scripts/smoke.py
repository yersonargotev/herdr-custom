#!/usr/bin/env python3
"""Exercise the real packaged runtime and pinned Git plugin in disposable roots."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time

from build import isolated_env

PLUGIN_ID = 'yersonargotev.tab-git'
PLUGIN_REF = '5ef7d5a69ccfc7552d3cc81a1a7cfb059cb256df'


class SmokeRun:
    def __init__(self, release, output):
        self.release = release.resolve()
        self.output = output.resolve()
        self.output.mkdir(parents=True, exist_ok=True)
        if any(self.output.iterdir()):
            raise ValueError('Smoke output directory must be empty')
        self.launcher = self.release / 'bin/herdr-custom'
        self.binary = self.release / 'libexec/herdr'
        self.lock = json.loads((self.release / 'upstream.lock.json').read_text())
        binary_digest = hashlib.sha256(self.binary.read_bytes()).hexdigest()
        provenance = self.release / 'provenance.json'
        packaged_provenance = json.loads(provenance.read_text()) if provenance.exists() else None
        self.root = Path(tempfile.mkdtemp(prefix='hc4-', dir='/tmp')).resolve()
        self.env = isolated_env(self.root)
        self.env.pop('HERDR_CONFIG_PATH')
        self.env.update(PATH='/usr/bin:/bin', TERM='xterm-256color',
                        GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL='/dev/null')
        self.server = None
        self.retained = False
        self.report = {
            'started_utc': datetime.now(timezone.utc).isoformat(),
            'platform': platform.system() + '-' + platform.machine(),
            'release': str(self.release), 'runtime_root': str(self.root),
            'upstream_commit': self.lock['commit'],
            'distribution_version': self.lock['distribution_version'],
            'binary_sha256': binary_digest,
            'plugin_ref': PLUGIN_REF, 'checks': [], 'verdict': 'NOT VERIFIED',
            'not_verified': ['live terminal appearance and interactions',
                             'matching official server attach and detach',
                             'downgrade of persisted state'],
        }
        self.report['packaged_provenance'] = packaged_provenance

    def save(self, name, value):
        (self.output / name).write_text(json.dumps(value, indent=2) + '\n')

    def check(self, name, evidence):
        self.report['checks'].append({'name': name, 'verdict': 'VERIFIED',
                                      'evidence': evidence})
        print(name + ': VERIFIED', flush=True)

    def command(self, args, env=None, cwd=None, check=True, record=True, timeout=30):
        result = subprocess.run([str(arg) for arg in args], env=env or self.env,
                                cwd=cwd or self.root, text=True, capture_output=True,
                                timeout=timeout)
        if record:
            entry = {'argv': [str(arg) for arg in args], 'exit_code': result.returncode,
                     'stdout': result.stdout, 'stderr': result.stderr}
            with (self.output / 'commands.jsonl').open('a') as log:
                log.write(json.dumps(entry) + '\n')
        if check and result.returncode:
            raise RuntimeError('Command failed: ' + shlex.join(entry['argv'] if record else args)
                               + '\n' + result.stderr)
        return result

    def cli(self, *args, **kwargs):
        return self.command([self.launcher, *args], **kwargs)

    def snapshot(self):
        result = self.cli('api', 'snapshot', check=False, record=False, timeout=5)
        if result.returncode:
            return None
        return json.loads(result.stdout)['result']['snapshot']

    def wait_snapshot(self, name, predicate, timeout=45):
        deadline = time.monotonic() + timeout
        latest = None
        while time.monotonic() < deadline:
            latest = self.snapshot()
            if latest is not None and predicate(latest):
                self.save(name + '.json', latest)
                return latest
            if self.server is not None and self.server.poll() is not None:
                raise RuntimeError('Disposable server exited before ' + name)
            time.sleep(0.2)
        self.save(name + '-timeout.json', latest)
        raise RuntimeError('Timed out waiting for ' + name)

    def start(self):
        with (self.output / 'server.log').open('a') as log:
            self.server = subprocess.Popen([str(self.launcher), 'server'], env=self.env,
                                           cwd=self.root, stdout=log,
                                           stderr=subprocess.STDOUT, start_new_session=True)
        self.wait_snapshot('server-ready', lambda snapshot: snapshot['version'] == self.lock['version'])

    def wait_hook(self, field, value, name):
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            logs = json.loads(self.cli('plugin', 'log', '--plugin', PLUGIN_ID,
                                       '--limit', '100', record=False).stdout)
            matches = [item for item in logs['result']['logs'] if item.get(field) == value]
            if matches and matches[0]['status'] != 'running':
                self.save(name, logs)
                if matches[0]['status'] != 'succeeded':
                    raise RuntimeError('Plugin hook failed: ' + value)
                return
            time.sleep(0.2)
        raise RuntimeError('Timed out waiting for plugin hook: ' + value)

    def stop(self):
        if self.server is not None:
            if self.server.poll() is None:
                try:
                    self.cli('server', 'stop', check=False, timeout=20)
                except (OSError, subprocess.TimeoutExpired) as error:
                    self.report.setdefault('cleanup_notes', []).append(str(error))
                finally:
                    try:
                        self.server.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        self.server.terminate()
                        try:
                            self.server.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            self.server.kill()
                            self.server.wait(timeout=5)
            self.server = None

    def cleanup(self):
        self.stop()
        watchers = list(self.root.glob('state/**/watch.lock/pid'))
        for pid_file in watchers:
            try:
                pid = int(pid_file.read_text())
            except (OSError, ValueError):
                continue
            for requested_signal, timeout in [(None, 12), (signal.SIGTERM, 3), (signal.SIGKILL, 3)]:
                if requested_signal is not None and self.owned_watcher(pid):
                    try:
                        os.kill(pid, requested_signal)
                    except ProcessLookupError:
                        break
                deadline = time.monotonic() + timeout
                while self.owned_watcher(pid) and time.monotonic() < deadline:
                    time.sleep(0.2)
                if not self.owned_watcher(pid):
                    break
            else:
                raise RuntimeError('Owned watcher did not stop: ' + str(pid))
        shutil.rmtree(self.root)
        self.report['cleanup'] = 'Owned server and watchers stopped; runtime root removed'

    def owned_watcher(self, pid):
        process = subprocess.run(['/bin/ps', '-p', str(pid), '-o', 'command='],
                                 text=True, capture_output=True, timeout=5)
        return process.returncode == 0 and str(self.root) in process.stdout and '--watch' in process.stdout

    def prepare_observer(self):
        node = shutil.which('node')
        if node is None:
            raise ValueError('Node.js is required for the real plugin')
        node = str(Path(node).resolve())
        if shutil.which('herdr', path=self.env['PATH']) is not None:
            raise ValueError('Smoke PATH must not contain an official herdr executable')
        observer = self.root / 'observe-node.py'
        observer.write_text(
            'import json, os, sys\n'
            'entry = {key: os.environ.get(key) for key in '
            "['HERDR_BIN_PATH', 'HERDR_SOCKET_PATH', 'HERDR_PLUGIN_EVENT']}\n"
            'entry["argv"] = sys.argv[1:]\n'
            'fd = os.open(' + repr(str(self.output / 'routing.jsonl'))
            + ', os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)\n'
            'os.write(fd, (json.dumps(entry) + "\\n").encode())\n'
            'os.close(fd)\n'
            'os.execv(' + repr(node) + ', [' + repr(node) + ', *sys.argv[1:]])\n')
        entry = self.root / 'node-observer'
        entry.write_text('#!/bin/sh\nexec ' + shlex.quote(sys.executable) + ' '
                         + shlex.quote(str(observer)) + ' "$@"\n')
        entry.chmod(0o755)
        self.env['HERDR_TAB_GIT_NODE'] = str(entry)
        self.report['node_observer'] = {'kind': 'transparent logger then exec of real Node.js',
                                        'node': node}
        self.save('environment.json', self.env)

    def make_repo(self, name):
        repo = self.root / name
        repo.mkdir()
        self.command(['git', 'init', '--initial-branch=smoke-base', repo])
        (repo / 'tracked.txt').write_text('baseline\n')
        self.command(['git', '-C', repo, 'add', 'tracked.txt'])
        self.command(['git', '-C', repo, '-c', 'user.name=Herdr Smoke',
                      '-c', 'user.email=smoke@example.invalid', 'commit', '-m', 'fixture'])
        return repo

    def verify(self):
        self.prepare_observer()
        expected = ('herdr-custom ' + self.lock['distribution_version']
                    + ' (upstream herdr ' + self.lock['version'] + ')')
        if self.cli('--version').stdout.strip() != expected:
            raise ValueError('Launcher version differs from packaged lock')
        self.cli('config', 'check')
        link = self.root / 'custom symlink'
        link.symlink_to(self.launcher)
        if self.command([link, '--version']).stdout.strip() != expected:
            raise ValueError('Real launcher symlink version differs')
        override = self.root / 'override.toml'
        override.write_text('onboarding = false\n[ui]\nsidebar_width = "invalid"\n')
        override_env = dict(self.env, HERDR_CONFIG_PATH=str(override))
        if self.cli('config', 'check', env=override_env, check=False).returncode == 0:
            raise ValueError('Launcher ignored an invalid explicit config override')
        override.write_text('onboarding = false\n')
        self.cli('config', 'check', env=override_env)
        update = self.cli('update', check=False)
        if update.returncode == 0 or 'self-update is disabled for herdr-custom' not in update.stdout + update.stderr:
            raise ValueError('Real custom self-update guard failed')
        self.check('real launcher, symlink, config default and override, update guard', 'commands.jsonl')

        repos = [self.make_repo('packy-catalog'), self.make_repo('second-project')]
        self.start()
        fixtures = []
        for index, repo in enumerate(repos):
            result = json.loads(self.cli('workspace', 'create', '--cwd', str(repo),
                                        '--label', repo.name,
                                        '--focus' if index == 0 else '--no-focus').stdout)['result']
            self.cli('tab', 'rename', result['tab']['tab_id'], 'codex' if index == 0 else 'review')
            fixtures.append({'workspace_id': result['workspace']['workspace_id'],
                             'pane_id': result['root_pane']['pane_id'], 'project': repo.name,
                             'tab_name': 'codex' if index == 0 else 'review'})
        self.save('fixtures.json', fixtures)
        self.wait_snapshot('before-install', lambda snapshot: len(snapshot['workspaces']) == 2)
        self.stop()
        self.cli('plugin', 'install', 'yersonargotev/herdr-tab-git', '--ref', PLUGIN_REF,
                 '--yes', timeout=180)
        plugins = json.loads(self.cli('plugin', 'list', '--json').stdout)['result']['plugins']
        plugin = next(item for item in plugins if item['plugin_id'] == PLUGIN_ID)
        plugin_root = Path(plugin['plugin_root'])
        if (plugin['source']['resolved_commit'] != PLUGIN_REF or plugin['version'] != '1.4.0'
                or plugin['min_herdr_version'] != '0.9.5' or not plugin['enabled']):
            raise ValueError('Installed plugin identity differs from exact requested revision')
        if self.command(['git', '-C', plugin_root, 'rev-parse', 'HEAD']).stdout.strip() != PLUGIN_REF:
            raise ValueError('Installed checkout differs from registry revision')
        self.save('installed-plugin.json', plugin)
        shutil.copy2(Path(self.env['XDG_CONFIG_HOME']) / 'herdr/plugins.json', self.output / 'plugins.json')
        shutil.copy2(plugin['manifest_path'], self.output / 'herdr-plugin.toml')
        self.check('exact plugin installed through custom launcher', 'installed-plugin.json')
        self.start()

        expected_spaces = {item['project']: {'gitbranch': 'smoke-base', 'gitclean': 'clean',
                                             'tab_name': item['tab_name']} for item in fixtures}

        def tokens_match(snapshot):
            spaces = {item['label']: item for item in snapshot['workspaces']}
            panes = {Path(item['cwd']).name: item for item in snapshot['panes']}
            return all(spaces.get(item['project'], {}).get('tokens') == expected_spaces[item['project']]
                       and panes.get(item['project'], {}).get('tokens', {}).get('project') == item['project']
                       for item in fixtures)

        startup = self.wait_snapshot('startup', tokens_match)
        self.wait_hook('event', 'startup', 'startup-plugin-log.json')
        self.check('startup publishes both Space Git tokens and per-pane projects', 'startup.json')
        focused = next(item for item in startup['workspaces'] if item['focused'])
        if focused['label'] != 'packy-catalog':
            raise ValueError('Restored polling target is not the first fixture')
        self.cli('plugin', 'action', 'invoke', 'clear', '--plugin', PLUGIN_ID)
        self.wait_snapshot('cleared', lambda snapshot: all(not item.get('tokens')
                           for item in snapshot['workspaces']) and all(not item.get('tokens')
                           for item in snapshot['panes']))
        self.wait_hook('action_id', 'clear', 'clear-plugin-log.json')
        (repos[0] / 'tracked.txt').write_text('modified for explicit refresh\n')
        expected_spaces['packy-catalog'] = {'gitbranch': 'smoke-base', 'gitmodified': '~1',
                                            'gitworkmodified': '!1', 'tab_name': 'codex'}
        self.cli('plugin', 'action', 'invoke', 'refresh', '--plugin', PLUGIN_ID)
        self.wait_hook('action_id', 'refresh', 'refresh-plugin-log.json')
        self.wait_snapshot('refresh', tokens_match)
        self.check('explicit refresh resumes paused publication and reports modification', 'refresh.json')
        (repos[0] / 'untracked.txt').write_text('created for polling\n')
        expected_spaces['packy-catalog']['gituntracked'] = '?1'
        self.wait_snapshot('polling', tokens_match)
        self.check('polling observes untracked file without action or focus command', 'polling.json')
        routing = [json.loads(line) for line in (self.output / 'routing.jsonl').read_text().splitlines()]
        if not routing or not any(item['HERDR_PLUGIN_EVENT'] == 'startup' for item in routing):
            raise ValueError('No actual startup hook executable routing was observed')
        if any(Path(item['HERDR_BIN_PATH']).resolve() != self.binary.resolve()
               or item['HERDR_SOCKET_PATH'] != self.env['HERDR_SOCKET_PATH'] for item in routing):
            raise ValueError('A plugin hook was routed outside the owned custom runtime')
        self.check('runtime supplies its private executable to real plugin hooks', 'routing.jsonl')
        self.cli('pane', 'report-agent', fixtures[0]['pane_id'], '--source', 'custom-smoke',
                 '--agent', 'codex', '--state', 'working')
        self.wait_snapshot('reported-agent', lambda snapshot: bool(snapshot['agents']))
        self.report['agent_fixture'] = 'Real report-agent API, not live Codex process detection'
        self.report['server_pid'] = self.server.pid
        self.report['cleanup_argv'] = [str(self.launcher), 'server', 'stop']
        self.report['cleanup_environment'] = 'environment.json'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--keep-runtime', action='store_true', help='Retain owned server for terminal checks')
    args = parser.parse_args()
    run = SmokeRun(args.release, args.output)
    try:
        run.verify()
        run.retained = args.keep_runtime
        run.report['verdict'] = 'VERIFIED automated plugin checks'
    except BaseException as error:
        run.report['verdict'] = 'NOT VERIFIED'
        run.report['error'] = str(error)
        raise
    finally:
        run.report['runtime_retained'] = run.retained
        try:
            if not run.retained:
                run.cleanup()
        except BaseException as error:
            run.report['verdict'] = 'NOT VERIFIED'
            run.report['cleanup_error'] = str(error)
            raise
        finally:
            run.report['finished_utc'] = datetime.now(timezone.utc).isoformat()
            run.save('report.json', run.report)
            print(run.output / 'report.json', flush=True)


if __name__ == '__main__':
    main()
