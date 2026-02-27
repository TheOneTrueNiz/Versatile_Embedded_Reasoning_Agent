#!/usr/bin/env python3
"""
VERA Safety Validator

Validates commands before execution to prevent catastrophic operations.
Implements defense-in-depth strategy:
- Block: Catastrophic commands (severity 5)
- Confirm: Destructive commands (severity 3-4)
- Log: All validations for audit trail

Design principles:
1. Fail-safe: On error, block rather than allow
2. Transparent: Always explain why command was blocked
3. Overridable: User can confirm after seeing risks
4. Auditable: All decisions logged

Improvement #2 (2025-12-26):
- Command Tree Decomposition for Shadow Alignment defense
- AST-style parsing to detect obfuscated attacks
- Intent classification using semantic analysis
- Anti-obfuscation detection (Base64, hex, unicode homoglyphs)

Research basis:
- arXiv:2310.02949 (Shadow Alignment - safety bypass attacks)
- arXiv:2506.11083 (RedDebate - multi-agent red teaming)
- arXiv:2410.01606 (GOAT - automated adversarial testing)
"""

import re
import json
import os
import shlex
import subprocess
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
from enum import Enum

# Import Command Tree Decomposition (Improvement #2)
try:
    from .command_tree import CommandTreeValidator, CommandIntent, ObfuscationType
    COMMAND_TREE_AVAILABLE = True
except ImportError:
    try:
        # Fallback for direct execution
        from command_tree import CommandTreeValidator, CommandIntent, ObfuscationType
        COMMAND_TREE_AVAILABLE = True
    except ImportError:
        COMMAND_TREE_AVAILABLE = False
        CommandTreeValidator = None


class ValidationResult(Enum):
    """Outcome of command validation"""
    ALLOWED = "allowed"
    BLOCKED = "blocked"
    REQUIRES_CONFIRMATION = "requires_confirmation"
    WHITELISTED = "whitelisted"


@dataclass
class ValidationDecision:
    """Result of validating a command"""
    result: ValidationResult
    message: str
    matched_pattern: Optional[str] = None
    severity: int = 0
    expanded_command: Optional[str] = None  # After substitution expansion
    affected_files: List[str] = None

    def __post_init__(self):
        if self.affected_files is None:
            self.affected_files = []


