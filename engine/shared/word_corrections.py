"""Display-only spelling fixes; original word coordinates and evidence stay intact."""
import re
def validate(value,words):
    if value is None:return {}
    if not isinstance(value,dict) or len(value)>len(words):raise ValueError('错字校正无效')
    for index,text in value.items():
        if not isinstance(index,str) or not re.fullmatch(r'0|[1-9]\d*',index) or int(index)>=len(words) or not isinstance(text,str) or not text.strip() or len(text)>24 or any(ord(c)<32 for c in text):raise ValueError('错字校正无效')
    return dict(value)
def display_words(segment):
    corrections=validate(segment.get('wordCorrections'),segment['words'])
    return [{**w,'word':corrections.get(str(i),w['word'])} for i,w in enumerate(segment['words'])]
