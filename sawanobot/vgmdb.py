# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.


import urllib.request

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
