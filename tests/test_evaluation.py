from kedb.evaluation import recall_at_k, mrr

def test_metrics():
    assert recall_at_k('b',['a','b'],1)==0
    assert recall_at_k('b',['a','b'],2)==1
    assert mrr('b',['a','b'])==0.5
