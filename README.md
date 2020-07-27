### newrelic Python 代理源码分析 ###

#### 代码结构
```buildoutcfg
-- newrelic/
   -- admin/
   -- api/
   -- bootstrap/
   -- common/
   -- core/
   -- extras/
   -- hooks/
   -- network/
   -- packages/
   -- samplers/
   -- __init__.py
   -- agent.py
   -- build.py
   -- config.py
   -- console.py
```

admin/ 是与管理有关<br>
api/ 对外接口<br>
core/ 核心的数据结构<br>
hooks/ 钩子，监控第三方框架的钩子，也可以自己扩展<br>
packages/  必用的第三方依赖包<br>


#### 主要数据结构
core.agent.Agent: 代理对象，单例模式，一个线程只能启用一个Agent对象，它会将core.application.Application对象的收集数据的函数设置成守护线程，然后定时执行 <br>
core.application.Application: 应用，一个Agent可以有多个Application，Application里主要完成上报数据(requests.Session会话对象来完成数据上报)和收集数据的存储器(是core.stats_engine.StatsEngine对象，通过调用该对象的方法来记录事务数据，异常数据，分布式数据等等；当采集到的数据都存储在此处，如果满足上报数据条件，就会将数据上报，然后清空存储器)<br>
core.stats_engine.StatsEngine:数据收集器，所有采集的数据都存储在此处，按事件种类收集数据,每个core.application.Application对象有一个收集器<br>
api.application.Application:



