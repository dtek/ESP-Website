
__author__    = "MIT ESP"
__date__      = "$DATE$"
__rev__       = "$REV$"
__license__   = "GPL v.2"
__copyright__ = """
This file is part of the ESP Web Site
Copyright (c) 2007 MIT ESP

The ESP Web Site is free software; you can redistribute it and/or
modify it under the terms of the GNU General Public License
as published by the Free Software Foundation; either version 2
of the License, or (at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program; if not, write to the Free Software
Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.

Contact Us:
ESP Web Group
MIT Educational Studies Program,
84 Massachusetts Ave W20-467, Cambridge, MA 02139
Phone: 617-253-4882
Email: web@esp.mit.edu
"""
from esp.program.modules.base    import ProgramModuleObj, main_call, aux_call
from esp.middleware              import ESPError
from esp.program.models          import ClassSubject, ClassSection
from datetime                    import timedelta
from esp.users.models            import ESPUser
from esp.web.util        import render_to_response

class TeacherPreviewModule(ProgramModuleObj):
    """ This program module allows teachers to view classes already added to the program.
        And, for now, also some printables. """

    @classmethod
    def module_properties(cls):
        return {
            "link_title": "Preview Other Classes",
            "module_type": "teach",
            "seq": -10,
            "main_call": "preview"
            }

    def teacherhandout(self, request, tl, one, two, module, extra, prog, template_file='teacherschedules.html'):
        #   Use the template defined in ProgramPrintables
        from esp.program.modules.handlers import ProgramPrintables
        context = {'module': self}
        pmos = ProgramModuleObj.objects.filter(program=prog,module__handler__icontains='printables')
        if pmos.count() == 1:
            pmo = ProgramPrintables(pmos[0])
            teacher = ESPUser(request.user)
            scheditems = []
            for cls in teacher.getTaughtClasses().filter(parent_program = self.program):
                if cls.isAccepted():
                    for section in cls.sections.all():
                        scheditems.append({'name': teacher.name(), 'teacher': teacher, 'cls': section})
            scheditems.sort()
            context['scheditems'] = scheditems
            return render_to_response(pmo.baseDir()+template_file, request, (prog, tl), context)
        else:
            raise ESPError(False), 'No printables module resolved, so this document cannot be generated.  Consult the webmasters.' 

    @aux_call
    def teacherschedule(self, request, tl, one, two, module, extra, prog):
        return self.teacherhandout(request, tl, one, two, module, extra, prog, template_file='teacherschedule.html')

    @aux_call
    def classroster(self, request, tl, one, two, module, extra, prog):
        return self.teacherhandout(request, tl, one, two, module, extra, prog, template_file='classrosters.html')

    def get_handouts(self):
        return {'teacherschedule': 'Your Class Schedule', 'classroster': 'Class Rosters'}

    def prepare(self, context={}):
        if context is None: context = {}

        classes = ClassSubject.objects.catalog(self.program, None, True)
        
        #   First, the already-registered classes.
        categories = {}
        for cls in classes:
            if cls.category_id not in categories:
                categories[cls.category_id] = {'id': cls.category_id, 'category': cls.category_txt, 'classes': [cls]}
            else:
                categories[cls.category_id]['classes'].append(cls)
        
        context['categories'] = [categories[cat_id] for cat_id in categories]
        context['prog'] = self.program
        
        #   Then, the printables.
        
        handout_dict = self.get_handouts()
        context['handouts'] = [{'url': key, 'title': handout_dict[key]} for key in handout_dict]
        
        return context
