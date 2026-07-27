import React, { useEffect, useState } from "react";
import { Alert, View, StyleSheet } from "react-native";
import * as ImagePicker from "expo-image-picker";
import {
  createRecord,
  getCategories,
  uploadPhoto,
} from "../api";
import { Btn, Chip, Field, Label, Screen, TopBar } from "../components/ui";

export function CreateScreen({
  busy,
  setBusy,
  onBack,
  onCreated,
}: {
  busy: boolean;
  setBusy: (v: boolean) => void;
  onBack: () => void;
  onCreated: () => void;
}) {
  const [kind, setKind] = useState<"expense" | "fuel" | "income">("expense");
  const [amount, setAmount] = useState("");
  const [category, setCategory] = useState("");
  const [categories, setCategories] = useState<string[]>([]);
  const [comment, setComment] = useState("");
  const [liters, setLiters] = useState("");
  const [odometer, setOdometer] = useState("");
  const [clientName, setClientName] = useState("");
  const [paymentMethod, setPaymentMethod] = useState<"cash" | "transfer">("cash");
  const [photoUrl, setPhotoUrl] = useState("");

  useEffect(() => {
    (async () => {
      try {
        const res = await getCategories(kind);
        const list = res.categories[kind] || [];
        setCategories(list);
        setCategory(list[0] || "");
      } catch {
        setCategories([]);
      }
    })();
  }, [kind]);

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
    setBusy(true);
    try {
      await createRecord({
        kind,
        amount: value,
        category,
        comment,
        photo_url: photoUrl,
        payment_method: kind === "income" ? paymentMethod : "",
        client_name: kind === "income" ? clientName : "",
        liters: kind === "fuel" && liters ? Number(liters.replace(",", ".")) : undefined,
        odometer: kind === "fuel" && odometer ? Number(odometer.replace(",", ".")) : undefined,
      });
      onCreated();
    } catch (e) {
      Alert.alert("Fos", e instanceof Error ? e.message : "Failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Screen scroll>
      <TopBar onBack={onBack} onCancel={onBack} />
      <Label>New record</Label>
      <View style={styles.kinds}>
        {(["expense", "fuel", "income"] as const).map((k) => (
          <Chip key={k} label={k} on={kind === k} onPress={() => setKind(k)} />
        ))}
      </View>
      <Label>Amount</Label>
      <Field keyboardType="decimal-pad" value={amount} onChangeText={setAmount} />
      <Label>Category</Label>
      <View style={styles.kinds}>
        {categories.map((c) => (
          <Chip key={c} label={c} on={category === c} onPress={() => setCategory(c)} />
        ))}
      </View>
      {kind === "fuel" && (
        <>
          <Label>Liters</Label>
          <Field keyboardType="decimal-pad" value={liters} onChangeText={setLiters} />
          <Label>Odometer</Label>
          <Field keyboardType="decimal-pad" value={odometer} onChangeText={setOdometer} />
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
      <Btn title={photoUrl ? "Photo attached ✓ (library)" : "Photo from library"} onPress={() => pickPhoto(false)} variant="ghost" disabled={busy} />
      <Btn title="Photo from camera" onPress={() => pickPhoto(true)} variant="ghost" disabled={busy} />
      <Btn title={busy ? "…" : "Submit for approval"} onPress={submit} disabled={busy} />
    </Screen>
  );
}

const styles = StyleSheet.create({
  kinds: { flexDirection: "row", gap: 8, marginBottom: 8, flexWrap: "wrap" },
});
