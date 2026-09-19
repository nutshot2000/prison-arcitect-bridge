# Working on PA-Agent

Read README.md, docs/project-specification.md and docs/validation.md first.

- First delivered scope is milestones 1–3, a standalone Windows controller. Next is camera calibration, not a benchmark or dashboard.
- Do not claim a feature works in-game solely because its unit tests pass.
- Do not distribute extracted Prison Architect data/scripts, saves, executables or local screenshots.
- Keep input dry-run by default, process-path allowlisting, bounded actions, focus checks and cleanup.
- Preserve separate dispatch/evidence/semantic outcomes. Never equate pixel changes with construction success.
- Keep model-specific code and strategy out of the controller.
- Use current library documentation; do not assume Lua IPC or camera access works without a capability probe.
- Record live tests and remaining limitations in docs/validation.md.
