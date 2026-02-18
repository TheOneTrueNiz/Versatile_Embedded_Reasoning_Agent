#!/usr/bin/env python3
"""
Git Context Awareness
=====================

Provides version control context before file operations.

Source: Ported from GROKSTAR's GIT_MODE detection and dirty state checks

Problem Solved:
- VERA might suggest edits that overwrite uncommitted work
- No context on why code is the way it is (history)
- Risk of losing work without realizing

Solution:
- Check git status before file operations
- Warn about uncommitted changes
- Provide commit history context
- Suggest branch/stash workflows

Usage:
    from git_context import GitContext, GitStatus

    git = GitContext("/path/to/repo")

    # Check before editing
    status = git.check_file_status("src/main.py")
    if status.is_dirty:
        print(f"Warning: {status.message}")

    # Get file history
    history = git.get_file_history("src/main.py", limit=5)
"""

import subprocess
from pathlib import Path
from dataclasses import dataclass
from typing import List, Optional, Tuple
from enum import Enum
import logging
logger = logging.getLogger(__name__)


class FileGitStatus(Enum):
    """Git status of a file"""
    CLEAN = "clean"              # No changes
    MODIFIED = "modified"        # Modified but not staged
    STAGED = "staged"            # Staged for commit
    UNTRACKED = "untracked"      # Not tracked by git
    DELETED = "deleted"          # Deleted but not staged
    RENAMED = "renamed"          # Renamed
    CONFLICT = "conflict"        # Merge conflict
    IGNORED = "ignored"          # In .gitignore
    NOT_IN_REPO = "not_in_repo"  # File not in a git repo


@dataclass
class GitFileStatus:
    """Detailed status for a file"""
    path: str
    status: FileGitStatus
    is_dirty: bool
    staged_changes: bool
    message: str
    diff_preview: Optional[str] = None


@dataclass
class GitCommit:
    """A git commit"""
    hash: str
    short_hash: str
    author: str
    date: str
    message: str
    files_changed: int = 0


@dataclass
class GitRepoStatus:
    """Overall repository status"""
    is_repo: bool
    branch: str
    is_clean: bool
    ahead: int = 0
    behind: int = 0
    staged_count: int = 0
    modified_count: int = 0
    untracked_count: int = 0
    has_stash: bool = False
    last_commit: Optional[GitCommit] = None


