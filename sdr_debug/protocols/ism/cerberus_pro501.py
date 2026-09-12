"""Receive-only CERBERUS / Selectronic PRO-501 OOK decoder.

The transmitter uses PWM with a markedly variable duty cycle.  Decisions are
therefore made from two clusters of HIGH/(HIGH+LOW) ratios for each burst,
never from a fixed pulse duration.
"""
from dataclasses import dataclass
from hashlib import sha256
from typing import Iterable
import numpy as np

PRO501_FRAME_BITS = 64
PRO501_GLITCH_MAX_US = 50
PRO501_TSYM_MIN_US = 800
PRO501_TSYM_MAX_US = 1600
PRO501_MIN_CLUSTER_SEPARATION = .12
PRO501_MAX_HAMMING = 4
PRO501_MIN_REPEATS = 3
PRO501_DEDUP_MS = 1000
PRO501_MIN_CONFIDENCE = .85


@dataclass(frozen=True)
class Pro501DecodeResult:
    valid: bool
    raw_bits: str
    raw_u64: int | None
    repeats: int
    frame_confidence: float
    symbol_confidence: float
    sensor_key: str | None
    event: str = 'ALARM'
    battery: str = 'UNKNOWN'
    changed_bits: list[int] | None = None
    timing_us: float = 0.
    ratio_short: float = 0.
    ratio_long: float = 0.


def parse_hex_records(text: str) -> list[tuple[int, int]]:
    """Parse the documented LLDDDD capture format."""
    value = ''.join(text.split())
    if len(value) % 6:
        raise ValueError('Capture PRO-501 : longueur non multiple de 6')
    result = []
    for pos in range(0, len(value), 6):
        try:
            level, duration = int(value[pos:pos + 2], 16), int(value[pos + 2:pos + 6], 16)
        except ValueError as exc:
            raise ValueError('Capture PRO-501 : hexadécimal invalide') from exc
        if level not in (0, 1) or duration <= 0:
            raise ValueError('Capture PRO-501 : niveau ou durée invalide')
        result.append((level, duration))
    return result


def deglitch_edges(edges: Iterable[tuple[int, int]], glitch_max_us=PRO501_GLITCH_MAX_US):
    values = [(int(level), int(duration)) for level, duration in edges if duration > 0]
    # Repeatedly absorb a short opposite-level pulse into its equal-level neighbours.
    changed = True
    while changed:
        changed = False
        merged = []
        index = 0
        while index < len(values):
            if (0 < index < len(values) - 1 and values[index][1] <= glitch_max_us
                    and values[index - 1][0] == values[index + 1][0]
                    and values[index][0] != values[index - 1][0]):
                level = values[index - 1][0]
                merged[-1] = (level, values[index - 1][1] + values[index][1] + values[index + 1][1])
                index += 2
                changed = True
            else:
                merged.append(values[index])
                index += 1
        values = merged
    compact = []
    for level, duration in values:
        if compact and compact[-1][0] == level:
            compact[-1] = (level, compact[-1][1] + duration)
        else:
            compact.append((level, duration))
    return compact


def _clusters(ratios):
    points = np.asarray(ratios, dtype=float)
    if len(points) < PRO501_FRAME_BITS:
        return None
    low, high = np.quantile(points, (.10, .90))
    # The protocol has long runs of zeroes, so a percentile seed can land in
    # the dominant class for both centres.  Preserve the adaptive k-means step
    # while seeding it from the observed extremes in that case.
    if abs(high - low) < 1e-9:
        low, high = float(points.min()), float(points.max())
    for _ in range(32):
        membership = np.abs(points - low) <= np.abs(points - high)
        if not membership.any() or membership.all():
            return None
        next_low, next_high = points[membership].mean(), points[~membership].mean()
        if abs(next_low-low) + abs(next_high-high) < 1e-7:
            break
        low, high = next_low, next_high
    low, high = sorted((float(low), float(high)))
    return (low, high) if high - low >= PRO501_MIN_CLUSTER_SEPARATION else None


def _symbols(edges):
    values = deglitch_edges(edges)
    rows = []
    for (level, high), (next_level, low) in zip(values, values[1:]):
        total = high + low
        if level == 1 and next_level == 0 and PRO501_TSYM_MIN_US <= total <= PRO501_TSYM_MAX_US:
            rows.append((high / total, total))
    return rows


def _hamming(a, b):
    return sum(x != y for x, y in zip(a, b))


