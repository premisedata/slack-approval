from setuptools import setup, find_packages

setup(
    name="slack_approval",
    version="0.1.0",
    packages=find_packages(include=["slack_approval", "slack_approval.*"]),
    install_requires=["goblet-gcp>=0.8.3", "slack_sdk==3.18.1",],
    entry_points={"console_scripts": ["slack-approval=slack_approval.cli:main"]},
)
