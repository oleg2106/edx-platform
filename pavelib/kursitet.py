"""
Kursitet-specific paver tasks
"""

import sys
import subprocess
import os
import fnmatch

from path import path
from paver.easy import *
from paver import git

TRANSLATION_OVERRIDES_PATH = '/edx/app/edxapp/translation-overrides'
TRANSLATION_OVERRIDES_REPO = 'https://github.com/kursitet/translation-overrides'

try:
    from pygments.console import colorize
except ImportError:
    colorize = lambda color, text: text  # pylint: disable-msg=invalid-name

@task
def i18n_clone_overrides():
    """
    Initialise translation overrrides.
    """
    # I'm not sure that's the right way to do this, but whatever.
    if not os.path.isdir(TRANSLATION_OVERRIDES_PATH):
        git.clone(TRANSLATION_OVERRIDES_REPO,TRANSLATION_OVERRIDES_PATH)
    # Ensure that we're always pulling unfiltered translations.
    sh("sed -i -e 's/tx pull --mode=reviewed --all/tx pull --all/g' /edx/app/edxapp/venvs/edxapp/src/i18n-tools/i18n/transifex.py")

@task
@needs(
    "pavelib.kursitet.i18n_clone_overrides",
)
def i18n_pull_overrides():
    """
    Update translation overrides.
    """
    git.pull(TRANSLATION_OVERRIDES_PATH)

@task
@needs(
    "pavelib.i18n.i18n_transifex_pull",
    "pavelib.kursitet.i18n_pull_overrides",
)
def i18n_install_overrides():
    """
    Actually override files pulled from Transifex with our own.
    """
    platform = TRANSLATION_OVERRIDES_PATH+'/edx-platform'
    source = path(platform)
    for override in source.walkfiles('*.po'):
        destination = override[len(platform)+1:]
        # For the moment, just assume that the destination file exists...
        sh('msgcat --use-first -o {destination}.over {override} {destination}'.format(destination=destination, override=override))
        sh('rm {0}'.format(destination))
        sh('mv {0}.over {0}'.format(destination))

@task
@needs(
    "pavelib.kursitet.i18n_install_overrides",
    "pavelib.i18n.i18n_extract",
    "pavelib.i18n.i18n_dummy",
    "pavelib.i18n.i18n_generate_strict",
)
def i18n_update_with_override():
    """
    Does the full transifex-update cycle with overriding specific strings with our own translations.
    """
    sh('git clean -fdX conf/locale')
    # Validate the recently pulled translations just like the vanilla update does.
    cmd = "i18n_tool validate"
    sh("{cmd}".format(cmd=cmd))
    # The results are NOT meant to be committed anywhere.
