TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": (
                "List files recursively inside the authorized workspace. "
                "The path is relative to the workspace root. "
                "Use '.' to inspect the workspace root. "
                "Do NOT use 'projects', '../projects', '..', or absolute paths."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Directory path to inspect.",
                    }
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": (
                "Read a text file inside the authorized workspace. "
                "The path is relative to the workspace root. "
                "Do not use absolute paths or paths outside the workspace."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path of the file to read.",
                    }
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": (
                "Write a text file inside the authorized workspace. "
                "The path is relative to the workspace root. "
                "Do not use absolute paths or paths outside the workspace."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path of the file.",
                    },
                    "content": {
                        "type": "string",
                        "description": "Complete file content.",
                    },
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": (
                "Execute a Windows PowerShell or CMD command. "
                "Use this tool only when a dedicated tool cannot "
                "perform the required operation, or when running "
                "tests/builds/programs."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Command to execute.",
                    },
                    "cwd": {
                        "type": "string",
                        "description": "Working directory.",
                    },
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_command",
            "description": "Execute a Git command inside a repository.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Git command without the 'git' prefix.",
                    },
                    "cwd": {
                        "type": "string",
                        "description": "Git repository directory.",
                    },
                },
                "required": ["command", "cwd"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "move_file",
            "description": (
                "Move a file inside the authorized workspace. "
                "Both source and destination must remain inside "
                "the workspace."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "source": {
                        "type": "string",
                        "description": "Source file path.",
                    },
                    "destination": {
                        "type": "string",
                        "description": "Destination file path.",
                    },
                },
                "required": [
                    "source",
                    "destination",
                ],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_file",
            "description": (
                "Delete a file inside the authorized workspace. "
                "Never delete files outside the workspace."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "File path to delete.",
                    }
                },
                "required": ["path"],
            },
        },
    },
]