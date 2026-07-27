# RIDE&JOY Bot — Instructor Guide (Alex & Ray)

This guide covers **all functions available to instructors** in the Telegram bot.  
Managers (Flash, Valori) have extra buttons — those are **not** listed here.

**Language:** The bot menus and messages are in **English**.  
**Time zone:** All dates and times use **WITA (UTC+8, Bali time)**.

---

## 1. Getting started

1. Open the bot in **private chat** (not a group).
2. Send **`/start`**.
3. You see the main menu and your name (Alex or Ray).

If you see *“No access”* with a Telegram ID — send that ID to Flash so you can be added.

**Every multi-step form supports:**
- **⬅️ Back** — previous step  
- **❌ Cancel** — abort and return to the main menu  

---

## 2. Main menu overview

| Button | What it does |
|--------|----------------|
| **💸 Expenses** | Record a general expense (manual entry) |
| **🧾 Add expense (AI)** | Record an expense — bot reads the receipt photo |
| **⛽ Fuel** | Record fuel (Bensin) for a bike |
| **💰 Income** | Record money received (lessons, rental, etc.) |
| **📊 My balance** | Your current spendings & cash on hand |
| **📋 My records** | Last 5 expense rows for you |
| **🔄 Transfer to colleague** | Hand cash to another team member |
| **⏰ Alarm** | Start a lesson timer with reminders |
| **📅 Next lesson** | Your next lesson from Google Calendar |
| **🗓 My schedule** | Tomorrow’s lessons (your name only) |
| **🏍 Deliver bike** | Deliver a booked rental to the client |
| **🏁 Return bike** | Complete an active rental return |
| **⚠️ Report bike issue** | Report damage or a problem on a bike |
| **🆘 SOS** | Emergency alert to management |

If you paused **Deliver** or **Return**, an extra button appears:  
**▶ Resume delivery** or **▶ Resume return**.

---

## 3. Money basics (read this first)

The bot tracks two separate things for each instructor:

### 💸 Spendings (reimbursable)
- Expenses paid from **My pocket** since the last **expense payout** from the manager.
- The manager reimburses this when they **Pay expense**.

### 💰 Cash on hand
- **Income** you collected (cash) minus **expenses** paid from **Cash on hand**, since the last **income handover**.
- When you give cash to the company or a colleague, **cash on hand** goes down.

### Payment source (expenses & fuel)
| Option | Meaning |
|--------|---------|
| **My pocket** | You paid yourself → counts toward **spendings** (reimbursement) |
| **Cash on hand** | You paid from client/rental cash you are holding → reduces **cash on hand** |

Always pick the correct option — balances depend on it.

---

## 4. 💸 Expenses (manual)

Use for shop purchases, service, taxi, training area, etc.

**Steps:**
1. **Date** — tap a day on the calendar (or **📅 Today**).
2. **Category** — e.g. Bike service, Aqua, Taxi, Tires pressure / Wheel repair, Other…
3. **Purpose** — 🏍 Rental / 📚 Lesson / 🏢 Office / 📦 Other  
   - If **Rental** → select the **bike** (links Rental ID automatically).
4. **Bike** — only for Bike service, Tires, or Rental purpose.
5. **Place** — shop or location name.
6. **Amount (IDR)** — numbers only, e.g. `85000`.
7. **Paid from** — My pocket or Cash on hand.
8. **Mileage (km)** — required for **Bike service** and **Tires**; must not be lower than the last recorded mileage for that bike.
9. **Comment** — optional; for service/repairs describe **what was done** (feeds the service log). Tap **⏭ Skip** if nothing to add.
10. **Photo 1 — Receipt** — photograph the receipt (or Skip).  
    - Bot runs **AI reading**: may auto-fill Comment if you skipped it.  
    - If your comment and the receipt ** differ**, choose: **Keep mine / Use receipt / Append both**.  
    - Warns if receipt total ≠ amount you entered (does not change your amount).
11. **Photo 2 — Item(s)** — photo of what you bought (or Skip).
12. **Confirm** — check the summary → **✅ Confirm** or **✏️ Edit**.

