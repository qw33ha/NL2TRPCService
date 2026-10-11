from pathlib import Path, PureWindowsPath


def safe_destination(root: Path, relative: str) -> Path:
    """Reject generated file names that escape the isolated project directory."""
    name = relative.replace("\\", "/")
    if PureWindowsPath(name).drive or name.startswith("/") or ".." in name.split("/"):
        raise ValueError(f"Unsafe generated path: {relative}")
    destination = (root / name).resolve()
    if not destination.is_relative_to(root.resolve()):
        raise ValueError(f"Unsafe generated path: {relative}")
    return destination
