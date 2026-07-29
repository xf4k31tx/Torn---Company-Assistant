import sys
from pathlib import Path

def bump_patch_version():
    version_file = Path(__file__).resolve().parent / "version.txt"
    
    # Read the current tracking sequence
    if not version_file.is_file():
        version_str = "1.0.1"
    else:
        version_str = version_file.read_text(encoding="utf-8").strip()
    
    try:
        # Split, increment the patch digit, and rebuild
        major, minor, patch = map(int, version_str.split("."))
        patch += 1
        new_version = f"{major}.{minor}.{patch}"
    except Exception:
        new_version = "1.0.2" # Fallback safety default
        
    # Write the incremented tag back to disk for the next click run
    version_file.write_text(new_version, encoding="utf-8")
    
    # Print out explicitly so the batch variable catch hook can intercept it
    print(new_version)

if __name__ == "__main__":
    bump_patch_version()
