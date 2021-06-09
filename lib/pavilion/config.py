"""This module defines the base configuration for Pavilion itself.

Pavilion can have multiple configuration directories. However, many options apply
only to the 'base' configuration. Additional directories can be specified in that base
config or through other options."""

import logging
import os
import sys
from pathlib import Path
from collections import OrderedDict, UserDict
from typing import List

import pavilion.output
import yaml_config as yc

LOGGER = logging.getLogger('pavilion.' + __file__)

# Figure out what directories we'll search for the base configuration.
PAV_CONFIG_SEARCH_DIRS = [Path('./').resolve()]

PAV_CONFIG_NAME = 'pavilion.yaml'
CONFIG_NAME = 'config.yaml'

try:
    USER_HOME_PAV = (Path('~')/'.pavilion').expanduser()
except OSError:
    # I'm not entirely sure this is the right error to catch.
    USER_HOME_PAV = Path('/tmp')/os.getlogin()/'.pavilion'

PAV_CONFIG_SEARCH_DIRS.append(USER_HOME_PAV)

PAV_CONFIG_DIR = os.environ.get('PAV_CONFIG_DIR', None)

if PAV_CONFIG_DIR is not None:
    PAV_CONFIG_DIR = Path(PAV_CONFIG_DIR)

    if PAV_CONFIG_DIR.exists():
        PAV_CONFIG_SEARCH_DIRS.append(
            Path(PAV_CONFIG_DIR)
        )
    else:
        pavilion.output.fprint(
            "Invalid path in env var PAV_CONFIG_DIR: '{}'. Ignoring."
            .format(PAV_CONFIG_DIR),
            color=pavilion.output.YELLOW,
            file=sys.stderr
        )

PAV_ROOT = Path(__file__).resolve().parents[2]

# Use this config file, if it exists.
PAV_CONFIG_FILE = os.environ.get('PAV_CONFIG_FILE', None)


class ExPathElem(yc.PathElem):
    """Expand environment variables in the path."""

    def validate(self, value, partial=False):
        """Expand environment variables in the path."""

        path = super().validate(value, partial=partial)

        if path is None:
            return None
        elif isinstance(path, str):
            path = Path(path)

        path = Path(os.path.expandvars(path.as_posix()))
        path = path.expanduser()
        return path


def config_dirs_validator(config, values):
    """Get all of the configurations directories and convert them
    into path objects."""

    config_dirs = []

    if config['user_config'] and USER_HOME_PAV and USER_HOME_PAV.exists():
        config_dirs.append(USER_HOME_PAV.resolve())

    if PAV_CONFIG_DIR is not None and PAV_CONFIG_DIR.exists():
        config_dirs.append(PAV_CONFIG_DIR.resolve())

    for value in values:
        path = Path(value)
        try:
            if not path.exists():
                pavilion.output.fprint(
                    "Config directory {} does not exist. Ignoring."
                    .format(value),
                    file=sys.stderr,
                    color=pavilion.output.YELLOW
                )

                # Attempt to force a permissions error if we can't read this directory.
                list(path.iterdir())

        except PermissionError:
            pavilion.output.fprint(
                "Cannot access config directory {}. Ignoring.",
                file=sys.stderr, color=pavilion.output.YELLOW)
            continue

        if path not in config_dirs:
            path = path.resolve()
            config_dirs.append(path)

    return config_dirs


def _configs_validator(pav_cfg, values) -> OrderedDict:
    """Setup the config dictionaries for each configuration directory. This will involve loading
    each directories pavilion.yaml, and saving the results in this dict. These will be
    in an ordered dictionary by label."""

    configs = OrderedDict()

    if values:
        raise ValueError("The 'configs' option is not meant to be set manually.")

    config_dirs = pav_cfg['config_dirs']  # type: List[Path]
    loader = ConfigLoader()

    label_i = 1

    for config_dir in config_dirs:
        config_path = config_dir/CONFIG_NAME
        try:
            if not (config_path.exists() and config_path.is_file()):
                config = loader.load_empty()
            else:
                with config_path.open() as config_file:
                    config = loader.load(config_file)

        except PermissionError as err:
            pavilion.output.fprint(
                "Could not load pavilion config at '{}'. Skipping...: {}"
                    .format(config_path.as_posix(), err.args[0])
            )

            continue

        except Exception as err:
            raise RuntimeError("Pavilion.yaml for config path '{}' has error: {}"
                               .format(config_dir.as_posix(), err.args[0]))

        label = config.get('label')
        # Set the user's home pavilion directory label to 'user'.
        if not label:
            if config_dir == USER_HOME_PAV:
                label = 'user'
            # Set the label to 'main' if the config_dir is the one set by PAV_CONFIG_DIR
            elif config_dir == PAV_CONFIG_DIR:
                label = 'main'
            elif config_dir == Path(__file__).parent:
                label = 'lib'

        if label in configs or not label:
            label = '<not_defined>' if label is None else label
            new_label = 'lbl{}'.format(label_i)
            label_i += 1
            pavilion.output.fprint(
                "Missing or duplicate label '{}' for config path '{}'. "
                "Using label '{}'".format(label, config_path.as_posix(), new_label),
                file=sys.stderr, color=pavilion.output.YELLOW)
            config['label'] = new_label

        working_dir = config.get('working_dir')  # type: Path
        if working_dir is None:
            working_dir = pav_cfg['working_dir']
        working_dir = working_dir.expanduser()
        if not working_dir.is_absolute():
            working_dir = config_dir/working_dir

        try:
            _setup_working_dir(working_dir)
        except RuntimeError as err:
            pavilion.output.fprint(
                "Could not configure working directory for config path '{}'. Skipping.\n{}"
                .format(config_path.as_posix(), err.args[0]),
                file=sys.stderr, color=pavilion.output.YELLOW)
            continue

        config['working_dir'] = working_dir
        config['path'] = config_dir
        configs[label] = config

    return configs


