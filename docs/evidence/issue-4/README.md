# Issue 4 evidence

`terminal-report.md` describes the measured macOS ARM64 run. Selected PNGs are
rendered captures of real PTY output. They are not native Terminal.app screenshots.
The native Agent fixture uses the real reporting API, not a running coding agent.

`terminal-captures.tar.gz` contains the `cli-rerun/` paths referenced by that
report, including raw ANSI, compressed cell JSON, config variants, metadata,
process identities, and captures. Extract it in a disposable directory to follow
those references. `selected-captures/` exposes the main visual cases directly.

`check_terminal.py` reruns the terminal experiment on macOS with Python, pyte,
and Pillow. Pass an actual extracted custom release, a verified official0.9.5
binary, and an empty owned output directory. It creates and stops only disposable
servers. The public `scripts/smoke.py` covers automated real-plugin checks on
both native CI platforms.

`initial-ci-runtime/` records the parent run against the actual initial macOS CI
archive. `initial-ci-archive-inspection.json` records inspection of both initial
archives. Their recipe commit is explicit. These files do not claim to identify
the final published assets. Final tag builds and release inspection establish
those identities separately.

`decisions.tsv` is the append-only decision trail. The first timestamp was a
placeholder; the following correction records that limitation.
