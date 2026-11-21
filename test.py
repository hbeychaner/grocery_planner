from dataclasses import dataclass
from typing import Literal
from datetime import datetime
from collections import deque

@dataclass(frozen=True)
class TranscriptEvent:
    utterance_id: str
    speaker: Literal["rep", "prospect"]
    text: str
    is_final: bool
    confidence: float   # 0.0 to 1.0
    timestamp: float    # Epoch seconds


@dataclass(frozen=True)
class WindowMetrics:
    rep_wpm: float              # (rep_words / window_sec) * 60.0
    prospect_talk_share: float  # prospect_words / total_words (0.0 if no words)
    avg_confidence: float       # Unweighted mean confidence of valid events in window (0.0 if empty)


class CallStreamMonitor:
    events: deque[TranscriptEvent] = deque()
    current_time: float = 0.0

    def __init__(self, window_sec: float = 60.0, min_confidence: float = 0.75) -> None:
        self.window_sec = window_sec
        self.min_confidence = min_confidence

    def ingest(self, event: TranscriptEvent) -> None:
        if event.is_final and event.confidence >= self.min_confidence and len(event.text.split()) >= 0:
            if event.utterance_id not in [e.utterance_id for e in self.events]:
                self.events.append(event)
                
        

    def get_metrics(self) -> WindowMetrics:
        ...