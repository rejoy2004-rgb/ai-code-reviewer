import re
from typing import Dict, List, Set, NamedTuple, Optional


class DiffHunk(NamedTuple):
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: List[str]


class ParsedDiff(NamedTuple):
    added_lines: Set[int]          # 1-indexed line numbers added/modified in the new file (RIGHT side)
    deleted_lines: Set[int]        # 1-indexed line numbers deleted in the old file (LEFT side)
    line_to_content: Dict[int, str] # Maps new line number to the string content
    hunks: List[DiffHunk]


def parse_patch(patch_str: Optional[str]) -> ParsedDiff:
    """
    Parses a GitHub unified diff patch string.
    Returns:
        ParsedDiff containing sets of added/deleted lines, content mappings, and structured hunks.
    """
    added_lines: Set[int] = set()
    deleted_lines: Set[int] = set()
    line_to_content: Dict[int, str] = {}
    hunks: List[DiffHunk] = []

    if not patch_str:
        return ParsedDiff(added_lines, deleted_lines, line_to_content, hunks)

    hunk_header_regex = re.compile(r"^@@\s+-(\d+),?(\d*)\s+\+(\d+),?(\d*)\s+@@")
    
    current_new_line = 0
    current_old_line = 0
    current_hunk_lines: List[str] = []
    current_hunk_header: Optional[re.Match] = None

    lines = patch_str.splitlines()
    for line in lines:
        match = hunk_header_regex.match(line)
        if match:
            # If we were processing a hunk, save it
            if current_hunk_header:
                old_start = int(current_hunk_header.group(1))
                old_count = int(current_hunk_header.group(2)) if current_hunk_header.group(2) else 1
                new_start = int(current_hunk_header.group(3))
                new_count = int(current_hunk_header.group(4)) if current_hunk_header.group(4) else 1
                hunks.append(DiffHunk(old_start, old_count, new_start, new_count, current_hunk_lines))
            
            # Start a new hunk
            current_hunk_header = match
            current_hunk_lines = [line]
            
            # Extract line starts
            current_old_line = int(match.group(1))
            current_new_line = int(match.group(3))
            continue

        if current_hunk_header:
            current_hunk_lines.append(line)
            if line.startswith("+"):
                added_lines.add(current_new_line)
                line_to_content[current_new_line] = line[1:]
                current_new_line += 1
            elif line.startswith("-"):
                deleted_lines.add(current_old_line)
                current_old_line += 1
            else:
                # Context line (space prefix or empty)
                current_new_line += 1
                current_old_line += 1

    # Save the last hunk
    if current_hunk_header:
        old_start = int(current_hunk_header.group(1))
        old_count = int(current_hunk_header.group(2)) if current_hunk_header.group(2) else 1
        new_start = int(current_hunk_header.group(3))
        new_count = int(current_hunk_header.group(4)) if current_hunk_header.group(4) else 1
        hunks.append(DiffHunk(old_start, old_count, new_start, new_count, current_hunk_lines))

    return ParsedDiff(added_lines, deleted_lines, line_to_content, hunks)


def get_closest_valid_line(target_line: int, valid_lines: Set[int]) -> Optional[int]:
    """
    If Gemini reviews a file and identifies an issue at a line that is NOT in the list of
    modified/added lines, we want to find the closest line that IS in the modified lines.
    If no modified lines exist or it's too far, returns None.
    """
    if not valid_lines:
        return None
    if target_line in valid_lines:
        return target_line
    
    # Find closest line by absolute distance
    closest = min(valid_lines, key=lambda l: abs(l - target_line))
    # If the closest line is within a reasonable distance (e.g. 5 lines), return it.
    # Otherwise, returning None is safer so we don't post a comment on a completely unrelated change.
    if abs(closest - target_line) <= 5:
        return closest
    return None
