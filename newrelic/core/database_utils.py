"""Database utilities consists of routines for obfuscating SQL, retrieving
explain plans for SQL etc.

"""
# TODO 数据库相关包,用于安全模式下混淆SQL(比如将敏感的参数信息匿名化,以便保护敏感信息),SQL执行计划
# TODO 为什么需要SQLConnection和SQLConnections对象?获取用户SQL的执行计划,归根结底还是需要利用客户的数据库,然后发送获取执行计划的SQL语言.
# TODO 所有一旦客户开启了获取SQL执行计划配置,我们就需要捕获存储客户的SQL连接,然后为己所用,所以我们看下这两个对象的用处就目标其中的原理了

import logging
import re
import weakref

import newrelic.packages.six as six

from newrelic.core.internal_metrics import internal_metric
from newrelic.core.config import global_settings

_logger = logging.getLogger(__name__)

# Obfuscation of SQL is done when reporting SQL statements back to the
# data collector so that sensitive information is not being passed.
# Obfuscation consists of replacing any quoted strings, integer or float
# literals with a '?'. For quoted strings which types of quoted strings
# should be collapsed depend on the database in use.

# See http://stackoverflow.com/questions/6718874.
#
# Escaping of quotes in SQL isn't like normal C style string. That is,
# no backslash. Uses two successive instances of quote character in
# middle of the string to indicate one embedded quote.
# TODO SQL 在回数据收集器之前就已经被模糊化了,以便保护敏感信息,模糊化的地方包括:带引号的字符串,整数,浮点数,带?的文字

_single_quotes_p = r"'(?:[^']|'')*?(?:\\'.*|'(?!'))"  # TODO 单引号正则
_double_quotes_p = r'"(?:[^"]|"")*?(?:\\".*|"(?!"))'  # TODO 双引号正则
_dollar_quotes_p = r'(\$(?!\d)[^$]*?\$).*?(?:\1|$)'   # TODO  带$的
_oracle_quotes_p = (r"q'\[.*?(?:\]'|$)|q'\{.*?(?:\}'|$)|"
        r"q'\<.*?(?:\>'|$)|q'\(.*?(?:\)'|$)")
_any_quotes_p = _single_quotes_p + '|' + _double_quotes_p
_single_dollar_p = _single_quotes_p + '|' + _dollar_quotes_p
_single_oracle_p = _single_quotes_p + '|' + _oracle_quotes_p

_single_quotes_re = re.compile(_single_quotes_p)
_any_quotes_re = re.compile(_any_quotes_p)
_single_dollar_re = re.compile(_single_dollar_p)
_single_oracle_re = re.compile(_single_oracle_p)

# Cleanup regexes. Presence of a quote will indicate that the now obfuscated
# sql was actually malformed.

_single_quotes_cleanup_p = r"'"
_any_quotes_cleanup_p = r'\'|"'
_single_dollar_cleanup_p = r"'|\$(?!\?)"

_any_quotes_cleanup_re = re.compile(_any_quotes_cleanup_p)
_single_quotes_cleanup_re = re.compile(_single_quotes_cleanup_p)
_single_dollar_cleanup_re = re.compile(_single_dollar_cleanup_p)

# See http://www.regular-expressions.info/examplesprogrammer.html.
#
# Is important to take word boundaries into consideration so we do not
# match numbers which are used on the end of identifiers. Technically
# this will not match numbers on the start of identifiers even though
# leading digits on identifiers aren't valid anyway. As it shouldn't
# occur, shouldn't be an issue.
#
# We add one variation here in that don't want to replace a number that
# follows on from a ':'. This is because ':1' can be used as positional
# parameter with database adapters where 'paramstyle' is 'numeric'.

_uuid_p = r'\{?(?:[0-9a-f]\-?){32}\}?' # TODO UUID 正则
_int_p = r'(?<!:)-?\b(?:[0-9]+\.)?[0-9]+(e[+-]?[0-9]+)?' #  TODO 整数正则
_hex_p = r'0x[0-9a-f]+' # TODO 16进制正则
_bool_p = r'\b(?:true|false|null)\b'  # TODO bool 正则

