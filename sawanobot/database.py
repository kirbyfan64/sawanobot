# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.


from . import Config

from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import backref, relationship, sessionmaker

from sqlalchemy import ARRAY, Boolean, Column, DateTime, ForeignKey, Integer, String, \
                              Table

import os


class Database:
    @property
    def url(self):
        return 'postgresql://postgres@localhost/sawanobot'

    def add_extracted_album(self, extracted_album):
        album, tracks = extracted_album

        old_album = self.session.query(Album).filter_by(catalog=album.catalog).first()
        if old_album is not None:
            self.session.merge(album)
        else:
            self.session.add(album)
        self.session.commit()

        track_map = {(track.disc, track.track): track for track in tracks}

        for track in tracks:
            present = self.session.query(Track).filter_by(catalog=track.catalog,
                                                          disc=track.disc,
                                                          track=track.track).first()
            if present is not None:
                track.id = present.id
            self.session.merge(track)

        self.session.commit()


assert Config.current is not None

if Config.current is Config.BOT:
    import sqlalchemy
    import sqlalchemy.ext.declarative
    import sqlalchemy.orm

    Model = sqlalchemy.ext.declarative.declarative_base()

    def table(name, *args, **kw):
        return Table(name, Model.metadata, *args, **kw)

    class BotDatabase(Database):
        def __init__(self):
            engine = sqlalchemy.create_engine(self.url)
            Model.metadata.create_all(engine)
            self.session = sqlalchemy.orm.sessionmaker(bind=engine)()
else:
    from flask_migrate import Migrate
    from flask_security import SQLAlchemyUserDatastore, UserMixin, RoleMixin
    from flask_sqlalchemy import SQLAlchemy
    import sqlalchemy

    db = SQLAlchemy()
    migrate = Migrate(db=db)
    Model = db.Model

    table = db.Table

    class WebDatabase(Database):
        def __init__(self, app):
            self.app = app
            self.app.config['SQLALCHEMY_DATABASE_URI'] = self.url
            db.init_app(self.app)

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

            if self.default_composer is None:
                default_composer = Composer(name=default)
                db.session.add(default_composer)

            db.session.commit()

        @property
        def session(self):
            return db.session

        @property
        def default_composer(self):
            name = self.app.config['DEFAULT_COMPOSER']
            return Composer.query.filter_by(name=name).first()


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


tracks_vocalists = table('tracks_vocalists',
                         Column('track', Integer, ForeignKey('tracks.id')),
                         Column('vocalist', String, ForeignKey('vocalists.name')))

tracks_lyricists = table('tracks_lyricists',
                         Column('track', Integer, ForeignKey('tracks.id')),
                         Column('lyricist', String, ForeignKey('lyricists.name')))


class Composer(Model):
    __tablename__ = 'composers'

    name = Column(String, primary_key=True, nullable=False)
    tracks = relationship('Track', back_populates='composer')


class Vocalist(Model):
    __tablename__ = 'vocalists'

    name = Column(String, primary_key=True, nullable=False)
    tracks = relationship('Track', secondary=tracks_vocalists,
                          back_populates='vocalists')


class Lyricist(Model):
    __tablename__ = 'lyricists'

    name = Column(String, primary_key=True, nullable=False)
    tracks = relationship('Track', secondary=tracks_lyricists,
                          back_populates='lyricists')


class Album(Model):
    __tablename__ = 'albums'

    catalog = Column(String, primary_key=True, nullable=False)
    cover_art = Column(ARRAY(String))
    vgmdb_id = Column(String, nullable=False, unique=True)
    name = Column(String, nullable=False, unique=True)
    notes = Column(String)
    tracks = relationship('Track', passive_deletes=True, back_populates='album')

    def __repr__(self):
        return self.name


class Track(Model):
    __tablename__ = 'tracks'

    id = Column(Integer, primary_key=True)
    catalog = Column(String, ForeignKey(Album.catalog, ondelete='CASCADE'),
                     nullable=False)
    album = relationship(Album, foreign_keys=catalog, back_populates='tracks')
    disc = Column(Integer, nullable=False)
    track = Column(Integer, nullable=False)
    name = Column(String, nullable=False, unique=True)
    length = Column(Integer, nullable=False)
    meaning = Column(String)
    composer_name = Column(String, ForeignKey(Composer.name), nullable=False)
    composer = relationship(Composer, foreign_keys=composer_name)
    vocalists = relationship(Vocalist, secondary=tracks_vocalists,
                             back_populates='tracks')
    lyricists = relationship(Lyricist, secondary=tracks_lyricists,
                             back_populates='tracks')
    lyrics = Column(String)
    info = Column(String)

    def __repr__(self):
        return self.name
