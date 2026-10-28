"""Offline adaptive spectral denoising on voice only; preserve sample timing.
RNNoise weights tested on this recording were unstable; production uses afftdn.
"""
import math
MODES=('off','gentle','strong')
DELAY=.025

def validate(value='off'):
    if not isinstance(value,str) or value not in MODES:raise ValueError('降噪选项无效')
    return value

def audio_filter(mode='off',duration=None):
    validate(mode)
    if mode=='off':return None
    if type(duration) not in (int,float) or not math.isfinite(duration) or duration<=0:raise ValueError('降噪音轨时长无效')
    params='nr=10:nf=-35:tn=1:gs=5' if mode=='gentle' else 'nr=16:nf=-30:tn=1:gs=8'
    # Measured 1200-sample delay at 48kHz. Flush then trim to preserve sync.
    return f'aresample=48000,apad=pad_dur={DELAY},afftdn={params},atrim=start={DELAY}:end={duration+DELAY:.6f},asetpts=PTS-STARTPTS'

def receipt(mode='off'):
    validate(mode)
    return {'mode':mode,'engine':'FFmpeg afftdn adaptive FFT' if mode!='off' else None,'model':None,'delayCompensatedMs':25 if mode!='off' else 0,'voiceOnly':True,'preGain':1,'restoreGain':1,'noiseReductionDb':10 if mode=='gentle' else 16 if mode=='strong' else 0,'noiseTracking':mode!='off'}