# Join all literals into one compiled regular expression. Longest expressions
# first to avoid the situation of partial matches on shorter expressions. UUIDs
# might be an example.

_all_literals_p = '(' + ')|('.join([_uuid_p, _hex_p, _int_p, _bool_p]) + ')'
_all_literals_re = re.compile(_all_literals_p, re.IGNORECASE)

_quotes_table = {
    'single': (_single_quotes_re, _single_quotes_cleanup_re),
    'single+double': (_any_quotes_re, _any_quotes_cleanup_re),
    'single+dollar': (_single_dollar_re, _single_dollar_cleanup_re),
    'single+oracle': (_single_oracle_re, _single_quotes_cleanup_re),
}


def _obfuscate_sql(sql, database):
    """

    :param sql:
    :param SQLDatabase database :
    :return:
    """
    quotes_re, quotes_cleanup_re = _quotes_table.get(database.quoting_style,
            (_single_quotes_re, _single_quotes_cleanup_re))

    # Substitute quoted strings first.

    sql = quotes_re.sub('?', sql) # TODO 正则替换成问号

    # Replace all other sensitive fields

    sql = _all_literals_re.sub('?', sql)

    # Determine if the obfuscated query was malformed by searching for
    # remaining quote characters

    if quotes_cleanup_re.search(sql):
        sql = '?'

    return sql

# Normalization of the SQL is done so that when we can produce a hash
# value for a slow SQL such that it generates the same value for two SQL
# statements where only difference is values that may have been used.
#
# The main thing we need to contend with is the value sets where can
# have variable numbers of values for which we collapse them down to a
# single value. We also need to replace all the different variations of
# param styles with a '?'. This is in case in one situation a literal
# was used but in another it was a param, but param style is something
# other than '?' that literals are otherwise converted to. We also strip
# out all whitespace between identifiers and non identifiers to cope
# with varying amounts being used in different cases. A single space is
# left between identifiers.
#
# Note that we pickup up both ':1' and ':name' with the sub pattern
# ':\w+'. This can match ':1name', which is not strictly correct, but
# then it likely isn't valid in SQL anyway for that param style.
# TODO 完成SQL的规范化,对应两个仅参数值不同的SQL,规范化后,他们的哈希值应该是一样的
# TODO 我们需要解决的问题
# TODO   1. 哪里的值是可变参数值 2. 找出所有空格并规范化

#　TODO 这块就是匹配Python字符串拼接的集中方式的写法
_normalize_params_1_p = r'%\([^)]*\)s' #　TODO  对于参数化的SQL,正则匹配出命名参数
_normalize_params_1_re = re.compile(_normalize_params_1_p)
_normalize_params_2_p = r'%s' # TODO  对于参数化的SQL,正则匹配出顺序参数
_normalize_params_2_re = re.compile(_normalize_params_2_p)
_normalize_params_3_p = r':\w+' # TODO  对于参数化的SQL,正则匹配出
_normalize_params_3_re = re.compile(_normalize_params_3_p)

_normalize_values_p = r'\([^)]+\)' # TODO 正则匹配出具体值
_normalize_values_re = re.compile(_normalize_values_p)

_normalize_whitespace_1_p = r'\s+' #  TODO 正则匹配出空格
_normalize_whitespace_1_re = re.compile(_normalize_whitespace_1_p)
_normalize_whitespace_2_p = r'\s+(?!\w)'
_normalize_whitespace_2_re = re.compile(_normalize_whitespace_2_p)
_normalize_whitespace_3_p = r'(?<!\w)\s+'
_normalize_whitespace_3_re = re.compile(_normalize_whitespace_3_p)


def _normalize_sql(sql):
    # Note we that do this as a series of regular expressions as
    # using '|' in regular expressions is more expensive.

    # Convert param style of '%(name)s' to '?'. We need to do
    # this before collapsing sets of values to a single value
    # due to the use of the parenthesis in the param style.
    # TODO 规范化SQL
    sql = _normalize_params_1_re.sub('?', sql)

    # Collapse any parenthesised set of values to a single value.

    sql = _normalize_values_re.sub('(?)', sql)

    # Convert '%s', ':1' and ':name' param styles to '?'.

    sql = _normalize_params_2_re.sub('?', sql)
    sql = _normalize_params_3_re.sub('?', sql)

    # Strip leading and trailing white space.

    sql = sql.strip()

    # Collapse multiple white space to single white space.

    sql = _normalize_whitespace_1_re.sub(' ', sql)

    # Drop spaces adjacent to identifier except for case where
    # identifiers follow each other.

    sql = _normalize_whitespace_2_re.sub('', sql)
    sql = _normalize_whitespace_3_re.sub('', sql)

    return sql

# Helper function for extracting out any identifier from a string which
# might be preceded or followed by punctuation which we can expect in
# context of SQL statements.
#
# TODO This isn't always going to do what we require, but it is only used
# now for cases below which never get invoked, so is okay for now.


_identifier_re = re.compile(r'[\',"`\[\]\(\)]*')  # TODO 标识符的正则匹配格式


def _extract_identifier(token):
    return _identifier_re.sub('', token).strip().lower()


# Helper function for removing C style comments embedded in SQL statements.

_uncomment_sql_p = r'(?:#|--).*?(?=\r|\n|$)'
_uncomment_sql_q = r'\/\*(?:[^\/]|\/[^*])*?(?:\*\/|\/\*.*)'
_uncomment_sql_x = r'(%s)|(%s)' % (_uncomment_sql_p, _uncomment_sql_q)
_uncomment_sql_re = re.compile(_uncomment_sql_x, re.DOTALL)


def _uncomment_sql(sql):
    return _uncomment_sql_re.sub('', sql)

# Parser routines for the different SQL statement operation types.
#
# Picking out the name of the target identifier for the specific
# operation is more than a bit tricky. This is because names can contain
# special characters. Quoting can also be used to allow any characters
# with escaping of quotes with such values following the SQL
# conventions.
#
# The most broad naming rule which includes all other databases appears
# to be SQL server:
#
# http://msdn.microsoft.com/en-us/library/ms175874.aspx
#
# which says:
#
#   The first character must be one of the following:
#
#     A letter as defined by the Unicode Standard 3.2. The Unicode
#     definition of letters includes Latin characters from a through z,
#     from A through Z, and also letter characters from other languages.
#
#     The underscore (_), at sign (@), or number sign (#).
#
#   Subsequent characters can include the following:
#
#     Letters as defined in the Unicode Standard 3.2.
#
#     Decimal numbers from either Basic Latin or other national scripts.
#
#     The at sign, dollar sign ($), number sign, or underscore.
#
# One of the problems is that letters and numbers can be any which are
# valid for the locale in use, but how do we know for sure that locale
# setting of the process and what is used by the regular expression
# library even matches what the database is using. We therefore have to
# avoid trying to use \w pattern even if LOCALE flag is used.
#
# On top of the character set issues and quoting, different types of
# bracketing such as (), {}, and [] can also be used around names.
#
# Because of the difficulty in handling locales especially, what we do
# instead is try and match based on whatever occurs between the
# different delimiters we expect. That way we do not have to worry about
# locale.
#
# In the case of a schema and table reference, when quoting is used,
# the same type of quoting must be used on each in the one statement.
# You cannot mix different quoting schemes as then the regex gets
# even more messy.


def _parse_default(sql, regex):
    match = regex.search(sql)
    return match and _extract_identifier(match.group(1)) or ''


