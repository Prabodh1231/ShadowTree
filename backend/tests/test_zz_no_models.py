import sys


def test_no_model_packages_imported():
    """Runs last (file name sorts last): no test may have loaded a model package."""
    for mod in ("onnxruntime", "model2vec", "flashrank", "rapidocr", "pypdfium2", "cactus"):
        assert mod not in sys.modules, f"{mod} was imported during the test run"
