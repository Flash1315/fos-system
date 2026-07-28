import React, { useEffect, useRef, useState } from "react";
import { Alert, View, StyleSheet } from "react-native";
import {
  batchPaySpendings,
  batchTakeCash,
  createPayout,
  listMembers,
  makeIdempotencyKey,
  teamBalances,
  type TeamBalance,
  type User,
} from "../api";
import { Btn, Chip, Field, Label, Screen, Sub, TopBar } from "../components/ui";
import { parseFiniteMoney } from "../format";

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
  const payoutIdemRef = useRef<string | null>(null);
  const batchSpendIdemRef = useRef<string | null>(null);
  const batchCashIdemRef = useRef<string | null>(null);

  const reloadBalances = async () => {
    setBalances(await teamBalances());
  };

  const boot = async (opts?: { preserveSelection?: boolean }) => {
    const selected = userId;
    try {
      setBootError("");
      const rows = await listMembers();
      const active = rows.filter((m) => m.is_active !== false);
      setMembers(active);
      if (opts?.preserveSelection && selected != null && active.some((m) => m.id === selected)) {
        setUserId(selected);
      } else if (active[0]) {
        setUserId(active[0].id);
      } else {
        setUserId(null);
      }
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

  const onPullRefresh = async () => {
    setBooting(true);
    await boot({ preserveSelection: true });
  };

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

  useEffect(() => {
    payoutIdemRef.current = null;
  }, [userId, kind, method, amount]);

  useEffect(() => {
    batchSpendIdemRef.current = null;
    batchCashIdemRef.current = null;
  }, [method]);

  const submit = async () => {
    if (busy) return;
    const value = parseFiniteMoney(amount);
    if (!userId || value == null) {
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
          { text: "Cancel", style: "cancel", onPress: () => setBusy(false) },
          { text: "Continue", onPress: () => void doSubmit(value) },
        ],
      );
      setBusy(true);
      return;
    }
    const who = members.find((m) => m.id === userId)?.full_name || "teammate";
    const label =
      kind === "expense_payout"
        ? `Pay ${who} expense reimbursement ${value.toLocaleString()} via ${method}?`
        : `Take cash handover ${value.toLocaleString()} from ${who} via ${method}?`;
    setBusy(true);
    Alert.alert("Fos", label, [
      { text: "Cancel", style: "cancel", onPress: () => setBusy(false) },
      { text: "Confirm", onPress: () => void doSubmit(value) },
    ]);
  };

  const doSubmit = async (value: number) => {
    try {
      const bals = await teamBalances();
      setBalances(bals);
      const fresh = bals.find((b) => b.user_id === userId);
      const freshSuggested =
        kind === "expense_payout"
          ? fresh?.available_spendings ?? fresh?.spendings ?? 0
          : fresh?.available_cash ?? fresh?.cash_on_hand ?? 0;
      const freshReserved =
        kind === "expense_payout"
          ? fresh?.reserved_spendings ?? 0
          : fresh?.reserved_cash ?? 0;
      if (kind === "income_handover" && value > freshSuggested + 1e-6) {
        Alert.alert(
          "Fos",
          `Only ${freshSuggested.toLocaleString()} available now` +
            `${freshReserved > 0 ? ` (${freshReserved.toLocaleString()} reserved)` : ""}.`,
        );
        return;
      }
      if (
        kind === "expense_payout" &&
        value > freshSuggested + 1e-6 &&
        freshReserved > 1e-9
      ) {
        Alert.alert(
          "Fos",
          `Only ${freshSuggested.toLocaleString()} available now ` +
            `(${freshReserved.toLocaleString()} reserved by pending requests).`,
        );
        return;
      }
      if (!payoutIdemRef.current) payoutIdemRef.current = makeIdempotencyKey("pay");
      await createPayout(
        {
          user_id: userId!,
          kind,
          amount: value,
          payment_method: method,
          note,
        },
        { idempotencyKey: payoutIdemRef.current },
      );
      payoutIdemRef.current = null;
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
    if (busy) return;
    setBusy(true);
    try {
      const bals = await teamBalances();
      setBalances(bals);
      const payable = bals.filter((b) => (b.available_spendings ?? b.spendings) > 1e-6);
      const total = payable.reduce(
        (s, b) => s + (b.available_spendings ?? b.spendings ?? 0),
        0,
      );
      if (!payable.length) {
        Alert.alert("Fos", "No available spendings to pay");
        setBusy(false);
        return;
      }
      Alert.alert(
        "Fos",
        `Pay available spendings for ${payable.length} teammate(s) · ${total.toLocaleString()} via ${method}?`,
        [
          { text: "Cancel", style: "cancel", onPress: () => setBusy(false) },
          {
            text: "Pay all",
            onPress: async () => {
              try {
                if (!batchSpendIdemRef.current) {
                  batchSpendIdemRef.current = makeIdempotencyKey("bpay");
                }
                const rows = (await batchPaySpendings(method, {
                  idempotencyKey: batchSpendIdemRef.current,
                })) as unknown[];
                batchSpendIdemRef.current = null;
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
        ],
      );
    } catch (e) {
      Alert.alert("Fos", e instanceof Error ? e.message : "Failed");
      setBusy(false);
    }
  };

  const takeAllCash = async () => {
    if (busy) return;
    setBusy(true);
    try {
      const bals = await teamBalances();
      setBalances(bals);
      const payable = bals.filter((b) => (b.available_cash ?? b.cash_on_hand) > 1e-6);
      const total = payable.reduce(
        (s, b) => s + (b.available_cash ?? b.cash_on_hand ?? 0),
        0,
      );
      if (!payable.length) {
        Alert.alert("Fos", "No available cash to take");
        setBusy(false);
        return;
      }
      Alert.alert(
        "Fos",
        `Take available cash from ${payable.length} teammate(s) · ${total.toLocaleString()} via ${method}?`,
        [
          { text: "Cancel", style: "cancel", onPress: () => setBusy(false) },
          {
            text: "Take all",
            onPress: async () => {
              try {
                if (!batchCashIdemRef.current) {
                  batchCashIdemRef.current = makeIdempotencyKey("bcash");
                }
                const rows = (await batchTakeCash(method, {
                  idempotencyKey: batchCashIdemRef.current,
                })) as unknown[];
                batchCashIdemRef.current = null;
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
        ],
      );
    } catch (e) {
      Alert.alert("Fos", e instanceof Error ? e.message : "Failed");
      setBusy(false);
    }
  };

  return (
    <Screen scroll refreshing={booting && members.length > 0} onRefresh={() => void onPullRefresh()}>
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
