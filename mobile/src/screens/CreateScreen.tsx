import React, { useEffect, useState } from "react";
import { Alert, View, StyleSheet } from "react-native";
import * as ImagePicker from "expo-image-picker";
import {
  createRecord,
  getCategories,
  lastFuelOdometer,
  listMembers,
  myBalance,
  uploadPhoto,
  type User,
} from "../api";
import { Btn, Chip, Field, Label, Screen, Sub, TopBar } from "../components/ui";

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

  useEffect(() => {
    (async () => {
      try {
        const res = await getCategories(kind);
        const list = res.categories[kind] || [];
        setCategories(list);
        setCategory(list[0] || "");
        if (res.purposes?.length) {
          setPurposes(res.purposes);
          setPurpose(res.purposes[0]);
        }
      } catch {
        setCategories([]);
      }
    })();
  }, [kind]);

  useEffect(() => {
    if (!isManager) return;
    (async () => {
      try {
        const rows = await listMembers();
        setMembers(rows.filter((m) => m.is_active !== false));
      } catch {
        /* optional */
      }
    })();
  }, [isManager]);

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
    setBusy(true);
    try {
      const up = await uploadPhoto(shot.assets[0].uri);
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
    if (!confirming) {
      if (kind !== "income" && paymentSource === "cash_on_hand") {
        try {
          const bal = await myBalance();
          if (value > bal.cash_on_hand) {
            Alert.alert(
              "Fos",
              `Cash on hand is ${bal.cash_on_hand.toLocaleString()} ${bal.currency}. Amount exceeds held cash — continue anyway on confirm if intentional.`,
            );
          }
        } catch {
          /* ignore balance check */
        }
      }
      setConfirming(true);
      return;
    }
    setBusy(true);
    try {
      await createRecord({
        kind,
        amount: value,
        category,
        purpose,
        place,
        bike,
        comment,
        photo_url: photoUrl,
        payment_method: kind === "income" ? paymentMethod : "",
        payment_source: kind === "income" ? "" : paymentSource,
        client_name: kind === "income" ? clientName : "",
        liters: kind === "fuel" && liters ? Number(liters.replace(",", ".")) : undefined,
        odometer: kind === "fuel" && odometer ? Number(odometer.replace(",", ".")) : undefined,
        created_for_user_id: forUserId ?? undefined,
        occurred_at: occurredDate.trim() ? `${occurredDate.trim()}T12:00:00` : undefined,
        approve_now: isManager && approveNow,
      });
      onCreated();
    } catch (e) {
      Alert.alert("Fos", e instanceof Error ? e.message : "Failed");
    } finally {
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
      <Label>Category</Label>
      <View style={styles.kinds}>
        {categories.map((c) => (
          <Chip key={c} label={c} on={category === c} onPress={() => setCategory(c)} />
        ))}
      </View>
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
