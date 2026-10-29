# Herdr 0.9.5 release verification

This record covers issue [#4](https://github.com/yersonargotev/herdr-custom/issues/4).
The distribution version is `0.9.5-custom.1`. The supported platforms remain
macOS ARM64 and Linux AMD64 with static musl linking.

## Source review

The official `v0.9.5` tag resolves to
`2ecf19a92fc3a7fff75b6ce3655ef04f4625ec01`. The previous base was
`7b116c05bfda646af39d2524c54e70c751f57ee8`. The range has 81 commits and
428 changed files. It includes terminal input, navigation, managed plugin
installation, shutdown, and persistence changes.

[Rust 1.96.1](https://github.com/herdrdev/herdr/blob/2ecf19a92fc3a7fff75b6ce3655ef04f4625ec01/rust-toolchain.toml)
and [Zig 0.16.0](https://github.com/herdrdev/herdr/blob/2ecf19a92fc3a7fff75b6ce3655ef04f4625ec01/crates/ghostty-vt/build.rs)
remain upstream requirements. Both pins are unchanged. All five existing
patches apply sequentially without changes to their bytes or digests.

Private protocol 22, stable endpoint generation 1, and session snapshot format 3
remain unchanged. The API schema and snapshot definitions have no changes in
this range. These source facts do not certify mixed-version servers or downgrade
safety. The matching 0.9.5 runtime needs its own live checks.

The upstream Apache-2.0 LICENSE is unchanged. Neither revision has a root NOTICE.
No license, notice, or vendor metadata file changed. Existing custom notices
remain packaged.

## Baseline and verification design

The actual published `0.9.3-custom.6` macOS archive matched its checksum
`4145be9814004ece08edf99acb653f798bb09db7adbe1900ae02b6ffdc31021d`.
Its own launcher rejected plugin revision
`5ef7d5a69ccfc7552d3cc81a1a7cfb059cb256df` with exit 1 and the minimum-version
error recorded in the issue. The same revision declares plugin version 1.4.0
and minimum Herdr 0.9.5.

The selected design adds an independent archive inspector. Its trusted input is
the clean recipe commit, rather than provenance supplied by an archive. A shared
disposable environment helper owns HOME, configuration, cache, data, state,
temporary, and socket roots for real runtime checks. A separate smoke command
exercises the actual packaged runtime and exact plugin.

Two independent design candidates compared an integrated builder mode with a
standalone reader. The parent and cross-judge chose the standalone reader, 9/10
against 8/10, for the smaller read-only command and stronger cached-source
validation. The shared environment helper and executable architecture checks
were retained from the other candidate.

## Runtime and visual evidence

The initial [native build run](https://github.com/yersonargotev/herdr-custom/actions/runs/40822561211)
passed on macOS ARM64 and Linux AMD64 at recipe commit
`7cb24d879099b0947024b1a4522d0612306025a1`. The local macOS patched shell run
passed 385 tests with two upstream ignores. The integrated Python suite passed
19 tests. The final recipe also runs the real plugin smoke on both native CI
platforms before uploading release archives.

The independent inspector accepted both actual archives from that initial run
against its clean recipe commit. This was a tool validation, not publication of
those initial artifacts. Final tag builds identify the release commit separately.

The local preview runtime SHA-256 was
`4fe3fd331890eb33948f71c1fc1bc58b26cd5410376b8c461181e91ac20e6f1a`.
A second smoke used the actual initial macOS CI archive, whose runtime SHA-256 was
`4eb92b891ea2912f0f5f80b1f0c996b404e41f5e75d935f4a79477890a5a5b41`.
Both ran the exact plugin revision successfully. These are separate builds; no
byte-for-byte reproducibility claim is made.

The real plugin checks observed startup metadata in a restored disposable
session before an explicit refresh. They then paused publication with `clear`,
changed a tracked file, and resumed with `refresh`. A subsequent untracked file
changed polling metadata without another action or focus command. Both Space
token sets and both per-pane project values were checked at each stage. Actual
hook logs recorded the custom private `libexec/herdr` in `HERDR_BIN_PATH`, while
the test PATH contained no `herdr` executable. A transparent Node logger recorded
only selected routing fields and then executed real Node.js. No fake Herdr CLI
was used for runtime compatibility.

Live terminal checks ran on macOS ARM64 through isolated PTY processes. They
covered compact tabs and separators, dark and light themes, navigation and mouse
selection, sidebar drag and terminal resize, narrow alignment fallback, explicit
foreground overrides, Agent focus, status dots, and one-row entry gaps. Captures
retain raw ANSI and cell colors. PNGs render that actual terminal output; they
are not screenshots of Terminal.app. The host denied graphical Terminal control.
No graphical-terminal or Linux visual result is claimed.

After actual plugin startup, explicit refresh, and polling, the native Agent row
showed `packy-catalog › codex` with foreground `6c7086`. The Agent was introduced
through the real `pane report-agent` API. This proves native row rendering and
context preservation across plugin updates. It does not test Codex process
detection or persistence of report-agent authority. The fixture is restored after
server startup because report authority without a resume command is not saved.

Sequential custom and official clients attached to an official 0.9.5 server,
then to a custom 0.9.5 server, in separate disposable roots. Client detachment
preserved the server and each pane's shell PID. No simultaneous mixed-layout
clients or older-version server were used.

Selected captures, metadata, process identities, the rerunnable terminal
experiment, and the decision trail are retained under `docs/evidence/issue-4/`.
The final release workflow requires both native jobs, both real smoke tests,
and complete archive inspection before creating a draft. Publication requires
inspection of the downloaded draft artifacts as described in the README.

## Compatibility boundaries

Plugin subprocesses use the executable provided by the running server. A custom
client attached to an official server does not change that server's executable.
The bundled Agent rows retain the native muted `tab` token. Plugin `$project`
metadata does not replace that row.

Live checks use disposable roots and explicitly selected sockets. No operator
session or installed executable is upgraded. No dots pin is changed.

Version 0.9.5 changes managed plugin directories and persistence behavior.
Switching a client or a symlink does not downgrade a running server or persisted
state. Returning to 0.9.3 requires complete pre-upgrade configuration, registry,
managed-plugin, session, and history copies. That migration is an operator
procedure outside this issue's disposable tests.

## Decision trail

The run keeps an append-only decision log. Model the Domain selected one immutable
release identity. Foundational Thinking put verification before publication.
Sequence Work into Verifiable Units separated base preparation, native tests,
runtime checks, and archive inspection. Separate Before Serializing Shared State
gave each worker and test its own checkout or roots. Laziness Protocol retained
the exact patch series and rejected a general release framework. Prove It Works
requires actual metadata and terminal observations. Encode Lessons in Structure
turns integrity and isolation requirements into executable checks. Never Block on
the Human permits reversible work to proceed without repeated confirmation.
