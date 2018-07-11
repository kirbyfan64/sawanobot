# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.


from flask import Flask, redirect, request, url_for
from flask_admin import Admin, BaseView, helpers
from flask_admin.contrib.sqla import ModelView
from flask_mail import Mail
from flask_security import Security, current_user
from flask_security.utils import encrypt_password
from wtforms import TextAreaField, StringField

from . import Config
Config.current = Config.WEB

from .database import Album, Track, Role, User, WebDatabase, user_datastore

import os


class DefaultPasswordField(StringField):
    def __init__(self, *args, **kw):
        super(DefaultPasswordField, self).__init__(
            default=encrypt_password(app.config['DEFAULT_PASSWORD']),
            render_kw={'readonly': True}, *args, **kw)


class TallTextAreaField(TextAreaField):
    def __init__(self, *args, **kw):
        super(TallTextAreaField, self).__init__(render_kw={'rows': 20}, *args, **kw)


class SecurityRedirectView(BaseView):
    def __init__(self, name, endpoint, *, logged_in):
        self.logged_in = logged_in
        self.url = f'/{endpoint}'
        self._default_view = endpoint
        super(SecurityRedirectView, self).__init__(name=name, endpoint='security')

    def create_blueprint(self, admin):
        # Hack to get a unique blueprint name.
        self.endpoint = f'security.{self._default_view}.redirect'
        result = super(SecurityRedirectView, self).create_blueprint(admin)
        self.endpoint = 'security'
        return result

    def is_accessible(self):
        is_logged_in = current_user.is_active and current_user.is_authenticated
        return self.logged_in == is_logged_in


class CustomModelView(ModelView):
    column_display_pk = True

    def __init__(self, model, session, *, superuser):
        self.superuser = superuser
        super(CustomModelView, self).__init__(model, session)

    def is_accessible(self):
        if not current_user.is_active or not current_user.is_authenticated:
            return False

        required_role = 'superuser' if self.superuser else 'user'
        if not current_user.has_role(required_role):
            return False

        return True

    def _handle_view(self, name, **kwargs):
        if not self.is_accessible():
            if current_user.is_authenticated:
                abort(403)
            else:
                return redirect(url_for('security.login', next=request.url))


class DataModelView(CustomModelView):
    def __init__(self, model, session):
        table = model.metadata.tables[model.__tablename__]
        self.form_columns = []
        for column in table.c:
            self.form_columns.append(column.name)

        self.form_overrides = {'lyrics': TallTextAreaField}

        super(DataModelView, self).__init__(model, session, superuser=False)


class RestrictedModelView(CustomModelView):
    def __init__(self, model, session, *, exclude=None):
        if exclude is not None:
            self.column_exclude_list = exclude

        self.form_overrides = {'password': DefaultPasswordField}

        super(RestrictedModelView, self).__init__(model, session, superuser=True)


app = Flask('sawanobot')
app.config.from_object('local_config')
app.config['FLASK_ADMIN_SWATCH'] = 'cosmo'
app.config['SESSION_TYPE'] = 'filesystem'
app.config['SECURITY_CHANGEABLE'] = True
# app.config['SECURITY_PASSWORD_SALT'] = local_config
# app.config['SECURITY_CONFIRMABLE'] = True
# app.config['SECURITY_RECOVERABLE'] = True
# app.config['SECURITY_REGISTERABLE'] = False
# app.config['ADMIN_EMAIL'] = local_config
# app.config['ADMIN_PASSWORD'] = local_config
# app.config['SECRET_KEY'] = local_config
app.secret_key = app.config['SECRET_KEY']


mail = Mail(app)


security = Security(app, user_datastore)

@security.context_processor
def security_context_processor():
    return {
        'admin_base_template': admin.base_template,
        'admin_view': admin.index_view,
        'h': helpers,
        'get_url': url_for,
    }


db = WebDatabase(app)
admin = Admin(app, name='sawanobot', template_mode='bootstrap3',
              base_template='admin/master.html')
admin.add_view(DataModelView(Album, db.session))
admin.add_view(DataModelView(Track, db.session))
admin.add_view(RestrictedModelView(Role, db.session))
admin.add_view(RestrictedModelView(User, db.session, exclude=['password']))
admin.add_view(SecurityRedirectView('Log in', 'login', logged_in=False))
admin.add_view(SecurityRedirectView('Log out', 'logout', logged_in=True))
admin.add_view(SecurityRedirectView('Change password', 'change_password',
                                    logged_in=True))


@app.route('/')
def index():
    return redirect(url_for('admin.index'))


with app.app_context():
    db.initialize()

    if User.query.filter_by(email=app.config['ADMIN_EMAIL']).first() is None:
        user_datastore.create_user(
            email=app.config['ADMIN_EMAIL'],
            password=encrypt_password(app.config['DEFAULT_PASSWORD']),
            roles=[db.user_role, db.superuser_role],
        )
        db.session.commit()

app.run()
