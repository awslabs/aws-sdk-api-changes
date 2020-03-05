import os
from io import open
from setuptools import setup, find_packages


def read(fname):
    return open(
        os.path.join(os.path.dirname(__file__), fname),
        encoding='utf-8').read()


setup(
    name="apichanges",
    version='0.0.1',
    description="AWS API Changes",
    long_description=read('readme.md'),
    long_description_content_type='text/markdown',
    license="Apache-2.0",
    packages=find_packages(),
    entry_points={
        'console_scripts': [
            'apichanges = apichanges.cli:cli']},
    install_requires=[

        "botocore>=1.12.228",
        "Click==7.0",
        "docutils==0.15.2",
        "Jinja2==2.10.3",
        "jmespath==0.9.4",
        "MarkupSafe==1.1.1",
        "pycparser==2.19",
        "pygit2==0.28.2",
        "python-dateutil==2.8.0",
        "six==1.13.0",
        "lxml==4.4.2",
        "feedgen==0.9.0",
        "urllib3==1.25.7"
    ],
)
