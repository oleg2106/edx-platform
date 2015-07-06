# coding: utf-8
'''
So professors requested a hard copy of all the student answers to questions,
deanonymized. Which is easiest to achieve by parsing module states, actually.

'''

import io
import json
import codecs
import logging
from zipfile import ZipFile
from optparse import make_option

from bs4 import BeautifulSoup

from django.core.management.base import BaseCommand, CommandError
from django.core.management import call_command
from django.utils.html import clean_html, linebreaks

from courseware.models import StudentModule
from xmodule.modulestore.django import modulestore
from opaque_keys.edx.keys import CourseKey, UsageKey

# Using a pre-existing function still saves me some work.
from courseware.management.commands.dump_course_structure import dump_module

LOG = logging.getLogger(__name__)

class Command(BaseCommand):
    '''Base command class.'''

    option_list = BaseCommand.option_list + (
            make_option('--deanonymize',
                    action='store_true',
                    dest='deanonymize',
                    default=False,
                    help='Keep student real names and emails in the output.'), ) 
    args = '<course id>'
    
    help = 'Dump combinedopenended answers for a problem to human-readable files'

    def dump_studentmodules(self, module, display_header, display_prompt, deanonymize):
        '''Identify the list of StudentModule objects of combinedopenended type that belong to the specified module_id'''
        module = UsageKey.from_string(module)
        modules = StudentModule.objects.filter(
                      module_state_key=module,
                      module_type='combinedopenended'
                  )

        filename = "{0}.html".format(module).replace(':','-').replace('/','-')
        
        with io.StringIO() as handle:
            handle.write(u'<html><head></head><body>')
            handle.write(u'<h1>Задание "{0}"</h1>\n\n'.format(display_header))
            handle.write(u'<p>{0}</p>\n\n'.format(display_prompt))
            for module in modules:
                self.dump_studentmodule_answer(module, handle, deanonymize)
            handle.write(u'</body></html>')
            filedata = handle.getvalue()
        
        soup = BeautifulSoup(clean_html(filedata))
        metatag = soup.new_tag('meta')
        metatag.attrs['charset'] = 'UTF-8'
        soup.head.append(metatag)

        return (filename, u"<!DOCTYPE html>\n"+soup.prettify())
        
    def dump_studentmodule_answer(self, module, filehandle, deanonymize):
        '''Dump the actual module data.'''

        module_state = module.state
        if module_state is None:
            LOG.info("No state found for {type} module {id} for student {student} in course {course_id}"
                     .format(
                         type=module.module_type,
                         id=module.module_state_key,
                         student=module.student.username,
                         course_id=module.course_id
                     ))
            return

        state_dict = json.loads(module_state)

        # Modules with no answers in them should stay untouched...
        if not 'state' in state_dict:
            LOG.error("Module {id} for {student} in course {course_id} has no state!"
                      .format(
                          id=module.module_state_key,
                          student=module.student.username,
                          course_id=module.course_id
                      ))
            return

        stateflag = state_dict['state']

        # In our case, some modules have state 'initial' but actually contain scores anyway.

        if not stateflag in ["initial", "done", "assessing"]:
            LOG.info("module {id} for {student} is neither 'done' nor 'initial', it is '{stateflag}'"
                     .format(
                         id=module.module_state_key,
                         student=module.student.username,
                         stateflag=stateflag
                     ))
            return
        else:
            LOG.info("module {id} for {student} is '{stateflag}', investigating."
                     .format(
                         id=module.module_state_key,
                         student=module.student.username,
                         stateflag=stateflag
                     ))

        if not ('current_task_number' in state_dict and 'task_states' in state_dict):
            LOG.error("Somehow, module {id} for student {student} in course {course_id} has unexpected task states."
                      .format(
                          course_id=module.course.id,
                          student=module.student.username,
                          id=module.module_state_key
                      ))
            return

        task = json.loads(state_dict['task_states'][state_dict['current_task_number']])

        for childhistory in task['child_history']:
            if 'post_assessment' in childhistory:
                postassessment = json.loads(childhistory['post_assessment'])

                if postassessment['score'] != childhistory['score']:
                    LOG.error("Scores don't match, some assumptions about module_state storage are wrong...")
                    raise ValueError("Programmer misunderstood the nature of XModule.")

                if deanonymize:
                    filehandle.write(u"\n\n<h2>Студент {0} ({1})</h2>\n\n".format(
                        student.profile.name, module.student.profile.email
                    ))
                else:
                    filehandle.write(u"\n\n<h2>Студент #{0}</h2>\n\n".format(module.student.pk))
                    
                filehandle.write(linebreaks(childhistory['answer']))

                filehandle.write(u"\n\n<h4>Оценка: {0}</h4>\n\n".format(postassessment['score']))

                try:
                    feedback = json.loads(postassessment['feedback'])['feedback']
                    if len(feedback) > 0:
                        filehandle.write(u"\n\n<h3>Комментарий преподавателя</h3>\n\n")
                        filehandle.write(linebreaks(feedback))
                except:
                    LOG.error("Something is odd about the feedback field...")
            else:
                LOG.error("Somehow the child history does not include assessment. Skipping.")


    def handle(self, *args, **options):
        '''Handle management command request'''

        if len(args) != 1:
            raise CommandError('Usage is dump_combinedopenended {0}'.format(self.args))
            
        deanonymize = options['deanonymize']

        course_id = CourseKey.from_string(args[0])
        
        course = modulestore().get_course(course_id)
        
        if not course:
            raise CommandError('Course {0} not found'.format(course_id))

        LOG.info("Gathering information about course {0}".format(course_id))
        
        coursedata = dump_module(course)
        
        resulting_files = []

        for block_id in coursedata:
            if 'category' in coursedata[block_id]:
                if coursedata[block_id]['category'] == 'combinedopenended':

                    try:
                        display_header = coursedata[block_id]['metadata']['display_name']
                    except KeyError:
                        display_header = u"без названия"

                    try:
                        display_prompt = coursedata[block_id]['metadata']['markdown'].split('[prompt]')[1]
                    except KeyError:
                        display_prompt = u"без пояснений"

                    resulting_files.append(self.dump_studentmodules(block_id, display_header, display_prompt, deanonymize))

        if len(resulting_files) > 0:
            zipfilename = "{0}.zip".format(course_id).replace('/','_')
            with ZipFile(zipfilename, 'w') as work_zip_file:
                for filename, blob in resulting_files:
                    work_zip_file.writestr(filename,codecs.encode(blob,'utf-8'))
            LOG.info("Done, output file {0}".format(zipfilename))
        else:
            LOG.info("Done, nothing to save.".format(zipfilename))


