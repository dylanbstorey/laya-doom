# deathmatch prompt eval

`bench/prompts.py`, 4 episodes per variant, lockstep, seed 8200.
Bounded commitments are active: an aim holds 4 tics, a sweep 12, a weapon 20,
and only a more urgent action interrupts one.

| variant | mean score | sd | kills | p50 |
| --- | ---: | ---: | ---: | ---: |
| `move=strategy/weapon=blind` | **+5.75** | 3.40 | 2.2 | 197 ms |
| `move=strategy/weapon=inventory` | **+5.75** | 3.40 | 2.2 | 196 ms |
| `move=plain/weapon=blind` | **+5.25** | 2.87 | 2.2 | 185 ms |
| `move=plain/weapon=inventory` | **+5.25** | 2.87 | 2.2 | 185 ms |

## Answer distributions

- `move=strategy/weapon=blind`: {'weapon:pistol': 0.326, 'move:scan': 0.18, 'move:hold': 0.173, 'weapon:chaingun': 0.097, 'move:aim_left': 0.089, 'move:aim_right': 0.058, 'weapon:shotgun': 0.044, 'weapon:keep': 0.034}
- `move=strategy/weapon=inventory`: {'weapon:keep': 0.36, 'move:scan': 0.18, 'move:hold': 0.173, 'weapon:chaingun': 0.094, 'move:aim_left': 0.089, 'move:aim_right': 0.058, 'weapon:shotgun': 0.046}
- `move=plain/weapon=blind`: {'weapon:pistol': 0.388, 'move:scan': 0.194, 'move:hold': 0.155, 'move:aim_right': 0.076, 'move:aim_left': 0.068, 'weapon:shotgun': 0.048, 'weapon:keep': 0.033, 'weapon:chaingun': 0.03, 'move:advance': 0.008}
- `move=plain/weapon=inventory`: {'weapon:keep': 0.405, 'move:scan': 0.194, 'move:hold': 0.155, 'move:aim_right': 0.076, 'weapon:shotgun': 0.071, 'move:aim_left': 0.068, 'weapon:chaingun': 0.024, 'move:advance': 0.008}
