import logging,httpx,json
from pathlib import Path
from dotenv import dotenv_values
logging.getLogger('dotenv.main').setLevel(logging.ERROR)
e=dotenv_values('.env');c=httpx.Client(base_url=e['JIRA_BASE_URL'].rstrip('/'),auth=(e['JIRA_EMAIL'],e['JIRA_API_TOKEN']),timeout=60)
def call(method,path,**kw):
 r=c.request(method,path,**kw);r.raise_for_status();return r.json() if r.content else None
p=Path('outputs/jira_agile_epics.json')
def save():p.write_text(json.dumps(s,indent=2),encoding='utf-8')
m=json.loads(Path('outputs/jira_agile_import_20261028.json').read_text(encoding='utf-8'))
s=json.loads(p.read_text(encoding='utf-8')) if p.exists() else {'epics':[],'assigned':[]}
groups=[('Access & Security',{'Access/Permissions','Security'}),('Infrastructure & Data',{'Network','Cloud/Infrastructure','Database'}),('Workplace Technology',{'Hardware','Software','Email/Communication'})]
for name,cats in groups:
 if any(x['name']==name for x in s['epics']):continue
 children=[x['key'] for x,row in zip(m['created'][:60],m['selected'][:60]) if row['category'] in cats]
 epic=call('POST','/rest/api/3/issue',json={'fields':{'project':{'key':'PROBLEM'},'issuetype':{'id':'10000'},'summary':name,'labels':['kedb-agile-epic'],'description':{'type':'doc','version':1,'content':[{'type':'paragraph','content':[{'type':'text','text':'Groups the Agile JSON-import tickets in these categories: '+', '.join(sorted(cats))+'.'}]}]}}})
 s['epics'].append({'name':name,'key':epic['key'],'children':children});save();print('Created',epic['key'],name,len(children),flush=True)
for epic in s['epics']:
 for key in epic['children']:
  if key in s['assigned']:continue
  call('PUT','/rest/api/3/issue/'+key,json={'fields':{'parent':{'key':epic['key']}}});s['assigned'].append(key);save()
 print('Assigned',epic['name'],flush=True)
f=call('GET','/rest/api/3/filter/10067');s.setdefault('original_jql',f['jql']);save()
keys=[x['key'] for x in m['created'][:60]]+[x['key'] for x in s['epics']]
call('PUT','/rest/api/3/filter/10067',json={'jql':'project = PROBLEM AND key in ('+','.join(keys)+') ORDER BY Rank ASC'})
r=call('POST','/rest/api/3/search/jql',json={'jql':'filter = 10067','maxResults':100,'fields':['parent','issuetype','status']})
assert len(r['issues'])==63 and r['isLast']
by_key={x['key']:x for x in r['issues']}
for epic in s['epics']:
 assert by_key[epic['key']]['fields']['issuetype']['name']=='Epic'
 for key in epic['children']:assert by_key[key]['fields']['parent']['key']==epic['key']
s['verified']=True;save();print('VERIFIED: 3 epics, 60 children',flush=True)
