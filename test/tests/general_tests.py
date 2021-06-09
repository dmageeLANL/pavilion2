import grp
import os
import shutil
import stat
import subprocess as sp
from pathlib import Path, PurePath
from typing import List

import yc_yaml as yaml
from pavilion import utils
from pavilion.unittest import PavTestCase
from pavilion import test_run


class GeneralTests(PavTestCase):
    """Tests that apply to the whole of Pavilion, rather than some particular
    part."""

    def __init__(self, *args, **kwargs):

        super().__init__(*args, **kwargs)

        # Find a group that isn't the user's default group (or sudo), and
        # use that as our default group.
        login = utils.get_login()
        def_gid = os.getgid()
        candidates = [group for group in grp.getgrall() if
                      (login in group.gr_mem
                       and def_gid != group.gr_gid)]

        if not candidates:
            self.orig_group = None
            self.alt_group = None
            self.alt_group2 = None
        else:
            self.orig_group = grp.getgrgid(def_gid).gr_name
            self.alt_group = candidates[0]  # type: grp.struct_group
            self.alt_group2 = candidates[1]  # type: grp.struct_group

        self.umask = 0o007

    def setUp(self) -> None:

        with self.PAV_CONFIG_PATH.open() as pav_cfg_file:
            raw_cfg = yaml.load(pav_cfg_file)

        self.working_dir = self.PAV_ROOT_DIR/'test'/'working_dir'/'wd_perms'

        if self.working_dir.exists():
            shutil.rmtree(self.working_dir.as_posix())

        self.working_dir.mkdir()

        if self.alt_group is None:
            self.fail("Your user must be in at least two groups (other than "
                      "the user's group) to run this test.")

        raw_cfg['shared_group'] = self.alt_group.gr_name
        raw_cfg['umask'] = self.umask
        raw_cfg['working_dir'] = self.working_dir.as_posix()

        self.config_dir = self.TEST_DATA_ROOT/'configs-permissions'
        with (self.config_dir/'pavilion.yaml').open('w') as pav_cfg_file:
            yaml.dump(raw_cfg, stream=pav_cfg_file)

    def test_permissions(self):
        """Make sure all files written by Pavilion have the correct
        permissions."""

        tests = [
            'perm.base',
            'perm.tar',
            'perm.dir',
        ]

        cmd = [(self.PAV_ROOT_DIR/'bin'/'pav').as_posix(), 'run'] + tests

        self.run_test_cmd(cmd)

        builds = [p for p in (self.working_dir/'builds').iterdir()
                  if p.is_dir()]
        self.check_permissions(self.working_dir, self.alt_group, self.umask,
                               exclude=builds)
        for build in builds:
            self.check_permissions(build, self.alt_group, self.umask | 0o222)

    def run_test_cmd(self, cmd, run_succeeds=True):

        env = os.environ.copy()
        env['PAV_CONFIG_DIR'] = self.config_dir.as_posix()

        proc = sp.Popen(cmd, env=env, stdout=sp.PIPE, stderr=sp.STDOUT)
        out = proc.stdout.read().decode()
        if (proc.wait(3) != 0) == run_succeeds:
            self.fail("Error running command.\n{}".format(out))
        self.wait_tests(self.working_dir)

    def test_legacy_runs(self):
        """Check loading of legacy run dirs."""

        legacy_path = self.TEST_DATA_ROOT/'legacy'
        runs_path = legacy_path/'runs.txt'
        wdir = self.pav_cfg.working_dir

        runs = []
        with runs_path.open() as runs_file:
            for line in runs_file:
                line = line.strip()
                if line and not line.startswith('#'):
                    runs.append(line)

        for run in runs:
            run_path = legacy_path/run
            dst_path = wdir/'test_runs'/run
            shutil.copytree(run_path.as_posix(), dst_path.as_posix(),
                            symlinks=True)

            # Move the build directory into place
            build_dst = Path(os.readlink((run_path/'build_origin').as_posix()))
            build_dst = dst_path/build_dst
            (dst_path/'build_dir').rename(build_dst)

            test = test_run.TestRun.load(self.pav_cfg, int(run))
            self.assertTrue(test.results)
            self.assertTrue(test.complete)
