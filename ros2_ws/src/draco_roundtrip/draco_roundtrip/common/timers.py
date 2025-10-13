"""ACK 타임아웃 스케줄러 유틸리티."""

from __future__ import annotations

import heapq
from typing import Dict, List, Optional, Tuple


class AckDeadlineHeap:
    """시퀀스별 ACK 마감 시각을 추적하는 최소 힙."""

    def __init__(self) -> None:
        self._heap: List[Tuple[float, int]] = []
        self._deadlines: Dict[int, float] = {}

    def push(self, sequence: int, deadline: float) -> bool:
        """새 시퀀스를 등록하고, 최솟값 변경 여부를 반환한다."""

        previous = self.next_deadline()
        self._deadlines[sequence] = deadline
        heapq.heappush(self._heap, (deadline, sequence))
        return self.next_deadline() != previous

    def cancel(self, sequence: int) -> bool:
        """대기 중인 시퀀스를 취소한다."""

        return self._deadlines.pop(sequence, None) is not None

    def pop_due(self, now: float) -> List[int]:
        """현재 시각 기준으로 만료된 시퀀스를 모두 반환한다."""

        due: List[int] = []
        while self._heap:
            deadline, sequence = self._heap[0]
            current = self._deadlines.get(sequence)
            if current is None:
                heapq.heappop(self._heap)
                continue
            if current != deadline:
                heapq.heappop(self._heap)
                heapq.heappush(self._heap, (current, sequence))
                continue
            if deadline > now:
                break
            heapq.heappop(self._heap)
            self._deadlines.pop(sequence, None)
            due.append(sequence)
        return due

    def next_deadline(self) -> Optional[float]:
        """가장 이른 마감 시각을 반환한다."""

        while self._heap:
            deadline, sequence = self._heap[0]
            current = self._deadlines.get(sequence)
            if current is None or current != deadline:
                heapq.heappop(self._heap)
                if current is not None:
                    heapq.heappush(self._heap, (current, sequence))
                continue
            return deadline
        return None

    def __len__(self) -> int:
        return len(self._deadlines)