# TODO 各种可能影响到标识符计算的正则规则
_parse_identifier_1_p = r'"((?:[^"]|"")+)"(?:\."((?:[^"]|"")+)")?'
_parse_identifier_2_p = r"'((?:[^']|'')+)'(?:\.'((?:[^']|'')+)')?"
_parse_identifier_3_p = r'`((?:[^`]|``)+)`(?:\.`((?:[^`]|``)+)`)?'
_parse_identifier_4_p = r'\[\s*(\S+)\s*\]'
_parse_identifier_5_p = r'\(\s*(\S+)\s*\)'
_parse_identifier_6_p = r'\{\s*(\S+)\s*\}'
_parse_identifier_7_p = r'([^\s\(\)\[\],]+)'

_parse_identifier_p = ''.join(('(', _parse_identifier_1_p, '|',
        _parse_identifier_2_p, '|', _parse_identifier_3_p, '|',
        _parse_identifier_4_p, '|', _parse_identifier_5_p, '|',
        _parse_identifier_6_p, '|', _parse_identifier_7_p, ')'))

_parse_from_p = r'\s+FROM\s+' + _parse_identifier_p # TODO  解析出FROM 后面的表名
_parse_from_re = re.compile(_parse_from_p, re.IGNORECASE)


def _join_identifier(m):
    """

    :param re.Pattern m:
    :return:
    """
    return m and '.'.join([s for s in m.groups()[1:] if s]).lower() or ''


def _parse_select(sql):
    # TODO 解析出FROM 后面的表面,对于子查询忽略
    return _join_identifier(_parse_from_re.search(sql))


def _parse_delete(sql):
    return _join_identifier(_parse_from_re.search(sql))


_parse_into_p = r'\s+INTO\s+' + _parse_identifier_p # TODO 解析INTO后面的表名
_parse_into_re = re.compile(_parse_into_p, re.IGNORECASE)


def _parse_insert(sql):
    """
    解析出INTO 后面的表名
    """
    return _join_identifier(_parse_into_re.search(sql))


_parse_update_p = r'\s*UPDATE\s+' + _parse_identifier_p  # TODO  解析出Update
_parse_update_re = re.compile(_parse_update_p, re.IGNORECASE)


def _parse_update(sql):
    return _join_identifier(_parse_update_re.search(sql))


_parse_table_p = r'\s+TABLE\s+' + _parse_identifier_p
_parse_table_re = re.compile(_parse_table_p, re.IGNORECASE)


def _parse_create(sql):
    return _join_identifier(_parse_table_re.search(sql))


def _parse_drop(sql):
    return _join_identifier(_parse_table_re.search(sql))


_parse_call_p = r'\s*CALL\s+(?!\()(\w+(\.\w+)*)'
_parse_call_re = re.compile(_parse_call_p, re.IGNORECASE)


def _parse_call(sql):
    return _parse_default(sql, _parse_call_re)

# TODO Following need to be reviewed again. They aren't currently used
# in actual use as only parse out target for select/insert/update/delete.


_parse_show_p = r'\s*SHOW\s+(.*)'
_parse_show_re = re.compile(_parse_show_p, re.IGNORECASE | re.DOTALL)


def _parse_show(sql):
    return _parse_default(sql, _parse_show_re)


_parse_set_p = r'\s*SET\s+(.*?)\W+.*'
_parse_set_re = re.compile(_parse_set_p, re.IGNORECASE | re.DOTALL)


def _parse_set(sql):
    return _parse_default(sql, _parse_set_re)


_parse_exec_p = r'\s*EXEC\s+(?!\()(\w+)'
_parse_exec_re = re.compile(_parse_exec_p, re.IGNORECASE)


def _parse_exec(sql):
    return _parse_default(sql, _parse_exec_re)


_parse_execute_p = r'\s*EXECUTE\s+(?!\()(\w+)'
_parse_execute_re = re.compile(_parse_execute_p, re.IGNORECASE)


def _parse_execute(sql):
    return _parse_default(sql, _parse_execute_re)


_parse_alter_p = r'\s*ALTER\s+(?!\()(\w+)'
_parse_alter_re = re.compile(_parse_alter_p, re.IGNORECASE)


