"""Cancels tests as prescribed by the user."""

import errno
import os
import signal

from pavilion import commands
from pavilion import output
from pavilion import schedulers
from pavilion import series
from pavilion import series_util
from pavilion.status_file import STATES
from pavilion.status_utils import print_from_tests
from pavilion.test_run import TestRun, TestRunError


class CancelCommand(commands.Command):
    """Cancel a set of commands using the appropriate scheduler."""

    def __init__(self):
        super().__init__(
            'cancel',
            'Cancel a test, tests, or test series.',
            short_help="Cancel a test, tests, or test series."
        )

    def _setup_arguments(self, parser):

        parser.add_argument(
            '-s', '--status', action='store_true', default=False,
            help='Prints status of cancelled jobs.'
        )
        parser.add_argument(
            '-j', '--json', action='store_true', default=False,
            help='Prints status of cancelled jobs in json format.'
        )
        parser.add_argument(
            '-a', '--all', action='store_true', default=False,
            help='Cancels all jobs currently queued that are owned by the '
                 'current user'
        )
        parser.add_argument(
            'tests', nargs='*', action='store',
            help='The name(s) of the tests to cancel. These may be any mix of '
                 'test IDs and series IDs. If no value is provided, the most '
                 'recent series submitted by the user is cancelled. '
        )

    def run(self, pav_cfg, args):
        """Cancel the given tests."""

        user_id = os.geteuid()  # gets unique user id

        if not args.tests:
            # user wants to cancel all current tests
            if args.all:
                tests_dir = pav_cfg.working_dir/'test_runs'
                # iterate through all the tests in the tests directory
                for test in tests_dir.iterdir():
                    test_owner_id = test.stat().st_uid
                    if test_owner_id == user_id:
                        if not (test/'RUN_COMPLETE').exists():
                            test_id = test.name
                            args.tests.append(test_id)
            else:
                # Get the last series ran by this user.
                series_id = series_util.load_user_series_id(pav_cfg)
                if series_id is not None:
                    args.tests.append(series_id)

        test_list = []
        for test_id in args.tests:
            if test_id.startswith('s'):
                try:
                    series_pgid = series.TestSeries.get_pgid(pav_cfg, test_id)
                    test_list.extend(series.TestSeries.from_id(pav_cfg,
                                                               test_id)
                                     .tests)
                except series_util.TestSeriesError as err:
                    output.fprint(
                        "Series {} could not be found.\n{}"
                        .format(test_id, err.args[0]),
                        file=self.errfile, color=output.RED)
                    return errno.EINVAL
                except ValueError as err:
                    output.fprint(
                        "Series {} is not a valid series.\n{}"
                        .format(test_id, err.args[0]),
                        color=output.RED, file=self.errfile)
                    return errno.EINVAL

                try:
                    # if there's a series PGID, kill the series PGID
                    if series_pgid:
                        os.killpg(series_pgid, signal.SIGTERM)
                        output.fprint('Killed process {}, which is series {}.'
                                      .format(series_pgid, test_id),
                                      file=self.outfile)

                except ProcessLookupError:
                    output.fprint("Unable to kill {}. No such process: {}"
                                  .format(test_id, series_pgid),
                                  color=output.RED, file=self.errfile)
            else:
                try:
                    test_list.append(int(test_id))
                except ValueError as err:
                    output.fprint(
                        "Test {} is not a valid test.\n{}".format(test_id,
                                                                  err),
                        file=self.errfile, color=output.RED
                    )
                    return errno.EINVAL

        cancel_failed = False
        test_object_list = []
        for test_id in test_list:
            try:
                test = TestRun.load(pav_cfg, test_id)
                sched = schedulers.get_plugin(test.scheduler)
                test_object_list.append(test)

                status = test.status.current()
                # Only attempt to cancel test runs that are actually running
                # or scheduled to run.
                if status.state in (STATES.RUNNING, STATES.SCHEDULED):
                    # Sets status based on the result of sched.cancel_job.
                    # Ran into trouble when 'cancelling' jobs that never
                    # actually started, ie. build errors/created job states.
                    cancel_status = sched.cancel_job(test)
                    test.status.set(cancel_status.state, cancel_status.note)
                    test.set_run_complete()
                    output.fprint(
                        "Test {} cancelled."
                        .format(test_id), file=self.outfile,
                        color=output.GREEN)

                else:
                    output.fprint(
                        "Test {} could not be cancelled has state: {}."
                        .format(test_id, status.state),
                        file=self.outfile,
                        color=output.RED)

            except TestRunError as err:
                output.fprint(
                    "Test {} could not be cancelled, cannot be found. \n{}"
                    .format(test_id, err),
                    file=self.errfile,
                    color=output.RED)
                return errno.EINVAL

        # Only prints statuses of tests if option is selected
        # and test_list is not empty
        if args.status and test_object_list:
            print_from_tests(pav_cfg, test_object_list, self.outfile,
                             args.json)
            return cancel_failed

        return cancel_failed
