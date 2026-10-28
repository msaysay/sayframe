"""Fast proposal assembly; flagship review remains the execution gate."""
VERSION=2
FAST_PHASES=frozenset(('interview-catalog','speech-detection','visual-brief'))
def model_for_phase(phase,thinking='disabled'):
    import mimo
    return 'mimo-v2.6-flash' if thinking=='disabled' and phase in FAST_PHASES else mimo.MODEL