After save, a message is posted to **your instructor group** (Alex or Ray’s team chat).

---

## 5. 🧾 Add expense (AI)

Same accounting as manual expenses, but the **receipt comes first**.

**Steps:**
1. **Date**
2. **Purpose** (+ bike if Rental)
3. **Category**
4. **Bike** — if category needs it (Bike service, Tires, Bensin)
5. **Receipt photo** — bot reads place, items, amount, date on receipt  
   - Unreadable → enter **amount manually**  
   - Review screen: **Confirm / Edit / Retake photo**
6. **Paid from**
7. **Mileage** — if Bike service or Tires
8. **Item photo** (optional)
9. **Final confirm**

**Tip:** Use AI flow when you have a clear receipt; use manual flow if you need to enter everything by hand first.

---

## 6. ⛽ Fuel

Dedicated flow for refuelling (saved as category **Bensin**).

**Steps:**
1. **Date**
2. **Purpose** — Rental / Lesson / Office / Other
3. **Bike** — select from Work or Rental list (or enter manually)
4. **Station name**
5. **Fuel type** — Pertalite or Pertamax
6. **Amount paid (IDR)**
7. **Paid from** — My pocket or Cash on hand
8. **Mileage at refuel (km)** — must not decrease vs last entry for that bike
9. **Comment** — optional
10. **Fuel receipt photo** — AI may fill Comment or ask **Keep mine / Use receipt / Append both**
11. **Odometer photo** — photo showing mileage (or Skip where allowed)
12. **Confirm**

The bot may run **fuel consumption checks** and compare manual odometer vs GPS in the background.

---

## 7. 💰 Income

Record money you received from a client.

**Steps:**
1. **Date**
2. **Category** — Rental / Lesson / Other (sales equipment etc.)
3. **Purpose** — Rental / Lesson / Office / Other
4. **Client name**
5. **Number of lessons** — if category is Lesson (1–5 or Other)
6. **Amount (IDR)**
7. **Payment type** — 💵 Cash / 💳 Transfer / 🔳 QRIS / ✅ Already paid / 💳 Instructor's card
8. **Comment** — optional
9. **Payment confirmation photo** — useful for transfers (screenshot); Skip for cash
10. **Confirm**

Posted to your instructor group after save.

---

## 8. 📊 My balance & 📋 My records

### My balance
Shows:
- **Spendings** — reimbursable total since last expense payout (date shown)
- **Cash on hand** — net cash you hold since last income handover (date shown)

### My records
Shows your **last 5 expense rows** (date, category, place, amount).  
Income is not listed here — only expenses.

---

## 9. 🔄 Transfer to colleague

When you **physically give cash** to another instructor or manager.

**As sender:**
1. Tap **🔄 Transfer to colleague**
2. Select **recipient**
3. Enter **amount (IDR)**
4. **✅ Confirm**

A message goes to the **recipient’s group** with **✅ Received** / **❌ Reject**.

**As recipient:**  
Tap **✅ Received** only when you actually got the cash.  
Then the bot records income handover for the sender and income for you.

---

## 10. ⏰ Alarm (lesson timer)

Starts a timed lesson and notifies the **lesson Telegram group**.

1. Tap **⏰ Alarm**
2. Choose duration: **1h / 1.5h / 2h / Custom** (minutes)
3. Toggle **reminders** (before/after lesson end)
4. Tap **▶️ Start lesson**

While running:
- Group gets *“Lesson started”* with end time (+ calendar info if available)
- Reminders fire at chosen offsets
- Tap **⏹ Stop lesson** to end early

If a timer is already running, the bot offers **Stop** instead of starting a new one.

---

## 11. 📅 Next lesson & 🗓 My schedule

### Next lesson
Shows **your** next calendar event: time, client/summary, pickup, training site, bike — if assigned to you (Alex 💛 / Ray 💙).

### My schedule
Shows **tomorrow’s** lessons filtered to **your name** only.

---

## 12. 🏍 Deliver bike

When a rental is **booked** and you deliver the bike to the client.

