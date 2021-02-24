#!/usr/bin/env python3
import sqlite3
from pathlib import Path


def get_ll_path(asin, book_path):
    lang_layer_name = "LanguageLayer.en.{}.kll".format(asin)
    return Path(book_path).parent.joinpath(lang_layer_name)


def check_db_file(path):
    '''
    if file exists return None otherwise create file
    then return sqlite connection
    '''
    journal = path.parent.joinpath(path.name + '-journal')
    if path.is_file():
        if not journal.is_file():
            return None
        else:  # last time failed
            path.unlink()
            journal.unlink()

    path.parent.mkdir(exist_ok=True)
    path.touch()
    return sqlite3.connect(path)


def create_lang_layer(asin, book_path):
    if (ll_conn := check_db_file(get_ll_path(asin, book_path))) is None:
        return None
    ll_conn.executescript('''
        CREATE TABLE metadata (
            key TEXT,
            value TEXT
        );

        CREATE TABLE glosses (
            start INTEGER PRIMARY KEY,
            end INTEGER,
            difficulty INTEGER,
            sense_id INTEGER,
            low_confidence BOOLEAN
        );
    ''')

    metadata = [('acr', 'CR!AX4P53SCH15WF68KNBX4NWWVZXKG'),
                ('targetLanguages', 'en'),
                ('sidecarRevision', '9'),
                ('bookRevision', '8d271dc3'),
                ('sourceLanguage', 'en'),
                ('enDictionaryVersion', '2016-09-14'),
                ('enDictionaryRevision', '57'),
                ('enDictionaryId', 'kll.en.en'),
                ('sidecarFormat', '1.0')]
    ll_conn.executemany('INSERT INTO metadata VALUES (?, ?)', metadata)
    return ll_conn


def search_lemma(r, start, word, ll_conn):
    result = r.hgetall('lemma:' + word)
    if result:
        ll_conn.execute('''
        INSERT INTO glosses (start, difficulty, sense_id, low_confidence)
        VALUES (?, ?, ?, 0)
        ''', (start,
              result[b'difficulty'].decode('utf-8'),
              result[b'sense_id'].decode('utf-8')))


def start_redis_server(db_path):
    import platform
    import subprocess
    args = ['--dir', db_path, '--save', '']
    system = platform.system()
    socket_path = '/tmp/redis.sock'
    if system != 'Windows':
        args += ['--unixsocket', socket_path, '--unixsocketperm', '700']
    if system == 'Darwin':
        # when launch calibre from desktop instead of terminal
        # it needs the absolute path of redis-server
        args.insert(0, '/usr/local/bin/redis-server')
        subprocess.Popen(args)
    else:
        args.insert(0, 'redis-server')
        subprocess.Popen(args)

    import redis
    if system == 'Windows':
        return redis.Redis()
    else:
        return redis.Redis(unix_socket_path=socket_path)


def get_x_ray_path(asin, book_path):
    x_ray_name = 'XRAY.entities.{}.asc'.format(asin)
    return Path(book_path).parent.joinpath(x_ray_name)


def create_x_ray_db(asin, book_path, r):
    if (x_ray_conn := check_db_file(get_x_ray_path(asin, book_path))) is None:
        return None
    x_ray_conn.executescript('''
    PRAGMA user_version = 1;

    CREATE TABLE book_metadata (
    srl INTEGER,
    erl INTEGER,
    has_images TINYINT,
    has_excerpts TINYINT,
    show_spoilers_default TINYINT,
    num_people INTEGER,
    num_terms INTEGER,
    num_images INTEGER,
    preview_images TEXT);

    CREATE TABLE bookmentions_entity (
    id INTEGER,
    asin TEXT,
    title TEXT,
    authors TEXT,
    description TEXT,
    ratings INTEGER,
    totalRatings INTEGER,
    type TEXT,
    PRIMARY KEY(id));

    CREATE TABLE bookmentions_occurrence (
    entity INTEGER,
    start INTEGER,
    length INTEGER);

    CREATE TABLE entity (
    id INTEGER,
    label TEXT,
    loc_label INTEGER,
    type INTEGER,
    count INTEGER,
    has_info_card TINYINT,
    PRIMARY KEY(id));
    CREATE INDEX idx_entity_type ON entity(type ASC);

    CREATE TABLE entity_description (
    text TEXT,
    source_wildcard TEXT,
    source INTEGER,
    entity INTEGER,
    PRIMARY KEY(entity));

    CREATE TABLE entity_excerpt (
    entity INTEGER,
    excerpt INTEGER);
    CREATE INDEX idx_entity_excerpt ON entity_excerpt(entity ASC);

    CREATE TABLE excerpt (
    id INTEGER,
    start INTEGER,
    length INTEGER,
    image TEXT,
    related_entities TEXT,
    goto INTEGER,
    PRIMARY KEY(id));

    CREATE TABLE occurrence (
    entity INTEGER,
    start INTEGER,
    length INTEGER);
    CREATE INDEX idx_occurrence_start ON occurrence(start ASC);

    CREATE TABLE source (
    id INTEGER,
    label INTEGER,
    url INTEGER,
    license_label INTEGER,
    license_url INTEGER,
    PRIMARY KEY(id));

    CREATE TABLE string (
    id INTEGER,
    language TEXT,
    text TEXT);

    CREATE TABLE type (
    id INTEGER,
    label INTEGER,
    singular_label INTEGER,
    icon INTEGER,
    top_mentioned_entities TEXT,
    PRIMARY KEY(id));

    INSERT INTO entity (id, loc_label, has_info_card) VALUES(0, 1, 0);
    INSERT INTO source (id, label, url) VALUES(0, 5, 20);
    INSERT INTO source VALUES(1, 6, 21, 7, 8);
    INSERT INTO source (id, label, url) VALUES(2, 4, 22);
    ''')

    for data in r.lrange('x_ray_string', 0, -1):
        x_ray_conn.execute('INSERT INTO string VALUES(?, ?, ?)',
                           tuple(data.decode('utf-8').split('|')))

    return x_ray_conn


def insert_x_book_metadata(conn, data):
    conn.execute('''
    INSERT INTO book_metadata (srl, erl, has_images, has_excerpts,
    show_spoilers_default, num_people, num_terms, num_images)
    VALUES(0, ?, 0, 0, 1, ?, ?, 0)
    ''', data)


def insert_x_entity(conn, data):
    conn.execute('''
    INSERT INTO entity (id, label, type, count, has_info_card)
    VALUES(?, ?, ?, ?, 1)
    ''', data)


def insert_x_entity_description(conn, data):
    conn.execute('INSERT INTO entity_description VALUES(?, ?, ?, ?)', data)


def insert_x_occurrence(conn, data):
    conn.execute('INSERT INTO occurrence VALUES(?, ?, ?)', data)


def insert_x_type(conn, data):
    conn.execute('INSERT INTO type VALUES(?, ?, ?, ?, ?)', data)
