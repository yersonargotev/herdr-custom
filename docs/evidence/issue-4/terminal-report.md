# Herdr 0.9.5 live terminal verification

PASS for the measured macOS ARM64 PTY cases and matching 0.9.5 client/server combinations. This report covers the actual local preview executable. It does not identify a final published archive.

## Runtime identity and method

- Platform is macOS ARM64, Darwin 25.6.0. Full host identity is in `cli-rerun/identity.json`.
- The custom runtime is upstream `2ecf19a92fc3a7fff75b6ce3655ef04f4625ec01` with the five existing patches and `HERDR_CUSTOM_BUILD=0.9.5-custom.1`, supplied by the parent build.
- Measured custom executable SHA-256 is `4fe3fd331890eb33948f71c1fc1bc58b26cd5410376b8c461181e91ac20e6f1a`.
- Measured official 0.9.5 executable SHA-256 is `fb77c2232a05a8035421382c894392f4174e4e38a18e48af3dd0290157c3a7e2`.
- Both executable digests remained unchanged after the checks.
- `check.py` starts direct real server and TUI processes under fresh short `/tmp/h4v-*` roots. HOME, every XDG root, temporary files, configuration, and sockets are explicit and private. The command PATH contains `/usr/bin:/bin`; the actual Node executable is supplied explicitly for plugin hooks.
- Actual TUI output is captured through a controlling PTY. Raw `.ansi` files preserve those bytes. Pyte parses terminal cells, and Pillow renders those cells into `.png` files. The PNG files are recorded PTY renderings, not native Terminal.app screenshots.
- Mouse checks send SGR mouse protocol events into the live client. Resize checks change the PTY dimensions and send SIGWINCH to that specific client.
- Agent rows are deterministic fixtures reported through the real `pane report-agent` API. These checks prove report-and-render behavior, not detection of an actual Codex or Claude process.

## Visual results

| Case | Verdict | Evidence |
| --- | --- | --- |
| Compact one-row tabs, active/inactive styling, separators, and immediate pane row | PASS | `cli-rerun/custom-server/dark-focused.png`, `.txt`, `.cells.json.gz` |
| Blue Space selection marks, active blue name, inactive gray name, and one-row Space gap | PASS | `cli-rerun/custom-server/dark-focused.png`, `cli-rerun/cell-checks.json` |
| Navigation selection changes the selected Space name to blue and the current unselected name to gray; Escape restores focus colors | PASS | `cli-rerun/custom-server/navigation-second.png`, `navigation-exit.png`, `cli-rerun/cell-checks.json` |
| Agent focus colors, left name/state dot, right state text, muted native tab context, and one-row Agent gap | PASS | `cli-rerun/custom-server/dark-focused.png`, `mouse-second-space.png`, `cli-rerun/cell-checks.json` |
| Mouse Space/Agent selection changes the actual focused IDs | PASS | `cli-rerun/custom-server/mouse-second-space.json`, `mouse-first-agent.json` |
| Mouse sidebar drag reaches the configured minimum of 18 columns; branch/status remain visible | PASS | `cli-rerun/custom-server/mouse-sidebar-narrow.png`, `.txt` |
| Terminal resize to 72 by 28 and 140 by 36 preserves compact layout | PASS | `cli-rerun/custom-server/terminal-resized-narrow.png`, `terminal-resized-wide.png` |
| Normal-width branch is left aligned and Git status is right aligned | PASS | `cli-rerun/custom-server/dark-focused.txt` |
| Adaptive light appearance uses light sidebar/selection colors and muted native context | PASS | `cli-rerun/light-theme/focused.png`, `cli-rerun/cell-checks.json` |
| Explicit Space magenta and Agent green foregrounds survive focus/navigation colors | PASS | `cli-rerun/explicit-foreground/navigation-second.png`, `cli-rerun/cell-checks.json` |
| Native full tab label remains muted through exact-plugin startup, refresh and polling | PASS | `cli-rerun/plugin-native-context/context-checks.json`, `after-startup.png`, `after-refresh.png`, `after-polling.png` |