1. Tap **🏍 Deliver bike**
2. Pick the booking from the list
3. Review client/bike/dates → **✅ Confirm**
4. **Odometer photo** — AI reads km + fuel bars (confirm or edit manually)
5. **Video** of the bike (required)
6. **Checklist** — Yes/No for: phone holder, charger, first aid, papers, adjuster
7. **Helmets** — count (and custom if needed)
8. **Payment** — Cash / Transfer / Already paid (+ amount if paid now)
9. **Insurance** — if applicable
10. **Final confirm**

**⏸ Pause** saves progress; use **▶ Resume delivery** from the main menu to continue.  
**❌ Cancel** aborts the delivery flow.

On success: rental status → **active**, checklist saved, payment may create **Income**, notification to rental topic.

---

## 13. 🏁 Return bike

When a rental is **active** and the client returns the bike.

1. Tap **🏁 Return bike**
2. Pick the active rental
3. Review → **✅ Confirm**
4. **Video** of the bike
5. **Odometer photo** — AI or manual
6. **Checklist** — same items as delivery
7. **Damages?** — No damages / Yes → describe + photos
8. **Extra charges collected?** — if any
9. **✅ Confirm return**

**⏸ Pause** / **▶ Resume return** work like delivery.

If damages are reported, a **bike issue** may be created automatically.

---

## 14. ⚠️ Report bike issue

For problems outside a formal return (or general damage reports).

1. Select **bike** (Work / Rental lists)
2. **Describe** the issue (min 3 characters)
3. **Photos/videos** — send up to 10 files, then **✅ Done adding photos**, or **⏭ Skip**
4. **Confirm**

Notification goes to the **bike issues** forum topic and superadmin group.

---

## 15. 🆘 SOS — emergency

**Use only in a real emergency.**

1. Tap **🆘 SOS**
2. Alert is sent **immediately** to management and the lesson group (with manager tags).
3. Optionally tap **📍 Send my location** (share live GPS).
4. If false alarm: **✅ All good — Cancel SOS** — sends cancellation to the same groups.

---

## 16. Receipt AI — quick reference

| Situation | Bot behaviour |
|-----------|----------------|
| Comment empty (Skip) | Fills Comment from receipt items |
| Comment similar to receipt | Keeps your text |
| Comment differs from receipt | You choose: Keep mine / Use receipt / Append both |
| Amount on receipt ≠ your entry | Warning only — your entered amount is kept |
| Unreadable receipt (AI flow) | Enter amount manually |

---

## 17. Groups & notifications

| Your action | Where it appears |
|-------------|------------------|
| Expense / Fuel / Income saved | **Your instructor group** (Alex or Ray) |
| Transfer to colleague | **Recipient’s group** until they confirm |
| Lesson Alarm | **Lesson group** |
| SOS | **Superadmin group** + **Lesson group** |
| Bike issue | **Lesson group** (issues topic) + superadmin |
| Rental deliver/return | Rental notifications (managed by office) |

---

## 18. Tips & common mistakes

1. **Wrong payment source** — My pocket vs Cash on hand changes balances; double-check before Confirm.
2. **Mileage going down** — bot rejects lower km than last record; re-read the odometer.
3. **Receipt photos** — flat, well lit, all numbers visible → better AI results.
4. **Service expenses** — always add a clear Comment (or use AI receipt) so repairs appear in the service log.
5. **Paused delivery/return** — don’t start a new Deliver/Return until you Resume or Cancel the old one.
6. **Private chat only** — `/start` and forms work in DM with the bot, not in groups.

---

## 19. What instructors cannot do in the bot

These are **manager-only** (you will not see these buttons):

- 👔 Manager panel (pay expense, receive income, all balances)
- Book new rentals / rental history / Teach AI
- Edit or delete any record
- GPS map, bike statistics, full statistics
- Manage calendar or bike lists

For those tasks, contact **Flash** or **Valori**.

---

## 20. Need help?

- **Bot not responding:** check internet; send `/start` again.
- **Wrong balance:** tell the manager — they can verify payouts and handovers in the sheet.
- **Access / bugs:** contact Flash with screenshots and what you tapped.

*Last updated: May 2026 — RIDE&JOY Spending Bot*