def _repeated_windows(bits, confidence):
    """Find a family of 64-bit windows repeated at approximately one frame apart."""
    best = None
    n = len(bits)
    windows = [int(bits[index:index + PRO501_FRAME_BITS], 2)
               for index in range(n - PRO501_FRAME_BITS + 1)]
    # A first frame is normally present near the beginning of a burst.  Limiting
    # the anchors preserves real-time operation for unusually long captures;
    # all later symbols remain candidates for repetitions.
    for start, candidate_value in enumerate(windows[:min(len(windows), 512)]):
        candidate = bits[start:start + PRO501_FRAME_BITS]
        # All-zero portions of an OOK capture are not sufficient evidence.
        if candidate.count('1') < 2:
            continue
        matches = [(start, candidate)]
        for other in range(start + 40, len(windows)):
            frame = bits[other:other + PRO501_FRAME_BITS]
            if (candidate_value ^ windows[other]).bit_count() <= PRO501_MAX_HAMMING:
                if other - matches[-1][0] >= 40:
                    matches.append((other, frame))
        if len(matches) < PRO501_MIN_REPEATS:
            continue
        positions = np.arange(PRO501_FRAME_BITS)
        votes = np.zeros(PRO501_FRAME_BITS)
        weights = np.zeros(PRO501_FRAME_BITS)
        for offset, frame in matches:
            weight = np.asarray(confidence[offset:offset + PRO501_FRAME_BITS])
            votes += weight * np.fromiter((bit == '1' for bit in frame), bool)
            weights += weight
        consensus = ''.join('1' if yes * 2 >= weight else '0' for yes, weight in zip(votes, weights))
        distances = [_hamming(consensus, frame) for _, frame in matches]
        keep = [(offset, frame) for (offset, frame), distance in zip(matches, distances) if distance <= PRO501_MAX_HAMMING]
        score = (len(keep), -float(np.mean([_hamming(consensus, frame) for _, frame in keep])))
        if best is None or score > best[0]:
            best = score, consensus, keep
    return None if best is None else best[1:]


def compare_frames(a: str, b: str) -> list[int]:
    return [index for index, (left, right) in enumerate(zip(a, b)) if left != right]


def build_consensus(frames):
    if not frames:
        return '', 0.
    output = []
    for column in zip(*frames):
        output.append('1' if column.count('1') * 2 >= len(column) else '0')
    raw = ''.join(output)
    distance = np.mean([_hamming(raw, frame) for frame in frames])
    return raw, max(0., 1. - distance / PRO501_FRAME_BITS)


def detect_pro501_burst(edges) -> bool:
    result = decode_pro501(edges)
    return result is not None and result.valid


def decode_pro501(edges) -> Pro501DecodeResult | None:
    symbols = _symbols(edges)
    if len(symbols) < PRO501_FRAME_BITS * PRO501_MIN_REPEATS:
        return None
    ratios = [ratio for ratio, _ in symbols]
    clusters = _clusters(ratios)
    if clusters is None:
        return None
    short, long = clusters
    threshold = (short + long) / 2
    confidence = [max(abs(ratio - short), abs(ratio - long)) /
                  (abs(ratio - short) + abs(ratio - long) + 1e-9) for ratio in ratios]
    # Short HIGH is a logical one; cap confidence to prevent outliers dominating.
    confidence = [min(1., max(.01, value)) for value in confidence]
    bits = ''.join('1' if ratio < threshold else '0' for ratio in ratios)
    found = _repeated_windows(bits, confidence)
    if found is None:
        return None
    consensus, matches = found
    frames = [frame for _, frame in matches]
    consensus, repeat_confidence = build_consensus(frames)
    symbol_confidence = float(np.mean([np.mean(confidence[offset:offset + PRO501_FRAME_BITS]) for offset, _ in matches]))
    timing = float(np.median([duration for _, duration in symbols]))
    frame_confidence = min(repeat_confidence, symbol_confidence)
    valid = len(frames) >= PRO501_MIN_REPEATS and frame_confidence >= PRO501_MIN_CONFIDENCE
    fingerprint = sha256(consensus.encode('ascii')).hexdigest()[:12] if valid else None
    return Pro501DecodeResult(valid, consensus, int(consensus, 2), len(frames), frame_confidence,
                              symbol_confidence, fingerprint, timing_us=timing,
                              ratio_short=short, ratio_long=long)