The normal dark selection has foreground `89b4fa`; inactive names have `7f849c`. Native dark tab context has foreground `6c7086`. The light inactive name has `8c8fa1` and native context has `9ca0b0`. These are measured cell values. `cli-rerun/cell-checks.json` records 13 explicit color assertions. The script also asserts row gaps, tab geometry, right alignment, narrow layout, and exact resize dimensions.

Pyte does not expose the faint attribute in its cell model. The cell evidence therefore records measured foreground/background and bold values, without inventing a dim value. Raw ANSI remains available. Terminal font rasterization in other emulators and physical mouse event generation are outside this PTY check.

## Exact plugin and native context

The real custom launcher installed `yersonargotev/herdr-tab-git` at `5ef7d5a69ccfc7552d3cc81a1a7cfb059cb256df`. Its actual startup command succeeded after restarting only this disposable server. The installed plugin and startup log are in `cli-rerun/plugin-native-context/plugins.json` and `startup-log.json`.

The disposable tab was explicitly named `packy-catalog › codex`. The existing native `tab` row displayed that complete label. The configuration never adopted `$project` for the Agent row. The reported Agent fixture was restored through the real API after server startup; no claim is made that report authority persisted through restart.

The observed sequence was:

1. Startup produced `gitbranch=visual-branch`, `gitclean=clean`, and the full `tab_name`. The actual log identifies a successful `startup` hook.
2. The clear action paused automatic updates. A tracked file changed. Explicit refresh produced `gitmodified=~1`.
3. An untracked file appeared. Only API snapshot reads followed, without action or focus changes. Polling produced `gituntracked=?1`.

At every capture, the native Agent context was still the full label at row 20, column 3, with foreground `6c7086`. `context-checks.json` records those assertions. Real snapshots are `startup.json`, `refresh.json`, and `polling.json`.

## Matching-server attachment

| Server | Client sequence | Observed stable identity | Verdict |
| --- | --- | --- | --- |
| Official Herdr 0.9.5, PID 64919 | Custom 0.9.5 client, detach, official 0.9.5 client, detach | Pane `w1:p1`, shell PID 64944 before and after both clients | PASS |
| Custom Herdr 0.9.5, PID 65486 | Custom 0.9.5 client, detach, official 0.9.5 client, detach | Pane `w1:p1`, shell PID 65516 before and after both clients | PASS |

Exact process information is in `cli-rerun/official-server/process-identities.json` and `cli-rerun/custom-server/process-identities.json`. API snapshots before and after each client are retained. Every detach returned zero. The server remained alive between clients. Clients were sequential, never simultaneous.

This verifies matching-version client replacement. It does not verify 0.9.3 clients or servers, downgrade of state saved by 0.9.5, or recovery of terminated coding-agent processes. The safe rollback boundary remains the complete pre-upgrade config/state/plugin backup described by the parent source audit.

## Cleanup and rerun

All six final disposable server cases stopped successfully. Every recorded server, client, and plugin watcher PID was absent from the process table after cleanup. `cleanup-verification.json` records the final check. No operator home, configuration, installed executable, live session, or dots repository was changed.

Run the retained script with a Python environment containing `pyte` and `Pillow`:

```sh
/path/to/python3 check.py \
  --custom-release /path/to/extracted/custom/release \
  --official-binary /path/to/verified/official-0.9.5 \
  --output /path/to/owned/evidence
```

The initial harness mistakes were observations, not product defects. Metadata mutations return no JSON. `process-info` requires `--pane`. Pyte needed to ignore unsupported private device-status callbacks and keyboard-protocol control sequences. Those corrections preserve the original raw ANSI and are encoded in the retained script.

Prove It Works selected real process identities, runtime snapshots, and actual terminal cells as the verdict. Separate Before Serializing Shared State selected one private root and socket per case.
