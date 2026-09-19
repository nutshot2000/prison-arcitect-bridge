# Prison Architect AI Agent Bridge — revised implementation specification

Revision: 19 September 2026. This supersedes implementation assumptions in the supplied proposal while retaining its model-independent, human-style gameplay goal. The original is preserved as `original-proposal.md`.

## Feasibility verdict

**A screenshot-and-input bridge is feasible on this installation. Autonomous full-prison management remains a research goal, not an established capability.** The difficult work is observation quality, calibration, asynchronous construction verification and recovery. MCP is an adapter to that work, not the mechanism that makes it reliable.

The installed assets and saves provide useful research material. They do not provide the engine's C++ source. Review packaged scripts/data locally; keep proprietary game files out of the open-source repository. Do not require reverse engineering the executable.

## Changes to the original proposal

| Original assumption | Revised decision |
| --- | --- |
| Lua writes `telemetry.json` atomically | Treat filesystem, sockets, logging and camera access as unverified capabilities. Probe a normal object mod before designing IPC. If unavailable, continue with screenshots and save snapshots. |
| Lua is a prerequisite before MCP | Lua is optional and may be added in v0.2. A proven screenshot/input core can receive MCP without it. |
| Visual change means action success | Return separate dispatch, visual evidence and semantic outcome. Animating prisoners can change pixels after a failed click; a successful action may have delayed or tiny visual effects. |
| Clamp invalid points into bounds | Reject them. Clamping can hit a real but unintended toolbar button. |
| Latest save equals current game | Explicitly bind a save to an episode and record its mtime, read time, checksum and in-game timestamp. File recency alone does not identify the loaded prison. |
| Persist a camera profile by resolution/zoom | Profiles are priors. Each usable transform needs current landmarks, residual error, validity bounds and a camera generation ID. Pan, zoom, load and resize invalidate it. |
| Pause/resume tools can press Space | Space is a toggle. Idempotent pause/resume requires observed state; otherwise expose a plainly named toggle. |
| Strict focus checks guarantee exclusive targeting | Windows SendInput is global. Revalidation and short actions reduce, but do not eliminate, the focus-change race. Use a dedicated desktop/session for unattended operation. |
| Large pre-created module tree | Create working modules as their milestones arrive. Do not expose empty tools or claim future integrations exist. |

## Core contract

The controller owns detection, capture, bounded input, evidence and mechanical recovery. It makes no gameplay decisions. Model/provider code and benchmark scoring remain separate. Preserve raw mouse and keyboard tools; never add tools that solve a prison-design problem for the model.

Every action should ultimately accept an observation/frame ID and camera generation where relevant. Reject stale observations after geometry/camera changes. Serialize all live input. Include action ID, requested operation, dispatch status, evidence frames, timings and semantic outcome (`verified`, `failed`, `unknown`). In the current prototype semantic outcome is always unknown and screenshot review is manual.

Keep initial transport local stdio; no unauthenticated network input server. A future MCP adapter returns image content as well as metadata, not just paths a remote model cannot read. Bound payload sizes, action durations and operation counts. Retrying clicks, drags or save operations is not inherently safe; observe before retrying.

## Coordinate contract

- Desktop: physical virtual-desktop pixels; may be negative on secondary monitors.
- Client: physical pixels from the client area's top-left; excludes borders and title bar.
- Screenshot region: a client-space rectangle with its original offset retained.
- Model image: if resized for transport, carry scale/offset and map points back explicitly.
- World: define tile-centre versus tile-edge coordinates during milestone 4; do not assume they coincide.

World input stays unavailable unless the transform has a bounded measured error and the requested point lies inside a validated, visible map region. A successful screen change near a point is evidence, not proof of correct tile placement.

## Revised milestones and acceptance gates

1. **Foundation:** installable package, strict TOML configuration, structured logs, CLI and automated tests.
2. **Observation:** identify exact process/window, DPI-aware client rectangle, real screenshot and cropped screenshot; reject absent/minimized/background/off-screen windows. Visually inspect captures.
3. **Input:** bounded raw controls, dry-run, foreground/owner checks, emergency-stop latch, per-action cleanup, single controller. Verify an innocuous menu round trip in the game; test failure paths.
4. **Calibration:** establish tile-centre landmarks at one camera setting; measure error; invalidate on pan/zoom/load/resize. Repeat at different zooms before accepting generalized conversion.
5. **Action verification:** distinguish tool selected, build order queued, construction underway and finished. Start with a few measured UI anchors. Use explicit wait budgets and unknown outcomes.
6. **Read-only save state:** parse nested `BEGIN`/`END`, repeated keys, inline sections and unknown fields. Never write saves to play. Stable-read checks must detect files changing during reads. Do not convert unknown values to zero.
7. **Unified observations and MCP:** expose a small schema-validated toolset over the proven core. Enforce mode permissions in the controller, not only by hiding tools. Attach source and freshness to every state field.
8. **Optional Lua capability experiment:** normal object context, harmless read-only probes, bounded output and measured overhead. Test whatever IPC is actually available. This may be deferred without blocking the core.
9. **First agent demo:** known practice save; model chooses foundation location, builds, adds entrance, designates a room, places objects and verifies completion. No scripted layout solution.
10. **Long sessions:** stale observations, overlays, agent timeouts, focus loss, recovery, retention quotas and watchdog behavior.
11. **Benchmark:** independent scenario reset/evaluator, repeatable configuration, immutable save hashes, trial repetitions and confidence intervals. No leaderboard until ordinary gameplay is reliable.
12. **Release:** install on a second machine, document tested clients, package only original bridge code, reproduce the demo from a fresh setup.

Milestones 1–3 are the scope of this first implementation. No benchmark, model integrations, high-level gameplay helpers or telemetry mod are required here.

## Lua feasibility spike

Do not infer normal-mod capabilities from campaign `Game.*` scripts. Inventory the actual object environment separately. Probe availability of object properties, nearby-object queries, timing, camera information and output facilities. Do not call mutation functions merely to inspect state. Record available, unavailable and untested functions separately.

If direct file I/O is unavailable, investigate whether a tagged bounded debug-log line or save-persisted custom property is supported. Neither is guaranteed. A debug-log channel needs rotation/truncation handling and rate limits; save-derived telemetry is delayed. Do not bypass the mod sandbox to obtain a channel.

## Benchmark design corrections

Human mode exposes only visual observations and raw controls. Assisted mode adds measured coordinate/UI helpers. Agent mode adds structured state. Save access may reveal hidden information, so enforce those boundaries centrally. The evaluator may read privileged state without revealing it to the agent.

Record wall-clock time, simulation time, pauses, latency, action limits and model token/cost budgets. A model must not gain unlimited thought by pausing indefinitely. Same saves/seeds may still produce nondeterministic runs; repeat trials. Track metric definitions and availability rather than assuming every proposed metric exists.

Record raw outcomes and explicit failures separately from weighted scores. Observe construction completion and operational requirements, not just queued blueprints or room labels. Preserve concise model-provided rationale only, never private chain of thought.

## Version gates

**0.1:** all twelve original v0.1 criteria, including an MCP-driven in-game construction demonstration, must be evidenced. This `0.1.0a1` controller does not satisfy that gate.

**0.2:** robust calibration, UI/state queries, reliable room/object workflows, session notes and tested recovery; Lua only if capability-tested.

**1.0:** installable, demonstrated long-running management, tested supported clients, repeatable benchmark runner and evaluator, replay/evidence and public release. List client compatibility as tested or untested; MCP support alone does not prove compatibility with every client.
