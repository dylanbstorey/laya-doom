---
id: vizdoom-state-serializer
level: task
title: "ViZDoom state serializer"
short_code: "LDOOM-T-0002"
created_at: 2026-09-23T02:45:21.945688+00:00
updated_at: 2026-09-23T02:54:51.937212+00:00
parent: LDOOM-I-0001
blocked_by: []
archived: false

tags:
  - "#task"
  - "#phase/completed"


exit_criteria_met: false
initiative_id: LDOOM-I-0001
---

# ViZDoom state serializer

## Parent Initiative

[[LDOOM-I-0001]]

## Objective **[REQUIRED]**

Turn a ViZDoom `GameState` into the compact dict LAYA sees. This is the highest-leverage file in
the project: discovery showed the model's answer quality is dominated by state phrasing, not by
question wording.

## Acceptance Criteria

## Acceptance Criteria

## Acceptance Criteria **[REQUIRED]**

- [x] `serialize(state) -> dict` emits health, ammo, and an `observation` sentence.
- [x] The `DoomPlayer` self-label is excluded (REQ-002).
- [x] Enemy bearing is derived from label bbox centre vs screen centre, in words
      ("centred in your crosshair" / "slightly left" / "far left"), with raw pixel offset
      alongside.
- [x] Distance comes from world coordinates; absent or zero player position degrades gracefully.
- [x] Enemy list sorted nearest-first and capped (NFR-005); the cap is stated in the state text
      so the model is not misled about how many enemies exist.
- [x] `None` state (episode finished) is handled without raising.
- [x] Recorded `GameState` fixtures committed, with a test per fixture asserting bearing sign
      and enemy count.
- [x] Serialized output stays within the 1024-token context; a test asserts an upper bound.

## Test Cases **[CONDITIONAL: Testing Task]**

### Test Case 1: Bearing sign
- **Test ID**: TC-001
- **Preconditions**: fixture with one enemy whose bbox centre is left of screen centre.
- **Steps**: serialize; read `observation` and the numeric offset.
- **Expected Results**: the word "left" appears and the numeric offset is negative. Sign errors
  here invert aim and are invisible from gameplay alone, which is why this is pinned.

### Test Case 2: Self-label excluded
- **Test ID**: TC-002
- **Preconditions**: any fixture — `DoomPlayer` is always present.
- **Steps**: serialize; inspect the enemy list.
- **Expected Results**: no entry named `DoomPlayer`; count matches visible enemies only.

## Implementation Notes **[CONDITIONAL: Technical Task]**

### Technical Approach
Follow the pong demo's idiom exactly: a natural-language `observation` field carrying the spatial
relation, with structured numbers beside it. The probe result is the evidence — given
"bearing +6 degrees right", the `turn` question came back near-uniform at **confidence 0.0115**.
Degrees are meaningless to this model; "slightly left of your crosshair" is not.

Screen-space bearing over world-space (the design's reasoning): bbox centre already folds in FOV
and player angle, and `POSITION_X/Y`/`ANGLE` all read 0.0 in the `defend_the_center` probe.

### Dependencies
[[LDOOM-T-0001]] for the venv. Fixture capture needs no model.

### Risk Considerations
Enemy `object_name` values are Doom internals (`MarineChainsawVzd` observed). Map them to plain
words — "a marine" — because the checkpoint was trained on support tickets and invoices, and
engine identifiers are out-of-distribution noise.

## Status Updates **[REQUIRED]**

### 2026-09-22 — complete

`src/laya_doom/state.py` (~305 lines), `bench/capture.py`, `tests/test_state.py`.
**70 tests passing** across client + state.

Captured fixtures from four scenarios (`defend_the_center`, `deadly_corridor`, `defend_the_line`,
`deathmatch`) via `bench/capture.py`, which also reports the distance distribution so the
phrasing bands are calibrated against real data rather than guessed.

**Finding — the label buffer is not an enemy list.** Captured object names included `Blood`,
`BulletPuff`, `TeleportFog`, `Medikit`, `Clip`, `GreenArmor`, `ArmorBonus`, `Shotgun`,
`DeadZombieman`, `DeadShotgunGuy` and `DoomImpBall` alongside the actual monsters. REQ-002 only
asked for the `DoomPlayer` self-label to be excluded, which would not have been enough:

- `Blood` and `BulletPuff` are produced *by shooting*, so counting them as enemies creates a
  feedback loop where firing manufactures new targets.
- `Dead*` corpses are scenery; aiming at them wastes the decision entirely.

Resolved with a monster **allowlist** (plus a `Marine*` prefix rule for ViZDoom's custom actors)
rather than a denylist, so an unrecognised label can never become a phantom enemy. Unknown
monsters degrade to "an enemy" instead of leaking an engine identifier into the prompt.

**Finding — nearest enemy and crosshair target diverge.** A real `defend_the_center` tick has the
closest demon far to the left while a marine further away sits dead centre. The first narration
said "not lined up" while also reporting a centred enemy — self-contradictory, and it would have
poisoned the `fire` question. Split into `Observation.nearest` (drives aiming) and
`Observation.crosshair_target` (drives firing), with `an_enemy_is_lined_up_with_your_crosshair`
surfaced as its own state field.

**Decisions:**

- **Crosshair alignment is bounding-box containment**, not an angle threshold: the crosshair is
  lined up exactly when screen-centre x falls inside the enemy's label box. For hitscan weapons
  this is geometrically exact, and it needs no FOV arithmetic.
- **Bearing comes from screen space**, as designed — `offset_fraction` is normalised by
  half-screen-width, so a 640-wide screen reads the same as a 320-wide one (pinned by test).
- Distance bands (150 / 350 / 650 world units) calibrated from captured quantiles:
  `defend_the_center` sightings span 24-812 with p50 672; `deadly_corridor` reaches 1328.
- Engine names mapped to plain words (`MarineChainsawVzd` -> "a marine"), since the checkpoint
  was trained on support tickets and invoices.

**Serialized size:** 128 chars minimum, ~400 median, 546 maximum. Comfortably inside the
1024-token context (NFR-005), with a test asserting an upper bound of 1200 chars per tick.