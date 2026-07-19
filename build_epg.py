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

# Оставляем текущую передачу
# + программу на 7 часов вперёд
HOURS_AHEAD = 7

# Коррекция отображаемого времени:
TIME_CORRECTION_HOURS = 0


# ============================================================
# ЧИТАЕМ 399 TVG-ID
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
# СКАЧИВАЕМ EPG
# ============================================================

print(
    f"Скачиваю EPG: {SOURCE}"
)

request = urllib.request.Request(
    SOURCE,
    headers={
        "User-Agent":
        "Mozilla/5.0 EPG-Updater/4.0"
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
# РАСПАКОВЫВАЕМ GZIP
# ============================================================

try:

    xml_data = gzip.decompress(raw)

except gzip.BadGzipFile:

    xml_data = raw

print(
    f"XML после распаковки: "
    f"{len(xml_data) / 1024 / 1024:.2f} MB"
)


# ============================================================
# ЧИТАЕМ XML
# ============================================================

root = ET.fromstring(xml_data)

new_root = ET.Element(
    "tv",
    root.attrib
)

matched_channels = set()


# ============================================================
# ДОБАВЛЯЕМ ТОЛЬКО НАШИ 399 КАНАЛОВ
# ============================================================

for channel in root.findall("channel"):

    channel_id = channel.get(
        "id",
        ""
    )

    if channel_id not in wanted:
        continue

    new_channel = ET.Element(
        "channel",
        {
            "id": channel_id
        }
    )

    # Оставляем только название канала.
    # Иконки и прочее удаляем для уменьшения XML.

    display_names = channel.findall(
        "display-name"
    )

    if display_names:

        for display_name in display_names:

            new_display_name = ET.SubElement(
                new_channel,
                "display-name",
                display_name.attrib
            )

            new_display_name.text = (
                display_name.text or ""
            )

    else:

        new_display_name = ET.SubElement(
            new_channel,
            "display-name"
        )

        new_display_name.text = channel_id

    new_root.append(
        new_channel
    )

    matched_channels.add(
        channel_id
    )


# ============================================================
# ФУНКЦИЯ ЧТЕНИЯ ВРЕМЕНИ XMLTV
# ============================================================

def parse_xmltv_time(value):

    if not value:
        return None

    try:

        value = value.strip()

        # Например:
        # 20260719183000 +0300

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

end_limit = (
    now
    + timedelta(
        hours=HOURS_AHEAD
    )
)

print()
print("Фильтр EPG:")

print(
    "  прошлые передачи: удаляем"
)

print(
    "  текущая передача: оставляем"
)

print(
    f"  вперёд: {HOURS_AHEAD} часов"
)

print(
    f"  коррекция времени: "
    f"{TIME_CORRECTION_HOURS} часов"
)


# ============================================================
# ОБРАБАТЫВАЕМ ПРОГРАММЫ
# ============================================================

programme_count = 0

programme_channels = set()

current_programmes = 0
future_programmes = 0

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


    # Нужен корректный start
    if start is None:

        skipped_invalid += 1

        continue


    # ========================================================
    # ОПРЕДЕЛЯЕМ ТЕКУЩУЮ ПЕРЕДАЧУ
    # ========================================================

    is_current = False

    if stop is not None:

        if start <= now < stop:

            is_current = True


    # ========================================================
    # ТЕКУЩУЮ ПЕРЕДАЧУ ВСЕГДА ОСТАВЛЯЕМ
    # ========================================================

    if is_current:

        current_programmes += 1


    else:

        # ====================================================
        # ВСЕ ПРОШЕДШИЕ ПЕРЕДАЧИ УДАЛЯЕМ
        # ====================================================

        if start < now:

            skipped_old += 1

            continue


        # ====================================================
        # ОСТАВЛЯЕМ ТОЛЬКО БЛИЖАЙШИЕ 7 ЧАСОВ
        # ====================================================

        if start > end_limit:

            skipped_future += 1

            continue

        future_programmes += 1


    # ========================================================
    # КОРРЕКЦИЯ ВРЕМЕНИ -6 ЧАСОВ
    #
    # ВАЖНО:
    # сначала мы определили текущую передачу
    # по реальному времени источника,
    # и только теперь меняем отображаемое время.
    # ========================================================

    corrected_start = (
        start
        + timedelta(
            hours=TIME_CORRECTION_HOURS
        )
    )

    attributes = {

        "start":
        corrected_start.strftime(
            "%Y%m%d%H%M%S +0000"
        ),

        "channel":
        channel_id
    }


    if stop is not None:

        corrected_stop = (
            stop
            + timedelta(
                hours=TIME_CORRECTION_HOURS
            )
        )

        attributes["stop"] = (
            corrected_stop.strftime(
                "%Y%m%d%H%M%S +0000"
            )
        )


    # ========================================================
    # СОЗДАЁМ МИНИМАЛЬНЫЙ PROGRAMME
    # ========================================================

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

        new_title = ET.SubElement(
            new_programme,
            "title"
        )

        new_title.text = "Программа"


    # НЕ КОПИРУЕМ:
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
    # Это максимально облегчает EPG.


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
# СОХРАНЯЕМ EPG.XML
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

output_size_mb = (
    OUTPUT.stat().st_size
    / 1024
    / 1024
)


# ============================================================
# ИТОГОВЫЙ ОТЧЁТ
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
    f"Текущих передач сохранено: "
    f"{current_programmes}"
)

print(
    f"Будущих передач сохранено: "
    f"{future_programmes}"
)

print(
    f"Всего передач сохранено: "
    f"{programme_count}"
)

print(
    f"Прошедших передач удалено: "
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
    f"EPG: текущая передача "
    f"+ {HOURS_AHEAD} часов вперёд"
)

print(
    f"Коррекция времени: "
    f"{TIME_CORRECTION_HOURS} часов"
)

print(
    f"Размер готового epg.xml: "
    f"{output_size_mb:.2f} MB"
)

print(
    "================================"
)
