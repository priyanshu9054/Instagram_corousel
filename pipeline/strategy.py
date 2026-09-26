import json
import random
from datetime import datetime, timezone

from pipeline.paths import STATIC_ASSETS_DIR, STATE_DIR

STRATEGY_FILE = STATE_DIR / "strategy.json"
QUOTES_FILE = STATIC_ASSETS_DIR / "quotes.json"

# Guardrails so one lucky/unlucky post can't swing the strategy — nudges are gradual
# and every option keeps a floor probability so nothing is ever fully abandoned.
MIN_SAMPLES_TO_ADJUST = 3
LEARNING_RATE = 0.25
MIN_WEIGHT = 0.25
MAX_WEIGHT = 3.0


def _all_authors() -> list[str]:
    quotes = json.loads(QUOTES_FILE.read_text(encoding="utf-8"))
    return sorted({q["author"] for q in quotes})


def _default_strategy() -> dict:
    authors = _all_authors()
    return {
        "author_weights": {a: 1.0 for a in authors},
        "content_type_weights": {"reel": 0.7, "carousel": 0.3},
        "created_at": datetime.now(timezone.utc).isoformat(),
        "last_adjusted_at": None,
        "history": [],
    }


def load_strategy() -> dict:
    if not STRATEGY_FILE.exists():
        strategy = _default_strategy()
        save_strategy(strategy)
        return strategy
    strategy = json.loads(STRATEGY_FILE.read_text(encoding="utf-8"))
    # Pick up any authors added to quotes.json since the strategy file was created.
    for a in _all_authors():
        strategy.setdefault("author_weights", {}).setdefault(a, 1.0)
    return strategy


def save_strategy(strategy: dict) -> None:
    STRATEGY_FILE.write_text(json.dumps(strategy, indent=2), encoding="utf-8")


def _weighted_choice(weights: dict[str, float]) -> str:
    keys = list(weights.keys())
    values = [max(0.01, w) for w in weights.values()]
    return random.choices(keys, weights=values, k=1)[0]


def choose_author(strategy: dict | None = None) -> str:
    strategy = strategy or load_strategy()
    return _weighted_choice(strategy["author_weights"])


def choose_content_type(strategy: dict | None = None) -> str:
    strategy = strategy or load_strategy()
    return _weighted_choice(strategy["content_type_weights"])


def _nudge(weights: dict[str, float], scores: dict[str, float], counts: dict[str, int]) -> list[str]:
    """
    Multiplicative weight update: groups that score above the overall average get a
    small boost, groups below average get a small cut. Groups without enough samples
    yet are left untouched. Weights are clipped and renormalized to keep the average
    around 1.0 so the whole distribution doesn't drift to extremes over time.
    """
    eligible = {k: v for k, v in scores.items() if counts.get(k, 0) >= MIN_SAMPLES_TO_ADJUST}
    changes = []
    if len(eligible) < 2:
        return changes  # not enough distinct, sampled groups to compare yet

    overall_avg = sum(eligible.values()) / len(eligible)
    if overall_avg <= 0:
        return changes

    for key, score in eligible.items():
        if key not in weights:
            continue
        old = weights[key]
        relative = (score - overall_avg) / overall_avg
        new = old * (1 + LEARNING_RATE * relative)
        new = max(MIN_WEIGHT, min(MAX_WEIGHT, new))
        if abs(new - old) > 0.01:
            weights[key] = round(new, 3)
            changes.append(f"{key}: {old:.2f} -> {new:.2f} (n={counts[key]}, score={score:.2f} vs avg={overall_avg:.2f})")

    return changes


def adjust_from_report(report: dict) -> dict:
    """Update author_weights and content_type_weights based on an analytics report."""
    strategy = load_strategy()
    changes = []

    changes += _nudge(
        strategy["author_weights"],
        {a: s["avg_engagement"] for a, s in report.get("by_author", {}).items()},
        {a: s["count"] for a, s in report.get("by_author", {}).items()},
    )
    changes += _nudge(
        strategy["content_type_weights"],
        {t: s["avg_engagement"] for t, s in report.get("by_content_type", {}).items()},
        {t: s["count"] for t, s in report.get("by_content_type", {}).items()},
    )

    strategy["last_adjusted_at"] = datetime.now(timezone.utc).isoformat()
    if changes:
        strategy["history"].append({
            "at": strategy["last_adjusted_at"],
            "changes": changes,
        })
    save_strategy(strategy)
    return strategy
