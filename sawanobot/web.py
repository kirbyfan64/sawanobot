# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.


from flask import Flask
from flask_admin import Admin
from flask_admin.contrib.sqla import ModelView
from wtforms import TextAreaField

from . import Config
Config.current = Config.WEB

from .database import Album, Track, WebDatabase


class TallTextAreaField(TextAreaField):
    def __init__(self, *args, **kw):
        kw['render_kw'] = {'rows': 20}
        super(TallTextAreaField, self).__init__(*args, **kw)


class CustomModelView(ModelView):
    column_display_pk = True

    form_overrides = {'lyrics': TallTextAreaField}

    def __init__(self, model, session):
        table = model.metadata.tables[model.__tablename__]
        self.form_columns = []
        for column in table.c:
            self.form_columns.append(column.name)

        super(CustomModelView, self).__init__(model, session)


app = Flask('sawanobot')
app.config['FLASK_ADMIN_SWATCH'] = 'cosmo'
app.config['SESSION_TYPE'] = 'filesystem'
app.secret_key = 'secret'

db = WebDatabase(app)
admin = Admin(app, name='sawanobot', template_mode='bootstrap3',
              base_template='admin/master.html')
admin.add_view(CustomModelView(Album, db.session))
admin.add_view(CustomModelView(Track, db.session))

app.run()
