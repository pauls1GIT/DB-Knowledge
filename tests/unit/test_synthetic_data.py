import importlib.util
from pathlib import Path
spec=importlib.util.spec_from_file_location("gen",Path("scripts/generate_mock_data.py")); mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
def test_generator_is_reproducible(): assert mod.generate(20,42)==mod.generate(20,42)
