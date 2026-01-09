import difflib
from pathlib import Path

PATCH_FILE = "git.txt"
TARGET_FILE = "roblox.py"

def apply_unified_diff(original_text, diff_text):
    original_lines = original_text.splitlines(keepends=True)
    diff_lines = diff_text.splitlines(keepends=True)

    patched = difflib.restore(diff_lines, 2)
    return "".join(patched)

def main():
    target_path = Path(TARGET_FILE)
    patch_path = Path(PATCH_FILE)

    if not target_path.exists():
        raise FileNotFoundError(f"{TARGET_FILE} not found")

    if not patch_path.exists():
        raise FileNotFoundError(f"{PATCH_FILE} not found")

    original = target_path.read_text(encoding="utf-8", errors="ignore")
    patch = patch_path.read_text(encoding="utf-8", errors="ignore")

    try:
        fixed = apply_unified_diff(original, patch)
        if not fixed.strip():
            raise ValueError("Patch failed or produced empty output")

        target_path.write_text(fixed, encoding="utf-8")
        print("✅ roblox.py successfully patched")

    except Exception as e:
        print("❌ Patch failed:", e)

if __name__ == "__main__":
    main()
