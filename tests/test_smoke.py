"""Smoke test: the package is installed and importable."""

import immo


def test_package_is_importable():
    assert immo.__version__
