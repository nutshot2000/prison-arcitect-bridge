# Working on PA-Agent

Read README.md, docs/project-specification.md and docs/validation.md first.

- The live bridge (native/, mod/ai_bridge, src/pa_agent/bridge) is now the primary way to play; see CLAUDE.md. The screen controller is a fallback.
- Do not claim a feature works in-game solely because its unit tests pass.
- Do not distribute extracted Prison Architect data/scripts, saves, executables or local screenshots.
- Keep input dry-run by default, process-path allowlisting, bounded actions, focus checks and cleanup.
- Preserve separate dispatch/evidence/semantic outcomes. Never equate pixel changes with construction success.
- Keep model-specific code and strategy out of the controller.
- Use current library documentation. Verify new game API calls live (scripts/explore_api.py, pa_lua) before relying on them.
- Record live tests and remaining limitations in docs/validation.md.
