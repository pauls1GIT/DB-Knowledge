from kedb.evaluation.metrics import recall_at_k, mean_reciprocal_rank, precision_recall_f1

def test_recall_at_k(): assert recall_at_k("a",["x","a"],2)==1.0
def test_mrr(): assert mean_reciprocal_rank(["a"],[["x","a"]])==0.5
def test_prf():
 r=precision_recall_f1({"problem","solution"},{"problem","solution"}); assert r["f1"]==1.0
