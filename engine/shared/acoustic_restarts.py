"""Find repeated source syllables omitted by transcription, without deleting.

Both recognition windows must independently contain the same extra immediate
copy. This is a repair/re-listen candidate, never an invented word timestamp.
"""
import difflib

NATURAL={'想想','看看','等等','慢慢','好好','人人','个个','常常','渐渐','刚刚','仅仅','稍稍','种种','处处','往往','多多','年年','天天','时时','家家','次次'}


def _candidates(expected,heard):
    result=[]
    for kind,a,b,c,d in difflib.SequenceMatcher(a=expected,b=heard,autojunk=False).get_opcodes():
        extra=heard[c:d]
        if kind!='insert' or not 1<=len(extra)<=6:continue
        if extra*2 in NATURAL or extra in NATURAL:continue
        if not (expected[a:a+len(extra)]==extra or expected[max(0,a-len(extra)):a]==extra):continue
        # Don't align a stray recognized copy at a wholly mismatched seam.
        left=expected[max(0,a-5):a];right=expected[a:a+5]
        if heard[max(0,c-len(left)):c]!=left or heard[d:d+len(right)]!=right:continue
        result.append({'offset':a,'quote':extra,'left':left,'right':right})
    return result


def detect(expected,first,second):
    clean=lambda text:''.join(c for c in text if c.isalnum()).upper()
    want=clean(expected);a=_candidates(want,clean(first));b=_candidates(want,clean(second))
    return [{**item,'reason':'两次原音均识别到文稿未列出的紧邻重说；需重新校准，不能只改字幕','automatic':False} for item in a if item in b]
