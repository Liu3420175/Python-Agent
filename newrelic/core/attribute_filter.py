# Attribute "destinations" represented as bitfields.
# TODO 属性是键值对
# TODO 可以通过多种方式收集属性：
# TODO 邮件属性：这些是在从队列或主题接收的邮件上设置的属性。
# TODO HTTP请求属性：这些是HTTP请求的参数。
# TODO 用户属性：这些是用户通过每个代理的API提供的属性。
# TODO 代理属性：这些是座席捕获的属性。 例如，httpResponseCode和httpResponseMessage。
# TODO 通过属性，我们能获取更详情的信息

# TODO NewRelic上报的数据有多种数据结构，不是所有的功能块都能查看属性，所有要把属性和功能块绑定起来，也就是目的地
# TODO https://docs.newrelic.com/docs/agents/manage-apm-agents/agent-data/agent-attributes

# TODO 配置文件里的attribute的目的地
# TODO
DST_NONE = 0x0
DST_ALL  = 0x3F
DST_TRANSACTION_EVENTS   = 1 << 0
DST_TRANSACTION_TRACER   = 1 << 1
DST_ERROR_COLLECTOR      = 1 << 2
DST_BROWSER_MONITORING   = 1 << 3
DST_SPAN_EVENTS          = 1 << 4
DST_TRANSACTION_SEGMENTS = 1 << 5

# TODO 通过用位域的方式来查了哪些目的地启动了收集属性功能,这种设计方法很好


class AttributeFilter(object):

    # Apply filtering rules to attributes.
    #
    # Upon initialization, an AttributeFilter object will take all attribute
    # related settings and turn them into an ordered tuple of
    # AttributeFilterRules. During registration of the agent, a single
    # AttributeFilter object will be created, and will remain unchanged for
    # the life of the agent run. Changing attribute related settings/rules
    # requires restarting the agent.
    #
    # Each attribute can belong to one or more destinations. To determine
    # which destination an attribute belongs to, call the apply() method,
    # which will apply all of the rules to the attribute and return a set of
    # destinations.
    #
    # Destinations are represented as bitfields, where the bit positions
    # specified in the DST_* constants are used to indicate which
    # destination an attribute belongs to.
    #
    # The algorithm for applying filtering rules is as follows:
    #
    #   1. Start with a bitfield representing the set of default destinations
    #      passed in to apply().
    #
    #   2. Mask this bitfield against the set of destinations that have
    #      attribute enabled at all.
    #
    #   3. Traverse the list of AttributeFilterRules in order, applying
    #      each matching rule, but taking care to not let rules override the
    #      enabled status of each destination. Each matching rule may mutate
    #      the bitfield.
    #
    #   4. Return the resulting bitfield after all rules have been applied.
    # TODO 为属性申请过滤规则
    # TODO 当初始化后，一个AttributeFilter对象会获取所有与setting有关的属性，并且将它们转换成一个有序的元组对象AttributeFilterRules
    # TODO 在代理注册期间，单个AttributeFilter会被创建并且在代理的生命周期里一直保存不变，更改setting/rule属性需要重启代理
    # TODO 一个属性可能有多个目的地,因为有的地方收集的属性相同,公用的话可以节省空间提高效率
    # TODO {'enabled_destinations': 55,                    开启了属性收集的地方
    #  'rules': (),                                        规则
    #  'cache': {('enable', 4): 4, ('include', 4): 4}}     缓存
    def __init__(self, flattened_settings):
        """

        :param flattened_settings:  # TODO 初始化后的setting,是个字典对象
        """
        # TODO enabled_destinations 通过位域的方式来确定有哪些地方要收集属性，上面的DST_*定义就定位了目的地和位的关系
        self.enabled_destinations = self._set_enabled_destinations(flattened_settings)
        self.rules = self._build_rules(flattened_settings)
        self.cache = {}

    def __repr__(self):
        return "<AttributeFilter: destinations: %s, rules: %s>" % (
                bin(self.enabled_destinations), self.rules)

    def _set_enabled_destinations(self, settings):

        # Determines and returns bitfield representing attribute destinations enabled.

        enabled_destinations = DST_NONE

        if settings.get('transaction_segments.attributes.enabled', None):
            enabled_destinations |= DST_TRANSACTION_SEGMENTS

        if settings.get('span_events.attributes.enabled', None):
            enabled_destinations |= DST_SPAN_EVENTS

        if settings.get('transaction_tracer.attributes.enabled', None):
            enabled_destinations |= DST_TRANSACTION_TRACER

        if settings.get('transaction_events.attributes.enabled', None):
            enabled_destinations |= DST_TRANSACTION_EVENTS

        if settings.get('error_collector.attributes.enabled', None):
            enabled_destinations |= DST_ERROR_COLLECTOR

        if settings.get('browser_monitoring.attributes.enabled', None):
            enabled_destinations |= DST_BROWSER_MONITORING

        if not settings.get('attributes.enabled', None):
            enabled_destinations = DST_NONE

        return enabled_destinations

    def _build_rules(self, settings):

        # "Rule Templates" below are used for building AttributeFilterRules.
        #
        # Each tuple includes:
        #   1. Setting name
        #   2. Bitfield value for destination for that setting.
        #   3. Boolean that represents whether the setting is an "include" or not.

        rule_templates = (
            ('attributes.include', DST_ALL, True), # TODO 全局
            ('attributes.exclude', DST_ALL, False),
            ('transaction_events.attributes.include', DST_TRANSACTION_EVENTS, True), # TODO 事物事件
            ('transaction_events.attributes.exclude', DST_TRANSACTION_EVENTS, False),
            ('transaction_tracer.attributes.include', DST_TRANSACTION_TRACER, True), # TODO 事物Tracer
            ('transaction_tracer.attributes.exclude', DST_TRANSACTION_TRACER, False),
            ('error_collector.attributes.include', DST_ERROR_COLLECTOR, True),  # TODO 错误收集器
            ('error_collector.attributes.exclude', DST_ERROR_COLLECTOR, False),
            ('browser_monitoring.attributes.include', DST_BROWSER_MONITORING, True),  # TODO 浏览器监控
            ('browser_monitoring.attributes.exclude', DST_BROWSER_MONITORING, False),
            ('span_events.attributes.include', DST_SPAN_EVENTS, True),  # TODO 跨度事物
            ('span_events.attributes.exclude', DST_SPAN_EVENTS, False),
            ('transaction_segments.attributes.include', DST_TRANSACTION_SEGMENTS, True),
            ('transaction_segments.attributes.exclude', DST_TRANSACTION_SEGMENTS, False),
        )

        rules = []

        for (setting_name, destination, is_include) in rule_templates:

            for setting in settings.get(setting_name) or ():
                rule = AttributeFilterRule(setting, destination, is_include)
                rules.append(rule)

        rules.sort()

        return tuple(rules)

    def apply(self, name, default_destinations):
        if self.enabled_destinations == DST_NONE:
            return DST_NONE

        cache_index = (name, default_destinations)

        if cache_index in self.cache:
            return self.cache[cache_index]

        destinations = self.enabled_destinations & default_destinations

        for rule in self.rules:
            if rule.name_match(name):
                if rule.is_include:
                    inc_dest = rule.destinations & self.enabled_destinations
                    destinations |= inc_dest
                else:
                    destinations &= ~rule.destinations

        self.cache[cache_index] = destinations
        return destinations