def _parse_alter(sql):
    return _parse_default(sql, _parse_alter_re)

# For SQL queries, if a target of some sort, such as a table can be
# meaningfully extracted, then this table should map to the function
# which extracts it. If no target can be extracted, but it is still
# desired that the operation be broken out separately with new Datastore
# metrics, then the operation should still be added, but with the value
# being set to None.


_operation_table = {
    'select': _parse_select,
    'delete': _parse_delete,
    'insert': _parse_insert,
    'update': _parse_update,
    'create': None,
    'drop': None,
    'call': _parse_call,
    'show': None,
    'set': None,
    'exec': None,
    'execute': None,
    'alter': None,
    'commit': None,
    'rollback': None,
}

_parse_operation_p = r'(\w+)'
_parse_operation_re = re.compile(_parse_operation_p)


def _parse_operation(sql):
    match = _parse_operation_re.search(sql)
    operation = match and match.group(1).lower() or ''
    return operation if operation in _operation_table else ''


def _parse_target(sql, operation):
    sql = sql.rstrip(';')
    parse = _operation_table.get(operation, None)
    return parse and parse(sql) or ''

# For explain plan obfuscation, the regular expression for matching the
# explain plan needs to give precedence to replacing double quotes from
# around table names, then single quotes from any text, typed or
# otherwise. We will swap single quotes with a token value. Next up we
# want to match anything we want to keep. Finally match all remaining
# numeric values. These we will also swap with a token value.


_explain_plan_postgresql_re_1_mask_false = re.compile(
    r"""((?P<double_quotes>"[^"]*")|"""
    r"""(?P<single_quotes>'([^']|'')*')|"""
    r"""(?P<cost_analysis>\(cost=[^)]*\))|"""
    r"""(?P<sub_plan_ref>\bSubPlan\s+\d+\b)|"""
    r"""(?P<init_plan_ref>\bInitPlan\s+\d+\b)|"""
    r"""(?P<dollar_var_ref>\$\d+\b)|"""
    r"""(?P<numeric_value>(?<![\w])[-+]?\d*\.?\d+([eE][-+]?\d+)?\b))""")

_explain_plan_postgresql_re_1_mask_true = re.compile(
    r"""((?P<double_quotes>"[^"]*")|"""
    r"""(?P<single_quotes>'([^']|'')*'))""")

_explain_plan_postgresql_re_2 = re.compile(
    r"""^(?P<label>[^:]*:\s+).*$""", re.MULTILINE)


def _obfuscate_explain_plan_postgresql_substitute(text, mask):
    # TODO 用替换的方式模糊化postgrepsql的执行计划
    # Perform substitutions for the explain plan on the text string.

    def replacement(matchobj):
        # The replacement function is called for each match. The group
        # dict of the match object will have a key corresponding to all
        # groups that could have matched, but only the first encountered
        # based on order of sub patterns will have non None value. We
        # use the name of the sub pattern to determine if we keep the
        # original value or swap it with our token value.

        for name, value in list(matchobj.groupdict().items()):
            if value is not None:
                if name in ('numeric_value', 'single_quotes'):
                    return '?'
                return value

    if mask:
        return _explain_plan_postgresql_re_1_mask_true.sub(replacement, text)
    else:
        return _explain_plan_postgresql_re_1_mask_false.sub(replacement, text)


