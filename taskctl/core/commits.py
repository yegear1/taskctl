"""Conventional Commits parser and validation engine for taskctl.

Adheres to Conventional Commits 1.0.0 specification:
<type>[optional scope][!]: <description>

[optional body]

[optional footer(s)]
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

STANDARD_TYPES: Set[str] = {
    "feat",
    "fix",
    "docs",
    "style",
    "refactor",
    "perf",
    "test",
    "build",
    "ci",
    "chore",
    "revert",
}

MAX_HEADER_LENGTH: int = 100

HEADER_REGEX = re.compile(
    r"^(?P<type>[a-zA-Z0-9_\-]+)(?:\((?P<scope>[a-zA-Z0-9_\-\/\.]+)\))?(?P<breaking>!)?:\s+(?P<description>.+)$"
)

FOOTER_REGEX = re.compile(
    r"^(?P<token>BREAKING CHANGE|BREAKING-CHANGE|[a-zA-Z0-9_\-]+)(?::\s+|\s+#)(?P<value>.+)$"
)


@dataclass
class ConventionalCommit:
    """Structured representation of a parsed Conventional Commit."""

    type: str
    description: str
    scope: Optional[str] = None
    is_breaking: bool = False
    body: Optional[str] = None
    footers: List[Dict[str, str]] = field(default_factory=list)
    raw: str = ""

    @property
    def header(self) -> str:
        scope_str = f"({self.scope})" if self.scope else ""
        break_str = "!" if self.is_breaking else ""
        return f"{self.type}{scope_str}{break_str}: {self.description}"


@dataclass
class CommitValidationResult:
    """Validation outcome for a commit message."""

    is_valid: bool
    errors: List[str]
    commit: Optional[ConventionalCommit] = None
    raw_message: str = ""

    @property
    def summary(self) -> str:
        if self.is_valid and self.commit:
            scope_part = f"({self.commit.scope})" if self.commit.scope else ""
            break_part = " [BREAKING]" if self.commit.is_breaking else ""
            return f"Valid Conventional Commit: {self.commit.type}{scope_part}{break_part}: {self.commit.description}"
        return f"Invalid Conventional Commit ({len(self.errors)} error(s)): " + "; ".join(self.errors)


def strip_git_comments(message: str) -> str:
    """Strips git comment lines (starting with '#') and trims whitespace."""
    lines = [line for line in message.splitlines() if not line.strip().startswith("#")]
    # Remove leading and trailing empty lines
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines)


def parse_conventional_commit(
    message: str,
    allowed_types: Optional[Set[str]] = None,
    max_header_length: int = MAX_HEADER_LENGTH,
) -> CommitValidationResult:
    """Parses and validates a commit message against Conventional Commits specification.

    Args:
        message: The raw commit message string.
        allowed_types: Set of allowed commit types (defaults to STANDARD_TYPES).
        max_header_length: Maximum allowed character length for the header line.

    Returns:
        CommitValidationResult containing validation status, errors, and parsed commit.
    """
    valid_types = allowed_types if allowed_types is not None else STANDARD_TYPES
    cleaned = strip_git_comments(message)

    if not cleaned.strip():
        return CommitValidationResult(
            is_valid=False,
            errors=["Commit message is empty."],
            raw_message=message,
        )

    lines = cleaned.splitlines()
    header = lines[0].strip()
    errors: List[str] = []

    # Check header length
    if len(header) > max_header_length:
        errors.append(
            f"Header line exceeds maximum length of {max_header_length} chars (length={len(header)})."
        )

    match = HEADER_REGEX.match(header)
    if not match:
        # Provide diagnostic feedback
        if ":" not in header:
            errors.append("Header is missing a colon ':' separating type/scope and description.")
        elif ": " not in header:
            errors.append("Header must have a space after the colon, e.g. 'type(scope): description'.")
        else:
            errors.append(
                "Header format does not match Conventional Commits: '<type>(<scope>)?: <description>'."
            )
        return CommitValidationResult(
            is_valid=False,
            errors=errors,
            raw_message=message,
        )

    commit_type = match.group("type")
    scope = match.group("scope")
    breaking_indicator = bool(match.group("breaking"))
    description = match.group("description").strip()

    # Verify type is lowercase and valid
    if commit_type != commit_type.lower():
        errors.append(f"Commit type '{commit_type}' must be lowercase (e.g. '{commit_type.lower()}').")

    normalized_type = commit_type.lower()
    if normalized_type not in valid_types:
        errors.append(
            f"Commit type '{commit_type}' is not recognized. Allowed types: {', '.join(sorted(valid_types))}."
        )

    if not description:
        errors.append("Commit description (subject) cannot be empty.")

    # Validate separation between header and body if multiple lines exist
    body_lines: List[str] = []
    footer_lines: List[str] = []
    footers: List[Dict[str, str]] = []
    is_breaking = breaking_indicator

    if len(lines) > 1:
        if lines[1].strip() != "":
            errors.append("A blank line is required between the commit header and body.")

        # Process rest of message (body and footers)
        # Scan paragraphs from bottom up to find footers
        remaining_lines = lines[2:] if len(lines) > 2 else []
        
        # Split remaining lines into paragraphs separated by blank lines
        paragraphs: List[List[str]] = []
        curr_p: List[str] = []
        for l in remaining_lines:
            if not l.strip():
                if curr_p:
                    paragraphs.append(curr_p)
                    curr_p = []
            else:
                curr_p.append(l)
        if curr_p:
            paragraphs.append(curr_p)

        body_paragraphs: List[str] = []
        for p in paragraphs:
            # Check if this paragraph consists of footers
            is_footer_p = False
            p_footers: List[Dict[str, str]] = []
            for l in p:
                f_match = FOOTER_REGEX.match(l)
                if f_match:
                    token = f_match.group("token")
                    val = f_match.group("value")
                    p_footers.append({"token": token, "value": val})
                    if token in ("BREAKING CHANGE", "BREAKING-CHANGE"):
                        is_breaking = True
                else:
                    p_footers = []
                    break
            
            if p_footers:
                footers.extend(p_footers)
            else:
                body_paragraphs.append("\n".join(p))

        body = "\n\n".join(body_paragraphs) if body_paragraphs else None
    else:
        body = None

    if errors:
        return CommitValidationResult(
            is_valid=False,
            errors=errors,
            raw_message=message,
        )

    parsed = ConventionalCommit(
        type=normalized_type,
        scope=scope,
        is_breaking=is_breaking,
        description=description,
        body=body,
        footers=footers,
        raw=message,
    )

    return CommitValidationResult(
        is_valid=True,
        errors=[],
        commit=parsed,
        raw_message=message,
    )
