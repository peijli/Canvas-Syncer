import os
import re

from setuptools import find_packages, setup


def get_version(package):
    """
    Return package version as listed in `__version__` in `__main__.py`.
    """
    path = os.path.join(package, "__main__.py")
    main_py = open(path, "r", encoding="utf8").read()
    return re.search("__version__ = ['\"]([^'\"]+)['\"]", main_py).group(1)


def get_long_description():
    """
    Return the README.
    """
    return open("README.md", "r", encoding="utf8").read()


def get_packages(package):
    """
    Return root package and all sub-packages.
    """
    return [
        dirpath
        for dirpath, dirnames, filenames in os.walk(package)
        if os.path.exists(os.path.join(dirpath, "__init__.py"))
    ]


setup(
    name='canvassyncer',
    version='1.3.1',
    description='Utility to sync course files from Canvas',
    url='https://github.com/pl-mich/Canvas-Syncer',
    author='Peijing Li',
    organization='Engineering Student Government, University of Michigan',
    author_email='peijli@umich.edu',
    packages=find_packages(),
    python_requires=">=3.6",
    entry_points={
        "console_scripts": [
            "canvassyncer=canvassyncer:main",
        ],
    },
    project_urls={
        'Bug Reports': 'https://github.com/pl-mich/Canvas-Syncer/issues',
        'Source': 'https://github.com/pl-mich/Canvas-Syncer',
    },
    install_requires=["httpx", "aiofiles", "tqdm"],
)
