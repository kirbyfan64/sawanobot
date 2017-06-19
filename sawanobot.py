#!/usr/bin/env python36

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from logbook import RotatingFileHandler, StreamHandler, Logger
from recordclass import recordclass
from discord.ext import commands
import discord, tatsu

import asyncio, enum, functools, os, re, sqlite3, sys, traceback, yaml
from pathlib import Path


QUERY_GRAMMAR = '''
start = kind op value $ ;
kind = 'vocal' | 'lyricist' | 'album' | 'albumid' | 'track' ;
op = '=' | '~' ;
value =  { /[^:]/ }+ ;
'''


QueryPart = recordclass('QueryPart', ['kind', 'op', 'value'])
Query = recordclass('Query', ['what', 'items'])


class Kind(enum.Enum):
    VOCAL = 'vocal'
    LYRICIST = 'lyricist'
    ALBUM = 'album'
    ALBUM_ID = 'albumid'
    TRACK = 'track'


class Op(enum.Enum):
    IS = '='
    MATCHES = '~'


def loadfile(path):
    with Path(path).open() as f:
        return yaml.load(f)


def like_escape(value):
    if isinstance(value, str):
        return re.sub(r'([\\_%])', r'\\\1', value)
    else:
        return value


class Config:
    def __init__(self, path='~/.sawanobot.yml'):
        self.path = os.path.expanduser(path)
        self.data = loadfile(self.path)

    @property
    def token(self): return self.data['token']

    @property
    def logfile(self): return self.data['logfile']


class Database:
    def __init__(self):
        self.conn = sqlite3.connect(':memory:')
        self.cursor = self.conn.cursor()
        self.cursor.execute(
            'CREATE TABLE albums (file text, album text, albumid real)')
        self.cursor.execute(
            'CREATE TABLE tracks (track text, album text, albumid real,'
                                 'vocal text, lyricist text, lyrics text)')

    def load(self, data_dir):
        all = loadfile(data_dir / 'all.yml')
        album_files = all['albums']

        for album_file in album_files:
            album_data = loadfile(data_dir / f'{album_file}.yml')
            self.cursor.execute('INSERT INTO albums VALUES (?, ?, ?)',
                                (album_file, album_data['name'],
                                 album_data['id']))

            for track in album_data['tracks']:
                if isinstance(track, str):
                    track_data = {}
                elif isinstance(track, dict):
                    track, track_data = list(track.items())[0]
                else:
                    assert 0, f'Bad track type {type(track)}'

                self.cursor.execute(
                    'INSERT INTO tracks VALUES (?, ?, ?, ?, ?, ?)',
                    (track, album_data['name'], album_data['id'],
                     track_data.get('vocal'), track_data.get('lyricist'),
                     track_data.get('lyrics')))

        self.conn.commit()


def safe_command(func):
    @functools.wraps(func)
    async def wrapper(self, *args):
        try:
            return await func(self, *args)
        except Exception as ex:
            self.logger.error(f'Fatal error inside {func.__name__}!!!!')
            self.logger.error(traceback.format_exc())
            self.logger.error(str(ex))

            await self.bot.say(f'''
*BOOOOOOOM*

Unfortunately, SawanoBot crashed while running your command. After the
flames and screaming, this info was left behind:

Function where the error occurred: `{func.__name__}`

```
{traceback.format_exc()}
```

Sorry! :(
'''.strip())

    return commands.command(name=func.__name__)(wrapper)


