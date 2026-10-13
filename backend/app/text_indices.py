"""Translate case-insensitive match positions without rewriting source text."""


def original_casefold_offset(text: str, offset: int) -> int:
    """Map a folded code-point offset, including the inside of an expansion."""
    if offset < 0:
        return -1
    folded_end = 0
    for index, character in enumerate(text):
        folded_end += len(character.casefold())
        if folded_end > offset:
            return index
    return len(text)
