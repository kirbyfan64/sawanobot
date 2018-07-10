# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import attr
import tatsu

import zdiscord

import asyncio, enum, os, re, sqlite3, sys, yaml
from pathlib import Path

from . import Config
Config.current = Config.BOT
from .database import BotDatabase


QUERY_GRAMMAR = '''
start = kind op value $ ;
kind = 'vocal' | 'lyricist' | 'album' | 'albumid' | 'track' ;
op = '=' | '~' ;
value =  { /[^:]/ }+ ;
'''


@attr.s
class QueryPart:
    kind = attr.s()
    op = attr.s()
    value = attr.s()


@attr.s
class Query:
    what = attr.s()
    items = attr.s()


class Kind(enum.Enum):
    VOCAL = 'vocal'
    LYRICIST = 'lyricist'
    ALBUM = 'album'
    ALBUM_ID = 'albumid'
    TRACK = 'track'


class Op(enum.Enum):
    IS = '='
    MATCHES = '~'


def like_escape(value):
    if isinstance(value, str):
        return re.sub(r'([\\_%])', r'\\\1', value)
    else:
        return value


class Config(zdiscord.Config):
    DEFAULT_PATH = '~/.sawanobot.yml'


class SawanoBotCommands:
    def __init__(self, bot):
        self.bot = bot
        self.logger = self.bot.logger
        self.db = BotDatabase()

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

    @zdiscord.safe_command
    async def track(self, *args):
        '''
        Prints information on the given track.

        Example usage:

        Show information about Barricades:
        $track barricades

        Show information about all tracks beginning with UNI:
        $track UNI

        Note that `$track name` is shorthand for `$query track name~name`.
        '''
        self.logger.info(f'track {args}')

        if len(args) != 1:
            self.logger.info('track: bad args!')
            await self.bot.say(
                f'WTH are you doing; this needs a track to search for')
            return
        name = args[0]

        query = Query('track', [QueryPart(Kind.TRACK, Op.MATCHES, name)])

        results = await self.run_query(query)
        if results is None:
            self.logger.error('Query run failed!')
            return

        await self.show_query_results(query, results)

    @zdiscord.safe_command
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


class SawanoBot(zdiscord.Bot):
    COMMAND_PREFIX = '$'
    COMMANDS = SawanoBotCommands


def main():
    asyncio.set_event_loop(asyncio.new_event_loop())
    zdiscord.main(SawanoBot, Config())


if __name__ == '__main__':
    main()
