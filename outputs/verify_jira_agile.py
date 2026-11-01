import json,logging,httpx
from pathlib import Path
from dotenv import dotenv_values
logging.getLogger('dotenv.main').setLevel(logging.ERROR)
e=dotenv_values('.env');c=httpx.Client(base_url=e['JIRA_BASE_URL'].rstrip('/'),auth=(e['JIRA_EMAIL'],e['JIRA_API_TOKEN']),timeout=60)
s=json.loads(Path('outputs/jira_agile_import_20261028.json').read_text(encoding='utf-8'))
def search(jql):
 body={'jql':jql,'maxResults':100,'fields':['summary','description','labels','status']}; rows=[]
 while True:
  r=c.post('/rest/api/3/search/jql',json=body);r.raise_for_status();d=r.json();rows+=d['issues']
  if not d.get('nextPageToken'):return rows
  body['nextPageToken']=d['nextPageToken']
rows=search('project = PROBLEM AND labels = kedb-import-20261028');assert len(rows)==200,len(rows)
by_key={r['key']:r for r in rows}
for created,source in zip(s['created'],s['selected']):
 f=by_key[created['key']]['fields'];assert f['summary']==source['subject'][:255];assert 'source-'+source['ticket_id'] in f['labels']
 text='\n'.join(p['content'][0]['text'] for p in f['description']['content'])
 assert not source.get('description') or source['description'] in text
 assert not source.get('resolution') or source['resolution'] in text
 if source['status'].lower() in ('closed','resolved'):assert f['status']['statusCategory']['key']=='done'
r=c.get('/rest/api/3/filter/'+s['filter']['id']);r.raise_for_status();board_rows=search(r.json()['jql']);assert {x['key'] for x in board_rows}=={x['key'] for x in s['created'][:60]}
r=c.get('/rest/agile/1.0/board/'+str(s['board']['id'])+'/configuration');r.raise_for_status();config=r.json();assert config['name']=='Agile';assert str(config['filter']['id'])==s['filter']['id']
print(json.dumps({'verified_imported':len(rows),'verified_board_filter_count':len(board_rows),'board_id':s['board']['id'],'board_configuration':config,'first':s['created'][0]['key'],'last':s['created'][-1]['key']},indent=2))
s['verification']={'imported':len(rows),'board_filter_count':len(board_rows),'content_and_status_checked':True}
Path('outputs/jira_agile_import_20261028.json').write_text(json.dumps(s,ensure_ascii=False,indent=2),encoding='utf-8')
