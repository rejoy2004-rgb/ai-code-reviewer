from app.utils.diff_parser import parse_patch, get_closest_valid_line


def test_parse_patch():
    patch = (
        "@@ -1,4 +1,6 @@\n"
        " context line\n"
        "-removed line\n"
        "+added line 1\n"
        "+added line 2\n"
        " other context line\n"
        "@@ -10,3 +12,4 @@\n"
        " context line\n"
        "+added line 3\n"
        " context line"
    )
    parsed = parse_patch(patch)
    
    # Assert added lines (1-indexed based on new file starts)
    # Hunk 1: starts at new_start=1.
    # line 1: context (new line 1)
    # line 2: removed (does not increment new line)
    # line 3: added line 1 (new line 2)
    # line 4: added line 2 (new line 3)
    # line 5: other context (new line 4)
    # Hunk 2: starts at new_start=12.
    # line 1: context (new line 12)
    # line 2: added line 3 (new line 13)
    
    assert 2 in parsed.added_lines
    assert 3 in parsed.added_lines
    assert 13 in parsed.added_lines
    assert 1 in parsed.line_to_content or 1 not in parsed.added_lines
    
    assert parsed.line_to_content[2] == "added line 1"
    assert parsed.line_to_content[3] == "added line 2"
    assert parsed.line_to_content[13] == "added line 3"


def test_get_closest_valid_line():
    valid = {10, 11, 12, 20}
    # Matches exactly
    assert get_closest_valid_line(11, valid) == 11
    # Shifts to closest
    assert get_closest_valid_line(13, valid) == 12
    # Too far (> 5 lines away)
    assert get_closest_valid_line(26, valid) is None
