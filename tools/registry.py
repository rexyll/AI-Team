from tools.filesystem import (
    list_files,
    read_file,
    write_file,
    move_file,
    delete_file,
)
from tools.terminal import run_command
from tools.git import git_command


TOOLS = {
    "list_files": list_files,
    "read_file": read_file,
    "write_file": write_file,
    "move_file": move_file,
    "delete_file": delete_file,
    "run_command": run_command,
    "git_command": git_command,
}