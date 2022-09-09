import click
import shutil
import os


@click.group()
def main():
    pass


@main.command()
def init():
    """
    """
    dir_path = os.path.dirname(os.path.realpath(__file__))
    shutil.copytree(f"{dir_path}/functions", f"{os.getcwd()}/functions")


if __name__ == "__main__":
    main()
