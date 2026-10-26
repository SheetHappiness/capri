"""Deliberately offline auxiliary boundary, monkeypatchable by upstream tests."""
def _get_task_timeout(task):
    return 30.0

def call_llm(*args, **kwargs):
    raise RuntimeError("Hermes Port 01 auxiliary LLM is dormant")
