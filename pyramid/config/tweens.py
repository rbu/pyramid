from zope.interface import implementer

from pyramid.interfaces import ITweens

from pyramid.compat import string_types
from pyramid.compat import is_nonstr_iter
from pyramid.compat import string_types
from pyramid.exceptions import ConfigurationError
from pyramid.tweens import excview_tween_factory
from pyramid.tweens import MAIN, INGRESS, EXCVIEW

from pyramid.config.util import action_method

class TweensConfiguratorMixin(object):
    def add_tween(self, tween_factory, under=None, over=None):
        """
        .. note:: This feature is new as of Pyramid 1.2.

        Add a 'tween factory'.  A :term:`tween` (a contraction of 'between')
        is a bit of code that sits between the Pyramid router's main request
        handling function and the upstream WSGI component that uses
        :app:`Pyramid` as its 'app'.  Tweens are a feature that may be used
        by Pyramid framework extensions, to provide, for example,
        Pyramid-specific view timing support, bookkeeping code that examines
        exceptions before they are returned to the upstream WSGI application,
        or a variety of other features.  Tweens behave a bit like
        :term:`WSGI` 'middleware' but they have the benefit of running in a
        context in which they have access to the Pyramid :term:`application
        registry` as well as the Pyramid rendering machinery.

        .. note:: You can view the tween ordering configured into a given
                  Pyramid application by using the ``ptweens``
                  command.  See :ref:`displaying_tweens`.

        The ``tween_factory`` argument must be a :term:`dotted Python name`
        to a global object representing the tween factory.

        The ``under`` and ``over`` arguments allow the caller of
        ``add_tween`` to provide a hint about where in the tween chain this
        tween factory should be placed when an implicit tween chain is used.
        These hints are only used when an explicit tween chain is not used
        (when the ``pyramid.tweens`` configuration value is not set).
        Allowable values for ``under`` or ``over`` (or both) are:

        - ``None`` (the default).

        - A :term:`dotted Python name` to a tween factory: a string
          representing the dotted name of a tween factory added in a call to
          ``add_tween`` in the same configuration session.

        - One of the constants :attr:`pyramid.tweens.MAIN`,
          :attr:`pyramid.tweens.INGRESS`, or :attr:`pyramid.tweens.EXCVIEW`.

        - An iterable of any combination of the above. This allows the user
          to specify fallbacks if the desired tween is not included, as well
          as compatibility with multiple other tweens.
        
        ``under`` means 'closer to the main Pyramid application than',
        ``over`` means 'closer to the request ingress than'.

        For example, calling ``add_tween('myapp.tfactory',
        over=pyramid.tweens.MAIN)`` will attempt to place the tween factory
        represented by the dotted name ``myapp.tfactory`` directly 'above'
        (in ``ptweens`` order) the main Pyramid request handler.
        Likewise, calling ``add_tween('myapp.tfactory',
        over=pyramid.tweens.MAIN, under='mypkg.someothertween')`` will
        attempt to place this tween factory 'above' the main handler but
        'below' (a fictional) 'mypkg.someothertween' tween factory.

        If all options for ``under`` (or ``over``) cannot be found in the
        current configuration, it is an error. If some options are specified
        purely for compatibilty with other tweens, just add a fallback of
        MAIN or INGRESS. For example, ``under=('mypkg.someothertween',
        'mypkg.someothertween2', INGRESS)``.  This constraint will require
        the tween to be located under both the 'mypkg.someothertween' tween,
        the 'mypkg.someothertween2' tween, and INGRESS. If any of these is
        not in the current configuration, this constraint will only organize
        itself based on the tweens that are present.

        Specifying neither ``over`` nor ``under`` is equivalent to specifying
        ``under=INGRESS``.

        Implicit tween ordering is obviously only best-effort.  Pyramid will
        attempt to present an implicit order of tweens as best it can, but
        the only surefire way to get any particular ordering is to use an
        explicit tween order.  A user may always override the implicit tween
        ordering by using an explicit ``pyramid.tweens`` configuration value
        setting.

        ``under``, and ``over`` arguments are ignored when an explicit tween
        chain is specified using the ``pyramid.tweens`` configuration value.

        For more information, see :ref:`registering_tweens`.

        """
        return self._add_tween(tween_factory, under=under, over=over,
                               explicit=False)

    @action_method
    def _add_tween(self, tween_factory, under=None, over=None, explicit=False):

        if not isinstance(tween_factory, string_types):
            raise ConfigurationError(
                'The "tween_factory" argument to add_tween must be a '
                'dotted name to a globally importable object, not %r' %
                tween_factory)

        name = tween_factory

        if name in (MAIN, INGRESS):
            raise ConfigurationError('%s is a reserved tween name' % name)

        tween_factory = self.maybe_dotted(tween_factory)

        def is_string_or_iterable(v):
            if isinstance(v, string_types):
                return True
            if hasattr(v, '__iter__'):
                return True

        for t, p in [('over', over), ('under', under)]:
            if p is not None:
                if not is_string_or_iterable(p):
                    raise ConfigurationError(
                        '"%s" must be a string or iterable, not %s' % (t, p))

        if over is INGRESS or is_nonstr_iter(over) and INGRESS in over:
            raise ConfigurationError('%s cannot be over INGRESS' % name)

        if under is MAIN or is_nonstr_iter(under) and MAIN in under:
            raise ConfigurationError('%s cannot be under MAIN' % name)

        registry = self.registry

        tweens = registry.queryUtility(ITweens)
        if tweens is None:
            tweens = Tweens()
            registry.registerUtility(tweens, ITweens)
            tweens.add_implicit(EXCVIEW, excview_tween_factory, over=MAIN)

        def register():
            if explicit:
                tweens.add_explicit(name, tween_factory)
            else:
                tweens.add_implicit(name, tween_factory, under=under, over=over)

        self.action(('tween', name, explicit), register)

