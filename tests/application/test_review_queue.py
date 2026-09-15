from uuid import uuid4
from kedb.application.use_cases.review_queue import ReviewQueue

class Repo:
    def __init__(self):
        self.items={}
        self.by_workflow={}
    def get_import_item(self,batch_id,item_id): return self.items.get(item_id)
    def update_import_item(self,item_id,**kwargs): self.items[item_id].update(kwargs)
    def update_import_item_by_workflow(self,workflow_id,*,status): self.by_workflow[workflow_id]=status

class Graph: pass

def test_skip_marks_item_skipped():
    repo=Repo(); batch=uuid4(); item=uuid4()
    repo.items[item]={"id":str(item),"batch_id":str(batch),"status":"PENDING"}
    out=ReviewQueue(repo,Graph()).skip_item(batch,item)
    assert out["status"]=="SKIPPED"
    assert repo.items[item]["status"]=="SKIPPED"

def test_reject_result_marks_item_rejected():
    repo=Repo(); q=ReviewQueue(repo,Graph()); wf=uuid4()
    q.sync_review_result(wf,{"review":{"decision":"REJECT"}})
    assert repo.by_workflow[wf]=="REJECTED"

def test_approve_result_marks_item_published():
    repo=Repo(); q=ReviewQueue(repo,Graph()); wf=uuid4()
    q.sync_review_result(wf,{"review":{"decision":"APPROVE"},"publication_result":{"id":"x"}})
    assert repo.by_workflow[wf]=="PUBLISHED"

def test_modify_interrupt_stays_in_review():
    repo=Repo(); q=ReviewQueue(repo,Graph()); wf=uuid4()
    q.sync_review_result(wf,{"__interrupt__":[{}],"review":{"decision":"MODIFY"}})
    assert repo.by_workflow[wf]=="AWAITING_REVIEW"
