"""Lakeflow Job: transactional-outbox -> Unity Catalog article_chunks -> AI Search sync.
Environment:
  KEDB_DATABASE_URL (psycopg URL), KEDB_UC_CHUNK_TABLE, DATABRICKS_AI_SEARCH_ENDPOINT,
  DATABRICKS_AI_SEARCH_INDEX
"""
import hashlib, os
from uuid import UUID
import psycopg
from pyspark.sql import Row
from kedb.domain import ArticleVersion, ArticleStatus
from kedb.application.use_cases.publish import semantic_chunks

DB=os.environ['KEDB_DATABASE_URL'].replace('postgresql+psycopg://','postgresql://')
TABLE=os.environ['KEDB_UC_CHUNK_TABLE']


def load_batch(limit=100):
    with psycopg.connect(DB) as c, c.cursor() as cur:
        cur.execute("SELECT id, article_version_id FROM publication_outbox WHERE processed=false ORDER BY created_at LIMIT %s",(limit,))
        return cur.fetchall()

def load_article(article_id):
    with psycopg.connect(DB) as c, c.cursor() as cur:
        cur.execute("SELECT id,known_error_id,version_number,title,problem,root_cause,solution,status,source_jira_issue_id,review_id,published_at FROM article_version WHERE id=%s",(article_id,))
        r=cur.fetchone()
        if not r: raise LookupError(article_id)
        return ArticleVersion(id=UUID(str(r[0])),known_error_id=UUID(str(r[1])),version_number=r[2],title=r[3],problem=r[4],root_cause=r[5],solution=r[6],status=ArticleStatus(r[7]),source_jira_issue_id=UUID(str(r[8])) if r[8] else None,review_id=UUID(str(r[9])) if r[9] else None,published_at=r[10])

def set_all_versions_not_current(known_error_id):
    spark.sql(f"UPDATE {TABLE} SET is_current=false WHERE known_error_id='{known_error_id}'")

def write_chunks(article):
    chunks=semantic_chunks(article)
    set_all_versions_not_current(article.known_error_id)
    rows=[]
    for c in chunks:
        rows.append(Row(chunk_id=str(c.id),known_error_id=str(c.known_error_id),article_version_id=str(c.article_version_id),version_number=article.version_number,title=article.title,section=c.section,content=c.content,error_codes=[],source_jira_issue_id=str(article.source_jira_issue_id) if article.source_jira_issue_id else None,review_id=str(article.review_id),status='PUBLISHED',is_current=True,published_at=article.published_at,content_hash=hashlib.sha256(c.content.encode()).hexdigest()))
    spark.createDataFrame(rows).createOrReplaceTempView('_kedb_chunks')
    spark.sql(f"""MERGE INTO {TABLE} t USING _kedb_chunks s ON t.chunk_id=s.chunk_id
      WHEN MATCHED THEN UPDATE SET * WHEN NOT MATCHED THEN INSERT *""")

def mark_done(outbox_id):
    with psycopg.connect(DB) as c, c.cursor() as cur:
        cur.execute('UPDATE publication_outbox SET processed=true, attempts=attempts+1 WHERE id=%s',(outbox_id,)); c.commit()

def mark_attempt(outbox_id):
    with psycopg.connect(DB) as c, c.cursor() as cur:
        cur.execute('UPDATE publication_outbox SET attempts=attempts+1 WHERE id=%s',(outbox_id,)); c.commit()

def sync_index():
    from databricks.ai_search.client import AISearchClient
    client=AISearchClient(disable_notice=True)
    idx=client.get_index(endpoint_name=os.environ['DATABRICKS_AI_SEARCH_ENDPOINT'],index_name=os.environ['DATABRICKS_AI_SEARCH_INDEX'])
    idx.sync()

pending=load_batch()
changed=False
for outbox_id, article_id in pending:
    try:
        article=load_article(article_id)
        if not article.can_embed: raise ValueError('Outbox referenced non-published/unapproved version')
        write_chunks(article); mark_done(outbox_id); changed=True
    except Exception:
        mark_attempt(outbox_id); raise
if changed: sync_index()
print(f'Materialized {len(pending)} publication event(s)')
