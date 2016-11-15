import os
import sys
import re
import operator
import json
from commands import getoutput
from collections import defaultdict

import py
from dotmap import DotMap
import pygal

class SecondsFormatter(pygal.formatters.HumanReadable):

    def __call__(self, val):
        val = super(SecondsFormatter, self).__call__(val)
        if not val[-1].isdigit():
            val = val[:-1] + ' ' + val[-1]
        return val + 's'

class GroupedBarChart(object):
    """
    Helper class to build a pygal Bar chart with groups.
    Each data point has two property:

      - series_name: each series gets a different color and it's shown in the
        legend

      - group: the bars belonging to each group are located together, and the
        name of the group is shown on the X axis
    """

    def __init__(self, title):
        self.title = title
        self.all_series = set()
        self.all_groups = set()
        self.data = {} # [(series_name, group)] -> point

    def get_point(self, b):
        return {
            'value': b.stats.mean,
            'ci': {
                'type': 'continuous',
                'sample_size': b.stats.rounds,
                'stddev': b.stats.stddev
            }
        }

    def add(self, series_name, group, b):
        self.all_series.add(series_name)
        self.all_groups.add(group)
        key = (series_name, group)
        if key in self.data:
            raise ValueError("Duplicate key: %s" % (key,))
        self.data[(series_name, group)] = self.get_point(b)

    def build(self):
        chart = pygal.Bar(pretty_print=True)
        chart.config.value_formatter = SecondsFormatter()
        chart.y_title = 'Time'
        chart.title = self.title
        series_names = sorted(self.all_series)
        groups = sorted(self.all_groups)
        chart.x_labels = groups
        for name in series_names:
            series = [self.data.get((name, group), None)
                      for group in groups]
            chart.add(name, series)
        return chart

class TimelineChart(object):

    def __init__(self, title):
        self.title = title
        self.data = defaultdict(list)
        self.min = float('inf')
        self.max = float('-inf')

    def get_point(self, b):
        return {
            'value': b.stats.min,
            'label': b.name
        }

    def add(self, series_name, group, b):
        assert group is None
        p = self.get_point(b)
        self.data[series_name].append(p)
        self.min = min(self.min, p['value'])
        self.max = max(self.max, p['value'])

    def build(self):
        chart = pygal.Line()
        chart.title = self.title
        for name, points in self.data.iteritems():
            chart.add(name, points)
        #
        # try to compute a reasonable Y scale;
        chart.min_scale = 10 # make sure to have 10 horizontal bands
        estimate_max = self.min*2 # min+10% will cross one horizontal band
        estimate_max = max(self.max, estimate_max)
        chart.range = [0, estimate_max]
        return chart

def display(chart):
    # for development
    if isinstance(chart, GroupedBarChart):
        chart = chart.build()
    chart.render_to_png('/tmp/chart.png')
    os.system('feh /tmp/chart.png')


class PyQuery(list):
    """
    Extend a list with an API which is vaguely inspired by jQuery to filter
    and interact with the data.
    """

    def filter(self, predicate):
        new_items = [item for item in self if predicate(item)]
        return self.__class__(new_items)

    def getattr(self, attr, strict=False):
        getter = operator.attrgetter(attr)
        new_items = []
        for item in self:
            try:
                new_items.append(getter(item))
            except (AttributeError, KeyError):
                if strict:
                    raise
                pass
        return self.__class__(new_items)

    def __getattr__(self, attr):
        return self.getattr(attr, strict=True)

    def __call__(self, *args, **kwds):
        return self.__class__([item(*args, **kwds) for item in self])

    def pp(self):
        from pprint import pprint
        for item in self:
            if isinstance(item, DotMap):
                item.pprint()
            else:
                pprint(item)