def _setup_working_dir(working_dir: Path) -> None:
    """Create all the expected subdirectores for a working_dir."""

    for path in [
            working_dir,
            working_dir / 'builds',
            working_dir / 'series',
            working_dir / 'test_runs',
            working_dir / 'users']:

        try:
            path.mkdir(exist_ok=True)
        except OSError as err:
            raise RuntimeError("Could not create directory '{}': {}".format(path, err))


def _invalidator(msg):
    """Returns a function that provides an 'invalid option' validator. This will
    always give an error if the option isn't null."""

    def invalidator(_, value):
        """Raise a ValueError with the given message."""

        if value:
            raise ValueError("Invalid Option: {}".format(msg))

    return invalidator


class PavilionConfigLoader(yc.YamlConfigLoader):
    """This object uses YamlConfig to define Pavilion's base configuration
    format and options. If you're looking to add an option to the general
    pavilion.yaml format, this is the place to do it."""

    # Each and every configuration element needs to either not be required,
    # or have a sensible default. Essentially, Pavilion needs to work if no
    # config is given.
    ELEMENTS = [
        yc.ListElem(
            "config_dirs",
            sub_elem=ExPathElem(),
            post_validator=config_dirs_validator,
            help_text="Additional Paths to search for Pavilion config files. "
                      "Pavilion configs (other than this core config) are "
                      "searched for in the given order. In the case of "
                      "identically named files, directories listed earlier "
                      "take precedence."),
        yc.BoolElem(
            "user_config",
            default=False,
            help_text="Whether to automatically add the user's config "
                      "directory at ~/.pavilion to the config_dirs. Configs "
                      "in this directory always take precedence."
        ),
        ExPathElem(
            "working_dir",
            default='working_dir',
            help_text="Set the default working directory. Each config dir can set its"
                      "own working_dir."),
        ExPathElem(
            'spack_path', default=None, required=False,
            help_text="Where pavilion looks for a spack install."),
        yc.ListElem(
            "disable_plugins", sub_elem=yc.StrElem(),
            help_text="Allows you to disable plugins by '<type>.<name>'. For "
                      "example, 'module.gcc' would disable the gcc module "
                      "wrapper."),
        yc.StrElem(
            "shared_group", post_validator=_invalidator(
                "The option 'shared_group' is no longer used. Instead, use sticky group bits"
                "on your working directories to manage permissions."),
            help_text="No longer used."),
        yc.StrElem(
            "umask", default="2",
            help_text="The umask to apply to all files created by pavilion. "
                      "This should be in the format needed by the umask shell "
                      "command."),
        yc.IntRangeElem(
            "build_threads", default=4, vmin=1,
            help_text="Maximum simultaneous builds. Note that each build may "
                      "itself spawn off threads/processes, so it's probably "
                      "reasonable to keep this at just a few."),
        yc.StrElem(
            "log_format",
            default="{asctime}, {levelname}, {hostname}, {name}: {message}",
            help_text="The log format to use for the pavilion logger. "
                      "Uses the modern '{' format style. See: "
                      "https://docs.python.org/3/library/logging.html#"
                      "logrecord-attributes"),
        yc.StrElem(
            "log_level", default="info",
            choices=['debug', 'info', 'warning', 'error', 'critical'],
            help_text="The minimum log level for messages sent to the pavilion "
                      "logfile."),
        ExPathElem(
            "result_log",
            # Derive the default from the working directory, if a value isn't
            # given.
            post_validator=(lambda d, v: v if v is not None else d['working_dir']/'results.log'),
            help_text="Results are put in both the general log and a specific "
                      "results log. This defaults to 'results.log' in the default "
                      "working directory."),
        yc.BoolElem(
            "flatten_results", default=True,
            help_text="Flatten results with multiple 'per_file' values into "
                      "multiple result log lines, one for each 'per_file' "
                      "value. Each flattened result will have a 'file' key, "
                      "and the contents of its 'per_file' data will be added "
                      "to the base results mapping."),
        ExPathElem(
            'exception_log',
            post_validator=(lambda d, v: v if v is not None else
                            d['working_dir']/'exceptions.log'),
            help_text="Full exception tracebacks and related debugging "
                      "information is logged here."
        ),
        yc.IntElem(
            "wget_timeout", default=5,
            help_text="How long to wait on web requests before timing out. On "
                      "networks without internet access, zero will allow you "
                      "to spot issues faster."
        ),
        yc.CategoryElem(
            "proxies", sub_elem=yc.StrElem(),
            help_text="Proxies, by protocol, to use when accessing the "
                      "internet. Eg: http: 'http://myproxy.myorg.org:8000'"),
        yc.ListElem(
            "no_proxy", sub_elem=yc.StrElem(),
            help_text="A list of DNS suffixes to ignore for proxy purposes. "
                      "For example: 'blah.com' would match 'www.blah.com', but "
                      "not 'myblah.com'."),
        yc.ListElem(
            "env_setup", sub_elem=yc.StrElem(),
            help_text="A list of commands to be executed at the beginning of "
                      "every kickoff script."),
        yc.CategoryElem(
            "default_results", sub_elem=yc.StrElem(),
            help_text="Each of these will be added as a constant result "
                      "parser with the corresponding key and constant value. "
                      "Generally, the values should contain a pavilion "
                      "variable of some sort to resolve."),

        # The following configuration items are for internal use and provide a
        # convenient way to pass around core pavilion components or data.
        # They are not intended to be set by the user, and will generally be
        # overwritten without even checking for user provided values.
        ExPathElem(
            'pav_cfg_file', hidden=True,
            help_text="The location of the loaded pav config file."
        ),
        ExPathElem(
            'pav_root', default=PAV_ROOT, hidden=True,
            help_text="The root directory of the pavilion install. This "
                      "shouldn't be set by the user."),
        yc.KeyedElem(
            'pav_vars', elements=[], hidden=True, default={},
            help_text="This will contain the pavilion variable dictionary."),
        yc.KeyedElem(
            'configs', elements=[], hidden=True, default={},
            post_validator=_configs_validator,
            help_text="The configuration dictionaries for each config dir.")
    ]


