from config import FUEL_NORMS, FUEL_WARNING_MULTIPLIER, FUEL_PRICES, SUPERADMIN_GROUP_CHAT_ID

def get_bike_norm(bike_name):
    """Get fuel norm for bike by matching name."""
    bike_name_lower = bike_name.lower()
    for key, norm in FUEL_NORMS.items():
        if any(word.lower() in bike_name_lower for word in key.split()):
            return norm
    return None

def get_fuel_price(fuel_type="Pertalite"):
    return FUEL_PRICES.get(fuel_type, 10000)

async def check_fuel_consumption(bot, employee_name, bike_name, current_odo, amount_idr, fuel_type="Pertalite"):
    """
    Check fuel consumption after a fuel entry.
    Compares with previous fuel entry for same bike to calculate L/100km.
    """
    try:
        from utils.sheets import get_sheet
        ws = get_sheet("Expenses")
        rows = ws.get_all_values()
        
        # Find previous fuel entries for this bike
        fuel_rows = []
        from utils.sheets import EXP_COL_EMPLOYEE, EXP_COL_MILEAGE, EXP_COL_CATEGORY, _parse_mileage_km
        for row in rows:
            if (len(row) > EXP_COL_EMPLOYEE and
                row[EXP_COL_EMPLOYEE] == employee_name and
                row[EXP_COL_CATEGORY] == "Bensin" and
                row[0] not in ("", "Date", "TOTAL") and
                not row[0].startswith("=")):
                fuel_rows.append(row)
        
        if len(fuel_rows) < 1:
            return  # Need at least 1 previous entry

        prev = fuel_rows[-1]
        prev_odo = _parse_mileage_km(prev[EXP_COL_MILEAGE] if len(prev) > EXP_COL_MILEAGE else "")
        
        try:
            if not prev_odo:
                return
            curr_odo = int(''.join(c for c in str(current_odo) if c.isdigit()))
        except:
            return
        
        if curr_odo <= prev_odo:
            return
        
        distance = curr_odo - prev_odo
        
        # Calculate liters from IDR amount
        price_per_liter = get_fuel_price(fuel_type)
        liters = amount_idr / price_per_liter
        
        if distance < 5:  # Too short distance, skip
            return
        
        consumption = (liters / distance) * 100  # L/100km
        
        norm = get_bike_norm(bike_name)
        if not norm:
            return
        
        # Adjust norm for fuel type efficiency
        from config import FUEL_EFFICIENCY
        efficiency = FUEL_EFFICIENCY.get(fuel_type, 1.0)
        adjusted_norm = norm * efficiency
        warning_threshold = adjusted_norm * FUEL_WARNING_MULTIPLIER
        
        if consumption > warning_threshold:
            from utils.sheets import format_idr
            text = (
                f"⚠️ <b>Fuel overconsumption alert</b>\n\n"
                f"👤 {employee_name}\n"
                f"🏍 {bike_name}\n"
                f"📍 Distance: {distance} km\n"
                f"⛽ Consumed: {liters:.1f}L ({format_idr(amount_idr)})\n"
                f"📊 Consumption: <b>{consumption:.2f} L/100km</b>\n"
                f"✅ Normal: {adjusted_norm:.2f} L/100km ({fuel_type})\n"
                f"🔴 Threshold: {warning_threshold:.2f} L/100km"
            )
            await bot.send_message(
                chat_id=SUPERADMIN_GROUP_CHAT_ID,
                text=text,
                parse_mode="HTML"
            )
    except Exception as e:
        print(f"Fuel check error: {e}")


async def check_gps_odometer(bot, bike_name: str, manual_odo: int, prev_odo: int, entry_date_ts: int):
    """
    Compare manual odometer with GPS mileage for the same period.
    Sends alert to superadmin group if difference > 20%.
    """
    try:
        from utils.gps import get_device_mileage
        from config import SUPERADMIN_GROUP_CHAT_ID, BIKES_GPS

        # Find IMEI by bike name
        imei = None
        bike_name_lower = bike_name.lower()
        for imei_key, info in BIKES_GPS.items():
            if any(word.lower() in bike_name_lower for word in info["name"].split()):
                imei = imei_key
                break

        if not imei:
            return  # No GPS tracker for this bike

        import time
        end_ts = int(time.time())
        start_ts = entry_date_ts

        gps_km = await get_device_mileage(imei, start_ts, end_ts)
        if not gps_km or gps_km < 1:
            return

        manual_km = manual_odo - prev_odo
        if manual_km <= 0:
            return

        diff_pct = abs(gps_km - manual_km) / max(gps_km, manual_km) * 100

        if diff_pct > 20:
            text = (
                f"🔍 <b>Odometer mismatch!</b>\n\n"
                f"🏍 <b>{bike_name}</b>\n"
                f"📝 Manual: <b>{manual_km} km</b>\n"
                f"📡 GPS: <b>{gps_km:.1f} km</b>\n"
                f"⚠️ Difference: <b>{diff_pct:.0f}%</b>"
            )
            await bot.send_message(
                chat_id=SUPERADMIN_GROUP_CHAT_ID,
                text=text,
                parse_mode="HTML"
            )
    except Exception as e:
        print(f"GPS odometer check error: {e}")
