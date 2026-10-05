from collections import OrderedDict


class ReportCache:
    def __init__(self, max_entries: int = 2000):
        if max_entries < 1:
            raise ValueError("max_entries must be positive")
        self._max_entries = max_entries
        self._records = OrderedDict()

    def put(self, key, record) -> None:
        self._records[key] = record
        while len(self._records) > self._max_entries:
            self._records.popitem(last=False)

    def get(self, key):
        return self._records.get(key)

    def __len__(self) -> int:
        return len(self._records)
