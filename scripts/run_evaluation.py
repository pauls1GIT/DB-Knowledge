"""Small deterministic retrieval-metric runner.
For a full benchmark, replace the example rows with synthetic ground-truth results from the seeded DB.
"""
from kedb.evaluation.metrics import recall_at_k, mean_reciprocal_rank

if __name__=="__main__":
    expected=["ke-1","ke-2","ke-3"]
    ranked=[["ke-1","ke-9"],["ke-8","ke-2"],["ke-7","ke-3"]]
    for k in (1,3,5):
        score=sum(recall_at_k(e,r,k) for e,r in zip(expected,ranked))/len(expected)
        print(f"Recall@{k}: {score:.3f}")
    print(f"MRR: {mean_reciprocal_rank(expected,ranked):.3f}")
