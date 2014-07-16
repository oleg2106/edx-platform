'''
This command is made for fixing a specific course problem, where a
set of combinedopenended problems with grades spanning 0-5 was
instead treated as undifferentiated (i.e. pass-fail) by a subset of
graders. Since it is imractical to find out which grades are wrong now,
it was decided to normalize all grades to 0 and 5 for the particular
problems where this happened.
'''

import json
import logging
from optparse import make_option

from django.core.management.base import BaseCommand, CommandError

from courseware.models import StudentModule

LOG = logging.getLogger(__name__)

NUD_CUTOFF = 2.5
NUD_MIN = 0
NUD_MAX = 5

class Command(BaseCommand):
    '''
    The obvious least-invasive solution is to normalize the grades based
    on some cutoff value, where anything higher than this cutoff value
    becomes maximum, while anything lower becomes minimum. Least
    invasive is relative, because it's easier to reach into a json data
    dump than to try instantiating a module object.'''

    num_visited = 0
    num_changed = 0

    option_list = BaseCommand.option_list + (
        make_option('--save',
                    action='store_true',
                    dest='save_changes',
                    default=False,
                    help='Persist the changes.  If not set, no changes are saved.'), ) + (
        make_option('--debug',
                    action='store_true',
                    dest='debug',
                    default=False,
                    help='Dump module state before and after changes for debugging purposes.'), )
    args = '<module id>'
    help = 'Normalize grades for a certain combinedopenended module as if they were undifferentiated.'

    def fix_studentmodules(self, module, save_changes, debug):
        '''Identify the list of StudentModule objects of combinedopenended type that belong to the specified module_id and fix each one'''
        modules = StudentModule.objects.filter(module_state_key=module,
                                               module_type='combinedopenended'
        )

        for module in modules:
            self.fix_studentmodule_score(module, save_changes, debug)

    def fix_studentmodule_score(self, module, save_changes, debug):
        ''' Fix the grade assigned to a StudentModule in a combinedopenended state'''

        def normalize(value):
            ''' Actually normalize a value.'''
            if value > NUD_CUTOFF:
                return NUD_MAX
            else:
                return NUD_MIN

        module_state = module.state
        if module_state is None:
            LOG.info("No state found for {type} module {id} for student {student} in course {course_id}"
                     .format(type=module.module_type, id=module.module_state_key,
                     student=module.student.username, course_id=module.course_id))
            return

        state_dict = json.loads(module_state)
        self.num_visited += 1

        # Modules with no answers in them should stay untouched...
        if not 'state' in state_dict:
            LOG.error("Module {id} for {student} in course {course_id} has no state!"
                      .format(id=module.module_state_key,
                      student=module.student.username,
                      course_id=module.course_id))
            return

        stateflag = state_dict['state']

        # In our case, some modules have state 'initial' but actually contain scores anyway.
        # In these cases we alter the scores as well, just in case.

        if not stateflag in ["initial", "done"]:
            LOG.info("module {id} for {student} is neither 'done' nor 'initial', it is '{stateflag}'"
                .format(id=module.module_state_key,
                student=module.student.username, stateflag=stateflag))
            return
        else:
            LOG.info("module {id} for {student} is '{stateflag}', investigating."
                .format(id=module.module_state_key,
                student=module.student.username, stateflag=stateflag))

        # The correct way to do it would be to create the xmodule object
        # from that state, change it, and then save it back.
        # That's going to take way too long to figure out, we
        # need a fix fast.

        if not ('current_task_number' in state_dict and 'task_states' in state_dict):
            LOG.error("Somehow, module {id} for student {student} in course {course_id} has unexpected task states."
                      .format(course_id=module.course.id, student=module.student.username, id=module.module_state_key))
            return

        # So we have some task states, and one of them is current.
        # I don't really understand the structure here yet,
        # but in our case it's also always the only task.

        task = json.loads(state_dict['task_states'][state_dict['current_task_number']])

        change_needed = False
        # I have no clue which the 'current' child is in child history,
        # and this is complicated by the modules in state 'initial'
        # which contain readable scores, so it's easier to alter all
        # the children.
        for index, childhistory in enumerate(task['child_history']):
            postassessment = json.loads(childhistory['post_assessment'])

            if postassessment['score'] != childhistory['score']:
                LOG.error("Scores don't match, some assumptions about module_state storage are wrong...")
                raise ValueError("Programmer misunderstood the nature of XModule.")

            changed_postassessment_score = normalize(postassessment['score'])
            changed_main_score = normalize(childhistory['score'])

            if (changed_postassessment_score != postassessment['score']) or (changed_main_score != childhistory['score']):

                change_needed = True
                LOG.info("module {id} for {student} has scores that need changing: postassessment {psasc} => {psascn}, score {score} => {scoren}."
                         .format(psasc=postassessment['score'],
                         score=childhistory['score'],
                         psascn=changed_postassessment_score,
                         scoren=changed_main_score,
                         student=module.student.username,
                         id=module.module_state_key))

                postassessment['score'] = changed_postassessment_score
                childhistory['post_assessment'] = json.dumps(postassessment)
                childhistory['score'] = changed_main_score
                task['child_history'][index] = childhistory

        state_dict['task_states'][state_dict['current_task_number']] = json.dumps(task)

        result = json.dumps(state_dict)

        if not change_needed:
            LOG.info("module {id} for {student} needs no changes."
                .format(id=module.module_state_key,
                student=module.student.username, stateflag=stateflag))
            return
        else:
            if debug:
                LOG.info("Dumping state before:\n{state}".format(state=module_state))
                LOG.info("Dumping state after:\n{state}".format(state=result))

        if save_changes:
            LOG.info("module {id} for {student} - saving new state."
                     .format(student=module.student.username,
                             id=module.module_state_key))
            self.num_changed += 1
            module.state = result
            module.save()

    def handle(self, *args, **options):
        '''Handle management command request'''

        if len(args) != 1:
            raise CommandError('Usage is normalize_undifferentiated {0}'.format(self.args))

        module_id = args[0]

        save_changes = options['save_changes']
        debug = options['debug']

        LOG.info("Starting run: save_changes = {0}, debug = {1}".format(save_changes, debug))

        self.fix_studentmodules(module_id, save_changes, debug)

        LOG.info("Finished run: updating {0} of {1} modules".format(self.num_changed, self.num_visited))
