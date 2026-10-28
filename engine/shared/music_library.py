"""Metadata-aware low-presence beds and selected-track attribution."""
def choose(tracks,tone='clear'):
    def score(t):
        category=t.get('category','');scenes=t.get('scenes',[]);n=4 if t.get('tier')=='A' else 0
        if category in ({'平静陪伴':8,'情绪叙事':3} if tone=='warm' else {'商务积极':8,'轻松日常':3} if tone=='energetic' else {'通用讲解':8,'爵士质感':4}):n+=({'平静陪伴':8,'情绪叙事':3} if tone=='warm' else {'商务积极':8,'轻松日常':3} if tone=='energetic' else {'通用讲解':8,'爵士质感':4})[category]
        if any(s in scenes for s in ['知识科普','聊天访谈','教程']):n+=4
        if category in ['幽默短段','电影力量段落']:n-=12
        if {'warm':'温暖','clear':'沉稳','energetic':'利落'}.get(tone,'沉稳') in t.get('name',''):n+=5
        return n
    return max(tracks,key=score) if tracks else None

def recommended_volume(track):
    value=track.get('recommendedGainDb') if track else None
    return max(0,min(1,10**(value/20))) if isinstance(value,(int,float)) else .1

def write_credit(folder,track):
    if not track or not track.get('attribution'):return None
    path=folder/'music-attribution.txt'
    path.write_text(track['attribution'].rstrip()+'\nEdited / mixed for this video.\n',encoding='utf8')
    return path