class ConfigLoader(yc.YamlConfigLoader):
    """Loads the configuration for an individual Pavilion config directory."""

    ELEMENTS = [
        yc.RegexElem(
            'label', regex=r'[a-z]+', required=False,
            help_text="The label to apply to tests run from this configuration directory. "
                      "This should be specified for each config directory. A label will "
                      "be generated if absent."),
        ExPathElem(
            'working_dir', required=False,
            help_text="Where pavilion puts it's run files, downloads, etc. This defaults "
                      "to '<config_dir>/working_dir'."),
    ]


def find_pavilion_config(target=None, warn=True):
    """Search for a pavilion.yaml configuration file. Use the one pointed
to by the PAV_CONFIG_FILE environment variable. Otherwise, use the first
found in these directories the default config search paths:

- The given 'target' file (used only for testing).
- The ~/.pavilion directory
- The Pavilion source directory (don't put your config here).
"""

    for path in target, PAV_CONFIG_FILE:
        if path is not None:
            pav_cfg_file = Path(path)
            # pylint has a bug that pops up occasionally with pathlib.
            if pav_cfg_file.is_file():  # pylint: disable=no-member
                try:
                    cfg = PavilionConfigLoader().load(
                        pav_cfg_file.open())  # pylint: disable=no-member
                    cfg.pav_cfg_file = pav_cfg_file
                    return cfg
                except Exception as err:
                    raise RuntimeError("Error in Pavilion config at {}: {}"
                                       .format(pav_cfg_file, err))

    pav_cfg = None
    for config_dir in PAV_CONFIG_SEARCH_DIRS:
        path = config_dir/PAV_CONFIG_NAME
        if path.is_file():  # pylint: disable=no-member
            try:
                # Parse and load the configuration.
                cfg = PavilionConfigLoader().load(
                    path.open())  # pylint: disable=no-member
                cfg.pav_cfg_file = path
                pav_cfg = cfg
                break
            except Exception as err:
                raise RuntimeError("Error in Pavilion config at {}: {}"
                                   .format(path, err))

    if pav_cfg is None:
        if warn:
            LOGGER.warning("Could not find a pavilion config file. Using an "
                           "empty/default config.")
        pav_cfg = PavilionConfigLoader().load_empty()

    return pav_cfg


def make_config(options: dict):
    """Create a pavilion config given the raw config options."""

    loader = PavilionConfigLoader()

    values = loader.normalize(options)
    return loader.validate(values)


def get_version():
    """Returns the current version of Pavilion."""
    version_path = PAV_ROOT / 'RELEASE.txt'

    try:
        with version_path.open() as file:
            lines = file.readlines()
            for line in lines:
                if line.startswith('RELEASE='):
                    return line.split('=')[1].strip()

            return '<unknown>'

    except FileNotFoundError:
        return '<unknown>'
