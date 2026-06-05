import subprocess
import sys
import os

def run_cmd(cmd):
    print(f"> {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Status: {result.stderr.strip() or 'Warning/Info'}")
        return False, result.stdout, result.stderr
    if result.stdout.strip():
        print(result.stdout.strip())
    return True, result.stdout, result.stderr

def main():
    print("=" * 45)
    print("         📝 MCP Tool Git Push Helper")
    print("=" * 45)
    
    # Check git
    success, _, _ = run_cmd(["git", "--version"])
    if not success:
        print("Error: Git is not installed or not in PATH.")
        sys.exit(1)
        
    # Check if git repo exists
    if not os.path.exists(".git"):
        print("[INFO] Initializing git repository...")
        run_cmd(["git", "init"])
        
    # Configure main branch name
    run_cmd(["git", "checkout", "-b", "main"])
    
    # Remote URL
    remote_url = "https://github.com/anirudh1937/Documentr-by-MCP-"
    print(f"[INFO] Setting remote origin to: {remote_url}")
    
    # Check remote configuration
    _, stdout, _ = run_cmd(["git", "remote", "-v"])
    has_origin = False
    for line in stdout.splitlines():
        if "origin" in line:
            has_origin = True
            break
            
    if not has_origin:
        run_cmd(["git", "remote", "add", "origin", remote_url])
    else:
        run_cmd(["git", "remote", "set-url", "origin", remote_url])
        
    # Stage files
    print("[INFO] Staging all updated files...")
    run_cmd(["git", "add", "."])
    
    # Commit
    commit_msg = "feat: integrate collaborative editor, graph view, and tabbed HUD monitor"
    print(f"[INFO] Committing changes...")
    run_cmd(["git", "commit", "-m", commit_msg])
    
    # Push
    print("\n" + "=" * 45)
    print("Pushing to GitHub (origin main)...")
    print("NOTE: If a credentials window opens, please login to authenticate.")
    print("=" * 45)
    
    success, _, _ = run_cmd(["git", "push", "-u", "origin", "main"])
    if not success:
        print("\n[WARNING] Push failed. Attempting force push in case repository was freshly created...")
        success, _, _ = run_cmd(["git", "push", "-f", "origin", "main"])
        
    if success:
        print("\n🎉 Successfully pushed all files to GitHub repository!")
    else:
        print("\n❌ Push failed. Please verify repository existence, write access permissions, or run:")
        print("   git push -u origin main")

if __name__ == "__main__":
    main()
