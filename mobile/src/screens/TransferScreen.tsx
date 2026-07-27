import React, { useState } from "react";
import { Alert } from "react-native";
import { transferCash } from "../api";
import { Btn, Field, Label, Screen, Sub, TopBar } from "../components/ui";

export function TransferScreen({
  busy,
  setBusy,
  onBack,
  onDone,
}: {
  busy: boolean;
  setBusy: (v: boolean) => void;
  onBack: () => void;
  onDone: () => void;
}) {
  const [email, setEmail] = useState("");
  const [amount, setAmount] = useState("");
  const [comment, setComment] = useState("");

  const submit = async () => {
    const value = Number(amount.replace(",", "."));
    if (!email.trim() || !value || value <= 0) {
      Alert.alert("Fos", "Recipient email and amount required");
      return;
    }
    setBusy(true);
    try {
      await transferCash({
        to_email: email.trim(),
        amount: value,
        comment,
      });
      Alert.alert("Fos", "Transfer submitted for approval (both sides)");
      onDone();
    } catch (e) {
      Alert.alert("Fos", e instanceof Error ? e.message : "Failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Screen scroll>
      <TopBar onBack={onBack} onCancel={onBack} />
      <Label>Transfer cash to teammate</Label>
      <Sub>Creates pending expense for you and pending cash income for them.</Sub>
      <Label>Teammate email</Label>
      <Field autoCapitalize="none" keyboardType="email-address" value={email} onChangeText={setEmail} />
      <Label>Amount</Label>
      <Field keyboardType="decimal-pad" value={amount} onChangeText={setAmount} />
      <Label>Comment</Label>
      <Field value={comment} onChangeText={setComment} />
      <Btn title={busy ? "…" : "Submit transfer"} onPress={submit} disabled={busy} />
    </Screen>
  );
}
