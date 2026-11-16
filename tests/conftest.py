import pytest

from spark.core import llm


@pytest.fixture(autouse=True)
def _reset_llm_config():
    """Keep the process-wide LLM config from leaking between tests."""
    llm._config = llm.LLMConfig()
    yield
    llm._config = llm.LLMConfig()


@pytest.fixture(autouse=True)
def _isolate_spark_env(monkeypatch):
    """Tests must be offline and hermetic: ignore any SPARK_* vars from the caller's shell."""
    import os
    for key in [k for k in os.environ if k.startswith("SPARK_")]:
        monkeypatch.delenv(key)