class GitContext:
    """
    Provides git context for file operations.

    Helps VERA understand version control state before making changes.
    """

    def __init__(self, repo_path: Path = None) -> None:
        """
        Initialize git context.

        Args:
            repo_path: Path to git repository (or None to auto-detect)
        """
        self.repo_path = Path(repo_path) if repo_path else self._find_repo_root()
        self._is_repo = self._check_is_repo()

    def _find_repo_root(self) -> Optional[Path]:
        """Find git repo root from current directory"""
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                capture_output=True,
                text=True,
                cwd=Path.cwd()
            )
            if result.returncode == 0:
                return Path(result.stdout.strip())
        except (subprocess.SubprocessError, FileNotFoundError) as exc:
            logger.debug("Suppressed %s: %s", type(exc).__name__, exc)
        return Path.cwd()

    def _check_is_repo(self) -> bool:
        """Check if path is a git repository"""
        if not self.repo_path:
            return False

        try:
            result = subprocess.run(
                ["git", "rev-parse", "--git-dir"],
                capture_output=True,
                text=True,
                cwd=self.repo_path
            )
            return result.returncode == 0
        except (subprocess.SubprocessError, FileNotFoundError):
            return False

    def _run_git(self, *args, cwd: Path = None) -> Tuple[bool, str]:
        """Run a git command and return (success, output)"""
        try:
            result = subprocess.run(
                ["git"] + list(args),
                capture_output=True,
                text=True,
                cwd=cwd or self.repo_path
            )
            return result.returncode == 0, result.stdout.strip()
        except (subprocess.SubprocessError, FileNotFoundError):
            return False, ""

    def is_git_repo(self) -> bool:
        """Check if working in a git repository"""
        return self._is_repo

    def get_repo_status(self) -> GitRepoStatus:
        """Get overall repository status"""
        if not self._is_repo:
            return GitRepoStatus(
                is_repo=False,
                branch="",
                is_clean=True
            )

        # Get current branch
        success, branch = self._run_git("rev-parse", "--abbrev-ref", "HEAD")
        branch = branch if success else "unknown"

        # Get status counts
        success, status_output = self._run_git("status", "--porcelain")
        lines = status_output.split('\n') if status_output else []

        staged_count = 0
        modified_count = 0
        untracked_count = 0

        for line in lines:
            if not line:
                continue
            index_status = line[0] if len(line) > 0 else ' '
            work_status = line[1] if len(line) > 1 else ' '

            if index_status != ' ' and index_status != '?':
                staged_count += 1
            if work_status == 'M':
                modified_count += 1
            if index_status == '?':
                untracked_count += 1

        # Check ahead/behind
        success, tracking = self._run_git("rev-list", "--left-right", "--count", f"{branch}...origin/{branch}")
        ahead, behind = 0, 0
        if success and tracking:
            parts = tracking.split('\t')
            if len(parts) == 2:
                ahead, behind = int(parts[0]), int(parts[1])

        # Check stash
        success, stash = self._run_git("stash", "list")
        has_stash = bool(stash)

        # Get last commit
        last_commit = self.get_last_commit()

        return GitRepoStatus(
            is_repo=True,
            branch=branch,
            is_clean=(staged_count == 0 and modified_count == 0),
            ahead=ahead,
            behind=behind,
            staged_count=staged_count,
            modified_count=modified_count,
            untracked_count=untracked_count,
            has_stash=has_stash,
            last_commit=last_commit
        )

    def check_file_status(self, file_path: str) -> GitFileStatus:
        """
        Check git status of a specific file.

        Args:
            file_path: Path to file (relative or absolute)

        Returns:
            GitFileStatus with details and warnings
        """
        if not self._is_repo:
            return GitFileStatus(
                path=file_path,
                status=FileGitStatus.NOT_IN_REPO,
                is_dirty=False,
                staged_changes=False,
                message="Not in a git repository"
            )

        # Resolve path relative to repo
        abs_path = Path(file_path)
        if not abs_path.is_absolute():
            abs_path = self.repo_path / file_path

        try:
            rel_path = abs_path.relative_to(self.repo_path)
        except ValueError:
            return GitFileStatus(
                path=file_path,
                status=FileGitStatus.NOT_IN_REPO,
                is_dirty=False,
                staged_changes=False,
                message="File is outside the repository"
            )

        # Get file status
        success, status_output = self._run_git("status", "--porcelain", str(rel_path))

        if not status_output:
            # File is clean or doesn't exist
            if abs_path.exists():
                return GitFileStatus(
                    path=str(rel_path),
                    status=FileGitStatus.CLEAN,
                    is_dirty=False,
                    staged_changes=False,
                    message="File is clean (no uncommitted changes)"
                )
            else:
                return GitFileStatus(
                    path=str(rel_path),
                    status=FileGitStatus.UNTRACKED,
                    is_dirty=False,
                    staged_changes=False,
                    message="File does not exist"
                )

        # Parse status
        line = status_output.split('\n')[0]
        index_status = line[0] if len(line) > 0 else ' '
        work_status = line[1] if len(line) > 1 else ' '

        # Determine file status
        if index_status == '?' and work_status == '?':
            status = FileGitStatus.UNTRACKED
            message = "File is not tracked by git"
            is_dirty = False
            staged = False
        elif index_status == 'M' or work_status == 'M':
            status = FileGitStatus.MODIFIED
            is_dirty = True
            staged = index_status == 'M'
            message = "File has uncommitted changes"
            if staged:
                message += " (staged)"
        elif index_status == 'A':
            status = FileGitStatus.STAGED
            is_dirty = True
            staged = True
            message = "File is staged for commit (new file)"
        elif index_status == 'D' or work_status == 'D':
            status = FileGitStatus.DELETED
            is_dirty = True
            staged = index_status == 'D'
            message = "File is marked for deletion"
        elif index_status == 'R':
            status = FileGitStatus.RENAMED
            is_dirty = True
            staged = True
            message = "File has been renamed"
        elif index_status == 'U' or work_status == 'U':
            status = FileGitStatus.CONFLICT
            is_dirty = True
            staged = False
            message = "File has merge conflicts!"
        else:
            status = FileGitStatus.MODIFIED
            is_dirty = work_status != ' '
            staged = index_status != ' '
            message = "File has changes"

        # Get diff preview for dirty files
        diff_preview = None
        if is_dirty:
            success, diff = self._run_git("diff", "--stat", str(rel_path))
            if success and diff:
                diff_preview = diff[:200]

        return GitFileStatus(
            path=str(rel_path),
            status=status,
            is_dirty=is_dirty,
            staged_changes=staged,
            message=message,
            diff_preview=diff_preview
        )

    def get_last_commit(self) -> Optional[GitCommit]:
        """Get the last commit on current branch"""
        if not self._is_repo:
            return None

        success, output = self._run_git(
            "log", "-1",
            "--format=%H|%h|%an|%ai|%s"
        )

        if not success or not output:
            return None

        parts = output.split('|')
        if len(parts) < 5:
            return None

        return GitCommit(
            hash=parts[0],
            short_hash=parts[1],
            author=parts[2],
            date=parts[3],
            message='|'.join(parts[4:])  # Message might contain |
        )

    def get_file_history(
        self,
        file_path: str,
        limit: int = 10
    ) -> List[GitCommit]:
        """
        Get commit history for a specific file.

        Args:
            file_path: Path to file
            limit: Maximum commits to return

        Returns:
            List of commits that touched this file
        """
        if not self._is_repo:
            return []

        success, output = self._run_git(
            "log", f"-{limit}",
            "--format=%H|%h|%an|%ai|%s",
            "--", file_path
        )

        if not success or not output:
            return []

        commits = []
        for line in output.split('\n'):
            if not line:
                continue
            parts = line.split('|')
            if len(parts) >= 5:
                commits.append(GitCommit(
                    hash=parts[0],
                    short_hash=parts[1],
                    author=parts[2],
                    date=parts[3],
                    message='|'.join(parts[4:])
                ))

        return commits

    def get_uncommitted_files(self) -> List[GitFileStatus]:
        """Get all files with uncommitted changes"""
        if not self._is_repo:
            return []

        success, output = self._run_git("status", "--porcelain")
        if not success or not output:
            return []

        files = []
        for line in output.split('\n'):
            if not line or len(line) < 4:
                continue

            file_path = line[3:].strip()
            # Handle renamed files (old -> new)
            if " -> " in file_path:
                file_path = file_path.split(" -> ")[1]

            files.append(self.check_file_status(file_path))

        return files

    def suggest_workflow(self, file_path: str) -> str:
        """
        Suggest a workflow based on file and repo status.

        Args:
            file_path: File that will be modified

        Returns:
            Suggested workflow message
        """
        file_status = self.check_file_status(file_path)
        repo_status = self.get_repo_status()

        suggestions = []

        if file_status.status == FileGitStatus.CONFLICT:
            return "STOP: File has merge conflicts. Resolve conflicts before proceeding."

        if file_status.is_dirty:
            if file_status.staged_changes:
                suggestions.append(
                    f"'{file_path}' has staged changes. "
                    "Consider committing first or stashing."
                )
            else:
                suggestions.append(
                    f"'{file_path}' has uncommitted changes. "
                    "Options: (1) Commit now, (2) Stash, (3) Proceed anyway."
                )

        if repo_status.behind > 0:
            suggestions.append(
                f"Branch is {repo_status.behind} commit(s) behind remote. "
                "Consider pulling first."
            )

        if repo_status.modified_count > 5:
            suggestions.append(
                f"{repo_status.modified_count} files modified. "
                "Consider committing current work before new changes."
            )

        if not suggestions:
            return f"OK to proceed. Branch '{repo_status.branch}' is clean."

        return " ".join(suggestions)

    def format_status_summary(self) -> str:
        """Format repository status for display"""
        status = self.get_repo_status()

        if not status.is_repo:
            return "Not in a git repository"

        lines = [f"**Git Status** ({status.branch})"]

        if status.is_clean:
            lines.append("  Clean (no uncommitted changes)")
        else:
            if status.staged_count:
                lines.append(f"  Staged: {status.staged_count} file(s)")
            if status.modified_count:
                lines.append(f"  Modified: {status.modified_count} file(s)")
            if status.untracked_count:
                lines.append(f"  Untracked: {status.untracked_count} file(s)")

        if status.ahead or status.behind:
            lines.append(f"  Remote: {status.ahead} ahead, {status.behind} behind")

        if status.has_stash:
            lines.append("  Has stashed changes")

        if status.last_commit:
            lines.append(f"  Last commit: {status.last_commit.short_hash} - {status.last_commit.message[:40]}")

        return '\n'.join(lines)


