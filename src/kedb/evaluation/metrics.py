from __future__ import annotations


def recall_at_k(expected_id, ranked_ids, k: int) -> float:
    return 1.0 if expected_id in ranked_ids[:k] else 0.0


def mean_reciprocal_rank(expected_ids, ranked_lists) -> float:
    values=[]
    for expected, ranked in zip(expected_ids,ranked_lists):
        try: values.append(1.0/(ranked.index(expected)+1))
        except ValueError: values.append(0.0)
    return sum(values)/len(values) if values else 0.0


def precision_recall_f1(expected: set[str], predicted: set[str]):
    tp=len(expected & predicted); fp=len(predicted-expected); fn=len(expected-predicted)
    precision=tp/(tp+fp) if tp+fp else 0.0
    recall=tp/(tp+fn) if tp+fn else 0.0
    f1=2*precision*recall/(precision+recall) if precision+recall else 0.0
    return {"precision":precision,"recall":recall,"f1":f1}
