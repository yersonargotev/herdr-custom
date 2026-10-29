#!/usr/bin/env python3
import argparse, codecs, fcntl, hashlib, json, os, platform, re, select, shutil, signal, struct, subprocess, tempfile, termios, time
from pathlib import Path
import pyte
from PIL import Image, ImageDraw, ImageFont

OUT: Path
CUSTOM: Path
OFFICIAL: Path
CONFIG: Path
COMMANDS = []


class Runtime:
    def __init__(self, name, binary, theme="dark", width=38, overrides=False):
        self.clients = []
        self.theme = theme
        self.name = name
        self.binary = binary
        self.root = Path(tempfile.mkdtemp(prefix="h4v-", dir="/tmp"))
        self.out = OUT / name
        self.out.mkdir(exist_ok=True)
        for n in ["home", "config", "data", "cache", "state", "run", "tmp"]:
            (self.root / n).mkdir(mode=0o700)
        self.env = {
            "PATH": "/usr/bin:/bin",
            "SHELL": "/bin/sh",
            "TERM": "xterm-256color",
            "LANG": "en_US.UTF-8",
            "HOME": str(self.root / "home"),
            "XDG_CONFIG_HOME": str(self.root / "config"),
            "XDG_DATA_HOME": str(self.root / "data"),
            "XDG_CACHE_HOME": str(self.root / "cache"),
            "XDG_STATE_HOME": str(self.root / "state"),
            "XDG_RUNTIME_DIR": str(self.root / "run"),
            "TMPDIR": str(self.root / "tmp"),
            "HERDR_SOCKET_PATH": str(self.root / "run/api.sock"),
            "HERDR_CONFIG_PATH": str(self.root / "config.toml"),
        }
        content = (
            CONFIG.read_text()
            .replace("manifest_check = true", "manifest_check = false")
            .replace("auto_switch = true", "auto_switch = false")
            .replace("sidebar_width = 38", f"sidebar_width = {width}")
        )
        if theme == "adaptive-light":
            content = content.replace("auto_switch = false", "auto_switch = true")
        if theme == "light":
            content = content.replace('name = "catppuccin"', 'name = "catppuccin-latte"', 1)
        if overrides:
            content = content.replace(
                '{ token = "$tab_name", bold = true, dim = false }',
                '{ token = "$tab_name", bold = true, dim = false, fg = "#ff00ff" }',
            ).replace(
                '{ token = "agent", bold = true }',
                '{ token = "agent", bold = true, fg = "#00ff00" }',
            )
        (self.root / "config.toml").write_text(content)
        (self.out / "config.toml").write_text(content)
        (self.out / "environment.json").write_text(json.dumps(self.env, indent=2))
        self.start()

    def start(self):
        self.log = (self.out / "server.log").open("a")
        self.proc = subprocess.Popen(
            [str(self.binary), "server"],
            cwd=self.root,
            env=self.env,
            stdout=self.log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        for _ in range(80):
            r = self.command("api", "snapshot", check=False)
            if r.returncode == 0:
                break
            if self.proc.poll() is not None:
                raise RuntimeError("server exited")
            time.sleep(0.1)
        else:
            raise RuntimeError("server startup timeout")

    def command(self, *args, check=True, binary=None):
        cmd = [str(binary or self.binary), *map(str, args)]
        r = subprocess.run(
            cmd, cwd=self.root, env=self.env, text=True, capture_output=True, timeout=15
        )
        COMMANDS.append(
            dict(
                case=self.name, argv=cmd, returncode=r.returncode, stdout=r.stdout, stderr=r.stderr
            )
        )
        if check and r.returncode:
            raise RuntimeError(f"{cmd}: {r.stderr}")
        return r

    def api(self, *args):
        result = self.command(*args).stdout
        return json.loads(result)["result"] if result.strip() else {}

    def snapshot(self, label):
        x = self.api("api", "snapshot")["snapshot"]
        (self.out / (label + ".json")).write_text(json.dumps(x, indent=2))
        return x

    def fixture(self):
        self.repo = self.root / "packy-catalog"
        self.repo.mkdir()
        for args in [
            ["init", "-b", "visual-branch"],
            ["config", "user.name", "Release visual"],
            ["config", "user.email", "visual@example.invalid"],
        ]:
            subprocess.run(
                ["git", "-C", str(self.repo), *args], env=self.env, capture_output=True, check=True
            )
        (self.repo / "tracked.txt").write_text("fixture\n")
        for args in [["add", "."], ["commit", "-m", "fixture"]]:
            subprocess.run(
                ["git", "-C", str(self.repo), *args], env=self.env, capture_output=True, check=True
            )
        a = self.api(
            "workspace", "create", "--cwd", self.repo, "--label", "packy-catalog", "--focus"
        )
        self.ws = a["workspace"]["workspace_id"]
        self.pane = a["root_pane"]["pane_id"]
        self.tab = a["tab"]["tab_id"]
        self.api("tab", "rename", self.tab, "codex")
        self.api(
            "tab",
            "create",
            "--workspace",
            self.ws,
            "--cwd",
            self.repo,
            "--label",
            "shell",
            "--no-focus",
        )
        self.api(
            "workspace",
            "report-metadata",
            self.ws,
            "--source",
            "release-visual",
            "--token",
            "tab_name=codex",
            "--token",
            "gitbranch=visual-branch",
            "--token",
            "gitmodified=~2",
            "--token",
            "gituntracked=?1",
        )
        self.api(
            "pane",
            "report-agent",
            self.pane,
            "--source",
            "release-visual",
            "--agent",
            "codex",
            "--state",
            "working",
        )
        b = self.api(
            "workspace", "create", "--cwd", self.repo, "--label", "second-space", "--no-focus"
        )
        self.ws2 = b["workspace"]["workspace_id"]
        self.pane2 = b["root_pane"]["pane_id"]
        self.tab2 = b["tab"]["tab_id"]
        self.api("tab", "rename", self.tab2, "review")
        self.api(
            "workspace",
            "report-metadata",
            self.ws2,
            "--source",
            "release-visual",
            "--token",
            "tab_name=review",
            "--token",
            "gitbranch=other-branch",
            "--token",
            "gitclean=clean",
        )
        self.api(
            "pane",
            "report-agent",
            self.pane2,
            "--source",
            "release-visual",
            "--agent",
            "claude",
            "--state",
            "idle",
        )
        self.api("tab", "focus", self.tab)
        self.snapshot("fixture")

    def close(self):
        watcher_pids = []
        for f in self.root.rglob("pid"):
            if f.parent.name == "watch.lock":
                pid = int(f.read_text())
                cmd = subprocess.run(
                    ["ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True
                ).stdout
                if (str(self.root) in cmd or str(self.root.resolve()) in cmd) and "--watch" in cmd:
                    watcher_pids.append(pid)
        self.command("server", "stop", check=False)
        try:
            self.proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            self.proc.terminate()
            self.proc.wait(timeout=8)
        self.log.close()
        for client in self.clients:
            if client.proc.poll() is None:
                client.proc.terminate()
                client.proc.wait(timeout=5)
            if client.master is not None:
                os.close(client.master)
                client.master = None
        for pid in watcher_pids:
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        (self.out / "cleanup.json").write_text(
            json.dumps(
                dict(
                    server_pid=self.proc.pid,
                    server_returncode=self.proc.returncode,
                    root=str(self.root),
                    client_pids=[
                        dict(pid=c.proc.pid, returncode=c.proc.poll()) for c in self.clients
                    ],
                    recorded_owned_watcher_pids=watcher_pids,
                ),
                indent=2,
            )
        )


class CaptureScreen(pyte.Screen):
    def report_device_status(self, *args, **kwargs):
        pass

    def report_device_attributes(self, *args, **kwargs):
        pass


class Client:
    def __init__(self, runtime, binary, cols=120, rows=32):
        self.runtime = runtime
        self.cols = cols
        self.rows = rows
        self.raw = bytearray()
        self.decoder = codecs.getincrementaldecoder("utf8")("replace")
        self.screen = CaptureScreen(cols, rows)
        self.stream = pyte.Stream(self.screen)
        self.master, slave = os.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))

        def attach_tty():
            os.setsid()
            fcntl.ioctl(0, termios.TIOCSCTTY, 0)

        self.proc = subprocess.Popen(
            [str(binary)],
            cwd=runtime.root,
            env=runtime.env,
            stdin=slave,
            stdout=slave,
            stderr=slave,
            preexec_fn=attach_tty,
            close_fds=True,
        )
        os.close(slave)
        runtime.clients.append(self)
        self.read(3)

    def read(self, duration=0.5):
        end = time.monotonic() + duration
        while time.monotonic() < end:
            if not select.select([self.master], [], [], min(0.1, max(0, end - time.monotonic())))[
                0
            ]:
                continue
            try:
                data = os.read(self.master, 65536)
            except OSError:
                break
            if not data:
                break
            self.raw.extend(data)
            self.stream.feed(re.sub(r"\x1b\[[><][0-9;]*[A-Za-z]", "", self.decoder.decode(data)))
            if b"\x1b]11;?" in data:
                os.write(
                    self.master,
                    (
                        b"\x1b]11;rgb:eeee/eeee/eeee\x1b\\"
                        if self.runtime.theme == "adaptive-light"
                        else b"\x1b]11;rgb:1e1e/1e1e/2e2e\x1b\\"
                    ),
                )
            if b"\x1b[6n" in data:
                os.write(self.master, b"\x1b[1;1R")
            if b"\x1b[?u" in data:
                os.write(self.master, b"\x1b[?0u")

    def send(self, data):
        os.write(self.master, data)
        self.read(0.6)

    def resize(self, cols, rows=32):
        self.cols = cols
        self.rows = rows
        self.screen.resize(rows, cols)
        fcntl.ioctl(self.master, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        os.kill(self.proc.pid, signal.SIGWINCH)
        self.read(0.8)

    def capture(self, name):
        base = self.runtime.out / name
        base.with_suffix(".ansi").write_bytes(self.raw)
        base.with_suffix(".txt").write_text("\n".join(self.screen.display) + "\n")
        cells = [
            [
                dict(x=x, y=y, data=c.data, fg=c.fg, bg=c.bg, bold=c.bold)
                for x, c in self.screen.buffer[y].items()
            ]
            for y in range(self.rows)
        ]
        base.with_suffix(".cells.json").write_text(json.dumps(cells, ensure_ascii=False, indent=1))
        colors = {
            "default": "#1e1e2e",
            "black": "#000000",
            "red": "#ff0000",
            "green": "#00ff00",
            "brown": "#aaaa00",
            "blue": "#0000ff",
            "magenta": "#ff00ff",
            "cyan": "#00ffff",
            "white": "#ffffff",
            "brightblack": "#777777",
            "brightwhite": "#ffffff",
        }

        def color(v, fg=False):
            return (
                "#" + v
                if len(v) == 6
                else ("#cdd6f4" if v == "default" and fg else colors.get(v, "#1e1e2e"))
            )

        font = ImageFont.truetype("/System/Library/Fonts/Menlo.ttc", 15)
        w = 10
        h = 21
        img = Image.new("RGB", (self.cols * w, self.rows * h), "#1e1e2e")
        draw = ImageDraw.Draw(img)
        for y in range(self.rows):
            for x in range(self.cols):
                c = self.screen.buffer[y][x]
                draw.rectangle((x * w, y * h, (x + 1) * w, (y + 1) * h), fill=color(c.bg))
                draw.text((x * w, y * h), c.data, font=font, fill=color(c.fg, True), stroke_width=0)
        img.save(base.with_suffix(".png"))
        return self.screen.display

    def detach(self):
        self.send(b"\x01")
        self.send(b"q")
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.terminate()
            self.proc.wait(timeout=5)
        os.close(self.master)
        self.master = None
        return self.proc.returncode


def case_capture(client, name):
    lines = client.capture(name)
    return dict(
        name=name, client_pid=client.proc.pid, cols=client.cols, rows=client.rows, lines=lines
    )


def verify_visual_cells():
    def frame(case, name):
        return json.loads((OUT / case / (name + ".cells.json")).read_text())

    def at(c, x, y):
        return next(q for q in c[y] if q["x"] == x)

    rules = [
        ("space focused blue", "custom-server", "dark-focused", 3, 2, "89b4fa"),
        ("space inactive gray", "custom-server", "dark-focused", 3, 5, "7f849c"),
        ("Agent focused blue", "custom-server", "dark-focused", 3, 19, "89b4fa"),
        ("Agent inactive gray", "custom-server", "dark-focused", 3, 22, "7f849c"),
        ("native tab muted", "custom-server", "dark-focused", 3, 20, "6c7086"),
        ("navigation selected blue", "custom-server", "navigation-second", 3, 5, "89b4fa"),
        ("navigation former focus gray", "custom-server", "navigation-second", 3, 2, "7f849c"),
        ("navigation exit restores blue", "custom-server", "navigation-exit", 3, 2, "89b4fa"),
        ("mouse focus follows Agent", "custom-server", "mouse-second-space", 3, 22, "89b4fa"),
        ("light inactive gray", "light-theme", "focused", 3, 5, "8c8fa1"),
        ("light native context muted", "light-theme", "focused", 3, 20, "9ca0b0"),
        ("Space explicit foreground", "explicit-foreground", "navigation-second", 3, 5, "ff00ff"),
        ("Agent explicit foreground", "explicit-foreground", "navigation-second", 3, 19, "00ff00"),
    ]
    results = []
    for name, case, capture, x, y, expected in rules:
        actual = at(frame(case, capture), x, y)["fg"]
        assert actual == expected, (name, actual, expected)
        results.append(
            dict(
                check=name,
                case=case,
                capture=capture,
                column=x,
                row=y,
                expected=expected,
                actual=actual,
            )
        )
    dark = (OUT / "custom-server/dark-focused.txt").read_text().splitlines()
    assert not dark[4][:37].strip() and not dark[21][:37].strip()
    assert (
        dark[0].count("│") >= 3
        and "codex" in dark[0]
        and "shell" in dark[0]
        and dark[1][38:].strip()
    )
    assert dark[19][:37].endswith("working ")
    assert dark[3][:37].endswith("~2 · ?1  ")
    narrow = (OUT / "custom-server/mouse-sidebar-narrow.txt").read_text().splitlines()
    assert narrow[0].index("│") == 17 and "~2 · ?1" in narrow[3][:17]
    light = frame("light-theme", "focused")
    assert at(light, 3, 5)["bg"] == "e6e9ef" and at(light, 3, 2)["bg"] == "ccd0da"
    for capture, columns, rows in [
        ("terminal-resized-narrow", 72, 28),
        ("terminal-resized-wide", 140, 36),
    ]:
        lines = (OUT / "custom-server" / (capture + ".txt")).read_text().splitlines()
        assert len(lines) == rows and all(len(line) == columns for line in lines)
    (OUT / "cell-checks.json").write_text(json.dumps(results, indent=2))


def assert_native_context(client):
    for y, line in enumerate(client.screen.display):
        if y > 17 and "packy-catalog › codex" in line:
            x = line.index("packy-catalog › codex")
            cell = client.screen.buffer[y][x]
            assert cell.fg == "6c7086", (y, x, cell)
            return dict(
                row=y,
                column=x,
                text="packy-catalog › codex",
                foreground=cell.fg,
                background=cell.bg,
            )
    raise AssertionError("full native Agent tab context not found")


def main():
    meta = dict(
        platform=platform.platform(),
        machine=platform.machine(),
        custom_sha256=hashlib.sha256(
            (CUSTOM.parent.parent / "libexec/herdr").read_bytes()
        ).hexdigest(),
        official_sha256=hashlib.sha256(OFFICIAL.read_bytes()).hexdigest(),
        capture_method="Actual live PTY bytes parsed into terminal cells and rendered to PNG. No native Terminal.app screenshot.",
        fixture_method="Workspace display metadata and agent state reported through the real runtime API, not actual coding-agent detection.",
    )
    (OUT / "identity.json").write_text(json.dumps(meta, indent=2))
    checks = []
    r = Runtime("official-server", OFFICIAL)
    try:
        r.fixture()
        before = r.api("pane", "process-info", "--pane", r.pane)
        r.snapshot("before-custom")
        c = Client(r, CUSTOM)
        case_capture(c, "custom-attached")
        code = c.detach()
        after = r.api("pane", "process-info", "--pane", r.pane)
        r.snapshot("after-custom")
        assert (
            code == 0
            and before["process_info"]["shell_pid"] == after["process_info"]["shell_pid"]
            and r.proc.poll() is None
        )
        c = Client(r, OFFICIAL)
        case_capture(c, "official-reattached")
        code = c.detach()
        last = r.api("pane", "process-info", "--pane", r.pane)
        r.snapshot("after-official")
        assert (
            code == 0
            and before["process_info"]["shell_pid"] == last["process_info"]["shell_pid"]
            and r.proc.poll() is None
        )
        (r.out / "process-identities.json").write_text(
            json.dumps(
                dict(before=before, after_custom=after, after_official=last, server_pid=r.proc.pid),
                indent=2,
            )
        )
        checks.append(
            dict(
                name="custom client then official client on official 0.9.5 server",
                verdict="PASS",
                evidence="official-server/process-identities.json",
            )
        )
    finally:
        r.close()
    r = Runtime("custom-server", CUSTOM)
    try:
        r.fixture()
        before = r.api("pane", "process-info", "--pane", r.pane)
        r.snapshot("before-visual")
        c = Client(r, CUSTOM)
        case_capture(c, "dark-focused")
        c.send(b"\x01")
        c.send(b"w")
        case_capture(c, "navigation-initial")
        c.send(b"\x1b[B")
        case_capture(c, "navigation-second")
        c.send(b"\x1b")
        case_capture(c, "navigation-exit")
        c.send(b"\x1b[<0;8;6M")
        c.send(b"\x1b[<0;8;6m")
        case_capture(c, "mouse-second-space")
        snap = r.snapshot("mouse-second-space")
        assert snap["focused_workspace_id"] == r.ws2
        c.send(b"\x1b[<0;8;20M")
        c.send(b"\x1b[<0;8;20m")
        case_capture(c, "mouse-first-agent")
        snap = r.snapshot("mouse-first-agent")
        assert snap["focused_pane_id"] == r.pane
        c.send(b"\x1b[<0;38;12M")
        c.send(b"\x1b[<32;18;12M")
        c.send(b"\x1b[<0;18;12m")
        case_capture(c, "mouse-sidebar-narrow")
        c.resize(72, 28)
        case_capture(c, "terminal-resized-narrow")
        c.resize(140, 36)
        case_capture(c, "terminal-resized-wide")
        code = c.detach()
        after = r.api("pane", "process-info", "--pane", r.pane)
        assert (
            code == 0 and before["process_info"]["shell_pid"] == after["process_info"]["shell_pid"]
        )
        r.api("tab", "rename", r.tab, "packy-catalog › codex")
        c = Client(r, CUSTOM)
        case_capture(c, "native-tab-context")
        code = c.detach()
        assert code == 0
        c = Client(r, OFFICIAL)
        case_capture(c, "official-client-custom-server")
        code = c.detach()
        last = r.api("pane", "process-info", "--pane", r.pane)
        assert (
            code == 0
            and before["process_info"]["shell_pid"] == last["process_info"]["shell_pid"]
            and r.proc.poll() is None
        )
        (r.out / "process-identities.json").write_text(
            json.dumps(
                dict(before=before, after_custom=after, after_official=last, server_pid=r.proc.pid),
                indent=2,
            )
        )
        checks.append(
            dict(
                name="custom client then official client on custom 0.9.5 server",
                verdict="PASS",
                evidence="custom-server/process-identities.json",
            )
        )
    finally:
        r.close()
    for name, theme, override in [
        ("light-theme", "adaptive-light", False),
        ("explicit-foreground", "dark", True),
        ("native-full-context", "dark", False),
    ]:
        r = Runtime(name, CUSTOM, theme=theme, overrides=override)
        try:
            r.fixture()
            if name == "native-full-context":
                r.api("tab", "rename", r.tab, "packy-catalog › codex")
            c = Client(r, CUSTOM)
            case_capture(c, "focused")
            c.send(b"\x01")
            c.send(b"w")
            c.send(b"\x1b[B")
            case_capture(c, "navigation-second")
            c.send(b"\x1b")
            code = c.detach()
            assert code == 0
        finally:
            r.close()
    r = Runtime("plugin-native-context", CUSTOM)
    try:
        r.fixture()
        r.api("tab", "rename", r.tab, "packy-catalog › codex")
        r.close()
        r.env["HERDR_TAB_GIT_NODE"] = shutil.which("node")
        r.command(
            "plugin",
            "install",
            "yersonargotev/herdr-tab-git",
            "--ref",
            "5ef7d5a69ccfc7552d3cc81a1a7cfb059cb256df",
            "--yes",
        )
        r.start()

        def wait_tokens(expected, label):
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                snap = r.api("api", "snapshot")["snapshot"]
                ws = next(x for x in snap["workspaces"] if x["workspace_id"] == r.ws)
                if all(ws.get("tokens", {}).get(k) == v for k, v in expected.items()):
                    (r.out / (label + ".json")).write_text(json.dumps(snap, indent=2))
                    return snap
                time.sleep(0.2)
            raise RuntimeError("plugin metadata timeout " + label)

        wait_tokens({"gitbranch": "visual-branch", "gitclean": "clean"}, "startup")
        startup = r.api("plugin", "log", "--plugin", "yersonargotev.tab-git", "--limit", "100")
        (r.out / "startup-log.json").write_text(json.dumps(startup, indent=2))
        assert any(
            x.get("event") == "startup" and x.get("status") == "succeeded" for x in startup["logs"]
        )
        r.api(
            "pane",
            "report-agent",
            r.pane,
            "--source",
            "release-visual",
            "--agent",
            "codex",
            "--state",
            "working",
        )
        c = Client(r, CUSTOM)
        case_capture(c, "after-startup")
        context_checks = {"startup": assert_native_context(c)}
        r.api("plugin", "action", "invoke", "clear", "--plugin", "yersonargotev.tab-git")
        time.sleep(0.5)
        (r.repo / "tracked.txt").write_text("changed by explicit refresh\n")
        r.api("plugin", "action", "invoke", "refresh", "--plugin", "yersonargotev.tab-git")
        wait_tokens({"gitmodified": "~1"}, "refresh")
        c.read(0.5)
        case_capture(c, "after-refresh")
        context_checks["refresh"] = assert_native_context(c)
        (r.repo / "untracked.txt").write_text("polling only\n")
        wait_tokens({"gitmodified": "~1", "gituntracked": "?1"}, "polling")
        c.read(0.5)
        case_capture(c, "after-polling")
        context_checks["polling"] = assert_native_context(c)
        (r.out / "context-checks.json").write_text(json.dumps(context_checks, indent=2))
        assert c.detach() == 0
        (r.out / "plugins.json").write_text(r.command("plugin", "list").stdout)
        pids = []
        for f in r.root.rglob("pid"):
            if f.parent.name == "watch.lock":
                pid = int(f.read_text())
                cmd = subprocess.run(
                    ["ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True
                ).stdout
                if str(r.root) in cmd and "--watch" in cmd:
                    pids.append(pid)
        checks.append(
            dict(
                name="native muted tab context after exact plugin startup refresh and polling",
                verdict="PASS",
                evidence="plugin-native-context/after-startup.png, after-refresh.png, after-polling.png",
            )
        )
    finally:
        r.close()
        (r.out / "watcher-cleanup.json").write_text(
            json.dumps({"recorded_owned_watcher_pids": locals().get("pids", [])}, indent=2)
        )
    verify_visual_cells()
    assert (
        hashlib.sha256((CUSTOM.parent.parent / "libexec/herdr").read_bytes()).hexdigest()
        == meta["custom_sha256"]
    )
    assert hashlib.sha256(OFFICIAL.read_bytes()).hexdigest() == meta["official_sha256"]
    (OUT / "checks.json").write_text(json.dumps(checks, indent=2))
    (OUT / "commands.json").write_text(json.dumps(COMMANDS, indent=2))
    print(json.dumps(checks, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Verify Herdr custom visual cells and matching 0.9.5 attachment in owned macOS PTYs. Requires pyte and Pillow in the invoking Python environment."
    )
    parser.add_argument("--custom-release", type=Path, required=True)
    parser.add_argument("--official-binary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    CUSTOM = args.custom_release.resolve() / "bin/herdr-custom"
    CONFIG = args.custom_release.resolve() / "config/config.toml"
    OFFICIAL = args.official_binary.resolve()
    OUT = args.output.resolve()
    OUT.mkdir(parents=True, exist_ok=True)
    main()