# === CLI Test Interface ===

if __name__ == "__main__":
    import tempfile

    print("=" * 60)
    print("Git Context - Test Suite")
    print("=" * 60)

    # Create a test repository
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_path = Path(tmpdir) / "test_repo"
        repo_path.mkdir()

        # Initialize git repo
        subprocess.run(["git", "init"], cwd=repo_path, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo_path, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo_path, capture_output=True)

        # Create and commit a file
        test_file = repo_path / "test.txt"
        test_file.write_text("Hello, World!")
        subprocess.run(["git", "add", "test.txt"], cwd=repo_path, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=repo_path, capture_output=True)

        git = GitContext(repo_path)

        # Test 1: Is git repo
        print("\n=== Test 1: Detect Git Repo ===")
        assert git.is_git_repo()
        print(f"   Is git repo: {git.is_git_repo()}")
        print("   Result: PASS")

        # Test 2: Repo status (clean)
        print("\n=== Test 2: Clean Repo Status ===")
        status = git.get_repo_status()
        assert status.is_clean
        print(f"   Branch: {status.branch}")
        print(f"   Clean: {status.is_clean}")
        print("   Result: PASS")

        # Test 3: Clean file status
        print("\n=== Test 3: Clean File Status ===")
        file_status = git.check_file_status("test.txt")
        assert file_status.status == FileGitStatus.CLEAN
        assert not file_status.is_dirty
        print(f"   Status: {file_status.status.value}")
        print(f"   Message: {file_status.message}")
        print("   Result: PASS")

        # Test 4: Modified file status
        print("\n=== Test 4: Modified File Status ===")
        test_file.write_text("Modified content!")
        file_status = git.check_file_status("test.txt")
        assert file_status.status == FileGitStatus.MODIFIED
        assert file_status.is_dirty
        print(f"   Status: {file_status.status.value}")
        print(f"   Message: {file_status.message}")
        print("   Result: PASS")

        # Test 5: Untracked file
        print("\n=== Test 5: Untracked File ===")
        new_file = repo_path / "new_file.txt"
        new_file.write_text("New file!")
        file_status = git.check_file_status("new_file.txt")
        assert file_status.status == FileGitStatus.UNTRACKED
        print(f"   Status: {file_status.status.value}")
        print("   Result: PASS")

        # Test 6: Get uncommitted files
        print("\n=== Test 6: Uncommitted Files ===")
        uncommitted = git.get_uncommitted_files()
        assert len(uncommitted) == 2  # modified + untracked
        print(f"   Found {len(uncommitted)} uncommitted file(s)")
        for f in uncommitted:
            print(f"     - {f.path}: {f.status.value}")
        print("   Result: PASS")

        # Test 7: File history
        print("\n=== Test 7: File History ===")
        history = git.get_file_history("test.txt")
        assert len(history) == 1
        print(f"   Commits: {len(history)}")
        if history:
            print(f"   Last: {history[0].short_hash} - {history[0].message}")
        print("   Result: PASS")

        # Test 8: Workflow suggestion
        print("\n=== Test 8: Workflow Suggestion ===")
        suggestion = git.suggest_workflow("test.txt")
        # File was staged in Test 4, so it shows "staged changes"
        assert "staged changes" in suggestion or "uncommitted" in suggestion.lower()
        print(f"   Suggestion: {suggestion[:80]}...")
        print("   Result: PASS")

        # Test 9: Status summary
        print("\n=== Test 9: Status Summary ===")
        summary = git.format_status_summary()
        print("   Summary:")
        for line in summary.split('\n'):
            print(f"   {line}")
        print("   Result: PASS")

    # Test 10: Non-repo directory
    print("\n=== Test 10: Non-Git Directory ===")
    with tempfile.TemporaryDirectory() as tmpdir:
        git = GitContext(Path(tmpdir))
        assert not git.is_git_repo()
        status = git.get_repo_status()
        assert not status.is_repo
        print(f"   Is git repo: {git.is_git_repo()}")
        print("   Result: PASS")

    print("\n" + "=" * 60)
    print("ALL TESTS PASSED")
    print("=" * 60)
    print("\nGit Context is ready for integration!")
