"""
FinBERT sentiment scoring engine — lazy-loaded singleton.
Uses ProsusAI/finbert from HuggingFace.
"""
from typing import Any, Dict, List, Optional

_pipe = None  # type: Any


def _get_pipe():
    global _pipe
    if _pipe is None:
        print("[finbert] Loading ProsusAI/finbert model (first call)...")
        from transformers import pipeline as hf_pipeline
        _pipe = hf_pipeline(
            "sentiment-analysis",
            model="ProsusAI/finbert",
            truncation=True,
            max_length=512,
            top_k=None,  # return all three class probabilities
        )
        print("[finbert] Model loaded.")
    return _pipe


def score_texts(texts: List[str], batch_size: int = 16) -> List[Dict[str, Any]]:
    """
    Score a list of texts with FinBERT.
    Returns [{"sentiment_score": float (-1 to 1), "sentiment_label": str}, ...]
    Score = positive_prob - negative_prob (continuous, never exactly 0.0 unless tied).
    """
    if not texts:
        return []

    pipe = _get_pipe()
    results = []  # type: List[Dict[str, Any]]

    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        # Clean empty strings — FinBERT can't handle them
        batch = [t if t.strip() else "neutral" for t in batch]
        preds = pipe(batch)
        for pred_list in preds:
            # pred_list is a list of {"label": str, "score": float} for all 3 classes
            probs = {p["label"].lower(): float(p["score"]) for p in pred_list}
            pos = probs.get("positive", 0.0)
            neg = probs.get("negative", 0.0)
            score = round(pos - neg, 4)
            label = max(probs, key=lambda k: probs[k])
            results.append({
                "sentiment_score": score,
                "sentiment_label": label,
            })

    return results


def score_text(text: str) -> Dict[str, Any]:
    """Score a single text. Convenience wrapper."""
    return score_texts([text])[0]
