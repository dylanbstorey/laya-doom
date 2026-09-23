"""Distil LAYA's lockstep decisions into a small network.

Trained against the teacher's **probability distributions**, not its argmaxes:
a KL loss on the move head and a soft-target BCE on the trigger. On real harvested
data the argmax view says LAYA uses four of nine options while the probability
mass says `advance` carries 10%, `dodge` 13% and `retreat` 7% -- hard labels would
throw that away, and those are exactly the behaviours the policy is missing.

Held-out episodes are whole episodes, never sampled rows: consecutive ticks are
near-duplicates and a row split would report agreement with itself.

    uv run python bench/train_student.py --top-fraction 0.3
    uv run python bench/train_student.py --min-score 5 --epochs 400
"""

from __future__ import annotations

import argparse
import statistics
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from laya_doom.dataset import describe, load  # noqa: E402
from laya_doom.student import Student, new  # noqa: E402

DATA = Path(__file__).parent.parent / "data"
MODELS = Path(__file__).parent.parent / "models"


def to_torch(student: Student):
    import torch

    tensors = {}
    for name in ("w1", "b1", "w2", "b2", "w_fire", "b_fire", "w_move", "b_move"):
        tensor = torch.tensor(getattr(student, name), dtype=torch.float32, requires_grad=True)
        tensors[name] = tensor
    return tensors


def forward(tensors, x):
    import torch

    hidden = torch.tanh(x @ tensors["w1"] + tensors["b1"])
    hidden = torch.tanh(hidden @ tensors["w2"] + tensors["b2"])
    fire_logit = (hidden @ tensors["w_fire"] + tensors["b_fire"]).squeeze(-1)
    move_logits = hidden @ tensors["w_move"] + tensors["b_move"]
    return fire_logit, move_logits


def evaluate(student: Student, batch) -> dict:
    """How closely the student reproduces the teacher on unseen episodes."""
    fire, move = student.forward(batch.features)
    teacher_choice = batch.move.argmax(axis=1)
    student_choice = move.argmax(axis=1)
    agreement = float((teacher_choice == student_choice).mean())

    # Trigger agreement at the threshold the loop actually uses.
    fire_agreement = float(((fire >= 0.5) == (batch.fire >= 0.5)).mean())
    fire_error = float(np.abs(fire - batch.fire).mean())

    safe = np.clip(move, 1e-9, 1.0)
    kl = float((batch.move * (np.log(np.clip(batch.move, 1e-9, 1.0)) - np.log(safe))).sum(axis=1).mean())
    return {
        "move_agreement": agreement,
        "fire_agreement": fire_agreement,
        "fire_mean_abs_error": fire_error,
        "move_kl": kl,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data", type=Path, default=DATA / "deathmatch.jsonl")
    parser.add_argument("--out", type=Path, default=MODELS / "deathmatch_student.npz")
    parser.add_argument("--min-score", type=float)
    parser.add_argument("--top-fraction", type=float, default=0.3)
    parser.add_argument("--weight-by-score", action="store_true")
    parser.add_argument("--hidden", type=int, default=128)
    parser.add_argument("--epochs", type=int, default=300)
    parser.add_argument("--lr", type=float, default=3e-3)
    parser.add_argument("--holdout", type=float, default=0.25)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    import torch

    print("dataset:")
    summary = describe(args.data)
    print(f"  {summary['rows']} rows, {summary['episodes']} episodes, "
          f"scores {summary['worst']:+.0f}..{summary['best']:+.0f} (median {summary['median']:+.0f})")

    batch = load(
        args.data,
        min_score=args.min_score,
        top_fraction=None if args.min_score else args.top_fraction,
        weight_by_score=args.weight_by_score,
    )
    train, test = batch.split(holdout=args.holdout, seed=args.seed)
    kept = "min_score" if args.min_score else "top_fraction"
    print(f"  kept {len(batch)} rows by {kept}; "
          f"train {len(train)} / test {len(test)} (split by episode)")
    print(f"  move options: {batch.move_options}")

    student = new(batch.move_options, hidden=args.hidden, seed=args.seed)
    tensors = to_torch(student)
    optimiser = torch.optim.Adam(list(tensors.values()), lr=args.lr)

    x = torch.tensor(train.features)
    fire_target = torch.tensor(train.fire)
    move_target = torch.tensor(train.move)
    weights = torch.tensor(train.weights)

    for epoch in range(args.epochs):
        optimiser.zero_grad()
        fire_logit, move_logits = forward(tensors, x)
        # Soft-target BCE: the teacher's probability is the label, not a 0/1 flag.
        fire_loss = torch.nn.functional.binary_cross_entropy_with_logits(
            fire_logit, fire_target, reduction="none")
        # KL to the teacher's distribution, which is what carries the options the
        # argmax never shows.
        log_student = torch.log_softmax(move_logits, dim=-1)
        move_loss = -(move_target * log_student).sum(dim=-1)
        loss = ((fire_loss + move_loss) * weights).mean()
        loss.backward()
        optimiser.step()

        if epoch % max(1, args.epochs // 6) == 0 or epoch == args.epochs - 1:
            for name, tensor in tensors.items():
                setattr(student, name, tensor.detach().numpy())
            scores = evaluate(student, test)
            print(f"  epoch {epoch:4d} loss={loss.item():.4f} "
                  f"move_agree={scores['move_agreement']:.1%} "
                  f"fire_agree={scores['fire_agreement']:.1%} kl={scores['move_kl']:.4f}")

    for name, tensor in tensors.items():
        setattr(student, name, tensor.detach().numpy())

    on_train = evaluate(student, train)
    on_test = evaluate(student, test)
    print("\nheld-out episodes:")
    for key in ("move_agreement", "fire_agreement", "fire_mean_abs_error", "move_kl"):
        print(f"  {key:22s} train={on_train[key]:.4f}  test={on_test[key]:.4f}")

    # What the student would do, against what the teacher did.
    _, move = student.forward(test.features)
    print("\nmove marginals (teacher vs student, held-out):")
    for index, name in enumerate(batch.move_options):
        print(f"  {name:12s} teacher={test.move[:, index].mean():.3f}  student={move[:, index].mean():.3f}")

    student.metadata = {
        "rows": len(batch), "train": len(train), "test": len(test),
        "filter": kept, "min_score": args.min_score, "top_fraction": args.top_fraction,
        "test_move_agreement": on_test["move_agreement"],
        "test_fire_agreement": on_test["fire_agreement"],
        "episode_score_range": [float(batch.episode_scores.min()), float(batch.episode_scores.max())],
    }
    student.save(args.out)
    print(f"\nsaved {student.parameters:,} parameters -> {args.out}")


if __name__ == "__main__":
    main()
