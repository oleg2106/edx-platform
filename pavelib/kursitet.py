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
from pavelib.i18n import i18n_extract, i18n_dummy

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
        git.clone(TRANSLATION_OVERRIDES_REPO, TRANSLATION_OVERRIDES_PATH)


@task
@needs(
    "pavelib.kursitet.i18n_clone_overrides", )
def i18n_pull_overrides():
    """
    Update translation overrides.
    """
    git.pull(TRANSLATION_OVERRIDES_PATH)


@task
@needs(
    "pavelib.kursitet.i18n_pull_overrides", )
def i18n_install_overrides():
    """
    Actually override files pulled from Transifex with our own.
    """
    platform = TRANSLATION_OVERRIDES_PATH + '/edx-platform'
    source = path(platform)
    for override in source.walkfiles('*.po'):
        destination = override[len(platform) + 1:]
        # For the moment, just assume that the destination file exists...
        sh('msgcat --use-first -o {destination}.over {override} {destination}'.
           format(destination=destination, override=override))
        sh('rm {0}'.format(destination))
        sh('mv {0}.over {0}'.format(destination))


@task
def i18n_ensure_unreviewed_translations():
    # Ensure that we're always pulling unfiltered translations.
    sh("sed -i -e 's/tx pull --mode=reviewed -l/tx pull -l/g' "
       "/edx/app/edxapp/venvs/edxapp/lib/python2.7/site-packages/i18n/transifex.py"
       )


@task
def i18n_update_with_override():
    """
    Does the full transifex-update cycle with overriding specific strings with our own translations.
    """
    sh('tx pull -l ru')
    i18n_extract()
    i18n_dummy()
    i18n_install_overrides()
    sh('i18n_tool generate')
    sh("i18n_tool validate")
    sh('git clean -fdX conf/locale')
    # The results are NOT meant to be committed anywhere.
