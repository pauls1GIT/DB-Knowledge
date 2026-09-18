import argparse
from databricks.ai_search.client import AISearchClient

p=argparse.ArgumentParser()
p.add_argument('--endpoint',required=True); p.add_argument('--source-table',required=True); p.add_argument('--index',required=True)
p.add_argument('--embedding-endpoint',default='databricks-qwen3-embedding-0-6b')
a=p.parse_args()
client=AISearchClient(disable_notice=True)
try: client.create_endpoint(name=a.endpoint, endpoint_type='STANDARD')
except Exception: pass
idx=client.create_delta_sync_index(endpoint_name=a.endpoint,source_table_name=a.source_table,index_name=a.index,pipeline_type='TRIGGERED',primary_key='chunk_id',embedding_source_column='content',embedding_model_endpoint_name=a.embedding_endpoint)
print(idx.describe())
