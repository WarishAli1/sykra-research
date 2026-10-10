from pathlib import Path
from uuid import uuid4


class LocalPrivateStorage:
    """Private local storage with opaque, server-generated object names."""

    def __init__(self, root: str):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, scope: str, content: bytes) -> str:
        stored_filename = f"{uuid4().hex}.pdf"
        directory = (self.root / scope).resolve()
        directory.mkdir(parents=True, exist_ok=True)
        path = (directory / stored_filename).resolve()
        if self.root not in path.parents:
            raise ValueError("Invalid storage scope.")
        path.write_bytes(content)
        return stored_filename

    def resolve(self, scope: str, stored_filename: str) -> Path:
        if Path(stored_filename).name != stored_filename:
            raise ValueError("Invalid storage filename.")
        path = (self.root / scope / stored_filename).resolve()
        if self.root not in path.parents:
            raise ValueError("Invalid storage path.")
        return path

    def delete(self, scope: str, stored_filename: str) -> None:
        path = self.resolve(scope, stored_filename)
        if path.is_file():
            path.unlink()
