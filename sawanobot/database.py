# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.


from . import Config

from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

from sqlalchemy import ARRAY, Boolean, Column, DateTime, ForeignKey, Integer, String

import os


class Database:
    @property
    def url(self):
        return 'postgresql://postgres@localhost/sawanobot'


assert Config.current is not None

if Config.current is Config.BOT:
    import sqlalchemy
    import sqlalchemy.ext.declarative
    import sqlalchemy.orm

    Model = sqlalchemy.ext.declarative.declarative_base()

    class BotDatabase(Database):
        def __init__(self):
            engine = sqlalchemy.create_engine(self.url)
            Model.metadata.create_all()
            self.session = sqlalchemy.orm.sessionmaker(bind=engine)
else:
    from flask_migrate import Migrate
    from flask_security import SQLAlchemyUserDatastore, UserMixin, RoleMixin
    from flask_sqlalchemy import SQLAlchemy
    import sqlalchemy

    db = SQLAlchemy()
    migrate = Migrate(db=db)
    Model = db.Model

    class WebDatabase(Database):
        def __init__(self, app):
            app.config['SQLALCHEMY_DATABASE_URI'] = self.url
            db.init_app(app)

        def initialize(self):
            db.create_all()

            self.user_role = Role.query.filter_by(name='user').first()
            if self.user_role is None:
                self.user_role = Role(name='user')
                db.session.add(self.user_role)

            self.superuser_role = Role.query.filter_by(name='superuser').first()
            if self.superuser_role is None:
                self.superuser_role = Role(name='superuser')
                db.session.add(self.superuser_role)

            db.session.commit()

        @property
        def session(self):
            return db.session


    roles_users = db.Table('roles_users',
                           db.Column('user_id', db.Integer(), db.ForeignKey('user.id')),
                           db.Column('role_id', db.Integer(), db.ForeignKey('role.id')))

    class Role(Model, RoleMixin):
        id = Column(Integer(), primary_key=True)
        name = Column(String(80), unique=True)
        description = Column(String(255))

        def __str__(self):
            return self.name

    class User(Model, UserMixin):
        id = Column(Integer, primary_key=True)
        email = Column(String(255), unique=True)
        password = Column(String(255))
        active = Column(Boolean())
        confirmed_at = Column(DateTime())
        roles = db.relationship('Role', secondary=roles_users,
                                backref=db.backref('users', lazy='dynamic'))

        def __str__(self):
            return self.email

    user_datastore = SQLAlchemyUserDatastore(db, User, Role)

class Album(Model):
    __tablename__ = 'albums'

    catalog = Column(String, primary_key=True, nullable=False)
    vgmdb_id = Column(String, nullable=False, unique=True)
    name = Column(String, nullable=False, unique=True)


class Track(Model):
    __tablename__ = 'tracks'

    catalog = Column(String, ForeignKey('albums.catalog'), primary_key=True)
    disc = Column(Integer, primary_key=True, nullable=False)
    track = Column(Integer, primary_key=True, nullable=False)
    name = Column(String, nullable=False, unique=True)
    composer = Column(String, nullable=False)
    vocalists = Column(ARRAY(String))
    lyricists = Column(ARRAY(String))
    lyrics = Column(String)
    info = Column(String)
