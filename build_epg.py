#!/usr/bin/env python3

import gzip
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime, timedelta, timezone

# ============================================================
# НАСТРОЙКИ
# ============================================================

SOURCE = "http://s06.wsbof.com:8080/xml/b4a9c2c7.gz"

IDS_FILE = Path("channel_ids.txt")
OUTPUT = Path("epg.xml")

MISSING_FILE = Path("missing_ids.txt")
NO_PROGRAMME_FILE = Path("no_programme_ids.txt")

# Сколько часов программы хранить вперёд
HOURS_AHEAD = 12

# Небольшой запас назад.
# Нужен, чтобы сохранить передачу, которая уже началась,
# но всё ещё идёт.
HOURS_BACK = 2


# ============================================================
# ЧТЕНИЕ СПИСКА КАНАЛОВ
# ============================================================

wanted = {
    line.strip()
    for line in IDS_FILE.read_text(
        encoding="utf-8"
    ).splitlines()
    if line.strip()
    and not line.lstrip().startswith("#")
}

print(
    f"Каналов в плейлисте: {len(wanted)}"
)


# ============================================================
# СКАЧИВАНИЕ EPG
# ============================================================

print(
    f"Скачиваю EPG: {SOURCE}"
)

request = urllib.request.Request(
    SOURCE,
    headers={
        "User-Agent":
        "Mozilla/5.0 EPG-Updater/3.0"
    }
)

with urllib.request.urlopen(
    request,
    timeout=180
) as response:

    raw = response.read()

print(
    f"Скачано: "
    f"{len(raw) / 1024 / 1024:.2f} MB"
)


# ============================================================
# РАСПАКОВКА GZIP
# ============================================================

try:

    xml_data = gzip.decompress(raw)

except gzip.BadGzipFile:

    # Если источник неожиданно вернул
    # обычный XML вместо gzip
    xml_data = raw

print(
    f"XML после распаковки: "
    f"{len(xml_data) / 1024 / 1024:.2f} MB"
)


# ============================================================
# ЧТЕНИЕ XML
# ============================================================

root = ET.fromstring(xml_data)

# Создаём новый облегчённый XMLTV
new_root = ET.Element(
    "tv",
    root.attrib
)

matched_channels = set()


# ============================================================
# КАНАЛЫ
# ============================================================

for channel in root.findall("channel"):

    channel_id = channel.get(
        "id",
        ""
    )

    if channel_id not in wanted:
        continue

    # Создаём облегчённую запись канала
    new_channel = ET.Element(
        "channel",
        {
            "id": channel_id
        }
    )

    # Оставляем display-name.
    # Логотипы каналов специально не копируем,
    # чтобы уменьшить XML.
    display_names = channel.findall(
        "display-name"
    )

    for display_name in display_names:

        new_display_name = ET.SubElement(
            new_channel,
            "display-name",
            display_name.attrib
        )

        new_display_name.text = (
            display_name.text or ""
        )

    new_root.append(
        new_channel
    )

    matched_channels.add(
        channel_id
    )


# ============================================================
# РАБОТА СО ВРЕМЕНЕМ XMLTV
# ============================================================

def parse_xmltv_time(value):

    if not value:
        return None

    try:

        # XMLTV обычно выглядит так:
        #
        # 20260719123000 +0300

        value = value.strip()

        date_part = value[:14]

        dt = datetime.strptime(
            date_part,
            "%Y%m%d%H%M%S"
        )

        parts = value.split()

        if len(parts) > 1:

            offset = parts[1]

            sign = (
                1
                if offset[0] == "+"
                else -1
            )

            hours = int(
                offset[1:3]
            )

            minutes = int(
                offset[3:5]
            )

            tz = timezone(
                sign * timedelta(
                    hours=hours,
                    minutes=minutes
                )
            )

            dt = dt.replace(
                tzinfo=tz
            )

        else:

            dt = dt.replace(
                tzinfo=timezone.utc
            )

        return dt.astimezone(
            timezone.utc
        )

    except Exception:

        return None


# ============================================================
# ВРЕМЕННОЙ ДИАПАЗОН
# ============================================================

now = datetime.now(
    timezone.utc
)

start_limit = (
    now
    - timedelta(
        hours=HOURS_BACK
    )
)

end_limit = (
    now
    + timedelta(
        hours=HOURS_AHEAD
    )
)

print(
    "Фильтр EPG:"
)

print(
    f"  назад: {HOURS_BACK} ч."
)

print(
    f"  вперёд: {HOURS_AHEAD} ч."
)


# ============================================================
# ПРОГРАММЫ
# ============================================================

programme_count = 0

programme_channels = set()

skipped_old = 0
skipped_future = 0
skipped_invalid = 0