class CyclicDependencyError(Exception):
    def __init__(self, cycles):
        self.cycles = cycles

    def __str__(self):
        L = []
        cycles = self.cycles
        for cycle in cycles:
            dependent = cycle
            dependees = cycles[cycle]
            L.append('%r sorts over %r' % (dependent, dependees))
        msg = 'Implicit tween ordering cycle:' + '; '.join(L)
        return msg

@implementer(ITweens)
class Tweens(object):
    def __init__(self):
        self.explicit = []
        self.names = []
        self.req_over = set()
        self.req_under = set()
        self.factories = {}
        self.order = []

    def add_explicit(self, name, factory):
        self.explicit.append((name, factory))

    def add_implicit(self, name, factory, under=None, over=None):
        self.names.append(name)
        self.factories[name] = factory
        if under is None and over is None:
            under = INGRESS
        if under is not None:
            if not is_nonstr_iter(under):
                under = (under,)
            self.order += [(u, name) for u in under]
            self.req_under.add(name)
        if over is not None:
            if not is_nonstr_iter(over): #hasattr(over, '__iter__'):
                over = (over,)
            self.order += [(name, o) for o in over]
            self.req_over.add(name)

    def implicit(self):
        order = [(INGRESS, MAIN)]
        roots = []
        graph = {}
        names = [INGRESS, MAIN]
        names.extend(self.names)

        for a, b in self.order:
            order.append((a, b))

        def add_node(node):
            if not node in graph:
                roots.append(node)
                graph[node] = [0] # 0 = number of arcs coming into this node

        def add_arc(fromnode, tonode):
            graph[fromnode].append(tonode)
            graph[tonode][0] += 1
            if tonode in roots:
                roots.remove(tonode)

        for name in names:
            add_node(name)

        has_over, has_under = set(), set()
        for a, b in order:
            if a in names and b in names: # deal with missing dependencies
                add_arc(a, b)
                has_over.add(a)
                has_under.add(b)

        if not self.req_over.issubset(has_over):
            raise ConfigurationError(
                'Detected tweens with no satisfied over dependencies: %s'
                % (', '.join(sorted(self.req_over - has_over)))
            )
        if not self.req_under.issubset(has_under):
            raise ConfigurationError(
                'Detected tweens with no satisfied under dependencies: %s'
                % (', '.join(sorted(self.req_under - has_under)))
            )

        sorted_names = []

        while roots:
            root = roots.pop(0)
            sorted_names.append(root)
            children = graph[root][1:]
            for child in children:
                arcs = graph[child][0]
                arcs -= 1
                graph[child][0] = arcs 
                if arcs == 0:
                    roots.insert(0, child)
            del graph[root]

        if graph:
            # loop in input
            cycledeps = {}
            for k, v in graph.items():
                cycledeps[k] = v[1:]
            raise CyclicDependencyError(cycledeps)

        result = []

        for name in sorted_names:
            if name in self.names:
                result.append((name, self.factories[name]))

        return result

    def __call__(self, handler, registry):
        if self.explicit:
            use = self.explicit
        else:
            use = self.implicit()
        for name, factory in use[::-1]:
            handler = factory(handler, registry)
        return handler
