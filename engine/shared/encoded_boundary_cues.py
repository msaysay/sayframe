"""Read-only, source-bound cues at encoded phrase-cut boundaries.

Independent blind windows must agree. A cue is never permission to delete or
restore speech, normalize a number/negation, or certify an entire movie.
"""
import difflib, math

VERSION = 1


def plain(text):
    return ''.join(c.upper() for c in text if c.isalnum())


def analyze(target, trace, retained, lo, hi):
    point = target['nearSeconds']
    # Avoid crop-edge recognition errors. Word timing is only a localization
    # hint; it never supplies a cutting time or independent acoustic evidence.
    low, high = lo + .25, hi - .25
    expected = []
    for word in retained:
        if not isinstance(word.get('id'), str) or type(word.get('wordIndex')) is not int:
            continue
        if word['nearSeconds'] < low or word['endSeconds'] > high:
            continue
        expected.extend({**word, 'char': c} for c in plain(word['word']))
    observed = []
    for token in trace:
        time = token.get('time'); probability = token.get('probability')
        char = plain(token.get('text', ''))
        if (len(char) != 1 or type(time) not in (int, float) or not math.isfinite(time)
                or type(probability) not in (int, float) or not math.isfinite(probability)
                or not low <= time <= high):
            continue
        observed.append({'char': char, 'time': time, 'probability': probability})
    expected_text = ''.join(w['char'] for w in expected)
    observed_text = ''.join(w['char'] for w in observed)
    codes = difflib.SequenceMatcher(None, expected_text, observed_text, autojunk=False).get_opcodes()
    anchors = []
    for tag, a, b, c, d in codes:
        if tag == 'equal':
            anchors.extend((expected[i], observed[c + i - a]) for i in range(a, b)
                           if observed[c + i - a]['probability'] >= .55
                           and abs(observed[c + i - a]['time'] - expected[i]['nearSeconds']) <= .6)
    nearby = [(w, t) for w, t in anchors if abs(t['time'] - point) <= 2]
    # Repeated character tokens from one original word are one anchor.
    refs = {(w['id'], w['wordIndex']) for w, _ in nearby}
    covered = len(refs) >= 2
    guards = {(w['id'], w['wordIndex']) for w in target.get('neighbors', [])}
    events = []
    if covered:
        for tag, a, b, c, d in codes:
            if tag == 'equal':
                continue
            old, new = expected[a:b], observed[c:d]
            # Normal-word differences require the actual kept original word
            # beside this cut, not an unrelated omission elsewhere in a crop.
            for word in old:
                ref = (word['id'], word['wordIndex'])
                if ref not in guards or abs(word['nearSeconds'] - point) > .65:
                    continue
                if any(t['probability'] < .55 for t in new):
                    continue
                recognized = ''.join(t['char'] for t in new)
                if new and min(abs(t['time'] - point) for t in new) > .65:
                    continue
                events.append({'kind': 'replace' if new else 'delete', 'expected': word['char'],
                               'recognized': recognized, 'source': {k: word[k] for k in
                               ('id', 'wordIndex', 'word', 'nearSeconds')}, 'at': word['nearSeconds']})
            if tag != 'insert':
                continue
            close = [t for t in new if abs(t['time'] - point) <= .4 and t['probability'] >= .55]
            extra = ''.join(t['char'] for t in close)
            removed = target['quote']
            # Single normal characters cannot establish phrase residue. A
            # retained duplicate may also be a recognizer error: cue only.
            if len(extra) >= 2 and extra in removed:
                events.append({'kind': 'insert', 'expected': '', 'recognized': extra,
                               'source': target['source'], 'at': close[0]['time']})
    return {'covered': covered, 'matchedNeighborAnchors': len(refs), 'events': events[:6]}


def agree(target, windows):
    if len(windows) != 2 or windows[0]['window'] == windows[1]['window']:
        return []
    if not all(w.get('boundary', {}).get('covered') for w in windows):
        return []
    issues = []
    for event in windows[0]['boundary']['events']:
        other = next((e for e in windows[1]['boundary']['events']
                      if (e['kind'], e['expected'], e['recognized'], e['source']['id'], e['source']['wordIndex'])
                      == (event['kind'], event['expected'], event['recognized'], event['source']['id'], event['source']['wordIndex'])
                      and abs(e['at'] - event['at']) <= .12), None)
        if other is None:
            continue
        issues.append({k: event[k] for k in ('kind', 'expected', 'recognized', 'source')})
    return issues
