import React, { useEffect, useState } from "react";
import { Alert, View, StyleSheet } from "react-native";
import { createPayout, listMembers, teamBalances, type TeamBalance, type User } from "../api";
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
  const [balances, setBalances] = useState<TeamBalance[]>([]);
  const [userId, setUserId] = useState<number | null>(null);
  const [kind, setKind] = useState<"expense_payout" | "income_handover">("expense_payout");
  const [amount, setAmount] = useState("");
  const [method, setMethod] = useState<"cash" | "transfer">("cash");
  const [note, setNote] = useState("");

  useEffect(() => {
    (async () => {
      try {
        const [rows, bals] = await Promise.all([listMembers(), teamBalances()]);
        setMembers(rows.filter((m) => m.is_active !== false));
        setBalances(bals);
        if (rows[0]) setUserId(rows[0].id);
      } catch (e) {
        Alert.alert("Fos", e instanceof Error ? e.message : "Failed");
      }
    })();
  }, []);

  const selectedBal = balances.find((b) => b.user_id === userId);
  const suggested =
    kind === "expense_payout"
      ? selectedBal?.spendings ?? 0
      : selectedBal?.cash_on_hand ?? 0;

  useEffect(() => {
    if (suggested > 0) setAmount(String(suggested));
    else setAmount("");
  }, [userId, kind, suggested]);

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
      {selectedBal && (
        <Sub>
          Spendings {selectedBal.spendings.toLocaleString()} · Cash held{" "}
          {selectedBal.cash_on_hand.toLocaleString()}
        </Sub>
      )}
      <Label>Amount</Label>
      <Field keyboardType="decimal-pad" value={amount} onChangeText={setAmount} />
      <View style={styles.kinds}>
        <Chip
          label={kind === "expense_payout" ? "Pay all owed" : "Take all held"}
          on={Number(amount) === suggested && suggested > 0}
          onPress={() => suggested > 0 && setAmount(String(suggested))}
        />
      </View>
      <Sub>
        Paying more than current spendings auto-stores overpayment and reduces the next cycle.
      </Sub>
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
