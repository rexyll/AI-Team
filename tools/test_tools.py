from pathlib import Path

from tools.filesystem import read_file, write_file
from terminal import run_command
from git import git_command


TEST_FILE = Path("../workspace/tool_test.txt")


def main():
    write_file(str(TEST_FILE), "Hello AI Developer!")

    content = read_file(str(TEST_FILE))
    print("FILE:", content)

    print("\nTERMINAL:")
    print(run_command("python --version"))

    print("\nGIT:")
    print(git_command("status --short", ".."))


if __name__ == "__main__":
    main()