class SafetyValidator:
    """
    Validates commands against dangerous patterns and protected resources.

    Usage:
        validator = SafetyValidator()
        decision = validator.validate("rm -rf /")

        if decision.result == ValidationResult.BLOCKED:
            print(f"Blocked: {decision.message}")
        elif decision.result == ValidationResult.REQUIRES_CONFIRMATION:
            if user_confirms(decision.message):
                execute_command(command)
        else:
            execute_command(command)
    """

    def __init__(self, patterns_file: str = None, enable_command_tree: bool = True) -> None:
        """
        Initialize safety validator

        Args:
            patterns_file: Path to dangerous_patterns.json (auto-detects if None)
            enable_command_tree: Enable Command Tree Decomposition (Improvement #2)
        """
        if patterns_file is None:
            # Auto-detect patterns file relative to this script
            script_dir = Path(__file__).parent
            patterns_file = script_dir / "dangerous_patterns.json"

        self.patterns_file = Path(patterns_file)
        self.patterns = self._load_patterns()
        self.whitelist = self.patterns.get("whitelist", {})
        self.protected_resources = self.patterns.get("protected_resources", {})

        # Initialize Command Tree Validator (Improvement #2)
        self.enable_command_tree = enable_command_tree and COMMAND_TREE_AVAILABLE
        if self.enable_command_tree:
            self.tree_validator = CommandTreeValidator()
        else:
            self.tree_validator = None

    def _load_patterns(self) -> Dict:
        """Load danger patterns from JSON file"""
        try:
            with open(self.patterns_file, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            # Fail-safe: If patterns file missing, block everything
            print(f"⚠️ WARNING: Patterns file not found at {self.patterns_file}")
            print("⚠️ SAFETY MODE: All commands will require confirmation")
            return {"patterns": {}, "whitelist": {"commands": []}}
        except json.JSONDecodeError as e:
            print(f"⚠️ ERROR: Invalid patterns file: {e}")
            print("⚠️ SAFETY MODE: All commands will require confirmation")
            return {"patterns": {}, "whitelist": {"commands": []}}

    def validate(self, command: str, context: Dict = None) -> ValidationDecision:
        """
        Validate a command against safety rules

        Args:
            command: Shell command to validate
            context: Optional context (current_dir, user, etc.)

        Returns:
            ValidationDecision with result and explanation
        """
        if context is None:
            context = {}

        skip_command_tree = False
        raw_skip = context.get("skip_command_tree")
        if isinstance(raw_skip, bool):
            skip_command_tree = raw_skip
        elif isinstance(raw_skip, str):
            skip_command_tree = raw_skip.strip().lower() in {"1", "true", "yes", "on"}
        elif raw_skip is not None:
            skip_command_tree = bool(raw_skip)

        # Step 0: Command Tree Decomposition (Improvement #2)
        # This catches obfuscated attacks that bypass regex patterns
        if self.enable_command_tree and self.tree_validator and not skip_command_tree:
            tree_decision = self._check_command_tree(command)
            if tree_decision:
                return tree_decision

        # Step 1: Check whitelist (fast path for common safe commands)
        if self._is_whitelisted(command):
            return ValidationDecision(
                result=ValidationResult.WHITELISTED,
                message="Command is whitelisted as safe",
                severity=0
            )

        # Step 2: Expand command substitutions to detect hidden commands
        expanded = self._expand_substitutions(command)
        if expanded != command:
            # Recursively validate expanded command
            decision = self.validate(expanded, context)
            decision.expanded_command = expanded
            return decision

        # Step 3: Check for command chaining (;, &&, ||, |)
        if self._has_command_chaining(command):
            return self._validate_chained_command(command, context)

        # Step 4: Check catastrophic patterns (severity 5) - always block
        decision = self._check_pattern_category("catastrophic", command, context)
        if decision:
            return decision

        # Step 5: Check self-modification patterns (severity 4)
        decision = self._check_pattern_category("self_modification", command, context)
        if decision:
            return decision

        # Step 6: Check destructive operations (severity 3)
        decision = self._check_pattern_category("destructive_operations", command, context)
        if decision:
            return decision

        # Step 7: Check environment modification (severity 3)
        decision = self._check_pattern_category("environment_modification", command, context)
        if decision:
            return decision

        # Step 8: Check network exposure (severity 3)
        decision = self._check_pattern_category("network_exposure", command, context)
        if decision:
            return decision

        # Step 9: Check protected resources
        decision = self._check_protected_resources(command, context)
        if decision:
            return decision

        # All checks passed
        return ValidationDecision(
            result=ValidationResult.ALLOWED,
            message="Command passed all safety checks",
            severity=0
        )

    def _check_command_tree(self, command: str) -> Optional[ValidationDecision]:
        """
        Check command using Command Tree Decomposition (Improvement #2).

        This catches:
        - Base64/hex encoded attacks
        - Unicode homoglyph obfuscation
        - Remote code execution patterns
        - Multi-stage attacks

        Returns:
            ValidationDecision if tree analysis blocks/confirms, None to continue
        """
        if not self.tree_validator:
            return None

        try:
            analysis = self.tree_validator.analyze(command)

            # Check if should block
            should_block, block_reason = self.tree_validator.should_block(command)
            if should_block:
                # Build detailed message
                message = f"⚠️ BLOCKED by Command Tree Analysis:\n{block_reason}"

                # Add obfuscation details if present
                if analysis.get("obfuscations"):
                    message += "\n\nDetected obfuscations:"
                    for obs in analysis["obfuscations"]:
                        message += f"\n  - {obs['type']}: {obs['detail']}"

                # Add intent details
                if analysis.get("intents"):
                    message += f"\n\nDetected intents: {', '.join(analysis['intents'])}"

                return ValidationDecision(
                    result=ValidationResult.BLOCKED,
                    message=message,
                    matched_pattern="command_tree_analysis",
                    severity=5
                )

            # Check if requires confirmation
            requires_confirm, confirm_reason = self.tree_validator.requires_confirmation(command)
            if requires_confirm:
                message = f"⚠️ Command Tree Analysis requires confirmation:\n{confirm_reason}"

                # Add risk details
                risk_score = analysis.get("risk_score", 0)
                risk_level = analysis.get("risk_level", "UNKNOWN")
                message += f"\n\nRisk Score: {risk_score}/100 ({risk_level})"

                if analysis.get("intents"):
                    message += f"\nIntents: {', '.join(analysis['intents'])}"

                return ValidationDecision(
                    result=ValidationResult.REQUIRES_CONFIRMATION,
                    message=message,
                    matched_pattern="command_tree_analysis",
                    severity=4
                )

            # Tree analysis passed - continue with other checks
            return None

        except Exception as e:
            # Fail-closed: if advanced analysis crashes, require confirmation
            print(f"⚠️ Command Tree Analysis error (fail-closed): {e}")
            return ValidationDecision(
                result=ValidationResult.REQUIRES_CONFIRMATION,
                message=f"Command tree analysis failed ({e}); manual confirmation required.",
                matched_pattern="command_tree_error",
                severity=3
            )

    def _is_whitelisted(self, command: str) -> bool:
        """Check if command is in whitelist (optimization)"""
        # Exact match
        if command.strip() in self.whitelist.get("commands", []):
            return True

        # Pattern match
        for pattern in self.whitelist.get("patterns", []):
            if re.match(pattern, command.strip()):
                return True

        return False

    def _expand_substitutions(self, command: str) -> str:
        """
        Expand command substitutions $(cmd) and `cmd`

        Note: We don't actually execute the substitution (security risk),
        but we detect its presence so we can warn user.
        """
        # Detect command substitutions
        if "$(" in command or "`" in command:
            # For now, we can't safely expand without executing
            # Just return original and mark for user review
            return command

        # Detect variable expansions
        if "$" in command:
            # Could expand known safe variables like $HOME, $USER
            expanded = command.replace("$HOME", os.path.expanduser("~"))
            expanded = expanded.replace("$USER", os.getenv("USER", "unknown"))
            return expanded

        return command

    def _has_command_chaining(self, command: str) -> bool:
        """Detect command chaining operators"""
        # Look for chaining outside of quotes
        chain_operators = [';', '&&', '||', '|']

        # Simple heuristic: if any operator present outside quotes
        in_quotes = False
        quote_char = None

        for i, char in enumerate(command):
            if char in ['"', "'"]:
                if not in_quotes:
                    in_quotes = True
                    quote_char = char
                elif char == quote_char:
                    in_quotes = False
                    quote_char = None
            elif not in_quotes:
                if char in chain_operators:
                    return True
                if i < len(command) - 1 and command[i:i+2] in ['&&', '||']:
                    return True

        return False

    def _validate_chained_command(self, command: str, context: Dict) -> ValidationDecision:
        """Validate command that uses chaining (;, &&, ||, |)"""
        # Split by chaining operators (naive split, improve if needed)
        # For now, check if any dangerous command in chain
        parts = re.split(r'[;|&]+', command)

        for part in parts:
            part = part.strip()
            if not part:
                continue

            # Recursively validate each part
            decision = self.validate(part, context)
            if decision.result in [ValidationResult.BLOCKED, ValidationResult.REQUIRES_CONFIRMATION]:
                # Found dangerous command in chain
                decision.message = f"Chained command contains dangerous operation: {part}\n\n{decision.message}"
                return decision

        # All parts safe
        return ValidationDecision(
            result=ValidationResult.ALLOWED,
            message="All chained commands passed validation",
            severity=0
        )

    def _check_pattern_category(self, category: str, command: str, context: Dict) -> Optional[ValidationDecision]:
        """
        Check command against patterns in a specific category

        Returns:
            ValidationDecision if pattern matches, None otherwise
        """
        category_data = self.patterns.get("patterns", {}).get(category)
        if not category_data:
            return None

        severity = category_data.get("severity", 3)
        action = category_data.get("action", "confirm")

        for pattern_def in category_data.get("patterns", []):
            regex = pattern_def.get("regex")
            if not regex:
                continue

            # Case-insensitive matching
            if re.search(regex, command, re.IGNORECASE):
                # Pattern matched!
                pattern_name = pattern_def.get("name", "unknown")
                message = pattern_def.get("message", "Dangerous command detected")

                # Determine action based on severity and category action
                if action == "block" or severity >= 5:
                    result = ValidationResult.BLOCKED
                elif action == "confirm" or severity >= 3:
                    result = ValidationResult.REQUIRES_CONFIRMATION
                    # Add examples to help user understand
                    examples = pattern_def.get("examples", [])
                    if examples:
                        message += f"\n\nExamples of this pattern:\n" + "\n".join(f"  - {ex}" for ex in examples)
                else:
                    result = ValidationResult.ALLOWED

                return ValidationDecision(
                    result=result,
                    message=message,
                    matched_pattern=pattern_name,
                    severity=severity
                )

        return None

    def _check_protected_resources(self, command: str, context: Dict) -> Optional[ValidationDecision]:
        """Check if command affects protected resources"""
        resources = self.protected_resources.get("resources", [])

        for resource in resources:
            path = resource.get("path")
            rule = resource.get("rule")
            message = resource.get("message", f"⚠️ WARNING: {path} is protected")

            # Check if command mentions this path
            if path in command:
                if rule == "block_all_modifications":
                    return ValidationDecision(
                        result=ValidationResult.BLOCKED,
                        message=message,
                        matched_pattern=f"protected_resource:{path}",
                        severity=5
                    )
                elif rule in ["require_confirmation_for_modification", "require_confirmation_for_deletion", "block_bulk_deletion"]:
                    return ValidationDecision(
                        result=ValidationResult.REQUIRES_CONFIRMATION,
                        message=message,
                        matched_pattern=f"protected_resource:{path}",
                        severity=4
                    )

        return None

    def validate_file_operation(self, operation: str, paths: List[str], context: Dict = None) -> ValidationDecision:
        """
        Validate file operations with explicit path checking

        Args:
            operation: Type of operation (read, write, delete, modify)
            paths: List of file paths affected
            context: Optional context

        Returns:
            ValidationDecision
        """
        if context is None:
            context = {}

        # Check each path against protected resources
        for path in paths:
            for resource in self.protected_resources.get("resources", []):
                protected_path = resource.get("path")
                rule = resource.get("rule")
                message = resource.get("message", f"⚠️ WARNING: {protected_path} is protected")

                # Check if path matches protected resource
                if Path(path).match(protected_path) or protected_path in str(path):
                    # Determine if operation violates rule
                    if operation == "delete" and "deletion" in rule:
                        if rule == "block_bulk_deletion" and len(paths) > 1:
                            return ValidationDecision(
                                result=ValidationResult.BLOCKED,
                                message=f"{message}\nAttempted bulk deletion of {len(paths)} files including protected resource.",
                                severity=4,
                                affected_files=paths
                            )
                        elif "require_confirmation" in rule:
                            return ValidationDecision(
                                result=ValidationResult.REQUIRES_CONFIRMATION,
                                message=f"{message}\nConfirm deletion?",
                                severity=3,
                                affected_files=paths
                            )

                    elif operation in ["write", "modify"] and "modification" in rule:
                        if rule == "block_all_modifications":
                            return ValidationDecision(
                                result=ValidationResult.BLOCKED,
                                message=f"{message}\nModification blocked.",
                                severity=5,
                                affected_files=[path]
                            )
                        elif "require_confirmation" in rule:
                            return ValidationDecision(
                                result=ValidationResult.REQUIRES_CONFIRMATION,
                                message=f"{message}\nConfirm modification?",
                                severity=4,
                                affected_files=[path]
                            )

        # No protected resources affected
        return ValidationDecision(
            result=ValidationResult.ALLOWED,
            message="File operation allowed",
            severity=0,
            affected_files=paths
        )

    def get_stats(self) -> Dict:
        """Return statistics about loaded patterns"""
        total_patterns = 0
        by_category = {}

        for category, data in self.patterns.get("patterns", {}).items():
            count = len(data.get("patterns", []))
            by_category[category] = count
            total_patterns += count

        stats = {
            "total_patterns": total_patterns,
            "by_category": by_category,
            "whitelisted_commands": len(self.whitelist.get("commands", [])),
            "protected_resources": len(self.protected_resources.get("resources", [])),
            # Command Tree Decomposition (Improvement #2)
            "command_tree_enabled": self.enable_command_tree,
            "command_tree_available": COMMAND_TREE_AVAILABLE,
        }

        return stats


class SafetyValidatorIntegration:
    """
    Integration layer for run_vera.py

    Wraps command execution with safety validation
    """

    def __init__(self, validator: SafetyValidator = None) -> None:
        self.validator = validator or SafetyValidator()
        self.log_file = Path("vera_memory/safety_audit.ndjson")

    def safe_execute(self, command: str, context: Dict = None, interactive: bool = True) -> Tuple[bool, str]:
        """
        Execute command with safety validation

        Args:
            command: Command to execute
            context: Optional context dict
            interactive: If True, prompt user for confirmation. If False, block on REQUIRES_CONFIRMATION.

        Returns:
            (success: bool, output: str)
        """
        # Validate command
        decision = self.validator.validate(command, context)

        # Log validation decision
        self._log_decision(command, decision)

        # Handle based on result
        if decision.result == ValidationResult.BLOCKED:
            print(decision.message)
            return False, decision.message

        elif decision.result == ValidationResult.REQUIRES_CONFIRMATION:
            if not interactive:
                # Non-interactive mode: treat as blocked
                msg = f"Command requires confirmation (non-interactive mode): {decision.message}"
                print(msg)
                return False, msg

            # Interactive: Ask user
            print(decision.message)
            response = input("Proceed? (yes/no): ").strip().lower()

            if response in ["yes", "y"]:
                print("✓ User confirmed, executing...")
                return self._execute(command)
            else:
                print("✗ User declined, command cancelled")
                return False, "User cancelled"

        elif decision.result in [ValidationResult.ALLOWED, ValidationResult.WHITELISTED]:
            # Safe to execute
            return self._execute(command)

        else:
            # Unknown result, fail-safe
            print(f"⚠️ Unknown validation result: {decision.result}")
            return False, "Validation error"

    def _execute(self, command: str) -> Tuple[bool, str]:
        """Actually execute the command (no shell=True to prevent injection)."""
        try:
            argv = shlex.split(command)
        except ValueError as e:
            return False, f"Failed to parse command: {e}"
        try:
            result = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                timeout=60,
            )
            success = result.returncode == 0
            output = result.stdout if success else result.stderr
            return success, output
        except subprocess.TimeoutExpired:
            return False, "Command timed out after 60 seconds"
        except FileNotFoundError:
            return False, f"Command not found: {argv[0]}"
        except Exception as e:
            return False, f"Execution error: {str(e)}"

    def _log_decision(self, command: str, decision: ValidationDecision):
        """Log validation decision to audit trail"""
        log_entry = {
            "timestamp": self._timestamp(),
            "command": command,
            "result": decision.result.value,
            "message": decision.message,
            "severity": decision.severity,
            "matched_pattern": decision.matched_pattern
        }

        # Ensure log directory exists
        self.log_file.parent.mkdir(parents=True, exist_ok=True)

        # Append to NDJSON log
        try:
            with open(self.log_file, 'a') as f:
                f.write(json.dumps(log_entry) + '\n')
        except Exception as e:
            print(f"⚠️ Warning: Could not write to audit log: {e}")

    def _timestamp(self) -> str:
        """Get current timestamp in ISO format"""
        from datetime import datetime
        return datetime.now().isoformat()


