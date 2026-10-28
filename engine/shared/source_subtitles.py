def validate_source_subtitle_status(value='unknown'):
    if not isinstance(value,str) or value not in ('unknown','present','absent'):
        raise ValueError('原画面字幕状态无效')
    return value
