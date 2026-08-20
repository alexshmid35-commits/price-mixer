import re
from pathlib import Path

import gspread
from oauth2client.service_account import ServiceAccountCredentials

from onliner_to_sheets import JSON_KEY_FILE, SPREADSHEET_ID, SHEET_TAB, slug_to_title


def authorize_google_sheets():
    if not Path(JSON_KEY_FILE).exists():
        raise FileNotFoundError(f"Файл ключа Google не найден: {JSON_KEY_FILE}")
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = ServiceAccountCredentials.from_json_keyfile_name(str(JSON_KEY_FILE), scope)
    client = gspread.authorize(creds)
    return client.open_by_key(SPREADSHEET_ID).worksheet(SHEET_TAB)


def extract_slug_from_url(url):
    if not url:
        return ""
    m = re.search(r"https?://catalog\.onliner\.by/([^/]+)/", str(url))
    return m.group(1).strip().lower() if m else ""


def extract_slug_from_category_text(category_text):
    text = str(category_text or "").strip().lower()
    if not text:
        return ""
    m = re.fullmatch(r"(?:категория:\s*)?([a-z0-9_]+)", text)
    return m.group(1) if m else ""


def normalize_sheet_categories():
    sheet = authorize_google_sheets()
    rows = sheet.get_all_values()
    if len(rows) <= 1:
        print("Лист пустой или содержит только заголовок.")
        return

    # Колонка A = category, F = url.
    new_col_a = []
    changed = 0
    unchanged = 0
    unresolved = 0

    for row in rows[1:]:
        old_category = row[0] if len(row) > 0 else ""
        url = row[5] if len(row) > 5 else ""

        slug = extract_slug_from_url(url)
        if not slug:
            slug = extract_slug_from_category_text(old_category)

        if slug:
            new_category = slug_to_title(slug)
        else:
            new_category = old_category
            unresolved += 1

        if new_category != old_category:
            changed += 1
        else:
            unchanged += 1

        new_col_a.append([new_category])

    end_row = len(rows)
    sheet.update(range_name=f"A2:A{end_row}", values=new_col_a, value_input_option="RAW")

    print(f"Готово. Обновлено строк: {changed}")
    print(f"Без изменений: {unchanged}")
    print(f"Не удалось определить slug: {unresolved}")


if __name__ == "__main__":
    normalize_sheet_categories()
