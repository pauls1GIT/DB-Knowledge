"""Article-level duplicate scoring; search scores never enter this calculation."""
import numpy as np


def article_text(article: dict) -> str:
    return "\n\n".join(
        f"{label}: {' '.join(str(article.get(key) or '').split())}"
        for label, key in (("Problem", "problem"), ("Root cause", "root_cause"),
                           ("Resolution", "solution"))
    )


def validate_vector(vector):
    result = np.asarray(vector, dtype=float)
    if (result.ndim != 1 or not result.size or not np.isfinite(result).all()
            or not np.isfinite(np.linalg.norm(result)) or np.linalg.norm(result) == 0):
        raise ValueError("Embedding must be a finite, nonzero vector")
    return result


def cosine_similarity(left, right) -> float:
    left, right = validate_vector(left), validate_vector(right)
    if left.shape != right.shape:
        raise ValueError("Embedding dimensions differ; check the embedding model version")
    return float(np.clip(np.dot(left / np.linalg.norm(left), right / np.linalg.norm(right)), -1, 1))
