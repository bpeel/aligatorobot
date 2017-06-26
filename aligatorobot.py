#!/usr/bin/python3

# Aligatorobot - A Telegram robot for automatically adding links to
#                Google Translate
# Copyright (C) 2017  Neil Roberts
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import urllib.request
import urllib.parse
import json
import io
import sys
import time
import os
import re
import langdetect

conf_dir = os.path.expanduser("~/.aligatorobot")
conf_file = os.path.join(conf_dir, "config")
update_id_file = os.path.join(conf_dir, "update_id")

conf_keys = ["api_key", "target_language"]
optional_keys = ["skip_languages"]
conf = {}

with open(conf_file, 'r', encoding='utf-8') as f:
    for line_num, line in enumerate(f):
        if re.match(r'^\s*(#|$)', line):
            continue

        md = re.match(r'^\s*([a-z_]+)\s*=\s*(\S+)\s*$', line)

        if md is None:
            print("{}:{}: bad line".format(conf_file, line_num + 1),
                  file=sys.stderr)
            sys.exit(1)

        key = md.group(1)
        value = md.group(2)

        if key not in conf_keys and key not in optional_keys:
            print("{}:{}: unknown option: {}".format(conf_file,
                                                     line_num + 1,
                                                     key),
                  file=sys.stderr)
            sys.exit(1)

        conf[md.group(1)] = value

for key in conf_keys:
    if key not in conf:
        print("{}: missing option: {}".format(conf_file, key),
              file=sys.stderr)
        sys.exit(1)

if "skip_languages" in conf:
    skip_languages = conf["skip_languages"].split(',')
else:
    skip_languages = []

target_language = conf["target_language"]
api_key = conf["api_key"]

urlbase = "https://api.telegram.org/bot" + api_key + "/"
get_updates_url = urlbase + "getUpdates"
send_message_url = urlbase + "sendMessage"

try:
    with open(update_id_file, 'r', encoding='utf-8') as f:
        last_update_id = int(f.read().rstrip())
except FileNotFoundError:
    last_update_id = None

class GetUpdatesException(Exception):
    pass

class ProcessCommandException(Exception):
    pass

langdetect_factory = langdetect.DetectorFactory()
langdetect_factory.load_profile(langdetect.PROFILES_DIRECTORY)

def send_message(args):
    try:
        req = urllib.request.Request(send_message_url,
                                     json.dumps(args).encode('utf-8'))
        req.add_header('Content-Type', 'application/json; charset=utf-8')
        rep = json.load(io.TextIOWrapper(urllib.request.urlopen(req), 'utf-8'))
    except urllib.error.URLError as e:
        raise ProcessCommandException(e)
    except json.JSONDecodeError as e:
        raise ProcessCommandException(e)

    try:
        if rep['ok'] is not True:
            raise ProcessCommandException("Unexpected response from "
                                          "sendMessage request")
    except KeyError as e:
        raise ProcessCommandException(e)

def send_reply(message, source_lang, target_lang):
    reply = ("<a href=\"http://translate.google.com/#{0}/{1}/{2}\">{0}→{1}</a>"
             .format(source_lang,
                     target_lang,
                     urllib.parse.quote(message['text'])))
    send_message({ 'chat_id' : message['chat']['id'],
                   'text' : reply,
                   'disable_web_page_preview' : True,
                   'parse_mode' : 'HTML' })

def save_last_update_id(last_update_id):
    with open(update_id_file, 'w', encoding='utf-8') as f:
        print(last_update_id, file=f)

def is_valid_update(update, last_update_id):
    try:
        update_id = update["update_id"]
        if not isinstance(update_id, int):
            raise GetUpdatesException("Unexpected response from getUpdates "
                                      "request")
        if last_update_id is not None and update_id <= last_update_id:
            return False

        if 'message' not in update:
            return False

        message = update['message']

        if 'chat' not in message or 'text' not in message:
            return False

    except KeyError as e:
        raise GetUpdatesException(e)

    return True

def get_updates(last_update_id):
    args = {
        'allowed_updates': ['message']
    }

    if last_update_id is not None:
        args['offset'] = last_update_id + 1

    try:
        req = urllib.request.Request(get_updates_url,
                                     json.dumps(args).encode('utf-8'))
        req.add_header('Content-Type', 'application/json; charset=utf-8')
        rep = json.load(io.TextIOWrapper(urllib.request.urlopen(req), 'utf-8'))
    except urllib.error.URLError as e:
        raise GetUpdatesException(e)
    except json.JSONDecodeError as e:
        raise GetUpdatesException(e)

    try:
        if rep['ok'] is not True or not isinstance(rep['result'], list):
            raise GetUpdatesException("Unexpected response from getUpdates "
                                      "request")
    except KeyError as e:
        raise GetUpdatesException(e)
        
    updates = [x for x in rep['result'] if is_valid_update(x, last_update_id)]
    updates.sort(key = lambda x: x['update_id'])
    return updates

while True:
    try:
        updates = get_updates(last_update_id)
    except GetUpdatesException as e:
        print("{}".format(e), file=sys.stderr)
        # Delay for a bit before trying again to avoid DOSing the server
        time.sleep(60)
        continue

    for update in updates:
        last_update_id = update['update_id']
        message = update['message']

        detector = langdetect_factory.create()
        detector.append(message['text'])
        language = detector.detect()

        if language != target_language and language not in skip_languages:
            send_reply(message, language, target_language)

        save_last_update_id(last_update_id)
