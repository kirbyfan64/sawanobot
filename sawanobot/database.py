# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.


from . import Config

from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

from sqlalchemy import ARRAY, Column, ForeignKey, Integer, String

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
            Model.metadata.create_all(engine)
            self.session = sqlalchemy.orm.sessionmaker(bind=engine)
else:
    from flask_sqlalchemy import SQLAlchemy

    db = SQLAlchemy()
    Model = db.Model

    class WebDatabase(Database):
        def __init__(self, app):
            app.config['SQLALCHEMY_DATABASE_URI'] = self.url
            db.init_app(app)

        @property
        def session(self):
            return db.session


class Album(Model):
    __tablename__ = 'albums'

    id = Column(String, primary_key=True, nullable=False)
    name = Column(String, nullable=False)


class Track(Model):
    __tablename__ = 'tracks'

    album_id = Column(String, ForeignKey('albums.id'), primary_key=True)
    disc = Column(Integer, primary_key=True, nullable=False)
    track = Column(Integer, primary_key=True, nullable=False)
    name = Column(String, nullable=False)
    lyrics = Column(String)
    lyricists = Column(ARRAY(String))
    vocalists = Column(ARRAY(String))
