"""Resolve portable metadata paths while retaining legacy absolute records."""
import pathlib

def resolve_record_paths(record,workspace):
    result=dict(record);workspace=pathlib.Path(workspace).resolve()
    for field in ('video_path','audio_path'):
        value=result.get(field)
        if not value:continue
        path=pathlib.Path(value)
        if not path.is_absolute():
            path=(workspace/path).resolve()
            if not path.is_relative_to(workspace):raise ValueError('素材相对路径超出工作台目录')
        result[field]=str(path)
    return result

def portable_path(path,workspace):
    path=pathlib.Path(path).resolve();workspace=pathlib.Path(workspace).resolve()
    if not path.is_relative_to(workspace):raise ValueError('素材不在工作台目录')
    return path.relative_to(workspace).as_posix()
