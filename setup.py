from pathlib import Path

from setuptools import find_namespace_packages, setup


BASE_DIR = Path(__file__).resolve().parent
README_PATH = BASE_DIR / "README.md"


setup(
    name="ffa-hedge",
    version="0.1.0",
    description="A professional FFA hedging and risk management engine for shipowners.",
    long_description=README_PATH.read_text(encoding="utf-8"),
    long_description_content_type="text/markdown",
    author="Kelvin Chi",
    packages=find_namespace_packages(include=["ffa_engine*"]),
    include_package_data=True,
    python_requires=">=3.10",
    install_requires=[
        "numpy>=1.26,<2.0",
        "cvxpy>=1.4,<1.5",
        "ecos>=2.0,<3.0",
        "pandas>=2.0,<3.0",
    ],
    extras_require={
        "dev": [
            "pytest>=8.0,<9.0",
            "pytest-cov>=5.0,<6.0",
        ]
    },
)