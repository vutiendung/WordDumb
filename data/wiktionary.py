#!/usr/bin/env python3

import json
import pickle
import re

CJK_LANGS = ["zh", "ja", "ko"]
POS_TYPES = ["adj", "adv", "noun", "phrase", "proverb", "verb"]


def download_wiktionary(download_folder, source_language, useragent, notif):
    if not download_folder.exists():
        download_folder.mkdir()
    filename_lang = re.sub(r"[\s-]", "", source_language)
    filename = f"kaikki.org-dictionary-{filename_lang}.json"
    download_path = download_folder.joinpath(filename)
    if not download_path.exists():
        import requests

        with requests.get(
            f"https://kaikki.org/dictionary/{source_language}/{filename}",
            stream=True,
            headers={"user-agent": useragent},
        ) as r, open(download_path, "wb") as f:
            total_len = int(r.headers.get("content-length", 0))
            chunk_size = 2**23
            total_chunks = total_len // chunk_size + 1
            chunk_count = 0
            for chunk in r.iter_content(chunk_size):
                f.write(chunk)
                if notif and total_len > 0:
                    chunk_count += 1
                    notif.put(
                        (
                            chunk_count / total_chunks,
                            f"Downloading {source_language} Wiktionary",
                        )
                    )

    return download_path


FILTER_TAGS = frozenset(
    {"plural", "alternative", "obsolete", "abbreviation", "initialism"}
)


def extract_wiktionary(download_path, lang, kindle_lemmas, notif):
    if notif:
        notif.put((0, "Extracting Wiktionary file"))
    words = []
    enabled_words = set()
    len_limit = 2 if lang in CJK_LANGS else 3
    with open(download_path, encoding="utf-8") as f:
        for line in f:
            data = json.loads(line)
            word = data.get("word")
            pos = data.get("pos")
            if (
                pos not in POS_TYPES
                or len(word) < len_limit
                or re.match(r"\W|\d", word)
            ):
                continue
            if lang in CJK_LANGS and re.fullmatch(r"[a-zA-Z\d]+", word):
                continue

            enabled = False if word in enabled_words else True
            if kindle_lemmas and enabled:
                enabled = word in kindle_lemmas
            if enabled:
                enabled_words.add(word)
            forms = set()
            for form in map(lambda x: x.get("form"), data.get("forms", [])):
                if form and form not in enabled_words and len(form) >= len_limit:
                    forms.add(form)

            for sense in data.get("senses", []):
                examples = sense.get("examples", [])
                glosses = sense.get("glosses")
                example_sent = None
                if not glosses:
                    continue
                tags = set(sense.get("tags", []))
                if tags.intersection(FILTER_TAGS):
                    continue
                for example in examples:
                    example = example.get("text")
                    if example and example != "(obsolete)":
                        example_sent = example
                        break
                short_gloss = short_def(glosses[0])
                if short_gloss == "of":
                    continue
                words.append(
                    (
                        enabled,
                        word,
                        short_gloss,
                        glosses[0],
                        example_sent,
                        ",".join(forms),
                        get_ipas(lang, data.get("sounds", [])),
                    )
                )
                enabled = False

    download_path.unlink()
    words.sort(key=lambda x: x[1])
    with open(
        download_path.with_name(f"wiktionary_{lang}.json"), "w", encoding="utf-8"
    ) as f:
        json.dump(words, f)


def get_ipas(lang, sounds):
    ipas = {}
    if lang == "en":
        for sound in sounds:
            if "ipa" in sound and "tags" in sound:
                if "US" in sound["tags"] and "US" not in ipas:
                    ipas["US"] = sound["ipa"]
                if "UK" in sound["tags"] and "UK" not in ipas:
                    ipas["UK"] = sound["ipa"]
    elif lang == "zh":
        for sound in sounds:
            if "zh-pron" in sound and "standard" in sound.get("tags", []):
                if "Pinyin" in sound["tags"] and "Pinyin" not in ipas:
                    ipas["Pinyin"] = sound["zh-pron"]
                elif "bopomofo" in sound["tags"] and "bopomofo" not in ipas:
                    ipas["bopomofo"] = sound["zh-pron"]
    else:
        for sound in sounds:
            if "ipa" in sound:
                return sound["ipa"]

    return ipas if ipas else ""


def dump_wiktionary(json_path, dump_path, lang, notif):
    if notif:
        notif.put((0, "Converting Wiktionary file"))

    with open(json_path, encoding="utf-8") as f:
        words = json.load(f)

    if lang in CJK_LANGS:
        import ahocorasick

        automaton = ahocorasick.Automaton()
        for _, word, short_gloss, gloss, example, forms, ipa in filter(
            lambda x: x[0] and not automaton.exists(x[1]), words
        ):
            automaton.add_word(word, (word, short_gloss, gloss, example, ipa))
            for form in filter(lambda x: not automaton.exists(x), forms.split(",")):
                automaton.add_word(form, (form, short_gloss, gloss, example, ipa))

        automaton.make_automaton()
        automaton.save(str(dump_path), pickle.dumps)
    else:
        from flashtext import KeywordProcessor

        keyword_processor = KeywordProcessor()
        for _, word, short_gloss, gloss, example, forms, ipa in filter(
            lambda x: x[0] and x[1] not in keyword_processor, words
        ):
            keyword_processor.add_keyword(word, (short_gloss, gloss, example, ipa))
            for form in filter(lambda x: x not in keyword_processor, forms.split(",")):
                keyword_processor.add_keyword(form, (short_gloss, gloss, example, ipa))

        with open(dump_path, "wb") as f:
            pickle.dump(keyword_processor, f)


def short_def(gloss: str) -> str:
    gloss = gloss[0].lower() + gloss[1:]
    gloss = gloss.removesuffix(".")
    gloss = re.sub(r"\([^)]+\)", "", gloss)
    gloss = re.split(r"[;,]", gloss, 1)[0]
    return gloss.strip()


def download_and_dump_wiktionary(
    json_path, dump_path, lang, kindle_lemmas, useragent, notif
):
    if useragent:
        download_path = download_wiktionary(
            json_path.parent, lang["kaikki"], useragent, notif
        )
        extract_wiktionary(download_path, lang["wiki"], kindle_lemmas, notif)
    if dump_path:
        dump_wiktionary(json_path, dump_path, lang["wiki"], notif)
