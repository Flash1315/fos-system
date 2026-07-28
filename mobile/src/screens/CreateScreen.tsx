import React, { useEffect, useRef, useState } from "react";
import { Alert, View, StyleSheet } from "react-native";
import * as ImagePicker from "expo-image-picker";
import {
  createRecord,
  getCategories,
  lastFuelOdometer,
  listMembers,
  makeIdempotencyKey,
  myBalance,
  myOrg,
  teamBalances,
  uploadPhoto,
  type TeamBalance,
  type User,
} from "../api";
import { Btn, Chip, Field, Label, Screen, Sub, TopBar } from "../components/ui";
import { formatWhen } from "../format";

export function CreateScreen({
  busy,
  setBusy,
  user,
  onBack,
  onCreated,
}: {
  busy: boolean;
  setBusy: (v: boolean) => void;
  user: User;
  onBack: () => void;
  onCreated: () => void;
}) {
  const isManager = user.role === "owner" || user.role === "manager";
  const submitLock = useRef(false);
  const idemKeyRef = useRef<string | null>(null);
  const [kind, setKind] = useState<"expense" | "fuel" | "income">("expense");
  const [amount, setAmount] = useState("");
  const [category, setCategory] = useState("");
  const [approveNow, setApproveNow] = useState(false);
  const [categories, setCategories] = useState<string[]>([]);
  const [purposes, setPurposes] = useState<string[]>(["Rental", "Lesson", "Office", "Other"]);
  const [purpose, setPurpose] = useState("Other");
  const [place, setPlace] = useState("");
  const [bike, setBike] = useState("");
  const [comment, setComment] = useState("");
  const [liters, setLiters] = useState("");
  const [odometer, setOdometer] = useState("");
  const [clientName, setClientName] = useState("");
  const [paymentMethod, setPaymentMethod] = useState<"cash" | "transfer">("cash");
  const [paymentSource, setPaymentSource] = useState<"my_pocket" | "cash_on_hand">("my_pocket");
  const [photoUrl, setPhotoUrl] = useState("");
  const [members, setMembers] = useState<User[]>([]);
  const [forUserId, setForUserId] = useState<number | null>(null);
  const [occurredDate, setOccurredDate] = useState("");
  const [confirming, setConfirming] = useState(false);
  const [lastOdo, setLastOdo] = useState<number | null>(null);
  const [closedCycleHint, setClosedCycleHint] = useState("");
  const [teamBals, setTeamBals] = useState<TeamBalance[]>([]);
  const [myCurrency, setMyCurrency] = useState("IDR");
  const [categoriesError, setCategoriesError] = useState("");
  const [teamLoadError, setTeamLoadError] = useState("");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        setCategoriesError("");
        const res = await getCategories(kind);
        if (cancelled) return;
        const list = res.categories[kind] || [];
        setCategories(list);
        setCategory(list[0] || "");
        if (res.purposes?.length) {
          setPurposes(res.purposes);
          setPurpose(res.purposes.includes("Other") ? "Other" : res.purposes[0]);
        }
      } catch (e) {
        if (cancelled) return;
        setCategories([]);
        setCategory("");
        setCategoriesError(e instanceof Error ? e.message : "Categories failed to load");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [kind]);

  const loadTeamContext = async () => {
    if (!isManager) return;
    try {
      setTeamLoadError("");
      const rows = await listMembers();
      setMembers(rows.filter((m) => m.is_active !== false));
      try {
        setTeamBals(await teamBalances());
      } catch {
        setTeamBals([]);
      }
      try {
        const org = await myOrg();
        setMyCurrency(org.currency || "IDR");
      } catch {
        /* ignore currency */
      }
    } catch (e) {
      setMembers([]);
      setTeamBals([]);
      setTeamLoadError(e instanceof Error ? e.message : "Failed to load teammates");
    }
  };

  useEffect(() => {
    void loadTeamContext();
  }, [isManager]);

  useEffect(() => {
    if (!occurredDate.trim()) {
      setClosedCycleHint("");
      return;
    }
    const day = occurredDate.trim();
    if (!/^\d{4}-\d{2}-\d{2}$/.test(day)) {
      setClosedCycleHint("");
      return;
    }
    (async () => {
      try {
        const cashTrack =
          kind === "income"
            ? paymentMethod === "cash"
            : paymentSource === "cash_on_hand";
        const spendTrack = kind !== "income" && paymentSource === "my_pocket";
        let cutoff: string | null | undefined = null;
        if (forUserId != null) {
          const row = teamBals.find((b) => b.user_id === forUserId);
          cutoff = cashTrack
            ? row?.last_income_handover_at
            : spendTrack
              ? row?.last_expense_payout_at
              : null;
        } else {
          const bal = await myBalance();
          setMyCurrency(bal.currency);
          cutoff = cashTrack
            ? bal.last_income_handover_at
            : spendTrack
              ? bal.last_expense_payout_at
              : null;
        }
        if (!cutoff) {
          setClosedCycleHint("");
          return;
        }
        const cutDay = cutoff.slice(0, 10);
        if (day <= cutDay) {
          setClosedCycleHint(
            `This date falls in a settled period (cutoff ${formatWhen(cutoff)}). Approving will not change the current balance — use an adjustment for the open cycle if needed.`,
          );
        } else {
          setClosedCycleHint("");
        }
      } catch {
        setClosedCycleHint("");
      }
    })();
  }, [occurredDate, kind, paymentSource, paymentMethod, forUserId, teamBals]);

  useEffect(() => {
    if (kind !== "fuel") {
      setLastOdo(null);
      return;
    }
    const handle = setTimeout(() => {
      void (async () => {
        try {
          const res = await lastFuelOdometer({
            bike: bike.trim() || undefined,
            user_id: forUserId ?? undefined,
          });
          setLastOdo(res.odometer);
        } catch {
          setLastOdo(null);
        }
      })();
    }, 300);
    return () => clearTimeout(handle);
  }, [kind, bike, forUserId]);

  const pickPhoto = async (fromCamera: boolean) => {
    if (fromCamera) {
      const perm = await ImagePicker.requestCameraPermissionsAsync();
      if (!perm.granted) {
        Alert.alert("Fos", "Camera permission required");
        return;
      }
    } else {
      const perm = await ImagePicker.requestMediaLibraryPermissionsAsync();
      if (!perm.granted) {
        Alert.alert("Fos", "Photo permission required");
        return;
      }
    }
    const shot = fromCamera
      ? await ImagePicker.launchCameraAsync({ quality: 0.7 })
      : await ImagePicker.launchImageLibraryAsync({
          mediaTypes: ["images"],
          quality: 0.7,
        });
    if (shot.canceled || !shot.assets[0]) return;
    const asset = shot.assets[0];
    const mime = (asset.mimeType || "").toLowerCase();
    const fname = (asset.fileName || asset.uri || "").toLowerCase();
    if (
      mime.includes("heic") ||
      mime.includes("heif") ||
      fname.endsWith(".heic") ||
      fname.endsWith(".heif")
    ) {
      Alert.alert("Fos", "HEIC/HEIF is not supported. Choose JPEG, PNG, or WebP.");
      return;
    }
    setBusy(true);
    try {
      const up = await uploadPhoto(asset.uri, {
        name: asset.fileName || undefined,
        type: asset.mimeType || undefined,
      });
      setPhotoUrl(up.photo_url);
      Alert.alert("Fos", "Receipt photo attached");
    } catch (e) {
      Alert.alert("Fos", e instanceof Error ? e.message : "Upload failed");
    } finally {
      setBusy(false);
    }
  };

  const submit = async () => {
    const value = Number(amount.replace(",", "."));
    if (!value || value <= 0) {
      Alert.alert("Fos", "Enter a valid amount");
      return;
    }
    if (!category.trim()) {
      Alert.alert("Fos", categoriesError ? `Categories failed — ${categoriesError}` : "Category is required");
      return;
    }
    if ((kind === "expense" || kind === "fuel") && !purpose.trim()) {
      Alert.alert("Fos", "Purpose is required");
      return;
    }
    if (occurredDate.trim() && !/^\d{4}-\d{2}-\d{2}$/.test(occurredDate.trim())) {
      Alert.alert("Fos", "When must be YYYY-MM-DD or empty");
      return;
    }
    if (kind === "fuel") {
      const litersVal = Number(liters.replace(",", "."));
      const odoVal = odometer.trim() ? Number(odometer.replace(",", ".")) : null;
      if (!liters.trim() || !Number.isFinite(litersVal) || litersVal <= 0) {
        Alert.alert("Fos", "Liters is required for fuel");
        return;
      }
      if (odometer.trim() && (!Number.isFinite(odoVal as number) || (odoVal as number) < 0)) {
        Alert.alert("Fos", "Odometer must be a finite number");
        return;
      }
      if (lastOdo != null && (odoVal == null || !Number.isFinite(odoVal))) {
        Alert.alert("Fos", `Odometer is required (last reading ${lastOdo})`);
        return;
      }
      if (odoVal != null && lastOdo != null && odoVal < lastOdo) {
        Alert.alert(
          "Fos",
          `Odometer cannot decrease (last ${lastOdo}). Enter a higher reading.`,
        );
        return;
      }
    }
    if (!confirming) {
      if (kind !== "income" && paymentSource === "cash_on_hand") {
        try {
          let available = 0;
          let held = 0;
          let reserved = 0;
          let currency = myCurrency;
          if (forUserId != null) {
            const row = teamBals.find((b) => b.user_id === forUserId);
            if (row) {
              held = row.cash_on_hand;
              available = row.available_cash ?? row.cash_on_hand;
              reserved = row.reserved_cash ?? 0;
              if (row.currency) currency = row.currency;
            }
          } else {
            const bal = await myBalance();
            held = bal.cash_on_hand;
            available = bal.available_cash ?? bal.cash_on_hand;
            reserved = bal.reserved_cash || 0;
            currency = bal.currency;
            setMyCurrency(bal.currency);
          }
          if (value > available) {
            const who = forUserId != null ? "Teammate available cash" : "Available cash";
            const msg =
              `${who} is ${available.toLocaleString()} ${currency}` +
              ` (${held.toLocaleString()} held` +
              `${reserved > 0 ? `, ${reserved.toLocaleString()} reserved` : ""}).`;
            if (isManager && approveNow) {
              Alert.alert(
                "Fos",
                `${msg} Cannot approve from cash on hand for more than available.`,
              );
              return;
            }
            Alert.alert(
              "Fos",
              `${msg} Amount exceeds available — continue anyway on confirm if intentional.`,
            );
          }
        } catch (e) {
          if (isManager && approveNow) {
            Alert.alert(
              "Fos",
              e instanceof Error ? e.message : "Could not verify cash balance",
            );
            return;
          }
        }
      }
      if (isManager && approveNow && closedCycleHint) {
        Alert.alert(
          "Fos",
          `${closedCycleHint}\n\nApprove immediately anyway? Approving will not change the current open balance.`,
          [
            { text: "Cancel", style: "cancel" },
            { text: "Continue", onPress: () => setConfirming(true) },
          ],
        );
        return;
      }
      setConfirming(true);
      return;
    }
    if (busy || submitLock.current) return;
    // Re-check cash right before submit (approve_now must not use stale Review numbers)
    if (kind !== "income" && paymentSource === "cash_on_hand" && isManager && approveNow) {
      try {
        let available = 0;
        let currency = myCurrency;
        if (forUserId != null) {
          const bals = await teamBalances();
          setTeamBals(bals);
          const row = bals.find((b) => b.user_id === forUserId);
          available = row?.available_cash ?? row?.cash_on_hand ?? 0;
          if (row?.currency) currency = row.currency;
        } else {
          const bal = await myBalance();
          available = bal.available_cash ?? bal.cash_on_hand;
          currency = bal.currency;
          setMyCurrency(bal.currency);
        }
        if (value > available + 1e-6) {
          Alert.alert(
            "Fos",
            `Only ${available.toLocaleString()} ${currency} available now — cannot approve from cash.`,
          );
          return;
        }
      } catch (e) {
        Alert.alert("Fos", e instanceof Error ? e.message : "Could not verify cash balance");
        return;
      }
    }
    if (kind === "fuel" && odometer) {
      try {
        const last = await lastFuelOdometer({
          bike: bike.trim() || undefined,
          user_id: forUserId ?? undefined,
        });
        const lastVal = last.odometer;
        setLastOdo(lastVal);
        if (lastVal != null && Number(odometer.replace(",", ".")) < lastVal) {
          Alert.alert(
            "Fos",
            `Odometer cannot decrease (last ${lastVal}). Enter a higher reading.`,
          );
          return;
        }
      } catch (e) {
        Alert.alert("Fos", e instanceof Error ? e.message : "Could not verify odometer");
        return;
      }
    }
    if (submitLock.current) return;
    submitLock.current = true;
    if (!idemKeyRef.current) idemKeyRef.current = makeIdempotencyKey("rec");
    setBusy(true);
    try {
      await createRecord(
        {
          kind,
          amount: value,
          category: category.trim(),
          purpose,
          place: place.trim(),
          bike: bike.trim(),
          comment: comment.trim(),
          photo_url: photoUrl,
          payment_method: kind === "income" ? paymentMethod : "",
          payment_source: kind === "income" ? "" : paymentSource,
          client_name: kind === "income" ? clientName.trim() : "",
          liters: kind === "fuel" ? Number(liters.replace(",", ".")) : undefined,
          odometer:
            kind === "fuel" && odometer.trim()
              ? Number(odometer.replace(",", "."))
              : undefined,
          created_for_user_id: forUserId ?? undefined,
          occurred_at: occurredDate.trim() ? `${occurredDate.trim()}T12:00:00` : undefined,
          approve_now: isManager && approveNow,
        },
        { idempotencyKey: idemKeyRef.current },
      );
      idemKeyRef.current = null;
      onCreated();
    } catch (e) {
      Alert.alert("Fos", e instanceof Error ? e.message : "Failed");
    } finally {
      submitLock.current = false;
      setBusy(false);
    }
  };

  const forName =
    forUserId == null
      ? "Myself"
      : members.find((m) => m.id === forUserId)?.full_name || "Teammate";

  if (confirming) {
    const value = Number(amount.replace(",", ".") || 0);
    return (
      <Screen scroll>
        <TopBar onBack={() => setConfirming(false)} onCancel={onBack} />
        <Label>Confirm record</Label>
        <Label>For</Label>
        <Field editable={false} value={forName} />
        <Label>Kind</Label>
        <Field editable={false} value={kind} />
        <Label>Purpose</Label>
        <Field editable={false} value={purpose} />
        <Label>Amount</Label>
        <Field editable={false} value={String(value)} />
        <Label>When</Label>
        <Field editable={false} value={occurredDate || "now"} />
        {!!closedCycleHint && <Sub>{closedCycleHint}</Sub>}
        <Label>Category</Label>
        <Field editable={false} value={category || "—"} />
        <Label>Place</Label>
        <Field editable={false} value={place || "—"} />
        <Label>Bike</Label>
        <Field editable={false} value={bike || "—"} />
        {kind !== "income" && (
          <>
            <Label>Payment source</Label>
            <Field
              editable={false}
              value={paymentSource === "my_pocket" ? "My pocket" : "Cash on hand"}
            />
          </>
        )}
        {kind === "income" && (
          <>
            <Label>Client / method</Label>
            <Field editable={false} value={`${clientName || "—"} · ${paymentMethod}`} />
          </>
        )}
        <Label>Comment</Label>
        <Field editable={false} value={comment || "—"} />
        <Label>Photo</Label>
        <Field editable={false} value={photoUrl ? "Attached" : "None"} />
        {isManager && (
          <>
            <Label>Status</Label>
            <Field editable={false} value={approveNow ? "Approve immediately" : "Send to queue"} />
          </>
        )}
        <Btn
          title={busy ? "…" : approveNow && isManager ? "Confirm & approve" : "Confirm & submit"}
          onPress={submit}
          disabled={busy}
        />
        <Btn title="Back to edit" variant="ghost" onPress={() => setConfirming(false)} />
      </Screen>
    );
  }

  return (
    <Screen scroll>
      <TopBar onBack={onBack} onCancel={onBack} />
      <Label>New record</Label>
      {isManager && members.length > 0 && (
        <>
          <Label>File for</Label>
          <Sub>Balances attribute to the selected teammate.</Sub>
          {!!teamLoadError && (
            <>
              <Sub>Could not load teammates — {teamLoadError}</Sub>
              <Btn title="Retry teammates" variant="ghost" onPress={loadTeamContext} />
            </>
          )}
          <View style={styles.kinds}>
            <Chip label="Myself" on={forUserId == null} onPress={() => setForUserId(null)} />
            {members
              .filter((m) => m.id !== user.id)
              .map((m) => (
                <Chip
                  key={m.id}
                  label={m.full_name.split(" ")[0] || m.full_name}
                  on={forUserId === m.id}
                  onPress={() => setForUserId(m.id)}
                />
              ))}
          </View>
        </>
      )}
      <View style={styles.kinds}>
        {(["expense", "fuel", "income"] as const).map((k) => (
          <Chip key={k} label={k} on={kind === k} onPress={() => setKind(k)} />
        ))}
      </View>
      <Label>Purpose</Label>
      <View style={styles.kinds}>
        {purposes.map((p) => (
          <Chip key={p} label={p} on={purpose === p} onPress={() => setPurpose(p)} />
        ))}
      </View>
      <Label>Amount</Label>
      <Field keyboardType="decimal-pad" value={amount} onChangeText={setAmount} />
      <Label>When (optional YYYY-MM-DD)</Label>
      <Field autoCapitalize="none" value={occurredDate} onChangeText={setOccurredDate} placeholder="leave empty = now" />
      {!!closedCycleHint && <Sub>{closedCycleHint}</Sub>}
      <Label>Category</Label>
      {!!categoriesError && (
        <Sub>Could not load categories — {categoriesError}. You can still type a category below if needed.</Sub>
      )}
      <View style={styles.kinds}>
        {categories.map((c) => (
          <Chip key={c} label={c} on={category === c} onPress={() => setCategory(c)} />
        ))}
      </View>
      {categories.length === 0 && (
        <Field value={category} onChangeText={setCategory} placeholder="Category" />
      )}
      <Label>Place</Label>
      <Field value={place} onChangeText={setPlace} placeholder="Station / shop (optional)" />
      {(kind === "fuel" || kind === "expense") && (
        <>
          <Label>Bike</Label>
          <Field value={bike} onChangeText={setBike} placeholder="Optional bike name" />
        </>
      )}
      {kind !== "income" && (
        <>
          <Label>Payment source</Label>
          <View style={styles.kinds}>
            <Chip
              label="My pocket"
              on={paymentSource === "my_pocket"}
              onPress={() => setPaymentSource("my_pocket")}
            />
            <Chip
              label="Cash on hand"
              on={paymentSource === "cash_on_hand"}
              onPress={() => setPaymentSource("cash_on_hand")}
            />
          </View>
        </>
      )}
      {kind === "fuel" && (
        <>
          <Label>Liters</Label>
          <Field keyboardType="decimal-pad" value={liters} onChangeText={setLiters} />
          <Label>Odometer</Label>
          <Field keyboardType="decimal-pad" value={odometer} onChangeText={setOdometer} />
          {lastOdo != null && (
            <Sub>Last reading {lastOdo.toLocaleString()} — cannot go lower.</Sub>
          )}
        </>
      )}
      {kind === "income" && (
        <>
          <Label>Client name</Label>
          <Field value={clientName} onChangeText={setClientName} />
          <Label>Payment method</Label>
          <View style={styles.kinds}>
            {(["cash", "transfer"] as const).map((m) => (
              <Chip key={m} label={m} on={paymentMethod === m} onPress={() => setPaymentMethod(m)} />
            ))}
          </View>
        </>
      )}
      <Label>Comment</Label>
      <Field value={comment} onChangeText={setComment} />
      {isManager && (
        <>
          <Label>After submit</Label>
          <View style={styles.kinds}>
            <Chip label="Send to queue" on={!approveNow} onPress={() => setApproveNow(false)} />
            <Chip label="Approve now" on={approveNow} onPress={() => setApproveNow(true)} />
          </View>
        </>
      )}
      <Btn
        title={photoUrl ? "Photo attached ✓ (library)" : "Photo from library"}
        onPress={() => pickPhoto(false)}
        variant="ghost"
        disabled={busy}
      />
      <Btn title="Photo from camera" onPress={() => pickPhoto(true)} variant="ghost" disabled={busy} />
      <Btn title={busy ? "…" : "Review"} onPress={submit} disabled={busy} />
    </Screen>
  );
}

const styles = StyleSheet.create({
  kinds: { flexDirection: "row", gap: 8, marginBottom: 8, flexWrap: "wrap" },
});
