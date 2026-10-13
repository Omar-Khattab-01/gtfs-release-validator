"""Accept Explorer's Copy as path and unquoted local paths alike."""


def normalize_path(value) -> str:
    text = str(value or '').strip()
    pairs = {'"':'"', "'":"'", '“':'”', '‘':'’'}
    while len(text) >= 2 and pairs.get(text[0]) == text[-1]:
        text = text[1:-1].strip()
    return text
