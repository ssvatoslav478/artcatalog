import json
from html import escape
from pathlib import Path


def caption(p):
    return (f"<b>Робота учасника №{p['id']:03d}</b>\n"
            f"{escape(p['name'])} / {escape(p['age'])}\n"
            f"{escape(p['school'])}\n{escape(p['city'])}\n\n"
            f"{escape(p['about'])}\n\n<b>{escape(p['title'])}</b>\n"
            f"{escape(p['description'])}")


def load_catalog(path):
    path = Path(path)
    records = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(records, list):
        raise ValueError('participants.json должен содержать массив')
    seen = set()
    for p in records:
        if type(p.get('id')) is not int or not 0 < p['id'] < 10**9 or p['id'] in seen:
            raise ValueError('ID участников должны быть уникальными положительными числами')
        seen.add(p['id'])
        for key in ('name', 'age', 'school', 'city', 'about', 'title', 'description', 'image'):
            if not isinstance(p.get(key), str) or not p[key].strip():
                raise ValueError(f"Участник {p['id']}: заполните {key}")
        if len(caption(p).encode('utf-16-le')) // 2 > 1000:
            raise ValueError(f"Участник {p['id']}: сократите текст карточки")
        image = (path.parent / p['image']).resolve()
        if not image.is_relative_to(path.parent.resolve()) or not image.is_file():
            raise ValueError(f"Участник {p['id']}: рисунок должен находиться внутри папки бота")
        if image.suffix.lower() not in ('.jpg', '.jpeg', '.png') or image.stat().st_size > 10_000_000:
            raise ValueError('Рисунок: JPG/PNG, не более 10 MB')
        p['image'] = str(image)
    return sorted(records, key=lambda p: p['id'])
