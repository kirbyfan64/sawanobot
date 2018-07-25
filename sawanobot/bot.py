# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import tatsu
import sqlalchemy.sql.operators

import zdiscord

import asyncio, enum, os, re, sqlite3, sys, yaml
from pathlib import Path

from . import Config
Config.current = Config.BOT
from .database import BotDatabase, Model, Album, Track, model_table


QUERY_GRAMMAR = '''
start = kind op value $ ;
kind = 'catalog' | 'name' ;
op = '=' | '~' ;
value =  { /[^:]/ }+ ;
'''


def fuzzy_like(value):
    escaped = re.sub(r'([\\_%])', r'\\\1', value).replace(' ', '%')
    return f'%{escaped}%'


class Config(zdiscord.Config):
    DEFAULT_PATH = '~/.sawanobot.yml'


class SawanoBotCommands:
    def __init__(self, bot):
        self.bot = bot
        self.logger = self.bot.logger
        self.db = BotDatabase()

        self.models = {}
        self.query_grammars = {}
        self.register_model(Album)
        self.register_model(Track)

    def register_model(self, model):
        table = model_table(model)
        grammar = tatsu.compile(QUERY_GRAMMAR)

        for column in table.c:
            grammar.rules[1].exp.options.append(tatsu.grammars.Token(column.name))

        self.models[model.__tablename__] = model
        self.query_grammars[model.__tablename__] = grammar

    def columns(self, model):
        columns = {column.name for column in model_table(model).c}
        if model is Album:
            return columns - {'notes'}
        elif model is Track:
            return (columns | {'album'}) - {'lyrics'}

    def q(self, *entities):
        return self.db.session.query(*entities)

    async def error(self, message, *, logged=None):
        await self.bot.say(message)
        self.logger.error(logged or message)

    async def get_model(self, name):
        self.logger.info(f'get_model {name}')
        if not name.endswith('s'):
            normalized = f'{name}s'

        if normalized not in self.query_grammars:
            await self.error(f'{name} is not something that can be queried.')
            return None

        return self.models[normalized]

    async def parse_query(self, model, query):
        self.logger.info(f'parse_query {query}')
        criteria = []
        grammar = self.query_grammars[model.__tablename__]

        for part in query:
            try:
                column_name, op, value = grammar.parse(part)
            except tatsu.exceptions.FailedParse as ex:
                await self.error(f'Invalid query: {ex.message}',
                                 logged=f'FailedParse {str(ex)}')
                return
            else:
                column = getattr(model, column_name)
                value = ''.join(value)

                if op == '=':
                    operator = sqlalchemy.sql.operators.eq
                elif op == '~':
                    operator = sqlalchemy.sql.operators.ilike_op
                    value = fuzzy_like(value)

                if column_name in ('vocalists', 'lyricists'):
                    criteria.append(column.any(value, operator=operator))
                else:
                    criteria.append(column.operate(operator, value))

        return criteria

    async def show_query_results(self, model, results, columns_to_show):
        self.logger.info(f'show_query_results {model} {results}')
        to_show = []

        for result in results:
            info = {}

            if model is Track:
                if 'name' in columns_to_show:
                    info['Name'] = result.name
                if 'album' in columns_to_show:
                    album = self.q(Album.name).filter_by(catalog=result.catalog).first()
                    assert album is not None
                    info['Album'] = album.name
                if 'vocalists' in columns_to_show and result.vocalists is not None:
                    info['Vocalist(s)'] = ', '.join(result.vocalists)
                if 'lyricists' in columns_to_show and result.lyricists is not None:
                    info['Lyricist(s)'] = ', '.join(result.lyricists)
                if 'lyrics' in columns_to_show and result.lyrics is not None:
                    info['Lyrics'] = '\n\n' + result.lyrics
            elif model is Album:
                if 'name' in columns_to_show:
                    info['Name'] = result.name
                if 'catalog 'in columns_to_show:
                    info['Catalog number'] = result.catalog
                if 'vgmdb_id' in columns_to_show:
                    info['VGMdb URL'] = f'https://vgmdb.net/album/{result.vgmdb_id}'
                if 'tracks 'in columns_to_show:
                    prefix = '\n\n' if info else ''
                    tracks = self.q(Track.name).filter_by(catalog=result.catalog).all()
                    info['Tracks'] =  '\n'.join(f'- `{name}`' for name, in tracks)
                if 'notes' in columns_to_show and result.notes:
                    info['Notes'] = result.notes
            else:
                assert 0, f'Bad model to show {model}'

            to_show.append(info)

        self.logger.info(f'to_show {to_show}')

        await self.bot.say(f'{len(results)} result(s) found!')

        for item in to_show:
            message = []

            for key, value in item.items():
                message.append(f'**{key}:** {value}')

            await self.bot.say('\n'.join(message))

    @zdiscord.safe_command
    async def track(self, *args):
        '''
        Prints information on the given track.

        Example usage:

        Show information about Barricades:
        $track barricades

        Show information about all tracks containing UNI:
        $track UNI

        Note that `$track <name>` is shorthand for `$query track name~<name> :- lyrics`.
        '''
        self.logger.info(f'track {args}')

        if len(args) < 1:
            self.logger.info('track: bad args!')
            await self.bot.say(
                f'WTH are you doing; this needs a track to search for')
            return
        name = ' '.join(args)

        results = self.q(Track).filter(Track.name.ilike(fuzzy_like(name))).all()
        await self.show_query_results(Track, results, self.columns(Track))

    @zdiscord.safe_command
    async def query(self, *query):
        '''
        Queries for information on a Sawano album or track.

        Example usage:

        Query all tracks with mpi doing vocals:
        $query track vocal=mpi

        Query all track with mpi *and* Mika Kobayashi doing vocals (quotes are used
        because of the space in the name):
        $query track vocalists~mpi "vocalists~mika kobayashi"

        Tracks with mpi doing lyrics and Cyua singing in the Unicorn OST (the
        "~" means "contains"):
        $query track lyricist=mpi vocal=cyua album~unicorn

        All the tracks on the Unicorn OST:
        $query track album~unicorn

        All the tracks with mpi doing lyrics, but showing only the name and
        lyrics:

        $query track lyricist=mpi : name lyrics
        '''

        self.logger.info(f'$query: {query}')
        if len(query) < 2:
            return await self.bot.say(f'$query needs a query (duh)')

        model = await self.get_model(query[0])
        if model is None:
            return

        criteria = await self.parse_query(model, query[1:])
        if criteria is None:
            return

        results = self.q(model).filter(*criteria).all()
        await self.show_query_results(model, results, self.columns(model))


class SawanoBot(zdiscord.Bot):
    COMMAND_PREFIX = '$'
    COMMANDS = SawanoBotCommands


def main():
    asyncio.set_event_loop(asyncio.new_event_loop())
    zdiscord.main(SawanoBot, Config())


if __name__ == '__main__':
    main()
