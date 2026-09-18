def recall_at_k(expected, retrieved, k=5): return 1.0 if expected in retrieved[:k] else 0.0
def mrr(expected, retrieved):
    try: return 1.0/(retrieved.index(expected)+1)
    except ValueError: return 0.0
