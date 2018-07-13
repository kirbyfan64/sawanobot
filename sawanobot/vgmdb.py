# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.


import contextlib
import json
import urllib.request

from .database import Album, Track


def extract_album_id(url):
    prefixes = 'vgmdb.net', 'http://vgmdb.net', 'https://vgmdb.net'
    for prefix in prefixes:
        prefix = f'{prefix}/album/'
        if url.startswith(prefix):
            album_id = url[len(prefix):]
            break
    else:
        return None

    if album_id.endswith('/'):
        album_id = album_id[:-1]

    if album_id.isdigit():
        return album_id
    else:
        return None


@contextlib.contextmanager
def vgmdb_info(url):
    with urllib.request.urlopen(f'http://vgmdb.info/{url}') as resp:
        yield json.load(resp)


def upto(string, character):
    if character in string:
        return string[:string.index(character)]
    else:
        return string


def parse_minutes_seconds(duration):
    minutes = '0'
    seconds = duration
    if ':' in duration:
        minutes, seconds = duration.split(':')
    return int(minutes) * 60 + int(seconds)


def fill_track_info(notes, track_map):
    current_track = None

    searchers = {
        'Lyrics by ': 'lyricist',
        'Lyrics: ': 'lyricist',
        'Vocal by ': 'vocal',
        'Vocal: ': 'vocal',
    }

    for line in notes.splitlines():
        if line.startswith('M') and line[1].isdigit():
            pos = upto(line, ' ')[1:]
            current_track = track_map[pos]
        elif line.startswith('M-') and line[2].isdigit():
            pos = upto(line, ' ')[2:]
            current_track = track_map[f'1-{pos}']
        else:
            for prefix, target in searchers.items():
                if line.startswith(prefix):
                    value = line[len(prefix):].replace(' & ', ', ').rstrip('.')
                    setattr(current_track, target, value)
                    break


def extract_album_and_tracks(album_id):
    LANGUAGES = 'Japanese', 'Greek', 'English'

    with vgmdb_info(f'album/{album_id}') as data:
        track_map = {}
        tracks = []
        catalog = data['catalog']
        notes = data['notes']
        album = Album(catalog=catalog, vgmdb_id=album_id, name=data['name'], notes=notes)

        for disc_id, disc_data in enumerate(data['discs'], start=1):
            for track_id, track_data in enumerate(disc_data['tracks'], start=1):
                names = track_data['names']
                length = parse_minutes_seconds(track_data['track_length'])
                meaning = None

                name = names.get('Japanese') or names.get('Greek')
                if name is not None:
                    meaning = names.get('English')
                else:
                    name = names.get('English')

                assert name, track_data

                track = Track(catalog=catalog, disc=disc_id, track=track_id,
                              name=name, length=length, meaning=meaning,
                              composer=data['composers'][0]['names']['en'])
                tracks.append(track)
                track_map[f'{disc_id}-{track_id:>02}'] = track

        fill_track_info(notes, track_map)

        return album, tracks
