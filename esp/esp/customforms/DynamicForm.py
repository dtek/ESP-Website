from esp.customforms.models import Field, Attribute, Section, Page, Form
from django import forms
from django.forms.models import fields_for_model
from form_utils.forms import BetterForm
from django.utils.datastructures import SortedDict
from django.contrib.formtools.wizard import FormWizard
from django.shortcuts import redirect, render_to_response, HttpResponse
from django.http import HttpResponseRedirect
from django.contrib.localflavor.us.forms import USStateField, USPhoneNumberField, USStateSelect
from esp.customforms.forms import NameField, AddressField
from esp.customforms.DynamicModel import DMH
from esp.users.models import ContactInfo
from esp.cache import cache_function
from esp.program.models import Program

from esp.customforms.linkfields import link_fields, only_fkey_models, cf_cache
from django.contrib.contenttypes.models import ContentType

class BaseCustomForm(BetterForm):
	"""
	This is the base class for all custom forms.
	"""
	def clean(self):
		"""
		This takes cleaned_data and expands the values for combo fields
		"""
		cleaned_data=self.cleaned_data.copy()
		for k,v in self.cleaned_data.items():
			if isinstance(v, list):
				cleaned_data[k]=";".join(v)
			if isinstance(v, dict):
				cleaned_data.update(v)
				del cleaned_data[k]
		return cleaned_data		
		