class Charter(object):
    """
    Chart-maker --> Charter :)
    """

    def __init__(self, dir, revision):
        self.dir = dir
        self.revision = revision
        self.clone_maybe()
        self.load_all()
        x = self.all.filter(
            lambda b: b.name == 'test_numeric[Capnpy-int16]' and b.info.machine_info.python_implementation == 'CPython')
        #import pdb;pdb.set_trace()

    def clone_maybe(self):
        # clone the .benchmarks repo, if it's needed
        if self.dir.check(exists=False):
            print 'Cloning the benchmarks repo'
            url = getoutput('git config remote.origin.url')
            cmd = 'git clone --depth=1 --branch=benchmarks {url} {dir}'
            ret = os.system(cmd.format(url=url, dir=self.dir))
            assert ret == 0

    def load_all(self):
        # load all benchmarks
        self.all = PyQuery()
        for f in self.dir.visit('*.json'):
            self.all += self.load_one(f)
        #
        # filter a subset containing only the results for the current revision
        self.latest_warning = None
        self.latest = self.all.filter(
            lambda b: b.info.commit_info.id == self.revision)
        if not self.latest:
            self.latest_warning = ('WARNING: rev %s not found, using latest '
                                   'data' % self.revision[:6])
            print self.latest_warning
            # no benchmarks found for the current revision. This is likely to
            # happen on the development machine; in this case, we simply take
            # the newest benchmarks, regardless of the revision
            self.latest = PyQuery()
            all_impls = set(self.all.info.machine_info.python_implementation)
            for impl in all_impls:
                subset = self.all.filter(
                    lambda b: b.info.machine_info.python_implementation == impl)
                newest_datetime = max(subset.info.datetime)
                self.latest += subset.filter(
                    lambda b: b.info.datetime == newest_datetime)

    @classmethod
    def load_one(cls, f):
        s = f.read()
        if s == '':
            return []
        d = json.loads(s)
        info = DotMap(d, _dynamic=False)
        #
        # reverse the relationship between info and benchmarks: each benchmark
        # has a pointer to the info (which has no longer a list of benhmarks)
        benchmarks = info.pop('benchmarks')
        for b in benchmarks:
            b.filename = str(f)
            b.info = info
            # just a shortcut
            b.python_implementation = b.info.machine_info.python_implementation
        return benchmarks

    @classmethod
    def extract_test_name(cls, name):
        m = re.match(r'test_([^\[]+)(\[.*\])?', name)
        assert m
        return m.group(1)

    def get_chart(self, timeline, benchmarks, title, filter, series, group):
        benchmarks = benchmarks.filter(filter)
        if timeline:
            # XXX: sort the values
            # XXX: check that the CPU is always the same
            chart = TimelineChart(title)
        else:
            chart = GroupedBarChart(title)
        #
        for b in benchmarks:
            series_name = series(b)
            group_name = group(b)
            chart.add(series_name, group_name, b)
        chart = chart.build()
        if self.latest_warning and not timeline:
            chart.x_title = self.latest_warning
        return chart

    def run_directive(self, title, options, content):
        namespace = {'charter': self}
        if content:
            src = py.code.Source('\n'.join(content))
            exec src.compile() in namespace
        #
        def get_function(name):
            src = 'lambda b: ' + options.get(name, 'None')
            return eval(src, namespace)
        #
        timeline = 'timeline' in options
        benchmarks = self.all if timeline else self.latest
        #
        # split the benchmarks into various group by using the foreach key
        foreach = get_function('foreach')
        d = defaultdict(PyQuery)
        for b in benchmarks:
            key = foreach(b)
            d[key].append(b)
        #
        # generate a chart for each "foreach" group
        res = []
        for key in sorted(d):
            benchmarks = d[key]
            newtitle = title
            if key:
                newtitle += ' [%s]' % key
            chart = self.get_chart(
                timeline = timeline,
                benchmarks = benchmarks,
                title = newtitle,
                filter = get_function('filter'),
                series = get_function('series'),
                group = get_function('group'))
            res.append(chart)
        return res
