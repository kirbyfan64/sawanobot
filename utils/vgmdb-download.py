#!/usr/bin/env python3


import contextlib, json, os, plac, sys, yaml
from collections import namedtuple
from urllib import request
from pathlib import Path


assert sys.version_info >= (3, 6), 'This only works on CPython 3.6'


this = Path(__file__)
data_dir = this.parent.parent/'data'


Data = namedtuple('Data', ['name', 'id', 'tracks', 'trackmap'])
Track = namedtuple('Track', ['name', 'info'])


class ExtraIndentDumper(yaml.Dumper):
    def increase_indent(self, flow=False, indentless=False):
        return super(ExtraIndentDumper, self).increase_indent(flow, False)


class UnsortableDict(dict): pass

def representer(self, data):
    return self.represent_mapping('tag:yaml.org,2002:map', data.items())

yaml.add_representer(UnsortableDict, representer)


@contextlib.contextmanager
def vgmdb_info(url):
    with request.urlopen(f'http://vgmdb.info/{url}') as resp:
        yield json.load(resp)


def fill_track_info(notes, tracks, trackmap):
    current_track = None

    for line in notes.splitlines():
        if line.startswith('M') and line[1].isdigit():
            pos = line[1:line.index(' ')]
            current_track = tracks[trackmap[pos]]
        elif line.startswith('Lyrics by '):
            current_track.info['lyricist'] = line[10:].replace(' & ', ', ')\
                                                      .rstrip('.""')
        elif line.startswith('Vocal by '):
            current_track.info['vocal'] = line[9:].replace(' & ', ', ')\
                                                  .rstrip('.')


def extract_data(albumid):
    with vgmdb_info(f'album/{albumid}') as data:
        trackmap = {}
        tracks = []
        notes = data['notes']

        for disc_id, disc in enumerate(data['discs']):
            for track_id, track_data in enumerate(disc['tracks']):
                tracks.append(Track(track_data['names']['Japanese'], {}))
                trackmap[f'{disc_id+1}-{track_id+1:>02}'] = len(tracks)-1

        fill_track_info(notes, tracks, trackmap)

        return Data(data['name'], int(albumid), tracks, trackmap)


def write_album_info(data, target):
    formatted_data = UnsortableDict()
    formatted_data['name'] = data.name
    formatted_data['id'] = data.id
    formatted_data['tracks'] = []

    for track in data.tracks:
        if track.info:
            info = {track.name: track.info}
        else:
            info = track.name

        formatted_data['tracks'].append(info)

    with (data_dir/(target+'.yml')).open('w') as out_file:
        yaml.dump(formatted_data, out_file, Dumper=ExtraIndentDumper,
                  default_flow_style=False, allow_unicode=True)


def main(albumid: 'The VGMdb album ID',
         target: 'The target file name, to be saved in ../data/{target}.yml'):
    data = extract_data(albumid)
    write_album_info(data, target)


if __name__ == '__main__':
    plac.call(main)