class CustomFormHandler():
	"""Handles creation of 'one' Django form (=one page)"""
	
	_field_types={
		'textField':{'typeMap': forms.CharField, 'attrs':{'widget':forms.TextInput,}, 'widget_attrs':{'size':'30', 'class':''}},
		'longTextField':{'typeMap': forms.CharField, 'attrs':{'widget':forms.TextInput,}, 'widget_attrs':{'size':'60', 'class':''}},
		'longAns':{'typeMap': forms.CharField, 'attrs':{'widget':forms.Textarea,}, 'widget_attrs':{'rows':'8', 'cols':'50', 'class':''}},
		'reallyLongAns':{'typeMap': forms.CharField, 'attrs':{'widget':forms.Textarea,}, 'widget_attrs':{'rows':'14', 'cols':'70', 'class':''}},
		'radio':{'typeMap': forms.ChoiceField, 'attrs':{'widget': forms.RadioSelect, }, 'widget_attrs':{'class':''}},
		'dropdown':{'typeMap': forms.ChoiceField, 'attrs':{'widget': forms.Select, }, 'widget_attrs':{'class':''}},
		'multiselect':{'typeMap': forms.MultipleChoiceField, 'attrs':{'widget': forms.SelectMultiple, }, 'widget_attrs':{'class':''}},
		'checkboxes':{'typeMap': forms.MultipleChoiceField, 'attrs':{'widget': forms.CheckboxSelectMultiple, }, 'widget_attrs':{'class':''}},
		'numeric':{'typeMap': forms.IntegerField, 'attrs':{'widget':forms.TextInput,}, 'widget_attrs':{'class':'digits'},},
		'date':{'typeMap': forms.DateField,'attrs':{'widget':forms.DateInput,}, 'widget_attrs':{'class':'ddate', 'format':'%m-%d-%Y'},},
		'time':{'typeMap': forms.TimeField, 'attrs':{'widget':forms.TimeInput,}, 'widget_attrs':{'class':'time'},},
		#'name':{'typeMap':NameField, 'attrs':{}, 'widget_attrs':{'class':''}},
		#'gender':{'typeMap': forms.ChoiceField, 'attrs':{'widget':forms.RadioSelect, 'choices':[('M','Male'), ('F', 'Female')]}, 'widget_attrs':{'class':''}},
		#'phone':{'typeMap': USPhoneNumberField, 'attrs':{'widget':forms.TextInput,}, 'widget_attrs':{'class':'USPhone'}},
		#'email':{'typeMap': forms.EmailField, 'attrs':{'max_length':30, 'widget':forms.TextInput,}, 'widget_attrs':{'class':'email'}},
		#'address':{'typeMap':AddressField, 'attrs':{}, 'widget_attrs':{'class':''}},
		#'street':{'typeMap': forms.CharField, 'attrs':{'max_length':100, 'widget':forms.TextInput,}, 'widget_attrs':{'class':''}},
		#'state':{'typeMap': USStateField, 'attrs':{'widget': USStateSelect}, 'widget_attrs':{'class':''}},
		#'city':{'typeMap': forms.CharField, 'attrs':{'max_length':50, 'widget':forms.TextInput,}, 'widget_attrs':{'class':''},},
		#'zip':{'typeMap': forms.CharField, 'attrs':{'max_length':5, 'widget':forms.TextInput,}, 'widget_attrs':{'class':'USZip'}},
		#'courses':{'typeMap': forms.ModelChoiceField, 'attrs':{'widget':forms.Select, 'empty_label':None}, 'widget_attrs':{'class':'courses'}},
	}
	
	_field_attrs=['label', 'help_text', 'required']
	
	_contactinfo_map={
		'name':['first_name', 'last_name'],
		'email':'e_mail',
		'phone':'phone_day',
		'address':['address_street', 'address_city', 'address_state', 'address_zip'],
		'street':'address_street',
		'city':'address_city',
		'zip':'address_zip',
		'state':'address_state'
	}
	
	_combo_fields=['name', 'address']
	
	def __init__(self, page, form):
		self.page=page
		self.form=form
		self.seq=page[0][0]['section__page__seq']
		self.fields=[]
		self.fieldsets=[]
		
	def _getAttrs(self, attrs):
		"""Takes attrs from the metadata and returns its Django equivalent"""
		
		other_attrs={}
		for attr in attrs:
			if attr['attr_type']=='options':
				other_attrs['choices']=[]
				options_list=attr['value'].split('|')[:-1]
				for option in options_list:
					other_attrs['choices'].append( (option, option) )
			elif attr['attr_type']=='limits':
				limits=attr['value'].split(',')
				if limits[0]: other_attrs['min_value']=int(limits[0])
				if limits[1]: other_attrs['max_value']=int(limits[1])
			elif attr['attr_type']=='charlimits':
				limits=attr['value'].split(',')
				if limits[0]: other_attrs['min_length']=int(limits[0])
				if limits[1]: other_attrs['max_length']=int(limits[1])
			"""elif attr['attr_type']=='wordlimits':
				limits=attr['value'].split(',')
				if limits[0]: other_attrs['min_words']=int(limits[0])
				if limits[1]: other_attrs['max_words']=int(limits[1])
			"""					
		return other_attrs
	
	def _getFields(self):
		"""
		Sets self.fields and self.fieldsets for this page
		"""
		model_fields_cache={}
		for section in self.page:
			curr_fieldset=[]
			curr_fieldset.extend([section[0]['section__title'], {'fields':[], 'classes':['section',]}])
			curr_fieldset[1]['description']=section[0]['section__description']
			
			#Check for only_fkey models.
			#If any, insert the relevant field into the first section of the fist page
			if section[0]['section__seq']==0 and self.seq==0:
				if self.form.link_type!='-1':
					label='Please pick the %s you want to fill the form for' % self.form.link_type
					link_cls=cf_cache.only_fkey_models[self.form.link_type]
					if self.form.link_id==-1:
						#User needs to be shown a list of instances from which to select
						queryset=link_cls.objects.all()
						widget=forms.Select()
					else:
						queryset=link_cls.objects.filter(pk=self.form.link_id)
						widget=forms.HiddenInput()	
					fld=forms.ModelChoiceField(queryset=queryset, label=label, initial=queryset[0], widget=widget, required=True, empty_label=None)
					self.fields.append(['link_'+link_cls.__name__, fld ])
					curr_fieldset[1]['fields'].append('link_'+link_cls.__name__)		
			
			for field in section:
				field_name='question_%d' % field['id']
				field_attrs={'label':field['label'], 'help_text':field['help_text'], 'required':field['required']}
				
				#Setting the 'name' attribute for combo fields
				"""
				if field['field_type'] in self._combo_fields:
					field_attrs['name']=field_name
				"""	
				
				#TODO: Change for multiple attributes - could be possible
				other_attrs=[]
				if field['attribute__attr_type'] is not None:
					other_attrs.append({'attr_type':field['attribute__attr_type'], 'value':field['attribute__value']})
				
				if other_attrs:
					field_attrs.update(self._getAttrs(other_attrs))
					
				#First, check for link fields.
				if cf_cache.isLinkField(field['field_type']):
					#Get all form fields for this model, if it hasn't already been done
					link_model=cf_cache.modelForLinkField(field['field_type'])
					if link_model.__name__ not in model_fields_cache:
						model_fields_cache[link_model.__name__]={}
						model_fields_cache[link_model.__name__].update(fields_for_model(link_model, widgets=getattr(link_model, 'link_fields_widgets', None)))
					model_field=cf_cache.getLinkFieldData(field['field_type'])['model_field']
					form_field=model_fields_cache[link_model.__name__][model_field]
					#TODO -> enforce "Required" constraint server-side as well, or trust the client-side code?
					form_field.__dict__.update(field_attrs)
					if form_field.required:
						#Add a class 'required' to the widget
						form_field.widget.attrs.update({'class':'required'})
					#Adding to field list
					self.fields.append([field_name, form_field])
					curr_fieldset[1]['fields'].append(field_name)
					continue	
				
				#Generic field								
				widget_attrs={}	
				field_attrs.update(self._field_types[field['field_type']]['attrs'])
				widget_attrs.update(self._field_types[field['field_type']]['widget_attrs'])
				typeMap=self._field_types[field['field_type']]['typeMap']
				
				#Setting classes required for front-end validation
				if field['required']:
					widget_attrs['class']+=' required'
				if 'min_value' in field_attrs:
					widget_attrs['min']=field_attrs['min_value']
				if 'max_value' in field_attrs:
					widget_attrs['max']=field_attrs['max_value']
				if 'min_length' in field_attrs:
					widget_attrs['minlength']=field_attrs['min_length']
				if 'max_length' in field_attrs:
					widget_attrs['maxlength']=field_attrs['max_length']
				if 'min_words' in field_attrs:
					widget_attrs['minWords']=field_attrs['min_words']
				if 'max_words' in field_attrs:
					widget_attrs['maxWords']=field_attrs['max_words']					
			
				#For combo fields, classes need to be passed in to the field
				if field['field_type'] in self._combo_fields:
					field_attrs.update(widget_attrs)
					
				#Setting the queryset for a courses field
				if field['field_type']=='courses':
					if self.form.link_type=='program' or self.form.link_type=='Program':
						field_attrs['queryset']=Program.objects.get(pk=self.form.link_id).classsubject_set.all()
						
				#Initializing widget				
				try:
					field_attrs['widget']=field_attrs['widget'](attrs=widget_attrs)
				except KeyError:
					pass
					
				self.fields.append([field_name, typeMap(**field_attrs) ])
				curr_fieldset[1]['fields'].append(field_name)			
			self.fieldsets.append(tuple(curr_fieldset))
			
	def getInitialLinkDataFields(self):
		"""
		Returns a dict mapping fields to be pre-populated with the corresponding model and model-field
		"""
		initial={}
		for section in self.page:
			for field in section:
				ftype=field['field_type']
				if cf_cache.isLinkField(ftype):
					field_name='question_%d' % field['id']
					initial[field_name]={'model':cf_cache.modelForLinkField(ftype)}
					"""
					if 'combo' in link_fields[ftype]:
						initial[field_name]['field']=[]
						for f in link_fields[ftype]['combo']:
							initial[field_name]['field'].append(link_fields[f]['model_field'])
					else:
					"""	
					initial[field_name]['model_field']=cf_cache.getLinkFieldData(ftype)['model_field']	
		return initial						
	
	def getForm(self):
		"""Returns the BetterForm class for the current page"""
		_form_name="Page_%d_%d" % (self.form.id, self.seq)
		
		if not self.fields:
			self._getFields()
		class Meta:
			fieldsets=self.fieldsets
		attrs={'Meta':Meta}
		attrs.update(SortedDict(self.fields))
		
		page_form=type(_form_name, (BaseCustomForm,), attrs)
		return page_form		
		
