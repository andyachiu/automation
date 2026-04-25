# automation — repo instructions

## README maintenance (required)

Any non-trivial change to this repo must be reflected in `README.md` before the work is considered done:

- **Latest Updates** section — prepend a one-line bullet for the change (PR # or short SHA, then a terse description). Trim entries older than the most recent ~5.
- **TODO / Ideas** section — if the change implements (fully or partially) an item there, check it off or remove it. If the work surfaced a new follow-up, add it.
- **What's Here** / **Scheduling** table — update if a user-visible feature, agent, or schedule changed.

Skip the README update only for: pure formatting, typo fixes, or changes confined to `BUG_REPORT.md` / internal notes. When in doubt, update it.

Stage the README edit in the same commit as the code change — not a follow-up commit.

## Fail loud

launchd-driven briefs must exit non-zero on permission, auth, or delivery failures — never swallow them into a "succeeded but empty" run. Silent failures are the failure mode PRs #7/#8 were specifically built to prevent. If you add a new failure path, surface it (raise / non-zero exit / loud log) rather than fall back.

## Don't hand-edit plists

`plists/*.plist` and `~/Library/LaunchAgents/com.andychiu.automation.*.plist` are rendered by `scripts/install_launch_agents.py`. Change the renderer, re-run `uv run install_launch_agents.py`, then `launchctl unload` + `load` the affected agent. Hand-edits will be clobbered on the next install.
