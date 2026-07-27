# RIDE&JOY Bot — Руководство супер-менеджера (Flash & Valori)

Полная пошаговая инструкция по всем функциям бота для **супер-админов** (`superadmin: True` — Flash и Valori).

**Язык интерфейса бота:** English (кнопки и сообщения).  
**Часовой пояс:** WITA (UTC+8, Бали).

> **RJ manager** видит панель менеджера, но **без** GPS, статистики, удаления/редактирования записей, календаря и т.д. Это руководство — только для Flash и Valori.

---

## Содержание

1. [Начало работы](#1-начало-работы)
2. [Два меню: главное и менеджера](#2-два-меню)
3. [Финансовая логика](#3-финансовая-логика)
4. [Главное меню — все функции](#4-главное-меню)
5. [Панель менеджера — общие функции](#5-панель-менеджера)
6. [Супер-админ: GPS и байки](#6-супер-админ-gps-и-байки)
7. [Супер-админ: аналитика](#7-супер-админ-аналитика)
8. [Супер-админ: календарь и расписание](#8-супер-админ-календарь-и-расписание)
9. [Аренда мотоциклов (Bike Rental)](#9-аренда-мотоциклов)
10. [Справочник: куда уходят уведомления](#10-куда-уходят-уведомления)

---

## 1. Начало работы

1. Откройте бота в **личном чате** (private), не в группе.
2. Отправьте **`/start`**.
3. Появится **главное меню** и приветствие с вашим именем.

**Навигация в любом пошаговом процессе:**
- **⬅️ Back** — предыдущий шаг  
- **❌ Cancel** — отмена, возврат в главное меню  
- **« Main menu** — сброс и главное меню (из панели менеджера)

---

## 2. Два меню

### Главное меню
Те же кнопки, что у инструкторов (Alex, Ray), **плюс** для вас:
- при записи расходов/дохода/топлива — выбор **группы** и **имени** сотрудника;
- **📋 My records** — записи любого сотрудника или всех;
- **🗓 My schedule** — расписание Alex / Ray / All.

### Панель менеджера — **👔 Manager**

| Кнопка | Кто видит |
|--------|-----------|
| 📋 Pending expenses / income | Все менеджеры |
| 💼 All balances | Все менеджеры |
| 💸 Pay expense / 💰 Receive income | Все менеджеры |
| 💬 Add comment | Все менеджеры |
| 🏍 Bike Rental | Все менеджеры |
| 🗑 Delete record / ✏️ Edit record | **Только superadmin** |
| GPS, статистика, календарь… | **Только superadmin** |
| « Main menu | Все |

---

## 3. Финансовая логика

### 💸 Spendings (к возмещению)
Расходы с **My pocket** с момента последнего **Expense payout** (выплата расходов менеджером).

### 💰 Cash on hand (нал на руках)
**Income** (наличные) минус расходы с **Cash on hand** с момента последнего **Income handover** (сдача наличных) или **Transfer to colleague**.

### Payment source (расходы и топливо)
| Вариант | Эффект |
|---------|--------|
| **My pocket** | Увеличивает spendings (менеджер потом возмещает) |
| **Cash on hand** | Уменьшает нал, который держит сотрудник |

### Payouts (лист Payouts в таблице)
| Тип | Значение |
|-----|----------|
| **Expense payout** | Менеджер выплатил расходы сотруднику → spendings обнуляются (с даты выплаты) |
| **Income handover** | Сотрудник сдал наличные компании → cash on hand обнуляется |
| **Transfer to colleague** | Передача наличных между коллегами (отправитель — handover, получатель — income) |

---

## 4. Главное меню

### 4.1 💸 Expenses (ручной расход)

**Старт для менеджера (не сотрудника):**
1. **👥 Send to which group?** — группа Alex, Ray или Manager group  
2. **👤 Record under whose name?** — Flash, Valori, Alex, Ray и т.д.

**Дальше по шагам:**
1. **📅 Дата** — календарь  
2. **📂 Category** — Bike service, Aqua, Taxi, Tires…, Other  
3. **🎯 Purpose** — Rental / Lesson / Office / Other (Rental → выбор байка для Rental ID)  
4. **🏍 Bike** — если нужен (Bike service, Tires, Rental)  
5. **🏪 Place** — название магазина  
6. **💵 Amount** — сумма IDR  
7. **💳 Paid from** — My pocket / Cash on hand  
8. **🔢 Mileage** — для Bike service и Tires (не меньше предыдущего)  
9. **💬 Comment** — что сделано/куплено (service log); Skip — ок  
10. **📸 Receipt** — фото чека → **AI читает чек**  
    - Comment пустой → подставит items с чека  
    - Comment отличается → **Keep mine / Use receipt / Append both**  
    - Сумма на чеке ≠ введённой → только предупреждение  
11. **📸 Item photo** — фото покупки (или Skip)  
12. **✅ Confirm** — сохранение в Expenses + уведомление в выбранную группу + Drive

---

### 4.2 🧾 Add expense (AI)

Отдельный поток: **сначала чек**, потом остальное.

1. (Для менеджера) группа + имя — как выше  
2. **📅 Date**  
3. **🎯 Purpose** (+ байк если Rental)  
4. **📂 Category**  
5. **🏍 Bike** — если Bike service / Tires / Bensin  
6. **📸 Receipt photo** → AI: place, items, amount, date  
   - Нечитаемо → ручной ввод суммы  
   - **Confirm / Edit / Retake photo**  
7. **💳 Payment source**  
8. **🔢 Mileage** — если Bike service / Tires  
9. **📸 Item photo**  
10. **✅ Final confirm**

---

### 4.3 ⛽ Fuel

1. (Менеджер) группа + имя  
2. **📅 Date**  
3. **🎯 Purpose**  
4. **🏍 Bike**  
5. **⛽ Station**  
6. **Fuel type** — Pertalite / Pertamax  
7. **💵 Amount**  
8. **💳 Paid from**  
9. **🔢 Mileage** — не уменьшается  
10. **💬 Comment** (optional)  
11. **📸 Fuel receipt** — AI + merge comment при конфликте  
12. **📸 Odometer photo**  
13. **✅ Confirm**

Фоном: проверка расхода топлива и GPS vs odometer.

---

### 4.4 💰 Income

1. **📅 Date**  
2. **📂 Category** — Rental / Lesson / Other  
3. **🎯 Purpose**  
4. **👤 Client name**  
5. **🔢 Lessons** — если Lesson  
6. **💵 Amount**  
7. **💳 Payment type** — Cash / Transfer / QRIS / Already paid / Instructor's card  
8. **💬 Comment**  
9. **📸 Payment photo** (для перевода — скрин; для cash — Skip)  
10. **✅ Confirm**

---

### 4.5 📊 My balance

Ваши **Spendings** и **Cash on hand** с датами последней выплаты/сдачи.

---

### 4.6 📋 My records

У superadmin: выбор **сотрудника** или **All employees** → последние 5 строк Expenses.

---

### 4.7 🔄 Transfer to colleague

**Отправитель:**
1. Выбор получателя  
2. Сумма IDR  
3. **✅ Confirm**

В **группе получателя** — кнопки **✅ Received** / **❌ Reject**.  
Только после **Received** запись попадает в Payouts/Income.

**Получатель:** нажать **✅ Received**, когда деньги реально получены.

---

### 4.8 ⏰ Alarm (таймер урока)

1. Длительность: 1h / 1.5h / 2h / Custom (минуты)  
2. Напоминания (до/после конца) — tap to toggle  
3. **▶️ Start lesson** → сообщение в **lesson group**

Можно **⏹ Stop lesson** досрочно.

---

### 4.9 📅 Next lesson

Ближайший урок из Google Calendar (время, клиент, pickup, площадка, байк).

---

### 4.10 🗓 My schedule

У superadmin:
1. Выбор **💛 Alex / 💙 Ray / 👥 All**  
2. Расписание на **завтра**

---

### 4.11 🏍 Deliver bike / 🏁 Return bike

Как у инструкторов (доставка booked → active, возврат active → returned).

**Deliver — по шагам:**
1. Выбор брони из списка **booked**  
2. Карточка → **✅ Confirm**  
3. **Odometer photo** (AI km + fuel) → confirm/edit  
4. **Video** байка  
5. **Checklist** (phone holder, charger, first aid, papers, adjuster) — Yes/No  
6. **Helmets**  
7. **Payment** — Cash / Transfer / Already paid (+ сумма если оплачено)  
8. **Insurance**  
9. **Final confirm** → Income при Cash/Transfer, статус **active**

**Return — по шагам:**
1. Выбор **active** rental  
2. Review → Confirm  
3. **Video**  
4. **Odometer**  
5. **Checklist**  
6. **Damages?** — текст + фото или «No damages»  
7. **Extras collected**  
8. **✅ Confirm return** → статус **returned**, при повреждениях — Bike Issue

**⏸ Pause** / **▶ Resume delivery|return** — сохранить прогресс и продолжить позже.

---

### 4.12 ⚠️ Report bike issue

1. **🏍 Bike**  
2. **📝 Description**  
3. **Photos** (до 10) → **✅ Done** или Skip  
4. **Confirm**

Уведомление в topic **Bike Issues** (/3775) и superadmin group.

---

### 4.13 🆘 SOS

1. **🆘 SOS** — мгновенный алерт в superadmin group + lesson group (с тегами менеджеров)  
2. **📍 Send my location** — GPS на карте  
3. **✅ All good — Cancel SOS** — отмена ложной тревоги

---

## 5. Панель менеджера

Откройте **👔 Manager**.

### 5.1 📋 Pending expenses / 📋 Pending income

Показывает до 10 новых записей без статуса.

На каждой записи:
- **✅ Approve** — Status = Approved  
- **❌ Reject** — Status = Rejected  
- **💬 Comment** — ввести Manager comment в таблицу

> Approve/Reject — пометка в таблице; выплата/сдача делается отдельно через Pay/Receive.

---

### 5.2 💼 All balances

1. Выбор сотрудника или **All**  
2. По каждому: **Spendings** (since payout) и **Cash on hand** (since handover)

---

### 5.3 💸 Pay expense (выплата расходов)

1. **Мультивыбор сотрудников** — tap ☑/☐, затем **✅ Confirm (N selected)**  
   (можно выбрать нескольких — выплата каждому по его spendings)
2. **💳 Payment type** — 💵 Cash / 💳 Transfer / 💰 Taken from revenue  
3. **✅ Confirm**

Для **одного** сотрудника (если выбран один):
- Можно **Pay full** (вся сумма spendings) или **Enter manually**  
- При переплате — overpayment учитывается в следующем цикле

**Эффект:** запись **Expense payout** в Payouts, подсветка строк в Expenses, уведомление в группу сотрудника.

---

### 5.4 💰 Receive income (приём наличных)

1. Выбор сотрудника  
2. Показ: total income collected + **cash on hand**  
3. **Receive full** или ручная сумма  
4. **💳 Payment type** — Cash / Transfer  
5. **✅ Confirm**

**Эффект:** **Income handover** в Payouts; income после handover по времени пересчитывается (`fix_income_times_after_handover`).

---

### 5.5 💬 Add comment

1. Лист — **Expenses** или **Income**  
2. Выбор записи (группировка по сотруднику и дате)  
3. Текст комментария → сохранение в **Comment** (Income) или доп. поле менеджера

Отличается от **💬 Comment** на pending-карточке — здесь полный список записей.

---

### 5.6 🗑 Delete record *(superadmin)*

1. Лист: **Expenses / Income / Payouts**  
2. **Мультивыбор** записей текущего месяца (☑)  
3. **🗑 Delete selected**  
4. Куда удалить:
   - **📋 Table only** — только Google Sheet  
   - **💬 Chat only** — только сообщение в Telegram (если есть TG Message ID)  
   - **🗑 Delete everywhere** — таблица + чат (в т.ч. media groups)

---

### 5.7 ✏️ Edit record *(superadmin)*

1. Лист Expenses / Income  
2. Запись  
3. Поле (Date, Amount, Place, Comment, Receipt photo…)  
4. Новое значение или новое фото  
5. Сохранение в таблицу

---

### 5.7 🏍 Bike Rental → подменю

| Кнопка | Действие |
|--------|----------|
| **📋 Book bike** | Новая бронь |
| **📖 Active rentals** | Список active → карточка → редактирование полей |
| **📊 Rental history** | История за 7/30/90 дней / all |
| **⚠️ Bike issues** | Список открытых issues из таблицы |
| **📚 Teach AI** | Правила для AI-бронирования |
| **« Back** | Назад в панель менеджера |

---

## 6. Супер-админ: GPS и байки

### 6.1 📍 GPS Status

Статус всех GPS-байков: Work (🔴) и Rental (🔵) — онлайн, напряжение, скорость, геозона, ссылка на карту.

### 6.2 📊 Mileage today

Пробег **work bikes** за сегодня (GPS).

### 6.3 📅 Mileage month

GPS + manual (по заправкам Bensin) за текущий месяц — по каждому work bike.

### 6.4 📊 GPS vs Odo

1. Байк или **All bikes**  
2. Период: 7 / 30 / 90 дней  
3. Таблица: Manual km vs GPS km, % diff (⚠️ если > 5%)

### 6.5 🗺 Live map

Ссылка на live-карту всех байков (обновление ~2 сек).

### 6.6 ✂️ Cut engine / 🔑 Restore engine

1. Выбор байка  
2. **Подтверждение** (cut — только когда байк стоит!)  
3. Команда на GPS-трекер + уведомление в superadmin group

### 6.7 🏍 Manage bikes

Перемещение байка между списками **Work ↔ Rental** (`bikes_config.json`):
1. **Work → Rental** или **Rental → Work**  
2. Выбор байка  
3. Подтверждение перемещения

---

## 7. Супер-админ: аналитика

### 7.1 📊 Bike statistics

1. Выбор байка (Work + Rental)  
2. Период: 7 / 30 / 90 / All  
3. Отчёт: fuel, service, mileage, cost/km, кто использовал, интервалы пробега  
4. Кнопки: **📈 Mileage history**, **🛠 Service log** (из Comment расходов + Bike Issues)

### 7.2 🏍 Bike profile

1. Выбор байка  
2. Карточка: GPS, выручка, fuel/service/rentals/issues, service log  
3. Кнопки по активным/историческим арендам

### 7.3 📈 Full statistics

1. Период: 7 / 30 / 90 / All time  
2. Сводка: **Calendar lessons** + **Income / Expenses / Rentals** за период

---

## 8. Супер-админ: календарь и расписание

### 8.1 📅 Send schedule

1. Выбор инструкторов (☑ Alex / Ray) или **Send to all**  
2. **📤 Send to selected**  
3. В **lesson group** уходит расписание на **завтра** с @username  
   - Если выходной — «Vacation / Day off»  
   - Если нет уроков — «Stay on call»

### 8.2 📆 Manage calendar

| Действие | Шаги |
|----------|------|
| **➕ Add lesson** | Instructor → Title → Date → Time → Duration → Site → Description → Confirm |
| **🔄 Reschedule** | Выбор урока (14 дней) → новая date/time → Confirm |
| **❌ Cancel lesson** | Выбор урока → подтверждение удаления из Google Calendar |

Инструкторы в календаре: **💛 Alex**, **💙 Ray**.

---

## 9. Аренда мотоциклов

### 9.1 📋 Book bike

**Шаг 0 — метод ввода:**
- **Voice / AI** — голос, текст или фото паспорта; Gemini заполняет поля; недостающее — вручную; **✅ Remember fix** — сохранить правило  
- **Enter manually** — все поля руками

**Ручной порядок полей:**
1. 📅 Delivery date  
2. 🕐 Delivery time  
3. 📆 Duration (дни / месяцы) → auto return date  
4. 🏍 Bike (rental list)  
5. 📣 Source (Ride&Joy / TravelAsk…)  
6. 👤 Client name  
7. 📱 Contact platform + contact  
8. 👨‍🏫 Instructor  
9. 📍 Location  
10. 💵 Price  
11. 🪖 Helmets  
12. 🛡 Insurance (+ cost если with insurance)  
13. ➕ Extra charges (optional)  
14. 🛂 Passport photo (optional, OCR ненадёжен — лучше имя вручную)  
15. 💬 Comment  
16. **✅ Confirm** → Rental ID (R-2026-XXX), status **booked**, уведомление в topic **Bike Rental** (/2)

**✏️ Edit** на confirm — правка полей. **« Back** — шаг назад.

---

### 9.2 📖 Active rentals

1. Список **active**  
2. Карточка rental  
3. **Edit** — instructor, location, dates, price, extras и др.  
4. Сохранение в таблицу Rentals

---

### 9.3 📊 Rental history

1. Период: 7 / 30 / 90 / All  
2. Список → полная карточка (видео, checklist, passport link)

---

### 9.4 📚 Teach AI

Правила для голосового/текстового бронирования (`rental_parse_rules.json`):

1. **➕ Add rule** — поле (location, price, bike…) → фраза из речи → значение  
2. **🗑 Delete rule**  
3. Пример: фраза `убуд` → Location = `Ubud`; `5 миллионов` → Price = `5000000`

На экране confirm брони: **✅ Remember fix** — быстро добавить правило из ошибки AI.

---

## 10. Куда уходят уведомления

| Событие | Куда |
|---------|------|
| Expense / Fuel / Income | Группа сотрудника (или выбранная при записи менеджером) |
| Expense payout / Income handover | Группа сотрудника |
| Transfer colleague | Группа получателя (до Received) |
| Lesson Alarm / schedule | **LESSON_GROUP** |
| SOS | **SUPERADMIN_GROUP** + lesson group |
| Bike Rental book/delivery/return | Lesson group topic **/2** |
| Bike Issues | Lesson group topic **/3775** + superadmin |
| GPS engine cut/restore | Superadmin group |
| Fuel anomaly | Superadmin group (фоновые проверки) |

**Не менять chat ID и routing без явного решения** — это критично для бизнес-процессов.

---

## Быстрые советы

1. **Pay expense** и **Receive income** — делайте регулярно, иначе балансы «разъезжаются» с реальностью.  
2. **Income handover** учитывает **дату и время** — income в тот же день после сдачи идёт уже «после handover».  
3. **Delete everywhere** — удаляет и TG; старые записи без Group Chat ID могут не удалить сообщение в чате.  
4. **Cut engine** — только на стоящем байке.  
5. **Deliver/Return** — используйте **Pause**, если процесс прервали.  
6. Запись расхода **от имени Alex/Ray** — всегда выбирайте правильную **группу** и **имя**, иначе баланс не того человека.

---

## Связанные документы

- **INSTRUCTOR_GUIDE.md** — то же для Alex и Ray (English)  
- **CONTEXT.md** — технический контекст для разработки  

*Обновлено: май 2026 — RIDE&JOY Spending Bot*
