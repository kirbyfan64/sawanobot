# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.


from flask import Flask, Markup, redirect, request, session, url_for
from flask_admin import Admin, BaseView, expose, helpers
from flask_admin.model.template import macro
from flask_admin.contrib.sqla import ModelView
from flask_admin.contrib.sqla.filters import BaseSQLAFilter
from flask_mail import Mail
from flask_security import Security, current_user
from flask_security.utils import encrypt_password
from flask_session import Session
from wtforms import Form, StringField, SubmitField, TextAreaField, ValidationError


from . import Config
Config.current = Config.WEB

from .database import Album, Track, Composer, Vocalist, Lyricist, Role, User, \
                      WebDatabase, migrate, user_datastore
from . import vgmdb

import os


class DefaultPasswordField(StringField):
    def __init__(self, *args, **kw):
        super(DefaultPasswordField, self).__init__(
            default=encrypt_password(app.config['DEFAULT_PASSWORD']),
            render_kw={'readonly': True}, *args, **kw)


class TallTextAreaField(TextAreaField):
    def __init__(self, *args, **kw):
        super(TallTextAreaField, self).__init__(render_kw={'rows': 20}, *args, **kw)


class ImportForm(Form):
    album_url = StringField('VGMdb album URL')
    submit = SubmitField('Import')

    def validate_album_url(form, field):
        if vgmdb.extract_album_id(field.data) is None:
            raise ValidationError('Invalid album URL')


class ImportConfirmForm(Form):
    submit = SubmitField('Import')


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


class ViewAuthMixin:
    column_display_pk = True

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


class ImportView(BaseView, ViewAuthMixin):
    def __init__(self):
        super(ImportView, self).__init__(name='VGMdb Import', endpoint='import')

    @expose('/', methods=('GET', 'POST'))
    def index(self):
        album_url = request.args.get('album_url')
        if album_url is not None:
            session_key = f'vgmdb-import-{album_url}'
            form = ImportConfirmForm(request.form)

            if request.method == 'POST':
                if session_key in session:
                    extracted_album = session[session_key]
                    db.add_extracted_album(extracted_album)
                    return redirect(url_for('album.edit_view',
                                            id=extracted_album.album.catalog))
                else:
                    abort(400)

            album_id = vgmdb.extract_album_id(album_url)
            if album_id is None:
                abort(400)

            composer = db.default_composer
            extracted_album = vgmdb.extract_album_and_tracks(album_id, composer)
            session[session_key] = extracted_album

            album, tracks = extracted_album
            return self.render('import_results.html', album=album, tracks=tracks,
                               form=form, album_url=album_url)
        else:
            form = ImportForm(request.form)
            if request.method == 'POST' and form.validate():
                return redirect(url_for('.index', album_url=form.album_url.data))
            return self.render('import.html', form=form)


def format_length(view, context, model, column):
    return f'{model.length // 60:>02}:{model.length % 60:>02}'


class DataModelView(ModelView, ViewAuthMixin):
    column_hide_backrefs = False
    column_exclude_list = ('notes', 'lyrics', 'info')
    column_formatters = {'catalog': macro('format_filters'),
                         'composer': macro('format_filters'),
                         'disc': macro('format_filters'),
                         'length': format_length}
    column_labels = {'catalog': 'Catalog number', 'vgmdb_id': 'VGMdb id',
                     'id': 'Unique ID'}
    form_overrides = {'lyrics': TallTextAreaField, 'notes': TallTextAreaField}
    list_template = 'admin/list_filtered.html'

    def __init__(self, model, session):
        table = model.metadata.tables[model.__tablename__]
        self.column_list = []
        self.form_columns = []

        for column in table.c:
            if model is Track and column.name == 'catalog':
                self.column_list.append(column.name)
                self.column_list.append('album')
                self.form_columns.append('album')
            elif model is Track and column.name == 'composer_name':
                self.column_list.append('composer_name')
                self.form_columns.append('composer')
            elif column.name != 'id':
                self.column_list.append(column.name)
                self.form_columns.append(column.name)

        if model is Track:
            self.form_columns.append('vocalists')
            self.form_columns.append('lyricists')

        super(DataModelView, self).__init__(model, session)
        self.superuser = False

    def get_request_filters(self):
        return {key: value for key, value in request.args.items()
                           if key in self.column_list}

    def get_filtered_query(self, query):
        filters = self.get_request_filters()
        if filters:
            return query.filter_by(**filters)
        else:
            return query

    def get_query(self):
        return self.get_filtered_query(super(DataModelView, self).get_query())

    def get_count_query(self):
        return self.get_filtered_query(super(DataModelView, self).get_count_query())

    def render(self, template, **kw):
        filters = self.get_request_filters()
        return super(DataModelView, self).render(template,
                                                 column_labels=self.column_labels,
                                                 request_filters=filters, **kw)


class RestrictedModelView(ModelView, ViewAuthMixin):
    def __init__(self, model, session, *, exclude=None):
        if exclude is not None:
            self.column_exclude_list = exclude

        self.form_overrides = {'password': DefaultPasswordField}

        super(RestrictedModelView, self).__init__(model, session)
        self.superuser = True


app = Flask('sawanobot')
app.jinja_env.add_extension('jinja2.ext.do')
app.config.from_object('local_config')
app.config['FLASK_ADMIN_SWATCH'] = 'cosmo'
app.config['SESSION_TYPE'] = 'filesystem'
app.config['SECURITY_CHANGEABLE'] = True
# app.config['DEFAULT_COMPOSER'] = local_config
# app.config['SECURITY_PASSWORD_SALT'] = local_config
# app.config['SECURITY_CONFIRMABLE'] = True
# app.config['SECURITY_RECOVERABLE'] = True
# app.config['SECURITY_REGISTERABLE'] = False
# app.config['ADMIN_EMAIL'] = local_config
# app.config['ADMIN_PASSWORD'] = local_config
# app.config['SECRET_KEY'] = local_config

app.secret_key = app.config['SECRET_KEY']


Mail(app)
Session(app)

migrate.init_app(app)

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
admin.add_view(DataModelView(Composer, db.session))
admin.add_view(DataModelView(Vocalist, db.session))
admin.add_view(DataModelView(Lyricist, db.session))
admin.add_view(RestrictedModelView(Role, db.session))
admin.add_view(RestrictedModelView(User, db.session, exclude=['password']))
admin.add_view(ImportView())
admin.add_view(SecurityRedirectView('Log in', 'login', logged_in=False))
admin.add_view(SecurityRedirectView('Log out', 'logout', logged_in=True))
admin.add_view(SecurityRedirectView('Change password', 'change_password',
                                    logged_in=True))


@app.route('/')
def index():
    return redirect(url_for('admin.index'))


@app.template_filter()
def format_model_list(models):
    return ', '.join([model.name for model in models] or ['None'])


with app.app_context():
    db.initialize()
    db.session.commit()

    if User.query.filter_by(email=app.config['ADMIN_EMAIL']).first() is None:
        user_datastore.create_user(
            email=app.config['ADMIN_EMAIL'],
            password=encrypt_password(app.config['DEFAULT_PASSWORD']),
            roles=[db.user_role, db.superuser_role],
        )
        db.session.commit()
