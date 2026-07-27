import React, { useEffect, useState } from "react";
import { Alert, View, StyleSheet } from "react-native";
import { createPayout, listMembers, type User } from "../api";
import { Btn, Chip, Field, Label, Screen, Sub, TopBar } from "../components/ui";

export function PayoutScreen({
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
  const [userId, setUserId] = useState<number | null>(null);
  const [kind, setKind] = useState<"expense_payout" | "income_handover">("expense_payout");
  const [amount, setAmount] = useState("");
  const [method, setMethod] = useState<"cash" | "transfer">("cash");
  const [note, setNote] = useState("");

  useEffect(() => {
    (async () => {
      try {
        const rows = await listMembers();
        setMembers(rows.filter((m) => m.is_active !== false));
        if (rows[0]) setUserId(rows[0].id);
      } catch (e) {
        Alert.alert("Fos", e instanceof Error ? e.message : "Failed");
      }
    })();
  }, []);

  const submit = async () => {
    const value = Number(amount.replace(",", "."));
    if (!userId || !value || value <= 0) {
      Alert.alert("Fos", "Select teammate and amount");
      return;
    }
    setBusy(true);
    try {
      await createPayout({
        user_id: userId,
        kind,
        amount: value,
        payment_method: method,
        note,
      });
      Alert.alert("Fos", kind === "expense_payout" ? "Expense payout recorded" : "Income handover recorded");
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
      <Label>Settlements</Label>
      <Sub>Expense payout clears my-pocket spendings. Income handover resets cash-on-hand cycle.</Sub>
      <Label>Type</Label>
      <View style={styles.kinds}>
        <Chip label="Pay expense" on={kind === "expense_payout"} onPress={() => setKind("expense_payout")} />
        <Chip label="Receive income" on={kind === "income_handover"} onPress={() => setKind("income_handover")} />
      </View>
      <Label>Teammate</Label>
      <View style={styles.kinds}>
        {members.map((m) => (
          <Chip key={m.id} label={m.full_name} on={userId === m.id} onPress={() => setUserId(m.id)} />
        ))}
      </View>
      <Label>Amount</Label>
      <Field keyboardType="decimal-pad" value={amount} onChangeText={setAmount} />
      <Label>Method</Label>
      <View style={styles.kinds}>
        <Chip label="cash" on={method === "cash"} onPress={() => setMethod("cash")} />
        <Chip label="transfer" on={method === "transfer"} onPress={() => setMethod("transfer")} />
      </View>
      <Label>Note</Label>
      <Field value={note} onChangeText={setNote} />
      <Btn title={busy ? "…" : "Record settlement"} onPress={submit} disabled={busy} />
    </Screen>
  );
}

const styles = StyleSheet.create({
  kinds: { flexDirection: "row", gap: 8, marginBottom: 8, flexWrap: "wrap" },
});
