import sys


def test_no_model_packages_imported():
    """Runs last (file name sorts last): no test may have loaded torch, gliclass or cactus."""
    for mod in ("torch", "gliclass", "cactus"):
        assert mod not in sys.modules, f"{mod} was imported during the test run"
