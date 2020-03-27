from __future__ import print_function

import sys
import logging

_builtin_plugins = [
    'debug_console',
    'generate_config',
    'license_info',
    'license_key',
    'local_config',
    'network_config',
    'record_deploy',
    'run_program',
    'run_python',
    'server_config',
    'validate_config'
]

_commands = {}


def command(name, options='', description='', hidden=False,
        log_intercept=True, deprecated=False):
    # TODO 这个装饰器用的巧妙，不知不觉中吧admin目录下的文件的函数装载进了全局变量里
    def wrapper(callback):
        callback.name = name
        callback.options = options
        callback.description = description
        callback.hidden = hidden
        callback.log_intercept = log_intercept
        callback.deprecated = deprecated
        _commands[name] = callback
        return callback
    return wrapper


def usage(name):
    details = _commands[name]
    if details.deprecated:
        print("[WARNING] This command is deprecated and will be removed")
    print('Usage: newrelic-admin %s %s' % (name, details.options))


@command('help', '[command]', hidden=True)
def help(args):
    if not args:
        print('Usage: newrelic-admin command [options]')
        print()
        print("Type 'newrelic-admin help <command>'", end='')
        print("for help on a specific command.")
        print()
        print("Available commands are:")

        commands = sorted(_commands.keys())
        for name in commands:
            details = _commands[name]
            if not details.hidden:
                print(' ', name)

    else:
        name = args[0]

        if name not in _commands:
            print("Unknown command '%s'." % name, end=' ')
            print("Type 'newrelic-admin help' for usage.")

        else:
            details = _commands[name]

            print('Usage: newrelic-admin %s %s' % (name, details.options))
            if details.description:
                print()
                description = details.description
                if details.deprecated:
                    description = '[DEPRECATED] ' + description
                print(description)


def setup_log_intercept():
    # Send any errors or warnings to standard output as well so more
    # obvious as use may have trouble finding the relevant messages in
    # the agent log as it will be full of debug output as well.

    class FilteredStreamHandler(logging.StreamHandler):
        def emit(self, record):
            # TODO 为什么重定义emit函数，看Handler类源码就知道了，当然也可以重定义handle函数,最后Handle是怎么执行的，看下Logger源码就明白了
            if len(logging.root.handlers) != 0:
                return

            if record.name.startswith('newrelic.packages'):
                return

            if record.levelno < logging.WARNING:
                return

            return logging.StreamHandler.emit(self, record)

    _stdout_logger = logging.getLogger('newrelic')
    _stdout_handler = FilteredStreamHandler(sys.stdout)
    _stdout_format = '%(levelname)s - %(message)s\n'
    _stdout_formatter = logging.Formatter(_stdout_format)
    _stdout_handler.setFormatter(_stdout_formatter)
    _stdout_logger.addHandler(_stdout_handler)


def load_internal_plugins():
    for name in _builtin_plugins:
        module_name = '%s.%s' % (__name__, name)
        __import__(module_name)  # TODO 动态加载admin包下的模块，这点用的好，代码更容易维护


def load_external_plugins():
    # TODO 导入外部包，在导入外部包的过程中完成了agent的初始化工作
    try:
        import pkg_resources
    except ImportError:
        return

    group = 'newrelic.admin'

    for entrypoint in pkg_resources.iter_entry_points(group=group):
        __import__(entrypoint.module_name)


def main():
    try:
        if len(sys.argv) > 1:
            command = sys.argv[1]
        else:
            command = 'help'

        callback = _commands[command]

    except Exception:
        print("Unknown command '%s'." % command, end='')
        print("Type 'newrelic-admin help' for usage.")
        sys.exit(1)

    if callback.log_intercept:
        setup_log_intercept()

    callback(sys.argv[2:]) # TODO 调用admin包里相关函数


load_internal_plugins()
load_external_plugins()

if __name__ == '__main__':
    main()
