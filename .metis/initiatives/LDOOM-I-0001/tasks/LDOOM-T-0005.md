---
id: browser-decision-panel-ui
level: task
title: "Browser decision panel UI"
short_code: "LDOOM-T-0005"
created_at: 2026-09-23T02:45:36.186167+00:00
updated_at: 2026-09-23T02:45:36.186167+00:00
parent: LDOOM-I-0001
blocked_by: []
archived: false

tags:
  - "#task"
  - "#phase/todo"


exit_criteria_met: false
initiative_id: LDOOM-I-0001
---

# Browser decision panel UI

## Parent Initiative

[[LDOOM-I-0001]]

## Objective **[REQUIRED]**

Make the model's reasoning legible. A video of Doom proves nothing; the frame *beside* the state
text, the chosen answer, its probability distribution and its latency is the demo.

## Acceptance Criteria **[REQUIRED]**

- [ ] FastAPI app serves a static page and a WebSocket stream (REQ-006).
- [ ] Doom frame rendered live as JPEG to a canvas.
- [ ] Panel shows the exact state text sent to the model that tick — verbatim, not a summary.
- [ ] Each answer shown with its full distribution as bars, not just the winning label (REQ-007).
- [ ] Low-confidence answers are visually distinct, so "the model does not know" reads as a
      first-class outcome rather than looking like a rendering glitch.
- [ ] Rolling latency readout: p50, p95, last — labelled as measured client-side wall clock.
- [ ] Start / pause / restart controls; restart bumps the generation counter.
- [ ] Episode score and baseline comparison visible (NFR-004).
- [ ] Works at laptop width; no build step, no framework, no CDN.

## Implementation Notes **[CONDITIONAL: Technical Task]**

### Technical Approach
Vanilla ES modules and plain CSS, same as the pong demo. A build toolchain for one page would be
overhead with no payoff.

JPEG over WebSocket at 320x240: at 10 Hz that is trivial bandwidth over loopback. Send the frame
and the decision record in the same message so the panel can never show a decision next to a
frame it did not come from — off-by-one-frame skew would make every screenshot subtly wrong.

Dark palette. It is Doom.

### Dependencies
[[LDOOM-T-0004]] — the loop must run headless first.

### Risk Considerations
The loop is synchronous while FastAPI is async. Run the loop in a worker thread and hand records
to the event loop via a queue, dropping frames rather than blocking the game if the browser
cannot keep up. The game clock must never wait on the UI.

## Status Updates **[REQUIRED]**

*To be added during implementation*
