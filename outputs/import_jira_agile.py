import json,logging,httpx
from pathlib import Path
from dotenv import dotenv_values
logging.getLogger('dotenv.main').setLevel(logging.ERROR)
e=dotenv_values('.env'); c=httpx.Client(base_url=e['JIRA_BASE_URL'].rstrip('/'),auth=(e['JIRA_EMAIL'],e['JIRA_API_TOKEN']),timeout=90)
p=Path('outputs/jira_agile_import_20261028.json')
def call(method,path,**kwargs):
 r=c.request(method,path,**kwargs)
 if r.is_error: raise RuntimeError(f'{method} {path}: {r.status_code} {r.text[:1500]}')
 return r.json() if r.content else {}
def save(): p.write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf-8')
def adf(lines): return {'type':'doc','version':1,'content':[{'type':'paragraph','content':[{'type':'text','text':str(t)}]} for t in lines if t]}
if p.exists(): state=json.loads(p.read_text(encoding='utf-8'))
else:
 existing=json.loads(Path('outputs/jira_existing_before_agile.json').read_text(encoding='utf-8'))
 used={x['source_ticket_id'] for x in json.loads(Path('data/jira_problem_import_manifest.json').read_text())}
 used.update(label[7:] for x in existing for label in x['fields']['labels'] if label.startswith('source-'))
 rows=json.loads(Path('data/tickets_clean.json').read_text(encoding='utf-8')); selected=[]
 for row in rows:
  if row['ticket_id'] not in used: selected.append(row); used.add(row['ticket_id'])
  if len(selected)==200: break
 assert len(selected)==200
 state={'source':'data/tickets_clean.json','selected':selected,'created':[]};save()
 print('Selected',selected[0]['ticket_id'],selected[-1]['ticket_id'],flush=True)
# Each bulk result is checkpointed; unexpected partial failure stops without retries.
while len(state['created'])<200:
 start=len(state['created']); chunk=state['selected'][start:start+50]; updates=[]
 for i,row in enumerate(chunk,start):
  lines=[row.get('description'), 'Resolution:',row.get('resolution'),'Original ticket metadata:']+[f'{k}: {v}' for k,v in row.items() if k not in ('subject','description','resolution')]
  fields={'project':{'key':'PROBLEM'},'issuetype':{'id':'10046'},'summary':row['subject'][:255],'description':adf(lines),'priority':{'id':{'Critical':'1','High':'2','Medium':'3','Low':'4'}.get(row.get('priority'),'3')},'labels':['kedb-json-import','source-'+row['ticket_id'],'kedb-import-20261028']}
  if i<60: fields['labels'].append('kedb-agile-20261028')
  updates.append({'fields':fields})
 result=call('POST','/rest/api/3/issue/bulk',json={'issueUpdates':updates})
 state.setdefault('bulk_results',[]).append(result);save()
 assert not result.get('errors'),result
 assert len(result['issues'])==len(chunk)
 for row,issue in zip(chunk,result['issues']): state['created'].append({**issue,'source_ticket_id':row['ticket_id'],'source_status':row['status']})
 save();print('Created',len(state['created']),flush=True)
if 'filter' not in state:
 keys=[x['key'] for x in state['created'][:60]]
 state['filter']=call('POST','/rest/api/3/filter',json={'name':'Agile - JSON import 2026-10-28','jql':'project = PROBLEM AND key in ('+','.join(keys)+') ORDER BY Rank ASC','description':'Exactly 60 tickets from the 200-ticket JSON import.','sharePermissions':[{'type':'project','project':{'id':'10034'}}]});save()
if 'board' not in state:
 state['board']=call('POST','/rest/agile/1.0/board',json={'name':'Agile','type':'kanban','filterId':int(state['filter']['id']),'location':{'type':'project','projectKeyOrId':'PROBLEM'}});save();print('Board',state['board']['id'],flush=True)
for i,issue in enumerate(state['created']):
 if issue.get('status_preserved'):continue
 status=issue['source_status'].lower()
 transition='41' if status in ('resolved','closed') else '31' if status in ('in progress','pending') else None
 if transition: call('POST','/rest/api/3/issue/'+issue['key']+'/transitions',json={'transition':{'id':transition}})
 issue['status_preserved']=True;save()
 if (i+1)%25==0:print('Statuses preserved',i+1,flush=True)
print('COMPLETE',state['created'][0]['key'],state['created'][-1]['key'],'board',state['board']['id'],flush=True)
