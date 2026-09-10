"""Explicit acquisition presets, in samples per second."""
SAMPLE_RATES=(2_400_000,2_560_000,4_000_000,8_000_000,10_000_000,
              12_000_000,15_360_000,16_000_000,20_000_000,30_720_000,61_440_000)


def usable_bandwidth(settings):
    if settings.backend=='PlutoSDR':
        return min(settings.sample_rate,settings.rf_bandwidth or 20_000_000,20_000_000)
    if settings.backend=='Rejeu SigMF' and settings.rf_bandwidth>0:
        return min(settings.sample_rate,settings.rf_bandwidth)
    return settings.sample_rate
