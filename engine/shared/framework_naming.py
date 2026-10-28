"""Shared public framework names; canonical editing IDs and course evidence stay unchanged."""
import json
from pathlib import Path

_registry = json.loads((Path(__file__).resolve().parent/'src'/'framework-branding.json').read_text(encoding='utf-8'))
VERSION = _registry['version']
_rows = _registry['frameworks']
_aliases = {name: row['id'] for row in _rows for name in [row['id'], row['name'], *row['aliases']]}
_names = {row['id']: row['name'] for row in _rows}

def framework_id(value):
    return _aliases.get(value, value)

def framework_name(value):
    return _names.get(framework_id(value), value)

RULE = ('SAYFRAME界面命名与协议兼容：用户说新名字或旧名字，均指向同一套既有剪辑方法，不改变适用条件、环节或声音保护。'
        '对应关系（界面名→协议ID）：'+ '；'.join(row['name']+'→'+row['id'] for row in _rows)+
        '。大四喜同样对应协议ID四喜。结构化framework、selectedFramework、suggestedFramework等枚举字段必须继续返回协议ID，'
        '不能把新名字写入这些字段；面向用户的策略说明使用界面名。原话引用、字幕、课程出处和历史回执必须逐字保留，'
        '不能为了换名称替换素材里实际说过的词；命名不赋予视频新的事实或证据。')
