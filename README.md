# Herdr Custom

An independent, compact UI distribution of Herdr for macOS Apple Silicon and Linux x86_64. This repository
stores a small patch set and a pinned build recipe, not a long-lived copy of the
upstream source. It is not an official Herdr release.

## What changes

- One-row tabs, without added numbering, underline, or vertical padding.
- Highlighted active tab; inactive tabs share the bar background; vertical separators.
- Blue selection marks for Spaces and Agents.
- Agent name and state dot on the left, state text aligned to the right.
- Space branch on the left, Git status and change counts on the right; narrow
  sidebars keep the compact inline layout.
- The bundled adaptive configuration uses stable workspace names, task and tab
  context, dots for status indicators, and no sidebar row gaps.

The native patches change client presentation and disable official self-update.
The executable still contains upstream server functionality. No server protocol
or persisted session format has been changed. Compatibility is verified against
the pinned upstream version; do not assume compatibility with future servers.

## Version and provenance

`upstream.lock.json` fixes the official Git commit, Rust and Zig versions, patch
hashes, and distribution version. `VERSION` identifies our release independently
from the upstream runtime version. Run `herdr-custom --version` to see both.

The current base is Herdr 0.9.3, commit
`7b116c05bfda646af39d2524c54e70c751f57ee8`. macOS Apple Silicon and Linux x86_64 have native CI jobs.
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

Set `ZIG=/absolute/path/to/zig` if needed. An optional
`--source-cache /path/to/existing/herdr-checkout` avoids fetching the commit;
the commit and patch checks are identical. Cargo's `CARGO_TARGET_DIR` may be used
for an absolute build-cache directory.

## Install and try

Download the archive and matching `.sha256` for your platform from this repository's
GitHub Releases. Apple Silicon uses `macos-aarch64`; Linux x86_64 uses `linux-x86_64`.
Verify the checksum before extraction:

```sh
shasum -a 256 -c herdr-custom-0.9.3-custom.4-macos-aarch64.tar.gz.sha256
tar -xzf herdr-custom-0.9.3-custom.4-macos-aarch64.tar.gz
./herdr-custom-0.9.3-custom.4-macos-aarch64/bin/herdr-custom --version
```

Keep the extracted directory together. You may move it under `~/.local/opt/`
and symlink its `bin/herdr-custom` into a directory on PATH. The launcher resolves
that symlink. Do not overwrite or rename the official `herdr` executable.

To attach to an existing session, detach its current client and use:

```sh
/path/to/release/bin/herdr-custom --session YOUR_SESSION
```

As with upstream, a missing session can start a server. Verify the session name
first if you intend only to attach. The supported base for this release is 0.9.3.
Do not run simultaneous clients with different layouts as a visual acceptance test.

The launcher defaults to the bundled config, and honors an explicit
`HERDR_CONFIG_PATH`. It does not copy anything into `~/.config/herdr`.
The bundled configuration is the approved dots adaptive configuration: its
Tabby, Git metadata, and Herdr Tasks fields require those existing plugins.
This project does not install plugins. Without them, their metadata fields may
be empty; an optional metrics command also requires the dots metrics setup.
No extra vertical padding is supported.

## Updates and rollback

Official `herdr update` is blocked in this build so it cannot replace the custom
binary. Update by downloading and verifying a new custom archive, then switching
the `herdr-custom` symlink after detaching the old client. Keep the previous
release directory for rollback. Source recipe and patch updates are reviewed
before adopting a new upstream version; updates are not automatic.

To return to official presentation, detach the custom client and attach using
`herdr --session YOUR_SESSION`. Use the same compatible upstream version. This
preserves the server's panes and agents; it does not migrate a newer server to an
older version. Remove only the custom symlink and release directory when done.

The dots Tag still installs official Herdr. Integrating this distribution into
dots is separate work tracked in https://github.com/yersonargotev/dots/issues/548.

## Maintaining the patch set

1. Choose an official stable commit and review upstream changes and notices.
2. Update the lock, adapt patches, recompute their SHA-256 values, and bump VERSION.
3. Run the recipe, native macOS and Linux CI, and live mouse/theme/resize acceptance checks.
4. Verify compatibility with the matching official server and rollback behavior.
5. Tag `v` followed by VERSION. CI builds both supported platforms and creates a draft
   release only after both jobs pass. Review archives and provenance before
   publishing that draft.

Do not add arbitrary features to this patch set or restore rejected padding.
CI is a regression check, not proof of live terminal rendering on every host.

## License

Apache-2.0. Original Herdr license notices remain in the distribution. See
`LICENSE` and `NOTICE`; source changes are supplied under `patches/`.
