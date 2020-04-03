"""This module implements a timer for measuring elapsed time. It will
attempt to use a monotonic clock where when available, or otherwise use
whatever clock has the highest resolution.

"""

import time

try:
    # Python 3.3 and later implements PEP 418. Use the
    # performance counter it provides which is monotonically
    # increasing.

    default_timer = time.perf_counter # TODO 高精度计时器，包括sleep时间,两次调用的差值就是这段代码执行所花时间，这是3.3里新增的功能，所以做了兼容处理
    timer_implementation = 'time.perf_counter()'

except AttributeError:
    try:
        # Next try our own bundled back port of the monotonic()
        # function. Python 3.3 does on Windows use a different
        # clock for the performance counter, but the standard
        # monotonic clock should suit our requirements okay.

        from newrelic.common._monotonic import monotonic as default_timer
        default_timer()
        timer_implementation = '_monotonic.monotonic()'

    except (ImportError, NotImplementedError, OSError):
        # If neither of the above, fallback to using the default
        # timer from the timeit module. This will use the best
        # resolution clock available on a particular platform,
        # albeit that it isn't monotonically increasing.

        import timeit
        default_timer = timeit.default_timer
        timer_implementation = 'timeit.default_timer()'

# A timer class which deals with remembering the start time based on
# wall clock time and duration based on a monotonic clock where
# available.

class _Timer(object):
    # TODO 计时器，计算小片段代码执行时间，参照Python的timeit内置模块

    def __init__(self):
        self._time_started = time.time() # TODO 起始时间戳
        self._started = default_timer()
        self._stopped = None

    def time_started(self):
        return self._time_started

    def stop_timer(self):
        # TODO 暂停计时器，返回时间差
        if self._stopped is None:
            self._stopped = default_timer()
        return self._stopped - self._started

    def restart_timer(self):
        # TODO 重启定时器，返回时间差
        elapsed_time = self.stop_timer() # TODO 重启之前先暂停
        self._time_started = time.time()
        self._started = default_timer()
        self._stopped = None
        return elapsed_time

    def elapsed_time(self):
        # TODO 从过去的固定时间点起，经过的真实时间
        if self._stopped is not None:
            return self._stopped - self._started
        return default_timer() - self._started

def start_timer():
    return _Timer()