def _obfuscate_explain_plan_postgresql(columns, rows, mask=None):
    settings = global_settings()

    if mask is None:
        mask = (settings.debug.explain_plan_obfuscation == 'simple')

    # Only deal with where we get back the one expected column. If we
    # get more than one column just ignore the whole explain plan. Need
    # to confirm whether we would always definitely only get one column.
    # The reason we do this is that swapping the value of quoted strings
    # could result in the collapsing of multiple rows and in that case
    # not sure what we would do with values from any other columns.

    if len(columns) != 1:
        return None

    # We need to join together all the separate rows of the explain plan
    # back together again. This is because an embedded newline within
    # any text quoted from the original SQL can result in that line of
    # the explain plan being split across multiple rows.

    text = '\n'.join(item[0] for item in rows)

    # Now need to perform the replacements on the complete text of the
    # explain plan.

    text = _obfuscate_explain_plan_postgresql_substitute(text, mask)

    # The mask option dictates whether we use the slightly more aggresive
    # obfuscation and simply mask out any line preceded by a label.

    if mask:
        text = _explain_plan_postgresql_re_2.sub(r'\g<label>?', text)

    # Now regenerate the list of rows by splitting again on newline.

    rows = [(_,) for _ in text.split('\n')]

    return columns, rows


_obfuscate_explain_plan_table = {
    'Postgres': _obfuscate_explain_plan_postgresql
} # TODO 全局变量,单例模式,存储SQL执行计划处理函数


def _obfuscate_explain_plan(database, columns, rows):
    """

    :param SQLDatabase database:
    :param columns:
    :param rows:
    :return:
    """
    # TODO 根据不同的数据库,获取对应的SQL执行计划
    obfuscator = _obfuscate_explain_plan_table.get(database.product)
    if obfuscator:
        return obfuscator(columns, rows)
    return columns, rows


class SQLConnection(object):

    def __init__(self, database, connection):
        self.database = database
        self.connection = connection
        self.cursors = {}

    def cursor(self, args=(), kwargs={}):
        key = (args, frozenset(kwargs.items()))

        cursor = self.cursors.get(key)

        if cursor is None:
            settings = global_settings()

            if settings.debug.log_explain_plan_queries:
                _logger.debug('Created database cursor for %r.',
                        self.database.client)

            cursor = self.connection.cursor(*args, **kwargs)
            self.cursors[key] = cursor

        return cursor

    def cleanup(self):
        settings = global_settings()

        if settings.debug.log_explain_plan_queries:
            _logger.debug('Cleanup database connection for %r.',
                    self.database)

        try:
            self.connection.rollback()
            pass
        except (AttributeError, self.database.NotSupportedError):
            pass

        self.connection.close()


class SQLConnections(object):

    def __init__(self, maximum=4):
        self.connections = []
        self.maximum = maximum

        settings = global_settings()

        if settings.debug.log_explain_plan_queries:
            _logger.debug('Creating SQL connections cache %r.', self)

    def connection(self, database, args, kwargs):
        """

        :param SQLDatabase database:
        :param args:
        :param kwargs:
        :return:
        """
        key = (database.client, args, kwargs)

        connection = None

        settings = global_settings()

        for i, item in enumerate(self.connections):
            if item[0] == key:
                connection = item[1]

                # Move to back of list so we know which is the
                # most recently used all the time.

                item = self.connections.pop(i)
                self.connections.append(item)

                break

        if connection is None:
            # If we are at the maximum number of connections to
            # keep hold of, pop the one which has been used the
            # longest amount of time.

            if len(self.connections) == self.maximum:
                connection = self.connections.pop(0)[1]

                internal_metric('Supportability/Python/DatabaseUtils/Counts/'
                                'drop_database_connection', 1)

                if settings.debug.log_explain_plan_queries:
                    _logger.debug('Drop database connection for %r as '
                            'reached maximum of %r.',
                            connection.database.client, self.maximum)

                connection.cleanup()

            connection = SQLConnection(database,
                    database.connect(*args, **kwargs))

            self.connections.append((key, connection))

            if settings.debug.log_explain_plan_queries:
                _logger.debug('Created database connection for %r.',
                        database.client)

        return connection

    def cleanup(self):
        settings = global_settings()

        if settings.debug.log_explain_plan_queries:
            _logger.debug('Cleaning up SQL connections cache %r.', self)

        for key, connection in self.connections:
            connection.cleanup()

        self.connections = []

    def __enter__(self):
        return self

    def __exit__(self, exc, value, tb):
        self.cleanup()


