"""Locate stop-pattern changes without treating an insertion as shifted stops."""
from difflib import SequenceMatcher


def change_positions(a_start, a_end, b_start, b_end, a_length, b_length):
    first = a_start == 0 and b_start == 0
    last = a_end == a_length and b_end == b_length
    positions = []
    if first:
        positions.append('first')
    if (not first and not last) or (first and last and max(a_length,b_length) > 2):
        positions.append('middle')
    if last:
        positions.append('last')
    return positions


def mismatch_positions(left, right):
    if not left or not right:
        return []  # Missing counterparts are source-only, not proven mismatches.
    positions = set()
    for tag,a,b,c,d in SequenceMatcher(a=left,b=right,autojunk=False).get_opcodes():
        if tag != 'equal':
            positions.update(change_positions(a,b,c,d,len(left),len(right)))
    return [position for position in ('first','middle','last') if position in positions]
