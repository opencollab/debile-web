from flask.ext.wtf import Form, TextField, BooleanField
from flask.ext.wtf import Required

class SearchPackageForm(Form):
    package = TextField('package', validators = [Required()])