class SawanoBotCommands:
    def __init__(self, bot):
        self.bot = bot
        self.db = Database()
        self.db.load(Path(__file__).parent / 'data')
        self.logger = self.bot.logger

    async def parse_query(self, query):
        self.logger.info(f'parse_query {query}')
        items = []
        what = query[0]

        for part in query[1:]:
            try:
                kind, op, value = tatsu.parse(QUERY_GRAMMAR, part)
            except tatsu.exceptions.FailedParse as ex:
                await self.bot.say(f'Invalid query: {ex.message}')
                self.logger.error(f'FailedParse {str(ex)}')
                return
            else:
                part = QueryPart(Kind(kind), Op(op),
                                 ''.join(value).replace('+', ' '))

                if part.kind == Kind.ALBUM_ID:
                    try:
                        part.value = int(part.value)
                    except ValueError:
                        await self.bot.say(
                            f"{part.value} isn't a valid album id")
                        self.logger.error(f'Bad integer {part.value}')

                items.append(part)

        return Query(what, items)

    async def run_query(self, query):
        self.logger.info(f'run_query {query}')

        where = []
        for item in query.items:
            if isinstance(item.value, str):
                where.append(f'{item.kind.value} like ?')
            else:
                where.append(f'{item.kind.value} == ?')

        if query.what == 'track':
            table = 'tracks'
        elif query.what == 'album':
            table = 'albums'
        else:
            await self.bot.say(f'Invalid item to query: {query.what}')
            self.logger.error(f'Invalid query item {query.what}')
            return

        items = []
        for item in query.items:
            if item.op == Op.MATCHES:
                items.append(f'%{like_escape(item.value).replace(" ", "%")}%')
            else:
                items.append(like_escape(item.value))

        self.logger.info(f'table: {table}, where: {where}, items: {items}')

        results = self.db.cursor.execute(
            f'SELECT * from {table} WHERE {" AND ".join(where)}', items)
        return list(results)

    async def show_query_results(self, query, results):
        self.logger.info(f'show_query_results {query} {results}')
        to_show = []

        for result in results:
            if query.what == 'track':
                name, album, albumid, vocal, lyricist, lyrics = result

                to_show.append({'Name': f'`{name}`', 'Album': album,
                                'VGMdb album id': str(int(albumid))})

                if vocal is not None:
                    to_show[-1]['Vocalist(s)'] = vocal
                if lyricist is not None:
                    to_show[-1]['Lyricist(s)'] = lyricist
                if lyrics is not None:
                    to_show[-1]['Lyrics'] = '\n\n' + lyrics
            elif query.what == 'album':
                file, album, albumid = result

                tracks = list(self.db.cursor.execute(
                    f'SELECT track FROM tracks WHERE albumid = ?', (albumid,)))

                to_show.append({'Name': album,
                                'VGMdb album id': str(int(albumid)),
                                'Tracks': '\n\n'+'\n'.join(
                                    f'- `{track}`' for track, in tracks)})
            else:
                assert 0, f'Bad query type to show {query.what}'

        self.logger.info(f'to_show {to_show}')

        await self.bot.say(f'{len(results)} result(s) found!')

        for item in to_show:
            message = []

            for key, value in item.items():
                message.append(f'**{key}:** {value}')

            await self.bot.say('\n'.join(message))

    @safe_command
    async def query(self, *query):
        '''
        Queries for information on a Sawano album or track.

        Example usage:

        Query all tracks with mpi doing vocals:
        $query track vocal=mpi

        Query all track with mpi *and* Mika Kobayashi doing vocals (the "+" is a
        stand-in for a space):
        $query track vocal=mpi vocal=mika+kobayashi

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

        pquery = await self.parse_query(query)
        if pquery is None:
            self.logger.error('Query parsing failed!')
            return

        results = await self.run_query(pquery)
        if results is None:
            self.logger.error('Query run failed!')
            return

        await self.show_query_results(pquery, results)


class SawanoBot(commands.Bot):
    def __init__(self, config):
        super(SawanoBot, self).__init__(command_prefix='$')
        self.config = config
        self.logger = Logger('sawanobot')
        self.event(self.on_ready)
        self.add_cog(SawanoBotCommands(self))

    def run(self):
        super(SawanoBot, self).run(self.config.token)

    async def on_ready(self):
        self.logger.info(f'Logged in: {self.user.name} {self.user.id}')


def main():
    asyncio.set_event_loop(asyncio.new_event_loop())
    config = Config()

    stream_handler = StreamHandler(sys.stdout)
    file_handler = RotatingFileHandler(os.path.expanduser(config.logfile))

    stream_handler.push_application()
    file_handler.push_application()

    bot = SawanoBot(config)
    bot.run()


if __name__ == '__main__':
    main()
