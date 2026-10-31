"""Archive obsolete entry points and remove rebuildable project caches."""
from pathlib import Path
import shutil
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
OLD = ("run_acceptance.py", "run_chain_test.py", "run_dut_test.py",
       "run_test_case.py", "hardware_smoke_test.py")


def contained(path):
    resolved = path.resolve()
    resolved.relative_to(ROOT)
    if resolved == ROOT:
        raise ValueError("cannot remove workspace root")
    return resolved


def main():
    files = [ROOT / name for name in OLD if (ROOT / name).is_file()]
    if files:
        archive = ROOT / "docs" / "legacy_tools_20261006.zip"
        archive.parent.mkdir(parents=True, exist_ok=True)
        if archive.exists():
            raise FileExistsError(f"refusing to overwrite {archive}")
        with ZipFile(archive, "w") as z:
            for path in files:
                z.write(contained(path), path.name)
        with ZipFile(archive) as z:
            assert z.testzip() is None
            for path in files:
                assert z.read(path.name) == path.read_bytes()
        for path in files:
            contained(path).unlink()
        print(f"Archived {len(files)} obsolete scripts: {archive}")
    caches = [ROOT / "__pycache__", ROOT / ".mplconfig"]
    for package in ("auto_test", "tests"):
        caches.extend((ROOT / package).rglob("__pycache__"))
    for path in caches:
        if path.exists() and not path.is_symlink():
            shutil.rmtree(contained(path))
    print("Removed rebuildable caches; retained .venv, source, documents and test reports")


if __name__ == "__main__":
    main()
