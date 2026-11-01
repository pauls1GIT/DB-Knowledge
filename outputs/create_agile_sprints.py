import json,logging,httpx
from pathlib import Path
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
from dotenv import dotenv_values
logging.getLogger('dotenv.main').setLevel(logging.ERROR)
e=dotenv_values('.env');c=httpx.Client(base_url=e['JIRA_BASE_URL'].rstrip('/'),auth=(e['JIRA_EMAIL'],e['JIRA_API_TOKEN']),timeout=60)
def call(method,path,**kw):
 r=c.request(method,path,**kw)
 if r.is_error:raise RuntimeError(f'{method} {path} {r.status_code} {r.text[:1800]}')
 return r.json() if r.content else None
p=Path('outputs/jira_agile_sprints.json');s=json.loads(p.read_text()) if p.exists() else {'sprints':[]}
def save():p.write_text(json.dumps(s,indent=2),encoding='utf-8')
epics=json.loads(Path('outputs/jira_agile_epics.json').read_text())['epics']
now=datetime.now(ZoneInfo('Europe/Bucharest'));start=now.replace(year=2026,month=10,day=28);end=start+timedelta(days=14)
for i,epic in enumerate(epics):
 if len(s['sprints'])>i:continue
 data={'name':'Agile - '+epic['name'],'goal':'Track and complete work for '+epic['key']+' ('+epic['name']+').','startDate':start.isoformat(),'endDate':end.isoformat()}
 if i==0: sprint=call('POST','/rest/agile/1.0/sprint/1',json=data)
 else:sprint=call('POST','/rest/agile/1.0/sprint',json={**data,'originBoardId':69})
 s['sprints'].append({'id':sprint['id'],'name':data['name'],'issues':epic['children']});save()
for sprint in s['sprints']:
 call('POST',f"/rest/agile/1.0/sprint/{sprint['id']}/issue",json={'issues':sprint['issues']});print('Assigned',sprint['name'],len(sprint['issues']),flush=True)
for sprint in s['sprints']:
 current=call('GET',f"/rest/agile/1.0/sprint/{sprint['id']}")
 if current['state']!='active':current=call('POST',f"/rest/agile/1.0/sprint/{sprint['id']}",json={'state':'active'})
 sprint['state']=current['state'];save();print('Started',sprint['id'],flush=True)
for sprint in s['sprints']:
 actual=call('GET',f"/rest/software/1.0/sprint/{sprint['id']}/issue",params={'maxResults':100,'fields':'status'})
 assert actual['isLast'];assert {x['key'] for x in actual['issues']}==set(sprint['issues'])
 assert call('GET',f"/rest/agile/1.0/sprint/{sprint['id']}")['state']=='active'
s['verified']=True;save();print('VERIFIED 60 tickets in 3 active sprints')
