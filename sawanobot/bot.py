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
from .database import BotDatabase, Model, Album, Track


QUERY_GRAMMAR = '''
start = kind op value $ ;
kind = 'catalog' | 'name' ;
op = '=' | '~=' | '~' ;
value =  { /[^:]/ }+ ;
'''

def fuzzy_like(value, *, bounded=False):
    escaped = re.sub(r'([\\_%])', r'\\\1', value).replace(' ', '%')
    return f'%{escaped}%' if not bounded else escaped


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
        self.register_model(Track, extra_fields=['vocalists', 'lyricists'])

    def register_model(self, model, *, extra_fields=[]):
        grammar = tatsu.compile(QUERY_GRAMMAR)

        for field in [column.name for column in model.__table__.c] + extra_fields:
            grammar.rules[1].exp.options.append(tatsu.grammars.Token(field))

        self.models[model.__tablename__] = model
        self.query_grammars[model.__tablename__] = grammar

    def fields(self, model):
        fields = {column.name for column in model.__table__.c}
        if model is Album:
            return (fields | {'catalog', 'cover_art', 'tracks'}) - {'notes'}
        elif model is Track:
            return (fields | {'album', 'vocalists', 'lyricists'}) - {'lyrics'}

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
                elif op in ('~', '~='):
                    operator = sqlalchemy.sql.operators.ilike_op
                    is_bounded = op == '~='
                    value = fuzzy_like(value, bounded=is_bounded)

                if column_name in ('vocalists', 'lyricists'):
                    related = column.property.argument
                    criteria.append(column.any(related.name.operate(operator, value)))
                else:
                    criteria.append(column.operate(operator, value))

        return criteria

    def search_by_name(self, model_type, name):
        for bounded in True, False:
            fuzzy = fuzzy_like(name, bounded=bounded)
            results = self.q(model_type).filter(model_type.name.ilike(fuzzy)).all()
            if results:
                return results

        return []

    async def show_query_results(self, model, results, fields_to_show):
        self.logger.info(f'show_query_results {model} {results}')
        to_show = []

        for result in results:
            info = {}

            if model is Track:
                if 'name' in fields_to_show:
                    info['Name'] = result.name
                if 'album' in fields_to_show:
                    info['Album'] = result.album.name
                if 'vocalists' in fields_to_show and result.vocalists:
                    info['Vocalist(s)'] = ', '.join(m.name for m in result.vocalists)
                if 'lyricists' in fields_to_show and result.lyricists:
                    info['Lyricist(s)'] = ', '.join(m.name for m in result.lyricists)
                if 'lyrics' in fields_to_show and result.lyrics is not None:
                    info['Lyrics'] = '\n' + result.lyrics
            elif model is Album:
                print('catalog' in fields_to_show)
                if 'name' in fields_to_show:
                    info['Name'] = result.name
                if 'catalog' in fields_to_show:
                    info['Catalog number'] = result.catalog
                if 'vgmdb_id' in fields_to_show:
                    info['VGMdb URL'] = f'https://vgmdb.net/album/{result.vgmdb_id}'
                if 'cover_art' in fields_to_show:
                    info['Cover art'] = ' '.join(result.cover_art)
                if 'tracks' in fields_to_show:
                    info['Tracks'] = '\n' + '\n'.join(f'- `{m.name}`'
                                                      for m in result.tracks)
                if 'notes' in fields_to_show and result.notes:
                    info['Notes'] = result.notes
            else:
                assert 0, f'Bad model to show {model}'

            to_show.append(info)

        self.logger.info(f'to_show {to_show}')

        await self.bot.say(f'{len(results)} result(s) found!')

        for item in to_show:
            message = []

            if not item:
                continue
            elif len(item) == 1:
                message.append(next(iter(item.values())))
            else:
                for key, value in item.items():
                    message.append(f'**{key}:** {value}')

            await self.bot.say('\n'.join(message))

    @zdiscord.safe_command
    async def album(self, *args):
        '''
        Prints information about the given album.

        Example usage:

        Show information about Binary Star / Cage:
        $album binary star cage

        Note that `$album <name>` is shorthand for `$query album name~<name>`.
        '''
        self.logger.info(f'album {args}')

        if len(args) < 1:
            self.logger.info('album: bad args!')
            await self.bot.say('This needs an album` to search for.')
            return

        name = ' '.join(args)
        results = self.search_by_name(Album, name)
        await self.show_query_results(Album, results, self.fields(Album))

    @zdiscord.safe_command
    async def track(self, *args):
        '''
        Prints information about the given track.

        Example usage:

        Show information about Barricades:
        $track barricades

        Show information about all tracks containing UNI:
        $track UNI

        Note that `$track <name>` is shorthand for `$query track name~<name>`.
        '''
        self.logger.info(f'track {args}')

        if len(args) < 1:
            self.logger.info('track: bad args!')
            await self.bot.say('This needs a track to search for.')
            return

        name = ' '.join(args)
        results = self.search_by_name(Track, name)
        await self.show_query_results(Track, results, self.fields(Track))

    @zdiscord.safe_command
    async def lyrics(self, *args):
        '''
        Prints the given track's lyrics.
        '''
        self.logger.info(f'lyrics {args}')

        if len(args) < 1:
            self.logger.info('lyrics: bad args!')
            await self.bot.say('This needs a track to search for.')
            return

        name = ' '.join(args)
        results = self.search_by_name(Track, name)
        await self.show_query_results(Track, results, {'lyrics'})

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

        query = list(query)

        self.logger.info(f'$query: {query}')
        if len(query) < 2:
            return await self.bot.say(f'$query needs a query (duh)')

        model = await self.get_model(query.pop(0))
        if model is None:
            return

        fields = self.fields(model)

        for formatter in ':', ':-':
            if formatter in query:
                index = query.index(formatter)
                requested_fields = set(query[index+1:])
                query = query[:index]

                if formatter == ':':
                    fields = set(requested_fields)
                elif formatter == ':-':
                    fields -= set(requested_fields)

                break

        criteria = await self.parse_query(model, query)
        if criteria is None:
            return

        results = self.q(model).filter(*criteria).all()
        await self.show_query_results(model, results, fields)


class SawanoBot(zdiscord.Bot):
    COMMAND_PREFIX = '$'
    COMMANDS = SawanoBotCommands


def main():
    asyncio.set_event_loop(asyncio.new_event_loop())
    zdiscord.main(SawanoBot, Config())


if __name__ == '__main__':
    main()