def _query_result_dicts_to_tuples(columns, rows):
    # Query results come back as a list of rows. If each row is a
    # dict, then its keys can be found in the columns list. Here, we
    # transform each row from a dict to a tuple, ordering the items
    # in the row in the same order as that found in columns.

    # Handle case where query results are empty.

    if not columns or not rows:
        return None

    return [tuple([row[col] for col in columns]) for row in rows]


def _could_be_multi_query(sql):
    return sql.rstrip().rstrip(';').count(';') > 0


def _explain_plan(connections, sql, database, connect_params, cursor_params,
        sql_parameters, execute_params):

    settings = global_settings()

    if _could_be_multi_query(sql):
        if settings.debug.log_explain_plan_queries:
            _logger.debug('Skipping explain plan for %r on %r due to '
                    'semicolons in the query string.', sql, database.client)
        else:
            _logger.debug('Skipping explain plan on %s due to '
                    'semicolons in the query string.', database.client)
        return None

    query = '%s %s' % (database.explain_query, sql)

    if settings.debug.log_explain_plan_queries:
        _logger.debug('Executing explain plan for %r on %r.', query,
                database.client)

    try:
        args, kwargs = connect_params
        connection = connections.connection(database, args, kwargs)

        if cursor_params is not None:
            args, kwargs = cursor_params
            cursor = connection.cursor(args, kwargs)
        else:
            cursor = connection.cursor()

        if execute_params is not None:
            args, kwargs = execute_params
        else:
            args, kwargs = ((), {})

        # If sql_parameters is None them args would need
        # to be an empty sequence. Don't pass it just in
        # case it wasn't for some reason, and only supply
        # kwargs. Right now the only time we believe that
        # passing in further params is needed is with
        # oursql cursor execute() method, which has
        # proprietary arguments outside of the DBAPI2
        # specification.

        if sql_parameters is not None:
            cursor.execute(query, sql_parameters, *args, **kwargs)
        else:
            cursor.execute(query, **kwargs)

        columns = []

        if cursor.description:
            for column in cursor.description:
                columns.append(column[0])

        rows = cursor.fetchall()

        # If rows have been returned as a list of dicts, then convert
        # them to a list of tuples before returning.

        if settings.debug.log_explain_plan_queries:
            _logger.debug('Explain plan row data type is %r',
                    rows and type(rows[0]))

        if rows and isinstance(rows[0], dict):
            rows = _query_result_dicts_to_tuples(columns, rows)

        if not columns and not rows:
            return None

        return (columns, rows)

    except Exception:
        if settings.debug.log_explain_plan_queries:
            _logger.exception('Error occurred when executing explain '
                    'plan for %r on %r where cursor_params=%r and '
                    'execute_params=%r.', query, database.client,
                    cursor_params, execute_params)

    return None


def explain_plan(connections, sql_statement, connect_params, cursor_params,
        sql_parameters, execute_params, sql_format):

    # If no parameters supplied for creating database connection
    # then mustn't have been a candidate for explain plans in the
    # first place, so skip it.

    if connect_params is None:
        return

    # Determine if we even know how to perform explain plans for
    # this particular database.

    database = sql_statement.database

    if sql_statement.operation not in database.explain_stmts:
        return

    details = _explain_plan(connections, sql_statement.sql, database,
            connect_params, cursor_params, sql_parameters, execute_params)

    if details is not None and sql_format != 'raw':
        return _obfuscate_explain_plan(database, *details)

    return details

# Wrapper for information about a specific database.


