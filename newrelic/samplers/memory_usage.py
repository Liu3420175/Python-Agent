"""This module implements a data source for generating metrics about
memory usage.

"""

from newrelic.common.system_info import physical_memory_used

from newrelic.samplers.decorators import data_source_generator


@data_source_generator(name='Memory Usage')
def memory_usage_data_source():
    yield ('Memory/Physical', physical_memory_used())


if __name__ == '__main__':
    @data_source_generator(name='test')
    def f():
        return 1

    print(f.__dict__['__wrapped__']())