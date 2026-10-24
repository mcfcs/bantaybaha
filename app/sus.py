"""System Usability Scale (Brooke, 1996) for the dashboard's user test: items, scoring and anonymous storage.

No names or identifiers are collected: only a role, the ten 1-5 answers, the task outcome and a UTC timestamp.
Responses go to data/processed/sus/sus_responses.csv (git-ignored); set BANTAY_SUS_PATH to write elsewhere (tests do).
"""

import csv
import os
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PATH = ROOT / "data" / "processed" / "sus" / "sus_responses.csv"

# the ten standard SUS statements, in order (odd items positive, even items negative)
ITEMS = [
    "I think that I would like to use this system frequently.",
    "I found the system unnecessarily complex.",
    "I thought the system was easy to use.",
    "I think that I would need the support of a technical person to be able to use this system.",
    "I found the various functions in this system were well integrated.",
    "I thought there was too much inconsistency in this system.",
    "I would imagine that most people would learn to use this system very quickly.",
    "I found the system very cumbersome to use.",
    "I felt very confident using the system.",
    "I needed to learn a lot of things before I could get going with this system.",
]
SCALE = {1: "Strongly disagree", 2: "Disagree", 3: "Neutral", 4: "Agree", 5: "Strongly agree"}
ROLES = ["DOH regional office", "LGU health office", "DRRM office", "Other"]
TASK_OUTCOMES = ["Completed", "Partly completed", "Not completed"]
FIELDS = ["submitted_utc", "role", *[f"q{i}" for i in range(1, 11)], "sus", "task_outcome", "task_minutes"]


def path():
    p = os.environ.get("BANTAY_SUS_PATH")
    return Path(p) if p else DEFAULT_PATH


def score(answers):
    """SUS score 0-100 from ten answers on 1-5: odd items contribute (x - 1), even items (5 - x), sum x 2.5."""
    a = list(answers)
    if len(a) != 10 or any(x not in SCALE for x in a):
        raise ValueError("SUS needs ten answers, each 1-5")
    return 2.5 * sum((x - 1) if i % 2 == 0 else (5 - x) for i, x in enumerate(a))


def save(role, answers, task_outcome, task_minutes, p=None):
    """Append one anonymous response; returns its SUS score."""
    if role not in ROLES:
        raise ValueError(f"role must be one of {ROLES}")
    if task_outcome not in TASK_OUTCOMES:
        raise ValueError(f"task outcome must be one of {TASK_OUTCOMES}")
    s = score(answers)
    p = Path(p) if p else path()
    p.parent.mkdir(parents=True, exist_ok=True)
    new = not p.exists() or p.stat().st_size == 0
    row = dict(submitted_utc=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M"), role=role,
               **{f"q{i}": int(x) for i, x in enumerate(answers, 1)}, sus=s, task_outcome=task_outcome,
               task_minutes="" if task_minutes is None else int(task_minutes))
    with p.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        w.writerow(row)
    return s


def load(p=None):
    import pandas as pd

    p = Path(p) if p else path()
    if not p.exists() or p.stat().st_size == 0:
        return pd.DataFrame(columns=FIELDS)
    return pd.read_csv(p)