class ComboForm(FormWizard):
	
	def __init__(self, form_list, form, form_handler,initial=None):
		self.form=form
		self.form_handler=form_handler
		super(ComboForm, self).__init__(form_list, initial)
	
	def get_template(self, step):
		return 'customforms/form.html'
	    
	def done(self, request, form_list):
		data={}
		dyn=DMH(form=self.form)
		dynModel=dyn.createDynModel()
		fields=dict(dyn.fields)
		link_models_cache={}
		
		#Plonking in user_id if the form is non-anonymous
		if not self.form.anonymous:
			data['user']=request.user
		
		#Populating data with the values that need to be inserted
		for form in form_list:
			for k,v in form.cleaned_data.items():
				#Check for only_fkey link models first
				if k.split('_')[0]=='link':
					data[k]=v
					continue
					
				field_id=int(k.split("_")[1])
				ftype=fields[field_id]
				
				#Now check for link fields
				if cf_cache.isLinkField(ftype):
					model=cf_cache.modelForLinkField(ftype)
					if model.__name__ not in link_models_cache:
						link_models_cache[model.__name__]={'model': model, 'data':{}}
						pre_instance=self.form_handler.getInstanceForLinkField(k, model)
						if pre_instance is not None:
							link_models_cache[model.__name__]['instance']=pre_instance
						else:	
							link_models_cache[model.__name__]['instance']=getattr(model, 'cf_link_instance')(request)
					model_field=cf_cache.getLinkFieldData(ftype)['model_field']
					#Not handling combo fields for now
					link_models_cache[model.__name__]['data'].update({model_field: v})	
				else:
					data[k]=v
		
		#Create/update instances corresponding to link fields
		#Also, populate 'data' with foreign-keys that need to be inserted into the response table
		for k,v in link_models_cache.items():
			if v['instance'] is not None:
				#TODO-> the following update won't work for fk fields.
				v['instance'].__dict__.update(v['data'])
				v['instance'].save()
				curr_instance=v['instance']
			else:
				try:
					new_instance=v['model'].objects.create(**v['data'])
				except:	
					#show some error message
					pass
			if v['instance'] is not None:
				data['link_%s' % v['model'].__name__]=v['instance']				
		
		#Saving response
		dynModel.objects.create(**data)	
		return HttpResponseRedirect('/customforms/success/')
		
	def prefix_for_step(self, step):
		"""The FormWizard implements a form prefix for each step. Setting the prefix to an empty string, 
		as the field name is already unique"""
		return ''			
		
