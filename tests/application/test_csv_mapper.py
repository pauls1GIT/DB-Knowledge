from kedb.application.services.jira_csv_mapper import JiraCsvMapper


def test_maps_jira_export_fields():
    row={"Issue key":"ABC-1","Issue id":"10001","Summary":"Failure","Description":"broken","Resolution":"fixed",
         "Status":"Done","Priority":"High","Issue Type":"Task","Environment":"prod","Parent key":"ABC-0",
         "Resolved":"11/Sep/26 2:35 PM","Created":"10/Sep/26 1:00 PM","Updated":"11/Sep/26 2:35 PM"}
    issue=JiraCsvMapper().map(row)
    assert issue.external_key=="ABC-1"
    assert issue.external_id=="10001"
    assert issue.status=="Done"
    assert issue.resolution=="fixed"
    assert issue.raw_payload["Priority"]=="High"
