from security.workspace import resolve_workspace_path


tests = [
    ".",
    "test.py",
    "calculator/main.py",
    "..",
    "../ai-dev-team",
    "C:/Windows",
    "/",
]


for path in tests:

    try:

        result = resolve_workspace_path(path)

        print(
            f"[ALLOW] {path}"
        )

        print(
            f"        -> {result}"
        )

    except Exception as e:

        print(
            f"[DENY]  {path}"
        )

        print(
            f"        -> {type(e).__name__}: {e}"
        )