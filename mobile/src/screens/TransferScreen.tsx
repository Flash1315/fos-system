import React, { useEffect, useState } from "react";
import { Alert, View, StyleSheet } from "react-native";
import { me, orgDirectory, transferCash, type User } from "../api";
import { Btn, Chip, Field, Label, Screen, Sub, TopBar } from "../components/ui";

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
  const [members, setMembers] = useState<User[]>([]);
  const [email, setEmail] = useState("");
  const [amount, setAmount] = useState("");
  const [comment, setComment] = useState("");

  useEffect(() => {
    (async () => {
      try {
        const u = await me();
        const rows = await orgDirectory();
        setMembers(rows.filter((m) => m.id !== u.id));
      } catch {
        /* ignore */
      }
    })();
  }, []);

  const submit = async () => {
    const value = Number(amount.replace(",", "."));
    if (!email.trim() || !value || value <= 0) {
      Alert.alert("Fos", "Recipient and amount required");
      return;
    }
    setBusy(true);
    try {
      await transferCash({
        to_email: email.trim(),
        amount: value,
        comment,
      });
      Alert.alert("Fos", "Transfer recorded — cash balances updated");
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
      <Sub>Moves cash on hand immediately (approved transfer pair).</Sub>
      {members.length > 0 && (
        <>
          <Label>Teammate</Label>
          <View style={styles.kinds}>
            {members.map((m) => (
              <Chip
                key={m.id}
                label={m.full_name}
                on={email === m.email}
                onPress={() => setEmail(m.email)}
              />
            ))}
          </View>
        </>
      )}
      <Label>Teammate email</Label>
      <Field
        autoCapitalize="none"
        keyboardType="email-address"
        value={email}
        onChangeText={setEmail}
        placeholder="colleague@example.com"
      />
      <Label>Amount</Label>
      <Field keyboardType="decimal-pad" value={amount} onChangeText={setAmount} />
      <Label>Comment</Label>
      <Field value={comment} onChangeText={setComment} />
      <Btn title={busy ? "…" : "Submit transfer"} onPress={submit} disabled={busy} />
    </Screen>
  );
}

const styles = StyleSheet.create({
  kinds: { flexDirection: "row", gap: 8, marginBottom: 8, flexWrap: "wrap" },
});