for programme in root.findall(
    "programme"
):

    channel_id = programme.get(
        "channel",
        ""
    )

    # Только наши каналы
    if channel_id not in matched_channels:

        continue


    start_text = programme.get(
        "start"
    )

    stop_text = programme.get(
        "stop"
    )

    start = parse_xmltv_time(
        start_text
    )

    stop = parse_xmltv_time(
        stop_text
    )


    # Без корректного start
    # запись использовать нельзя
    if start is None:

        skipped_invalid += 1

        continue


    # ----------------------------------------
    # УДАЛЯЕМ СТАРЫЕ ПЕРЕДАЧИ
    # ----------------------------------------

    if stop is not None:

        # Если передача закончилась
        # раньше допустимого диапазона
        if stop < start_limit:

            skipped_old += 1

            continue

    else:

        # Если stop отсутствует,
        # ориентируемся на start
        if start < start_limit:

            skipped_old += 1

            continue


    # ----------------------------------------
    # УДАЛЯЕМ СЛИШКОМ ДАЛЁКИЕ ПЕРЕДАЧИ
    # ----------------------------------------

    if start > end_limit:

        skipped_future += 1

        continue


    # ========================================================
    # СОЗДАЁМ МИНИМАЛЬНУЮ ЗАПИСЬ PROGRAMME
    # ========================================================

    attributes = {
        "start": start_text,
        "channel": channel_id
    }

    if stop_text:

        attributes["stop"] = (
            stop_text
        )


    new_programme = ET.Element(
        "programme",
        attributes
    )


    # ========================================================
    # ОСТАВЛЯЕМ ТОЛЬКО TITLE
    # ========================================================

    titles = programme.findall(
        "title"
    )

    if titles:

        for title in titles:

            new_title = ET.SubElement(
                new_programme,
                "title",
                title.attrib
            )

            new_title.text = (
                title.text or ""
            )

    else:

        # На случай передачи без title
        new_title = ET.SubElement(
            new_programme,
            "title"
        )

        new_title.text = "Программа"


    # НЕ копируем:
    #
    # desc
    # category
    # icon
    # credits
    # episode-num
    # rating
    # star-rating
    # country
    # date
    # sub-title
    #
    # Это сильно уменьшает размер XML.


    new_root.append(
        new_programme
    )

    programme_count += 1

    programme_channels.add(
        channel_id
    )


# ============================================================
# КАНАЛЫ, КОТОРЫХ НЕТ В ИСТОЧНИКЕ
# ============================================================

missing_channels = sorted(
    wanted
    - matched_channels
)

MISSING_FILE.write_text(

    "\n".join(
        missing_channels
    )

    + (
        "\n"
        if missing_channels
        else ""
    ),

    encoding="utf-8"
)


# ============================================================
# КАНАЛЫ БЕЗ ПРОГРАММЫ
# ============================================================

no_programme_channels = sorted(

    matched_channels
    - programme_channels
)

NO_PROGRAMME_FILE.write_text(

    "\n".join(
        no_programme_channels
    )

    + (
        "\n"
        if no_programme_channels
        else ""
    ),

    encoding="utf-8"
)


# ============================================================
# СОХРАНЕНИЕ XML
# ============================================================

tree = ET.ElementTree(
    new_root
)

tree.write(
    OUTPUT,
    encoding="utf-8",
    xml_declaration=True,
    short_empty_elements=True
)


# ============================================================
# РАЗМЕР ГОТОВОГО ФАЙЛА
# ============================================================

output_size = (
    OUTPUT.stat().st_size
    / 1024
    / 1024
)


# ============================================================
# ОТЧЁТ
# ============================================================

print()
print(
    "================================"
)

print(
    f"Каналов запрошено: "
    f"{len(wanted)}"
)

print(
    f"Каналов найдено: "
    f"{len(matched_channels)}"
)

print(
    f"Каналов отсутствует: "
    f"{len(missing_channels)}"
)

print(
    f"Каналов с программой: "
    f"{len(programme_channels)}"
)

print(
    f"Каналов без программы: "
    f"{len(no_programme_channels)}"
)

print(
    f"Передач сохранено: "
    f"{programme_count}"
)

print(
    f"Старых передач удалено: "
    f"{skipped_old}"
)

print(
    f"Дальних передач удалено: "
    f"{skipped_future}"
)

print(
    f"Некорректных записей: "
    f"{skipped_invalid}"
)

print(
    f"EPG назад: "
    f"{HOURS_BACK} часа"
)

print(
    f"EPG вперёд: "
    f"{HOURS_AHEAD} часов"
)

print(
    f"Размер готового epg.xml: "
    f"{output_size:.2f} MB"
)

print(
    "================================"
)
