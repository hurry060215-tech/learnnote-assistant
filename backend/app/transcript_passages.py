"""Caption retrieval passages follow cue boundaries, not a fixed visual index."""
def caption_passages(segments, max_seconds=120, max_chars=900):
    groups, current, chars = [], [], 0
    for item in sorted(segments, key=lambda value: (value["start"], value["end"])):
        if item["end"] <= item["start"]:
            continue
        if current:
            pause = item["start"] - current[-1]["end"]
            duration = item["end"] - current[0]["start"]
            sentence_end = current[-1]["text"].rstrip().endswith(("。", "！", "？", ".", "!", "?"))
            if pause > 3 or duration > max_seconds or chars + len(item["text"]) > max_chars or (chars >= 450 and sentence_end):
                groups.append(current)
                current, chars = [], 0
        current.append(item)
        chars += len(item["text"])
    if current:
        groups.append(current)
    return groups
