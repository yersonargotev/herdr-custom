# Herdr Custom

An independent, compact UI distribution of Herdr for macOS Apple Silicon and Linux x86_64. This repository
stores a small patch set and a pinned build recipe, not a long-lived copy of the
upstream source. It is not an official Herdr release.

## What changes

- One-row tabs, without added numbering, underline, or vertical padding.
- Highlighted active tab; inactive tabs share the bar background; vertical separators.
- Blue selection marks for Spaces and Agents.
- Space tab names follow the navigation selection in the theme accent; inactive
  names retain the original theme gray. Leaving navigation restores active-Space
  highlighting. Explicit token foregrounds still override the contextual color.
- Agent names follow pane focus in the theme accent; other names use the same
  gray as inactive Spaces. Explicit token foregrounds still take precedence.
- Agent name and state dot on the left, state text aligned to the right.
  Agent status colors and secondary tab context are unchanged.
- Space branch on the left, Git status and change counts on the right; narrow
  sidebars keep the compact inline layout.
- The bundled adaptive configuration uses active tab names, native Agent tab
  context, dots for status indicators, and one blank row between independent
  Space entries and between Agent entries.

The native patches change client presentation and disable official self-update.
The executable still contains upstream server functionality. No server protocol
or persisted session format has been changed. Compatibility is verified against
the pinned upstream version; do not assume compatibility with future servers.

## Version and provenance

`upstream.lock.json` fixes the official Git commit, Rust and Zig versions, patch
hashes, and distribution version. `VERSION` identifies our release independently
from the upstream runtime version. Run `herdr-custom --version` to see both.

The current distribution is `0.9.5-custom.1`, based on official Herdr 0.9.5, commit
`2ecf19a92fc3a7fff75b6ce3655ef04f4625ec01`. macOS Apple Silicon and Linux x86_64 have native CI jobs.
Apple Intel, Linux ARM64, and Windows are not supported. Linux binaries use
static musl linking.

Every archive includes the lock, patches, license notices, and `provenance.json`
with the recipe commit and executable SHA-256. Builds are source-pinned and
repeatable; byte-for-byte reproducibility has not been established.

## Build locally

Install Python 3, Git, Rust 1.96.1 through rustup, Zig 0.16.0, CMake, Ninja, and
Apple's command-line developer tools on macOS. On Linux, install `musl-tools`
and add the target with `rustup target add --toolchain 1.96.1 x86_64-unknown-linux-musl`. Then:

```sh
python3 -m unittest discover -s tests -v
python3 scripts/build.py
```

The recipe fetches only the pinned upstream commit, checks and applies patches,
runs the client-shell test suite, builds in release mode, checks the self-update
guard in a temporary home, and writes an archive and checksum under `dist/`.
It never installs the binary or changes the user's Herdr configuration.
Full builds require a clean recipe checkout so provenance identifies every
packaged input. Cached source must still match the pinned commit and complete
patch series. Commit recipe edits before packaging; `--prepare-only` supports
patch iteration without producing a release.

Set `ZIG=/absolute/path/to/zig` if needed. An optional
`--source-cache /path/to/existing/herdr-checkout` avoids fetching the commit;
the commit and patch checks are identical. Cargo's `CARGO_TARGET_DIR` may be used
for an absolute build-cache directory.

CI also runs the real Git plugin smoke test on both native platforms. To repeat
it against an extracted release:

```sh
python3 scripts/smoke.py --release /path/to/extracted/release --output /tmp/herdr-smoke-evidence
```