class SQLDatabase(object):

    def __init__(self, dbapi2_module):
        self.dbapi2_module = dbapi2_module

    def __getattr__(self, name):
        return getattr(self.dbapi2_module, name)

    @property
    def product(self):
        # TODO 注入数据库钩子时,会调用newrelic.api.database_trace.register_database_client函数,这个函数会给每个module加入一些属性,其中就有_nr_database_product,
        # TODO 以获取数据库的类型名称,比如MySQL,Redis等等,后面的property修饰的属性都是类似的
        return getattr(self.dbapi2_module, '_nr_database_product', None)

    @property
    def client(self):
        # TODO 获取模块名称
        name = getattr(self.dbapi2_module, '__name__', None)
        if name is None:
            name = getattr(self.dbapi2_module, '__file__', None)
        if name is None:
            name = str(self.dbapi2_module)
        return name

    @property
    def quoting_style(self):
        # TODO 是单引号风格还是双引号风格还是都有
        result = getattr(self.dbapi2_module, '_nr_quoting_style', None)

        if result is None:
            result = 'single'

        return result

    @property
    def explain_query(self):
        # TODO 执行计划
        return getattr(self.dbapi2_module, '_nr_explain_query', None)

    @property
    def explain_stmts(self):
        result = getattr(self.dbapi2_module, '_nr_explain_stmts', None)

        if result is None:
            result = ()

        return result


class SQLStatement(object):

    def __init__(self, sql, database=None):
        self._operation = None
        self._target = None
        self._uncommented = None
        self._obfuscated = None
        self._normalized = None
        self._identifier = None

        if isinstance(sql, six.binary_type):
            try:
                sql = sql.decode('utf-8')
            except UnicodeError as e:
                settings = global_settings()
                if settings.debug.log_explain_plan_queries:
                    _logger.debug('An error occurred while decoding sql '
                            'statement: %s' % e.reason)

                self._operation = ''
                self._target = ''
                self._uncommented = ''
                self._obfuscated = ''
                self._normalized = ''

        self.sql = sql
        self.database = database

    @property
    def operation(self):
        if self._operation is None:
            self._operation = _parse_operation(self.uncommented)
        return self._operation

    @property
    def target(self):
        if self._target is None:
            self._target = _parse_target(self.uncommented, self.operation)
        return self._target

    @property
    def uncommented(self):
        if self._uncommented is None:
            self._uncommented = _uncomment_sql(self.sql)
        return self._uncommented

    @property
    def obfuscated(self):
        if self._obfuscated is None:
            self._obfuscated = _uncomment_sql(_obfuscate_sql(self.sql,
                self.database))
        return self._obfuscated

    @property
    def normalized(self):
        if self._normalized is None:
            self._normalized = _normalize_sql(self.obfuscated)
        return self._normalized

    @property
    def identifier(self):
        if self._identifier is None:
            self._identifier = hash(self.normalized)
        return self._identifier

    def formatted(self, sql_format):
        if sql_format == 'off':
            return ''

        elif sql_format == 'raw':
            return self.sql

        else:
            return self.obfuscated


# TODO weakref.WeakValueDictionary本质是字典,但是与传统的字典又不一样,它里面的值类型是弱引用,当这些值不被引用时这个值就会被垃圾回收器回收,所以它是个动态字典
# TODO 有点类似于缓存(比如Redis里某些缓存如果长期不用的化也会被清除掉),实际上weakref.WeakValueDictionary对象被经常用来做缓存,在这里面也是一样
# TODO 先将所有DB钩子都装入_sql_statements里,在系统运行中发现用户用的是MySQL数据库,那其它的DB钩子就被垃圾回收器回收了,这可以优化内存使用
# TODO 这是一个高级用法!!!!!!!!
_sql_statements = weakref.WeakValueDictionary()


def sql_statement(sql, dbapi2_module):

    #TODO  dbapi2_module 到底是啥?他是与DB有关的钩子的module名,newrelic.api.database_trace.py register_database_client函数就是通过module来注册数据库源的
    # TODO 所以dbapi2_module是字符串,是项目里DB钩子的模块名

    key = (sql, dbapi2_module)

    result = _sql_statements.get(key, None)

    if result is not None:
        return result

    database = SQLDatabase(dbapi2_module)
    result = SQLStatement(sql, database)

    _sql_statements[key] = result

    return result
