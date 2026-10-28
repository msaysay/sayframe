"""Conservative recognition check for physical speech-run edges."""
import re


def matches(expected,heard):
    normalize=lambda text:''.join(c for c in text if c.isalnum()).upper()
    want=normalize(expected);got=normalize(heard)
    # A retained interjection can be absent from recognition. An interjection
    # that is NOT in the retained text cannot be silently ignored in the audio.
    if re.match('^[呃嗯额啊哦]',want):
        want=re.sub('^[呃嗯额啊哦]+','',want);got=re.sub('^[呃嗯额啊哦]+','',got)
    if not want or not got:return False,False
    return got.startswith(want[:min(2,len(want))]),got.endswith(want[-min(2,len(want)):])
