# coding: utf-8
'''
When settling a specific complaint, we needed to get ahold of every combinedopenended submission a particular student made.
This script should do it.

'''

import json
import logging
from optparse import make_option

import codecs
# It would be smarter to avoid the temporary file and pipe it straight in.
# Maybe later.
import subprocess, os

from django.core.management.base import BaseCommand, CommandError
from django.core.management import call_command
from django.contrib.auth.models import User

# This is slightly clever. We're going to capture the output
# of an existing command and parse it.
from StringIO import StringIO

from courseware.models import StudentModule
from student.models import UserProfile

LOG = logging.getLogger(__name__)

class Command(BaseCommand):
    '''Base command class.'''

    args = '<course id> <student_username>'
    
    help = 'Dump combinedopenended answers for a problem to human-readable files'

    def dump_studentmodules(self, module, display_header, display_prompt, userid):
        '''Identify the list of StudentModule objects of combinedopenended type that belong to the specified module_id'''
        modules = StudentModule.objects.filter(module_state_key=module,
                                               module_type='combinedopenended')

        filename = module.replace(':','-').replace('/','-').replace(':','-')
        LOG.info("Starting dump, saving to file {0}".format(filename))

        with codecs.open(filename, 'w', 'utf-8') as handle:
            handle.write(u'<h1>Задание "{0}"</h1>\n\n'.format(display_header))
            handle.write(u'<p>{0}</p>\n\n'.format(display_prompt))
            for module in modules:
                self.dump_studentmodule_answer(module, handle, userid)
        LOG.info("Piping output through external utilities.")
        self.pipe_through_pandoc(filename)
        os.remove(filename)

        return filename + ".html"

    def pipe_through_pandoc(self, filename):
        '''Process pseudo-html output through pandoc to produce normalized html.
           If we had pandoc 1.12 available, it could be straight docx,
           but no such luck. So instead we depend on html tidy'''
        try:
            os.remove(filename+'.html')
        except OSError:
            pass
            
        options = ['pandoc', filename, '-f', 'html', '-s', '-t', 'html', '-o', filename + '.html']
        return subprocess.check_call(options)
        
        # os.rename(filename, filename + '.html')
        # options = ['tidy', '-utf8', '-qcm', filename + '.html']
        # subprocess.call(options)
        # return

    def dump_studentmodule_answer(self, module, filehandle, userid):
        '''Dump the actual module data.'''
        
        
        # This is wrong.
        if module.student.username != userid.username:
            return
            
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
        # In these cases we alter the scores as well, just in case.

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

                student = UserProfile.objects.get(user=module.student)
               
                filehandle.write(u"\n\n<h2>Студент {0} ({1})</h2>\n\n".format(student.name, module.student.email))
                filehandle.write(u"\n\n<h3>Дата создания блока: {0}</h3>\n\n".format(module.created))
                filehandle.write(u"\n\n<h3>Дата последнего изменения блока: {0}</h3>\n\n".format(module.modified))

                filehandle.write(childhistory['answer'].replace("\r","<br>\r").replace("\n","<br>\n"))

                filehandle.write(u"\n\n<h4>Оценка: {0}</h4>\n\n".format(postassessment['score']))

                try:
                    feedback = json.loads(postassessment['feedback'])['feedback']
                    if len(feedback) > 0:
                        filehandle.write(u"\n\n<h3>Комментарий преподавателя</h3>\n\n")
                        filehandle.write(feedback)
                except:
                    LOG.error("Something is odd about the feedback field...")
            else:
                LOG.error("Somehow the child history does not include assessment. Skipping.")


    def handle(self, *args, **options):
        '''Handle management command request'''

        if len(args) != 2:
            raise CommandError('Usage is dump_combinedopenended {0}'.format(self.args))
            
        course_id = args[0]
        
        try:
            userid = User.objects.get(username=args[1])
        except User.DoesNotExist:
            try:
                userid = User.objects.get(email=args[1])
            except: 
                raise CommandError('Could not find user {0}'.format(args[1]))
                
        LOG.info("Gathering information about course {0} related to user {1}".format(course_id,userid.username))

        # There's already a dump_course_structure command which returns
        # all the metadata we wanted.
        content = StringIO()
        coursedata = call_command('dump_course_structure', course_id, interactive = False, stdout=content)
        content.seek(0)
        coursedata = json.loads(content.read())

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
                    except AttributeError:
                        display_prompt = u"Поврежденный блок?"

                    resulting_files.append(self.dump_studentmodules(block_id, display_header, display_prompt, userid))

        if len(resulting_files) > 0:
            LOG.info("Packing resulting course dumps.")
            zipfilename = course_id.replace('/','_')+'.zip'
            options = ['zip', '-m', zipfilename]
            options += resulting_files
            packoutput = subprocess.check_call(options)

            if packoutput == 0:
                LOG.info("Done, output file {0}".format(zipfilename))
            else:
                LOG.error("Packaging failed with error code {0}.".format(packoutput))

