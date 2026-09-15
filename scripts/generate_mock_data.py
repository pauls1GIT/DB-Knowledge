import argparse, json, random
from pathlib import Path

TEMPLATES=[
 ("oracle_timeout","ORA-12170","Oracle connection timeout","Application cannot connect to Oracle; requests time out.","Network path or listener is unavailable.","Validate routing/listener, restore connectivity, then retry."),
 ("tls_expired","TLS-CERT","Expired TLS certificate","Client rejects service TLS certificate.","Service certificate expired.","Renew the certificate and restart/reload the dependent service."),
 ("disk_full","ENOSPC","Filesystem full","Service cannot write files because disk is full.","Disk capacity exhausted.","Remove/archive safe data or extend storage, then restart failed workload."),
 ("dns_failure","DNS","DNS resolution failure","Application cannot resolve backend hostname.","DNS record or resolver configuration is incorrect.","Correct DNS/resolver configuration and verify name resolution."),
]
PARAPHRASES=["Users report {s}.","Resolved incident: {s}.","Production alert indicates {s}.","Service impact caused by {s}."]

def generate(n,seed):
 r=random.Random(seed); out=[]
 for i in range(n):
  g,code,title,problem,cause,solution=r.choice(TEMPLATES)
  roll=r.random(); kind="unique" if roll<.70 else "semantic_duplicate" if roll<.90 else "near_duplicate" if roll<.95 else "ambiguous"
  summary=title if kind=="near_duplicate" else r.choice(PARAPHRASES).format(s=title.lower())
  if kind=="ambiguous": summary=title+" with intermittent network symptoms"
  out.append({"external_key":f"INC-{i+1:04d}","summary":summary,"description":problem,"resolution":solution,"error_code":code,"ground_truth_error_group":g,"kind":kind})
 return out

if __name__=="__main__":
 p=argparse.ArgumentParser(); p.add_argument("--count",type=int,default=200); p.add_argument("--seed",type=int,default=42); p.add_argument("--output",default="mock_incidents.json")
 a=p.parse_args(); Path(a.output).write_text(json.dumps(generate(a.count,a.seed),indent=2)); print(f"Wrote {a.count} incidents to {a.output}")