class AttributeFilterRule(object):

    def __init__(self, name, destinations, is_include):
        self.name = name.rstrip('*')
        self.destinations = destinations
        self.is_include = is_include
        self.is_wildcard = name.endswith('*') # TODO 是否有通配符

    def _as_sortable(self):

        # Represent AttributeFilterRule as a tuple that will sort properly.
        #
        # Sorting rules:
        #
        #   1. Rules are sorted lexicographically by name, so that shorter,
        #      less specific names come before longer, more specific ones.
        #
        #   2. If names are the same, then rules with wildcards come before
        #      non-wildcards. Since False < True, we need to invert is_wildcard
        #      in the tuple, so that rules with wildcards have precedence.
        #
        #   3. If names and wildcards are the same, then include rules come
        #      before exclude rules. Similar to rule above, we must invert
        #      is_include for correct sorting results.
        #
        # By taking the sorted rules and applying them in order against an
        # attribute, we will guarantee that the most specific rule is applied
        # last, in accordance with the Agent Attributes spec.

        return (self.name, not self.is_wildcard, not self.is_include)

    def __eq__(self, other):
        return self._as_sortable() == other._as_sortable()

    def __ne__(self, other):
        return self._as_sortable() != other._as_sortable()

    def __lt__(self, other):
        return self._as_sortable() < other._as_sortable()

    def __le__(self, other):
        return self._as_sortable() <= other._as_sortable()

    def __gt__(self, other):
        return self._as_sortable() > other._as_sortable()

    def __ge__(self, other):
        return self._as_sortable() >= other._as_sortable()

    def __repr__(self):
        return '(%s, %s, %s, %s)' % (self.name, bin(self.destinations),
                self.is_wildcard, self.is_include)

    def name_match(self, name):
        if self.is_wildcard:
            return name.startswith(self.name)
        else:
            return self.name == name