The smoke test uses disposable repositories, homes, configuration, state, and
sockets. It installs the exact plugin revision into those roots and tests
startup, explicit refresh, polling, and the private executable path. It does not
establish visual acceptance or persisted-state downgrade safety. See
[the verification record](https://github.com/yersonargotev/herdr-custom/blob/main/docs/verification-0.9.5.md) for those boundaries and
the platform of each manual check.

## Install and try

Download the archive and matching `.sha256` for your platform from this repository's
GitHub Releases. Apple Silicon uses `macos-aarch64`; Linux x86_64 uses `linux-x86_64`.
Verify the checksum before extraction:

```sh
shasum -a 256 -c herdr-custom-0.9.5-custom.1-macos-aarch64.tar.gz.sha256
tar -xzf herdr-custom-0.9.5-custom.1-macos-aarch64.tar.gz
./herdr-custom-0.9.5-custom.1-macos-aarch64/bin/herdr-custom --version
```

Keep the extracted directory together. You may move it under `~/.local/opt/`
and symlink its `bin/herdr-custom` into a directory on PATH. The launcher resolves
that symlink. Do not overwrite or rename the official `herdr` executable.

To attach to an existing session, detach its current client and use:

```sh
/path/to/release/bin/herdr-custom --session YOUR_SESSION
```

As with upstream, a missing session can start a server. Verify the session name
first if you intend only to attach. The supported base for this release is 0.9.5.
Do not run simultaneous clients with different layouts as a visual acceptance test.

The launcher defaults to the bundled config, and honors an explicit
`HERDR_CONFIG_PATH`. It does not copy anything into `~/.config/herdr`.
The bundled configuration is the approved dots adaptive configuration: its
Tabby and Git metadata fields require those existing plugins.
This project does not install plugins automatically. Without them, their metadata fields may
be empty; an optional metrics command also requires the dots metrics setup.
No extra vertical padding is supported.

The Git plugin revision verified for this release is
`5ef7d5a69ccfc7552d3cc81a1a7cfb059cb256df`, version 1.4.0. Install it with the
custom launcher when you choose to change your plugin configuration:

```sh
/path/to/release/bin/herdr-custom plugin install yersonargotev/herdr-tab-git \
  --ref 5ef7d5a69ccfc7552d3cc81a1a7cfb059cb256df --yes
```

Plugins receive the running server's executable path. Run a custom 0.9.5 server
when you need plugin subprocesses to use the custom runtime. Attaching a custom
client to an official server leaves that server in charge of plugin commands.
The bundled Agent row retains the native muted `tab` context. It does not use
the plugin's `$project` token.

## Updates and rollback

Official `herdr update` is blocked in this build so it cannot replace the custom
binary. Update by downloading and verifying a new custom archive, then switching
the `herdr-custom` symlink after detaching the old client. Keep the previous
release directory for rollback. Source recipe and patch updates are reviewed
before adopting a new upstream version; updates are not automatic.

`0.9.3-custom.6` uses the older 0.9.3 runtime. Do not attach this release to an
older live server as an upgrade procedure. A new client executable does not
replace its server. First preserve a separate copy of the old configuration,
plugin registry and managed plugin directories, session state, and history.
Any stop, migration, or restart of live sessions requires a separate operator
decision. Test the new release with disposable roots before that decision.

Version 0.9.5 changes shutdown persistence and managed plugin installation paths.
The protocol and snapshot version numbers remain unchanged, but those numbers
do not establish downgrade safety. To return to 0.9.3, stop the newer server
and restore the complete pre-upgrade copies before starting the old release.
Do not feed state saved by 0.9.5 to 0.9.3 or treat a symlink change as a state
downgrade. Restoring state does not restore terminated agent processes.

To return to official presentation, detach the custom client and attach using
`herdr --session YOUR_SESSION`. Use the same compatible upstream version. This
preserves the server's panes and agents; it does not migrate a newer server to an
older version. Remove only the custom symlink and release directory when done.

Downstream dots adoption is separate work tracked in
https://github.com/yersonargotev/dots/issues/569. Its current contract retains
`0.9.3-custom.6`. This release does not authorize a change to that pin.

## Maintaining the patch set

1. Choose an official stable commit and review upstream changes and notices.
2. Update the lock, adapt patches, recompute their SHA-256 values, and bump VERSION.
3. Run the recipe, native macOS and Linux CI, and live mouse/theme/resize acceptance checks.
4. Verify compatibility with the matching official server and rollback behavior.
5. Tag `v` followed by VERSION. CI builds both supported platforms and creates a draft
   release only after both jobs pass. Review archives and provenance before
   publishing that draft.

Download both draft archives and checksums into an otherwise empty directory.
From the clean recipe checkout at the release commit, inspect the complete pair:

```sh
python3 scripts/verify_release.py --recipe-commit "$(git rev-parse HEAD)" --platform all dist/
```

The inspector checks the exact payload, executable architecture and digest,
patches, lock, notices, checksums, and recipe identity without executing or
extracting the archives. Missing platforms, stale extra files, or mismatches
fail the check. Publish only after this inspection and the native runtime checks.

Do not add arbitrary features to this patch set or restore rejected padding.
CI is a regression check, not proof of live terminal rendering on every host.

## License

Apache-2.0. Original Herdr license notices remain in the distribution. See
`LICENSE` and `NOTICE`; source changes are supplied under `patches/`.
