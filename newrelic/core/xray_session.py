# TODO X射线会话为Web事务提供了更具针对性的事务跟踪采样和线程分析。
#  跟线程分析器搭配使用
from collections import namedtuple

_XraySession = namedtuple('XraySession',
        ['xray_id', 'key_txn', 'stop_time_s', 'max_traces',
            'sample_period_s'])

class XraySession(_XraySession):

    def get_trace_count(self):
        if getattr(self, '_trace_count', None) is None:
            self._trace_count = 0
        return self._trace_count

    def set_trace_count(self, count):
        self._trace_count = count

    trace_count = property(get_trace_count, set_trace_count)
