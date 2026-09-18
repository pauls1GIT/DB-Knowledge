import argparse, json, random
FAMILIES=[
 ('database_connection_timeout','Oracle application connection timeout','ORA-12170'),
 ('tls_certificate','Application TLS certificate expired','TLS-CERT-EXPIRED'),
 ('disk_space','Service failed because disk is full','DISK-FULL'),
 ('dns','Application cannot resolve database hostname','DNS-FAIL'),
 ('memory','Worker terminated after memory exhaustion','OOM'),
]
def generate(count=200,seed=42):
    r=random.Random(seed); out=[]
    for i in range(count):
        group,base,code=r.choice(FAMILIES); mode=r.choices(['unique','semantic_duplicate','near_duplicate','ambiguous'],[70,20,5,5])[0]
        summary=base if mode=='near_duplicate' else f'{base} - incident {i+1}'
        if mode=='semantic_duplicate': summary=f'Application reports {group.replace("_"," ")} while completing request'
        out.append({'external_key':f'INC-{i+1:03d}','summary':summary,'description':f'Synthetic {mode} for {group}','resolution':f'Remediate {group.replace("_"," ")}.','error_code':code if r.random()<0.7 else None,'ground_truth_error_group':group,'ground_truth_known_error':group})
    return out
if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--count',type=int,default=200); p.add_argument('--seed',type=int,default=42); p.add_argument('--output',default='mock_incidents.json'); a=p.parse_args()
    with open(a.output,'w') as f: json.dump(generate(a.count,a.seed),f,indent=2)
