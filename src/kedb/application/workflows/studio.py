"""Local LangGraph Studio entrypoint.

Run from the repository root with:
    langgraph dev
"""

from langgraph.checkpoint.memory import MemorySaver

from kedb.application.workflows.curator import CuratorWorkflow, build_langgraph
from kedb.application.workflows.fakes import studio_fake_llm, studio_fake_retrieval

workflow = CuratorWorkflow(
    llm=studio_fake_llm(),
    retrieval=studio_fake_retrieval(),
)

graph = build_langgraph(workflow, checkpointer=MemorySaver())
