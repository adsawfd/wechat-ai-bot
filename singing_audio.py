"""Conservative local melody check for unlabelled, model-native singing.

The provider labels some genuine singing as 'default'. Sustained pitches at
several note heights distinguish our verified examples from spoken lyrics.
This is a heuristic, not a music-quality score; uncertain audio is rejected.
"""
import math


def has_melody(pcm, sample_rate=24000):
    import numpy as np
    if not isinstance(pcm, bytes) or len(pcm) % 2 or not 3 <= len(pcm)/(sample_rate*2) <= 46:
        return False
    signal = np.frombuffer(pcm, dtype='<i2').astype(np.float64) / 32768
    stride = max(1, sample_rate // 12000)
    signal = signal[::stride]
    rate = sample_rate / stride
    window, hop = int(rate*.080), int(rate*.020)
    low, high = int(rate/900), int(rate/75)
    notes = []
    for offset in range(0, len(signal)-window, hop):
        frame = signal[offset:offset+window].copy()
        frame -= frame.mean()
        if np.sqrt(np.mean(frame*frame)) < .008:
            notes.append(np.nan)
            continue
        # YIN cumulative normalized difference, using FFT autocorrelation.
        spectrum = np.fft.rfft(frame, n=2048)
        correlation = np.fft.irfft(spectrum*spectrum.conj(), n=2048)[:high+1]
        energy = np.r_[0., np.cumsum(frame*frame)]
        lag = np.arange(high+1)
        difference = np.maximum(0, energy[window-lag]+energy[window]-energy[lag]-2*correlation)
        cmnd = np.ones(high+1)
        cmnd[1:] = difference[1:]*lag[1:] / np.maximum(1e-12,np.cumsum(difference[1:]))
        candidates = [i for i in range(low, high)
                      if cmnd[i]<.22 and cmnd[i]<=cmnd[i-1] and cmnd[i]<cmnd[i+1]]
        chosen = candidates[0] if candidates else int(low+np.argmin(cmnd[low:high]))
        if cmnd[chosen] > .25:
            notes.append(np.nan)
            continue
        shift = 0.
        if 1 <= chosen < high:
            a,b,c = cmnd[chosen-1:chosen+2]
            denominator = a-2*b+c
            if denominator:
                shift = float(np.clip(.5*(a-c)/denominator,-.5,.5))
        notes.append(69+12*math.log2(rate/(chosen+shift)/440))
    notes = np.asarray(notes)
    held = []
    for start in range(len(notes)-9):
        group = notes[start:start+10]
        valid = group[np.isfinite(group)]
        if len(valid)>=9 and np.quantile(valid,.9)-np.quantile(valid,.1)<=.65:
            held.append(float(np.median(valid)))
    if len(held) < max(20, .22*len(notes)):
        return False
    # Reject silence, tones, and sustained speech at a single pitch.
    distinct = set(round(note) for note in held)
    return bool(len(distinct)>=3 and np.quantile(held,.9)-np.quantile(held,.1)>=2)