class FormHandler:
	"""Handles creation of a form (single page or multi-page). Uses Django's FormWizard."""
	
	_customFields={
		'name':['first_name', 'last_name'],
		'address':['street', 'state', 'city', 'zip'],
	}
	
	def __init__(self, form, request, user=None):
		self.form=form
		self.request=request
		self.wizard=None
		self.user=user
		self.handlers=[]
		
	def __marinade__(self):
		"""
		Implemented for caching convenience
		"""
		return "fh"	
	
	@cache_function
	def _getFormMetadata(self, form):
		"""
		Returns the metadata for this form. Gets everything in one large query, and then organizes the information.
		Used for rendering.
		"""
		fields=Field.objects.filter(form=form).order_by('section__page__seq', 'section__seq', 'seq').values('id', 'field_type', 'label', 'help_text', 'required', 'seq',
				'section__title', 'section__description', 'section__seq', 'section__id',
				'section__page__id', 'section__page__seq',
				'attribute__attr_type', 'attribute__value')
		
		#Generating the 'master' struct for metadata
		#master_struct is a nested list of the form (pages(sections(fields)))
		master_struct=[]
		for field in fields:
			try:
				page=master_struct[field['section__page__seq']]
			except IndexError:
				page=[]
				master_struct.append(page)
			try:
				section=page[field['section__seq']]
			except IndexError:
				section=[]
				page.append(section)
			section.append(field)
		return master_struct
	_getFormMetadata.depend_on_row(lambda: Field, lambda field: {'form': field.form})
	_getFormMetadata.depend_on_row(lambda: Attribute, lambda attr: {'form': attr.field.form})
	_getFormMetadata.depend_on_row(lambda: Section, lambda section: {'form': section.page.form})
	_getFormMetadata.depend_on_row(lambda: Page, lambda page: {'form': page.form})	
		
	def _getHandlers(self):
		"""
		Returns a list of CustomFormHandler instances corresponding to each page
		"""
		master_struct=self._getFormMetadata(self.form)
		for page in master_struct:
			self.handlers.append(CustomFormHandler(page=page, form=self.form))
		return self.handlers
	
	def _getFormList(self):
		"""
		Returns the list of BetterForm sub-classes corresponding to each page
		"""
		form_list=[]
		if not self.handlers:
			self._getHandlers()
		for handler in self.handlers:
			form_list.append(handler.getForm())
		return form_list
		
	def getInstanceForLinkField(self, field_name, model):
		"""
		Checks the link_id attribute for this field, and returns the corresponding model
		instance if one has been specified by the form creator.
		Returns None otherwise.
		"""
		master_struct=self._getFormMetadata(self.form)
		field_id=int(field_name.split("_")[1])
		for page in master_struct:
			for section in page:
				for field in section:
					if field['id']==field_id:
						if field['attribute__value']=="-1":
							return None
						else:
							instance_id=int(field['attribute__value'])
							instance=model.objects.get(pk=instance_id)
							return instance
		
	def _getInitialData(self, form, user):
		"""
		Returns the initial data, if any, for this form according to the format that FormWizard expects.
		"""
		initial_data={}
		link_models_cache={} #Stores data from a particular model
		"""
		if form.anonymous or user is None:
			return {}
		"""	
		if not self.handlers:
			self._getHandlers()
		for handler in self.handlers:
			initial=handler.getInitialLinkDataFields()
			if initial:
				initial_data[handler.seq]={}
				for k,v in initial.items():
					if v['model'].__name__ not in link_models_cache:
						#Get the corresponding instance, and get its values
						#First, check for pre-specified instances
						pre_instance=self.getInstanceForLinkField(k, v['model'])
						if pre_instance is not None:
							link_models_cache[v['model'].__name__]=pre_instance
						else:
							#Get the instance from the model method that should have been defined	
							link_models_cache[v['model'].__name__]=getattr(v['model'], 'cf_link_instance')(self.request)
						if link_models_cache[v['model'].__name__] is not None:
							link_models_cache[v['model'].__name__]=link_models_cache[v['model'].__name__].__dict__
					if link_models_cache[v['model'].__name__] is not None:		
						if not isinstance(v['model_field'], list):
							#Simple field
							initial_data[handler.seq].update({ k:link_models_cache[v['model'].__name__][v['model_field']] })
						"""	
						else:
							#Compound field. Needs to be passed a list of values.
							initial_data[handler.seq].update({k:[link_models[v['model']][val] for val in v['model_field'] ]})
						"""				
									
		return initial_data				
	
	def getWizard(self):
		"""Returns the ComboForm instance for this form"""
		self.wizard=ComboForm(self._getFormList(), self.form, self, self._getInitialData(self.form, self.user))	
		return self.wizard
		
	def deleteForm(self):
		"""Deletes all information relating to the form from the db.
			Also removes the response table
		"""
		dyn=DMH(form=self.form)
		dyn.deleteTable()
		self.form.delete() #Cascading Foreign Keys should take care of everything
		
	#IMPORTANT -> *NEED* TO REGISTER A CACHE DEPENDENCY ON THE RESPONSE MODEL
	#@cache_function
	def getResponseData(self, form):
		"""
		Returns the response data for this form, along with the questions
		"""
		dmh=DMH(form=form)
		dyn=dmh.createDynModel()
		response_data={'questions':[], 'answers':[]}
		responses=dyn.objects.all().order_by('id').values()
		fields=Field.objects.filter(form=form).order_by('section__page__seq', 'section__seq', 'seq').values('id', 'field_type', 'label')
		
		#Let's first do a bit of introspection to figure out
		#what the linked models are, and what values need to be added to the
		#response data from these linked models.
		#And since we're already iterating over fields,
		#let's also set the questions in the process.
		link_models={}
		add_fields={}
		
		for field in fields:
			#I'll do a lot of merging here later
			qname='question_%d' % field['id']
			ftype=field['field_type']
			if ftype in self._customFields:
				for f in self._customFields[field['field_type']]:
					response_data['questions'].append([qname+'_'+f, field['label'] + '_'+f])
			else:
				response_data['questions'].append([qname, field['label']])
			
			if ftype in link_fields:
				#Let's grab the model first
				if link_fields[ftype]['model']	not in link_models:
					app, model_name=link_fields[ftype]['model'].split('.')
					link_models[link_fields[ftype]['model']]=ContentType.objects.get(app_label=app, model=model_name).model_class()
				
				#Now let's see what fields need to be set
				if 'combo' not in link_fields[ftype]:
					#Simple field
					add_fields[qname]=[link_fields[ftype]['model'], link_fields[ftype]['model_field']]
				else:
					#Combo field
					for f in link_fields[ftype]['combo']:
						add_fields[qname+'_'+f]=[link_fields[f]['model'], link_fields[f]['model_field']]
		
		#Now let's set up the responses
		for response in responses:
			#First, grab the values dict from all linked instances. The id is stored in response.
			link_instances={}
			for model, model_cls in link_models.items():
				link_instances[model]=model_cls.objects.filter(pk=response[ model.split('.')[1]+'_id' ]).values()[0]
			
			#Now, put in the additional fields in response
			for qname, data in add_fields.items():
				response[qname]=link_instances[data[0]][data[1]]
				
		#Add responses to response_data
		response_data['answers'].extend(responses)									
					
		return response_data
	#getResponseData.depend_on_row(lambda: Field, lambda field: {'form': field.form})
	
	def rebuildData(self):
		"""
		Returns the metadata so that a form can be re-built in the form builder
		"""
		metadata={
			'title':self.form.title, 
			'desc':self.form.description, 
			'anonymous':self.form.anonymous, 
			'link_type':self.form.link_type,
			'link_id':self.form.link_id,
			'pages':self._getFormMetadata(self.form)
		}
		return metadata					
		
def test():
	f=Form.objects.get(id=13)
	fh=FormHandler(form=f)
	a=fh.getResponseData(f)
	
@cache_function
def rd(dyn, f):
	"""
	Returns the response data for this form, along with the questions
	"""
	a=FormHandler(form=f)
	response_data={'questions':[], 'answers':[]}
	responses=dyn.objects.all().order_by('id')
	fields=Field.objects.filter(form=f).order_by('section__page__seq', 'section__seq', 'seq').values('id', 'field_type', 'label')
	
	for field in fields:
		qname='question_%d' % field['id']
		if field['field_type'] in a._customFields:
			for f in a._customFields[field['field_type']]:
				response_data['questions'].append([qname+'_'+f, field['label'] + '_'+f])
		else:
			response_data['questions'].append([qname, field['label']])
	return response_data	

					
						
			
			 
			
			
	
	