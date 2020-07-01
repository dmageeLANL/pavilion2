import matplotlib.pyplot as plt
import numpy as np
import os
from datetime import datetime

from pavilion import commands
from pavilion import series
from pavilion.test_run import TestRun


class GraphCommand(commands.Command):

    def __init__(self):
        super().__init__(
            'graph',
            'Command used to produce graph for a group of tests.',
            short_help="Produce graph for tests."
        )

    def _setup_arguments(self, parser):

        parser.add_argument(
            '--exclude', nargs='*',
            help='Exclude tests, series, sys_names, test_names, '
                 'or users by providing specific IDs or names.'
        ),
        parser.add_argument(
            '--test_name', action='store', default=False,
            help='Filter tests to graph by test_name.'
        ),
        parser.add_argument(
            '--sys_name', action='store', default=False,
            help='Filter tests by sys_name.'
        ),
        parser.add_argument(
            '--user', action='store', default=False,
            help='Filter tests by user.'
        ),
        parser.add_argument(
            '--date', action='store', default=False,
            help='Filter tests by date.'
        ),
        parser.add_argument(
            'tests', nargs='*', action='store',
            help='The names of the tests to graph'
        ),
        parser.add_argument(
            '--y', nargs='+', action='store',
            help='Specify the value(s) graphed from the results '
                 'for each test.'
        ),
        parser.add_argument(
            '--x', nargs=1, action='store',
            help='Specify the value to be used on the X axis.'
        ),
        parser.add_argument(
            '--x_label', action='store', default=False,
            help='Specify the x axis label.'
        ),
        parser.add_argument(
            '--y_label', action='store', default=False,
            help='Specify the y axis label.'
        )
    def run(self, pav_cfg, args):

        tests_dir = pav_cfg.working_dir / 'test_runs'

        # No tests provided, check filters, append tests.
        if not args.tests:
            for test_path in tests_dir.iterdir():
                if not test_path.is_dir():
                    continue
                # Filter excluded test ids.
                if test_path.name in args.exclude:
                   continue
                # Filter tests by date.
                if args.date:
                    pass
                # Filter tests by user.
                if test_path.owner() in args.exclude:
                    continue
                if args.user and test_path.owner() not in args.user:
                    continue
                args.tests.append(test_path.name)

        test_list = []
        for test_id in args.tests:
            # Expand series provide, as long as it wasn't meant to be excluded.
            if test_id.startswith('s') and test_id not in args.exclude:
                test_list.extend(series.TestSeries.from_id(pav_cfg, test_id))
            else:
                test_list.append(int(test_id))



