"""This module implements a data source for generating metrics about CPU
usage.

"""

import os
import time

from newrelic.common.system_info import logical_processor_count
from newrelic.common.stopwatch import start_timer

from newrelic.samplers.decorators import data_source_factory

@data_source_factory(name='CPU Usage')
class _CPUUsageDataSource(object):
    """
    # TODO CPU 使用情况数据源
    """

    def __init__(self, settings, environ):
        self._timer = None # TODO 计时器，newrelic.common.stopwatch._Timer对象
        self._times = None # TODO 当前全局进程时间，user - 用户时间 ；system - 系统时间；children_user - 所有子进程的用户时间
      # TODO children_system - 所有子进程的系统时间；elapsed - 从过去的固定时间点起，经过的真实时间

    def start(self):
        self._timer = start_timer()
        try:
            self._times = os.times()
        except Exception:
            self._times = None

    def stop(self):
        self._timer = None
        self._times = None

    def __call__(self):
        if self._times is None:
            return

        new_times = os.times()
        user_time = new_times[0] - self._times[0] # TODO 用户时间

        elapsed_time = self._timer.restart_timer()
        utilization = user_time / (elapsed_time*logical_processor_count())  # TODO CPU利用率=该线程CPU使用时间/ 总CPU时间

        self._times = new_times

        yield ('CPU/User Time', user_time)
        yield ('CPU/User/Utilization', utilization)

cpu_usage_data_source = _CPUUsageDataSource