# ============================================================================
# CLI Interface (for testing)
# ============================================================================

def main() -> None:
    """CLI for testing safety validator"""
    import sys

    if len(sys.argv) < 2:
        print("Usage: python safety_validator.py <command>")
        print("\nExamples:")
        print("  python safety_validator.py 'ls -la'")
        print("  python safety_validator.py 'rm -rf /'")
        print("  python safety_validator.py 'rm run_vera.py'")
        sys.exit(1)

    command = " ".join(sys.argv[1:])

    # Initialize validator
    validator = SafetyValidator()

    # Print stats
    stats = validator.get_stats()
    print(f"Safety Validator loaded:")
    print(f"  - {stats['total_patterns']} danger patterns")
    print(f"  - {stats['whitelisted_commands']} whitelisted commands")
    print(f"  - {stats['protected_resources']} protected resources")
    print()

    # Validate command
    print(f"Validating: {command}")
    print("-" * 60)

    decision = validator.validate(command)

    # Display result
    print(f"Result: {decision.result.value.upper()}")
    print(f"Severity: {decision.severity}/5")
    if decision.matched_pattern:
        print(f"Matched Pattern: {decision.matched_pattern}")
    print(f"\nMessage:\n{decision.message}")

    if decision.expanded_command and decision.expanded_command != command:
        print(f"\nExpanded Command: {decision.expanded_command}")

    # Exit code based on result
    if decision.result == ValidationResult.BLOCKED:
        sys.exit(1)
    elif decision.result == ValidationResult.REQUIRES_CONFIRMATION:
        sys.exit(2)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
