"""Scope search candidates without treating software omission as user deletion."""
import re
VERSION=1

def full_source_search(messages):
    latest=next((m.get('content','') for m in reversed(messages) if m.get('role')=='user'),'')
    requested=False
    for clause in re.split(r'[，,。；;\n]',latest):
        if re.search(r'只(?:看|改|调整|处理|复核)(?:这份|当前|现有)(?:成片|稿|文稿)',clause):requested=False
        if not re.search(r'完整访谈|完整原稿|整段访谈|全部原片|原始访谈',clause):continue
        if re.search(r'不要|不必|不需要|无需|不能|别从|不从',clause):continue
        if re.search(r'从|通读|重新看|重看|搜索|寻找|查找|回到',clause):requested=True
    return requested

def context_rows(rows,allowed_ids):
    return [{**r,'availability':'not-retrieved-candidate' if r['id'] in allowed_ids else 'excluded-from-current-draft'} for r in rows]
