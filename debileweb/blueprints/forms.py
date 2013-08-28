from wtforms import TextField, BooleanField, Form
from wtforms.validators import Required

class SearchPackageForm(Form):
    package = TextField('package', validators = [Required()])
    maintainer = TextField('maintainer', validators = [Required()])
