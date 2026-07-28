import React, { useEffect, useState } from "react";
import { Alert, View, StyleSheet } from "react-native";
import {
  batchPaySpendings,
  batchTakeCash,
  createPayout,
  listMembers,
  teamBalances,
  type TeamBalance,
  type User,
} from "../api";
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
  const [booting, setBooting] = useState(true);
  const [bootError, setBootError] = useState("");

  const reloadBalances = async () => {
    setBalances(await teamBalances());
  };

  const boot = async () => {
    try {
      setBootError("");
      const rows = await listMembers();
      const active = rows.filter((m) => m.is_active !== false);
      setMembers(active);
      if (active[0]) setUserId(active[0].id);
      await reloadBalances();
    } catch (e) {
      setBootError(e instanceof Error ? e.message : "Failed");
      Alert.alert("Fos", e instanceof Error ? e.message : "Failed");
    } finally {
      setBooting(false);
    }
  };

  useEffect(() => {
    void boot();
  }, []);

  const selectedBal = balances.find((b) => b.user_id === userId);
  const suggested =
    kind === "expense_payout"
      ? selectedBal?.available_spendings ?? selectedBal?.spendings ?? 0
      : selectedBal?.available_cash ?? selectedBal?.cash_on_hand ?? 0;
  const reserved =
    kind === "expense_payout"
      ? selectedBal?.reserved_spendings ?? 0
      : selectedBal?.reserved_cash ?? 0;

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
    const total =
      kind === "expense_payout"
        ? selectedBal?.spendings ?? 0
        : selectedBal?.cash_on_hand ?? 0;
    if (value > suggested + 1e-6) {
      if (kind === "income_handover") {
        Alert.alert(
          "Fos",
          `Only ${suggested.toLocaleString()} available to take` +
            ` (${total.toLocaleString()} held` +
            `${reserved > 0 ? `, ${reserved.toLocaleString()} reserved` : ""}).`,
        );
        return;
      }
      // expense_payout: overpayment only when nothing is reserved
      if (reserved > 1e-9) {
        Alert.alert(
          "Fos",
          `Only ${suggested.toLocaleString()} available to pay` +
            ` (${total.toLocaleString()} owed, ${reserved.toLocaleString()} reserved by pending requests).`,
        );
        return;
      }
      Alert.alert(
        "Fos",
        `Amount exceeds spendings owed (${total.toLocaleString()}). Extra ${
          (value - total).toLocaleString()
        } will be recorded as overpayment. Continue?`,
        [
          { text: "Cancel", style: "cancel" },
          { text: "Continue", onPress: () => void doSubmit(value) },
        ],
      );
      return;
    }
    const who = members.find((m) => m.id === userId)?.full_name || "teammate";
    const label =
      kind === "expense_payout"
        ? `Pay ${who} expense reimbursement ${value.toLocaleString()} via ${method}?`
        : `Take cash handover ${value.toLocaleString()} from ${who} via ${method}?`;
    Alert.alert("Fos", label, [
      { text: "Cancel", style: "cancel" },
      { text: "Confirm", onPress: () => void doSubmit(value) },
    ]);
  };

  const doSubmit = async (value: number) => {
    setBusy(true);
    try {
      await createPayout({
        user_id: userId!,
        kind,
        amount: value,
        payment_method: method,
        note,
      });
      Alert.alert(
        "Fos",
        kind === "expense_payout" ? "Expense reimbursement recorded" : "Cash handover recorded",
      );
      onDone();
    } catch (e) {
      Alert.alert("Fos", e instanceof Error ? e.message : "Failed");
    } finally {
      setBusy(false);
    }
  };

  const payAllSpendings = async () => {
    Alert.alert("Fos", "Pay available spendings for all teammates?", [
      { text: "Cancel", style: "cancel" },
      {
        text: "Pay all",
        onPress: async () => {
          setBusy(true);
          try {
            const rows = (await batchPaySpendings(method)) as unknown[];
            Alert.alert(
              "Fos",
              `Paid spendings for ${Array.isArray(rows) ? rows.length : 0} teammate(s)`,
            );
            await reloadBalances();
            onDone();
          } catch (e) {
            Alert.alert("Fos", e instanceof Error ? e.message : "Failed");
          } finally {
            setBusy(false);
          }
        },
      },
    ]);
  };

  const takeAllCash = async () => {
    Alert.alert("Fos", "Take available cash from all teammates?", [
      { text: "Cancel", style: "cancel" },
      {
        text: "Take all",
        onPress: async () => {
          setBusy(true);
          try {
            const rows = (await batchTakeCash(method)) as unknown[];
            Alert.alert(
              "Fos",
              `Took cash from ${Array.isArray(rows) ? rows.length : 0} teammate(s)`,
            );
            await reloadBalances();
            onDone();
          } catch (e) {
            Alert.alert("Fos", e instanceof Error ? e.message : "Failed");
          } finally {
            setBusy(false);
          }
        },
      },
    ]);
  };

  return (
    <Screen scroll>
      <TopBar onBack={onBack} onCancel={onBack} />
      <Label>Settlements</Label>
      {booting ? (
        <Sub>Loading teammates…</Sub>
      ) : bootError ? (
        <>
          <Sub>Could not load — {bootError}</Sub>
          <Btn
            title="Retry"
            variant="ghost"
            onPress={() => {
              setBooting(true);
              void boot();
            }}
          />
        </>
      ) : members.length === 0 ? (
        <Sub>No active teammates to settle</Sub>
      ) : (
        <>
      <Sub>
        Amount defaults to available (track minus pending requests). Overpayment is allowed only for
        expense reimbursement when nothing is reserved. Cash handover cannot exceed available cash.
      </Sub>
      <Btn
        title={busy ? "…" : "Pay all available spendings"}
        variant="secondary"
        onPress={payAllSpendings}
        disabled={busy}
      />
      <Btn
        title={busy ? "…" : "Take all available cash"}
        variant="secondary"
        onPress={takeAllCash}
        disabled={busy}
      />
      <Label>Type</Label>
      <View style={styles.kinds}>
        <Chip
          label="Expense reimbursement"
          on={kind === "expense_payout"}
          onPress={() => setKind("expense_payout")}
        />
        <Chip
          label="Cash handover"
          on={kind === "income_handover"}
          onPress={() => setKind("income_handover")}
        />
      </View>
      <Label>Teammate</Label>
      <View style={styles.kinds}>
        {members.map((m) => (
          <Chip key={m.id} label={m.full_name} on={userId === m.id} onPress={() => setUserId(m.id)} />
        ))}
      </View>
      {selectedBal && (
        <Sub>
          Spendings {selectedBal.spendings.toLocaleString()} · available{" "}
          {(selectedBal.available_spendings ?? selectedBal.spendings).toLocaleString()}
          {" · "}
          Cash {selectedBal.cash_on_hand.toLocaleString()} · available{" "}
          {(selectedBal.available_cash ?? selectedBal.cash_on_hand).toLocaleString()}
          {reserved > 0 ? ` · reserved ${reserved.toLocaleString()}` : ""}
        </Sub>
      )}
      <Label>Amount</Label>
      <Field keyboardType="decimal-pad" value={amount} onChangeText={setAmount} />
      <View style={styles.kinds}>
        <Chip
          label={kind === "expense_payout" ? "Pay available" : "Take available"}
          on={Number(amount) === suggested && suggested > 0}
          onPress={() => suggested > 0 && setAmount(String(suggested))}
        />
      </View>
      <Sub>
        Overpayment only works when no pending settlement requests reserve the track.
      </Sub>
      <Label>Method</Label>
      <View style={styles.kinds}>
        <Chip label="cash" on={method === "cash"} onPress={() => setMethod("cash")} />
        <Chip label="transfer" on={method === "transfer"} onPress={() => setMethod("transfer")} />
      </View>
      <Label>Note</Label>
      <Field value={note} onChangeText={setNote} />
      <Btn title={busy ? "…" : "Record settlement"} onPress={submit} disabled={busy} />
        </>
      )}
    </Screen>
  );
}

const styles = StyleSheet.create({
  kinds: { flexDirection: "row", gap: 8, marginBottom: 8, flexWrap: "wrap" },
});
