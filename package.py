import shutil
from pathlib import Path
import subprocess

ROOT = Path(__file__).parent.resolve()
PACKAGE_DIR = ROOT / "utk_curio"

# Things to move into the package
ITEMS_TO_PACKAGE = [
    ("curio.py", PACKAGE_DIR / "curio.py"),
    ("backend", PACKAGE_DIR / "backend"),
    ("sandbox", PACKAGE_DIR / "sandbox"),
    ("frontend", PACKAGE_DIR / "frontend"),
    ("templates", PACKAGE_DIR / "templates"),
]

# Directory names to exclude during copy
EXCLUDE_DIRS = {"node_modules"}

def copytree_exclude_node_modules(src: Path, dst: Path):
    if dst.exists():
        shutil.rmtree(dst)
    def ignore_node_modules(dir, files):
        ignored = [f for f in files if Path(dir, f).is_dir() and f in EXCLUDE_DIRS]
        return ignored
    shutil.copytree(src, dst, ignore=ignore_node_modules)

def move_items_into_package():
    for src_name, dst_path in ITEMS_TO_PACKAGE:
        src_path = ROOT / src_name
        if not src_path.exists():
            print(f"Skipping missing {src_name}")
            continue

        print(f"Moving {src_name} to {dst_path}")
        if src_path.is_dir():
            copytree_exclude_node_modules(src_path, dst_path)
        else:
            dst_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src_path, dst_path)

def cleanup():
    for _, dst_path in ITEMS_TO_PACKAGE:
        if dst_path.is_dir():
            shutil.rmtree(dst_path, ignore_errors=True)
        elif dst_path.exists():
            dst_path.unlink()

if __name__ == "__main__":
    print("Preparing build...")
    move_items_into_package()

    try:
        print("Building wheel...")
        subprocess.run(["python", "-m", "build"], check=True)
    finally:
        print("Cleaning up package directory...")
        cleanup()
