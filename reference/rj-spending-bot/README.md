# RIDE&JOY Finance Bot — Инструкция по установке

## Структура проекта
```
rjbot/
├── bot.py                 # точка входа
├── config.py              # настройки (токены, имена, байки)
├── requirements.txt
├── rjbot.service          # systemd
├── credentials.json       # Google сервисный аккаунт (создать отдельно)
├── handlers/
│   ├── common.py          # /start, отмена
│   ├── expenses.py        # флоу расходов
│   ├── fuel.py            # флоу заправок
│   ├── income.py          # флоу приходов
│   └── manager.py         # панель менеджера
├── keyboards/
│   └── kb.py              # все клавиатуры
└── utils/
    └── sheets.py          # Google Sheets API
```

---

## Шаг 1 — Создать бота в Telegram

1. Открой @BotFather → `/newbot`
2. Дай имя и username
3. Скопируй токен → вставь в `config.py` → `BOT_TOKEN`

---

## Шаг 2 — Google Sheets API

### 2.1 Создать сервисный аккаунт
1. Перейди на https://console.cloud.google.com
2. Создай проект (или используй существующий)
3. APIs & Services → Enable APIs → включи **Google Sheets API** и **Google Drive API**
4. Credentials → Create Credentials → **Service Account**
5. Дай имя, нажми Create
6. На странице сервисного аккаунта → Keys → Add Key → JSON
7. Скачанный файл переименуй в `credentials.json` и положи в папку `rjbot/`

### 2.2 Создать Google Таблицу
1. Создай новую таблицу на Google Drive
2. Из URL скопируй ID (часть между `/d/` и `/edit`):
   `https://docs.google.com/spreadsheets/d/**ВОТ_ЭТО**/edit`
3. Вставь в `config.py` → `SPREADSHEET_ID`
4. Открой таблицу → поделись с email сервисного аккаунта (из credentials.json → `client_email`) с правами **Редактора**

---

## Шаг 3 — Заполнить config.py

```python
# Найти Telegram ID сотрудников: пусть каждый напишет @userinfobot
EMPLOYEES = {
    111111111: "Кирилл",   # ← реальные ID
    222222222: "Иван",
}

MANAGERS = {
    123456789,  # ← твой ID
}

# Добавь свои байки
BIKES = [
    "Honda CB500",
    "Yamaha MT-07",
    ...
]
```

---

## Шаг 4 — Деплой на VPS

```bash
# Загрузи файлы на сервер
scp -r rjbot/ ubuntu@YOUR_VPS_IP:/home/ubuntu/

# Подключись к серверу
ssh ubuntu@YOUR_VPS_IP

# Создай виртуальное окружение
cd /home/ubuntu/rjbot
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Проверь что всё работает
python bot.py
# (Ctrl+C для остановки)
```

### Установка как systemd-сервис

```bash
# Отредактируй rjbot.service — вставь BOT_TOKEN
nano rjbot.service

# Скопируй в systemd
sudo cp rjbot.service /etc/systemd/system/

# Запусти
sudo systemctl daemon-reload
sudo systemctl enable rjbot
sudo systemctl start rjbot

# Проверь статус
sudo systemctl status rjbot

# Логи
journalctl -u rjbot -f
```

---

## Структура Google Таблицы

После первого запуска бот автоматически создаст заголовки.

### Лист «Расходы»
| ID | Тип | Дата | Имя | Место покупки | Что купил | Кол-во | Для чего | Комментарий | Фото | Статус | Комментарий менеджера |

### Лист «Приход»
| ID | Дата прихода | За что | Имя клиента | Нал/Безнал | Комментарий | Статус | Комментарий менеджера |

---

## Как пользоваться

### Сотрудник
- `/start` — авторизация и главное меню
- **💸 Расходы** — внести покупку
- **⛽ Заправка** — внести заправку
- **💰 Приход** — внести поступление
- **📋 Мои записи** — просмотреть и отредактировать свои последние 5 записей

### Менеджер (ты)
- **👔 Менеджер** — панель управления
- **📊 Новые расходы / приходы** — список новых записей с кнопками
- На каждой записи: ✅ Принять / ❌ Отклонить / 💬 Комментарий / ✏️ Редактировать
- **🔍 Найти запись** — поиск по ID

---

## Добавление нового сотрудника

1. Попроси его написать @userinfobot — узнать свой ID
2. Добавь в `config.py`:
   ```python
   EMPLOYEES = {
       ...,
       999999999: "Новый сотрудник",
   }
   ```
3. Перезапусти бота:
   ```bash
   sudo systemctl restart rjbot
   ```
