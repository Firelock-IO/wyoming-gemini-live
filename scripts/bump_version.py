#!/usr/bin/env python3
import argparse
import re
import subprocess
import sys
from pathlib import Path

# We use simple regex locally to avoid requiring heavy dependencies for a simple script
# if run outside the environment. But typically run with 'uv run'.

FILES = {
    "config.yaml": r'(^version:\s*)"?([\d\.]+)"?',
    "pyproject.toml": r'(^version\s*=\s*)"([\d\.]+)"'
}

def bump_file(path: Path, new_version: str, pattern: str):
    if not path.exists():
        print(f"Error: {path} not found.")
        sys.exit(1)
    
    content = path.read_text(encoding="utf-8")
    
    # Check if version matches
    match = re.search(pattern, content, re.MULTILINE)
    if not match:
        print(f"Error: Could not find version pattern in {path}")
        sys.exit(1)
        
    current_version = match.group(2)
    print(f"{path}: {current_version} -> {new_version}")
    
    # Replace
    # We reconstruct the line using group 1 (prefix) and new version
    new_content = re.sub(pattern, f'\\g<1>"{new_version}"', content, count=1, flags=re.MULTILINE)
    
    path.write_text(new_content, encoding="utf-8")

def git_commit_tag_push(version: str):
    try:
        # Add files
        subprocess.check_call(["git", "add", "config.yaml", "pyproject.toml"])
        
        # Commit
        msg = f"Bump version to {version}"
        subprocess.check_call(["git", "commit", "-m", msg])
        
        # Tag
        subprocess.check_call(["git", "tag", f"v{version}"])
        
        # Push (triggers the parent-sync workflow)
        print("Pushing to GitHub (this will trigger parent repo update)...")
        subprocess.check_call(["git", "push"])
        subprocess.check_call(["git", "push", "--tags"])
        
    except subprocess.CalledProcessError as e:
        print(f"Git operation failed: {e}")
        sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description="Bump version in config.yaml and pyproject.toml")
    parser.add_argument("version", help="New version number (e.g. 0.1.1)")
    parser.add_argument("--dry-run", action="store_true", help="Don't write files or git commit")
    parser.add_argument("--files-only", action="store_true", help="Only update files, skip git commit/tag/push")
    args = parser.parse_args()
    
    root = Path(__file__).parent.parent
    
    for filename, pattern in FILES.items():
        if args.dry_run:
            print(f"[Dry Run] Would update {filename} to {args.version}")
        else:
            bump_file(root / filename, args.version, pattern)
            
    if not args.dry_run and not args.files_only:
        git_commit_tag_push(args.version)

if __name__ == "__main__":
    main()
