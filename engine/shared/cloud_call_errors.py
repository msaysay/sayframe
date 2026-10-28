"""Safe provider failures; never copy response bodies or credentials to UI."""
class TransientConnection(ValueError):
    def __init__(self):
        super().__init__('云端连接暂时中断；已完成的方案和原稿保留')

class RateLimited(ValueError):
    def __init__(self,retry_after=None):
        self.retry_after=retry_after
        super().__init__('小米接口当前繁忙，请稍后再试；原视频和编辑稿已保留')

class IncompleteResponse(ValueError):
    def __init__(self,usage,finish):
        from analysis_usage import safe_usage
        self.usage=safe_usage(usage);self.finish=finish if finish in ('length','stop','content_filter') else 'incomplete'
        super().__init__('剪辑分析没有完整返回，请稍后重试')

def http_failure(error):
    if error.code==429:
        raw=str(error.headers.get('Retry-After','')) if error.headers else ''
        return RateLimited(min(30,int(raw)) if raw.isdigit() else None)
    if error.code in (401,403):return ValueError('小米连接未通过验证，请检查普通API连接；原稿已保留')
    return ValueError('小米暂时没有完成分析，请稍后重试；原稿已保留')
