"""This module implements a data source for generating metrics about
memory usage.

"""

from newrelic.common.system_info import physical_memory_used

from newrelic.samplers.decorators import data_source_generator


@data_source_generator(name='Memory Usage')
def memory_usage_data_source():
    yield ('Memory/Physical', physical_memory_used())


if __name__ == '__main__':
    import sys
    def f(a):
        print(a.name)
    try:
        f(1)
    except:
        a,b,c = sys.exc_info()
        #print(a.__name__,c)

        print(b.message)

