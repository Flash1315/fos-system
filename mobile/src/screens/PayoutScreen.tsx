import React, { useEffect, useRef, useState } from "react";
import { Alert, View, StyleSheet } from "react-native";
import {
  BILLING_READONLY_MSG,
  billingMe,
  batchPaySpendings,
  batchTakeCash,
  createPayout,
  isBillingReadOnly,
  onResumeRefresh,
  makeIdempotencyKey,
  orgDirectory,
  teamBalances,
  type TeamBalance,
  type User,
} from "../api";
import { Btn, Chip, Field, Label, Screen, Sub, TopBar } from "../components/ui";
import { formatMoney, parseFiniteMoney } from "../format";

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
  const [billingReadonly, setBillingReadonly] = useState(false);
  const [actionError, setActionError] = useState("");
  const payoutIdemRef = useRef<string | null>(null);
  const batchSpendIdemRef = useRef<string | null>(null);
  const batchCashIdemRef = useRef<string | null>(null);
  const amountDirty = useRef(false);
  const bootGen = useRef(0);
  const balancesGen = useRef(0);

  const reloadBalances = async (expectedBootGen?: number) => {
    const gen = ++balancesGen.current;
    try {
      const next = await teamBalances();
      if (gen !== balancesGen.current) return;
      if (expectedBootGen != null && expectedBootGen !== bootGen.current) return;
      setBalances(next);
    } catch (e) {
      if (gen !== balancesGen.current) return;
      if (expectedBootGen != null && expectedBootGen !== bootGen.current) return;
      throw e;
    }
  };

  const boot = async (opts?: { preserveSelection?: boolean }) => {
    const gen = ++bootGen.current;
    const selected = userId;
    try {
      setBootError("");
      const rows = await orgDirectory();
      if (gen !== bootGen.current) return;
      const active = rows.filter((m) => m.is_active !== false && !m.must_set_password);
      setMembers(active);
      if (opts?.preserveSelection && selected != null && active.some((m) => m.id === selected)) {
        setUserId(selected);
      } else if (active[0]) {
        setUserId(active[0].id);
      } else {
        setUserId(null);
      }
      await reloadBalances(gen);
    } catch (e) {
      if (gen !== bootGen.current) return;
      setBootError(e instanceof Error ? e.message : "Failed");
    } finally {
      if (gen === bootGen.current) setBooting(false);
    }
  };

  useEffect(() => {
    void boot();
  }, []);

  useEffect(() => {
    void billingMe()
      .then((b) => setBillingReadonly(isBillingReadOnly(b.billing_status)))
      .catch(() => {});
  }, []);

  useEffect(() => onResumeRefresh(() => {
    void billingMe()
      .then((b) => setBillingReadonly(isBillingReadOnly(b.billing_status)))
      .catch(() => {});
    void boot({ preserveSelection: true });
  }), []);

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
    amountDirty.current = false;
  }, [userId, kind]);

  useEffect(() => {
    if (!amountDirty.current) {
      if (suggested > 0) setAmount(String(suggested));
      else setAmount("");
    }
  }, [userId, kind, suggested]);

  useEffect(() => {
    payoutIdemRef.current = null;
  }, [userId, kind, method, amount, note]);

  useEffect(() => {
    batchSpendIdemRef.current = null;
    batchCashIdemRef.current = null;
  }, [method]);

  const submit = async () => {
    if (busy || billingReadonly) return;
    setActionError("");
    const value = parseFiniteMoney(amount);
    if (!userId || value == null) {
      setActionError("Select teammate and amount");
      return;
    }
    const total =
      kind === "expense_payout"
        ? selectedBal?.spendings ?? 0
        : selectedBal?.cash_on_hand ?? 0;
    if (value > suggested + 1e-6) {
      if (kind === "income_handover") {
        setActionError(
          `Only ${formatMoney(suggested, selectedBal?.currency || "IDR")} available to take` +
            ` (${formatMoney(total, selectedBal?.currency || "IDR")} held` +
            `${reserved > 0 ? `, ${formatMoney(reserved, selectedBal?.currency || "IDR")} reserved` : ""}).`,
        );
        return;
      }
      // expense_payout: overpayment only when nothing is reserved
      if (reserved > 1e-9) {
        setActionError(
          `Only ${formatMoney(suggested, selectedBal?.currency || "IDR")} available to pay` +
            ` (${formatMoney(total, selectedBal?.currency || "IDR")} owed, ${formatMoney(reserved, selectedBal?.currency || "IDR")} reserved by pending requests).`,
        );
        return;
      }
      let confirmed = false;
      Alert.alert(
        "Fos",
        `Amount exceeds spendings owed (${formatMoney(total, selectedBal?.currency || "IDR")}). Extra ${
          formatMoney(value - total, selectedBal?.currency || "IDR")
        } will be recorded as overpayment. Continue?`,
        [
          { text: "Cancel", style: "cancel", onPress: () => setBusy(false) },
          {
            text: "Continue",
            onPress: () => {
              confirmed = true;
              void doSubmit(value);
            },
          },
        ],
        {
          cancelable: true,
          onDismiss: () => {
            if (!confirmed) setBusy(false);
          },
        },
      );
      setBusy(true);
      return;
    }
    const who = members.find((m) => m.id === userId)?.full_name || "teammate";
    const label =
      kind === "expense_payout"
        ? `Pay ${who} expense reimbursement ${formatMoney(value, selectedBal?.currency || "IDR")} via ${method}?`
        : `Take cash handover ${formatMoney(value, selectedBal?.currency || "IDR")} from ${who} via ${method}?`;
    setBusy(true);
    let confirmed = false;
    Alert.alert(
      "Fos",
      label,
      [
        { text: "Cancel", style: "cancel", onPress: () => setBusy(false) },
        {
          text: "Confirm",
          onPress: () => {
            confirmed = true;
            void doSubmit(value);
          },
        },
      ],
      {
        cancelable: true,
        onDismiss: () => {
          if (!confirmed) setBusy(false);
        },
      },
    );
  };

  const doSubmit = async (value: number) => {
    if (busy || billingReadonly) {
      if (billingReadonly) setActionError(BILLING_READONLY_MSG);
      return;
    }
    setActionError("");
    try {
      try {
        const b = await billingMe();
        const frozen = isBillingReadOnly(b.billing_status);
        setBillingReadonly(frozen);
        if (frozen) {
          setActionError(BILLING_READONLY_MSG);
          return;
        }
      } catch { /* API 403 if frozen */ }
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
        setActionError(
          `Only ${formatMoney(freshSuggested, fresh?.currency || selectedBal?.currency || "IDR")} available now` +
            `${freshReserved > 0 ? ` (${formatMoney(freshReserved, fresh?.currency || selectedBal?.currency || "IDR")} reserved)` : ""}.`,
        );
        return;
      }
      if (
        kind === "expense_payout" &&
        value > freshSuggested + 1e-6 &&
        freshReserved > 1e-9
      ) {
        setActionError(
          `Only ${formatMoney(freshSuggested, fresh?.currency || selectedBal?.currency || "IDR")} available now ` +
            `(${formatMoney(freshReserved, fresh?.currency || selectedBal?.currency || "IDR")} reserved by pending requests).`,
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
      setActionError(e instanceof Error ? e.message : "Settlement failed");
    } finally {
      setBusy(false);
    }
  };

  const payAllSpendings = async () => {
    if (busy || billingReadonly) {
      if (billingReadonly) setActionError(BILLING_READONLY_MSG);
      return;
    }
    setActionError("");
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
        setActionError("No available spendings to pay");
        setBusy(false);
        return;
      }
      let confirmed = false;
      Alert.alert(
        "Fos",
        `Pay available spendings for ${payable.length} teammate(s) · ${formatMoney(total, payable[0]?.currency || selectedBal?.currency || "IDR")} via ${method}?`,
        [
          { text: "Cancel", style: "cancel", onPress: () => setBusy(false) },
          {
            text: "Pay all",
            onPress: async () => {
              confirmed = true;
              try {
                try {
                  const b = await billingMe();
                  const frozen = isBillingReadOnly(b.billing_status);
                  setBillingReadonly(frozen);
                  if (frozen) {
                    setActionError(BILLING_READONLY_MSG);
                    return;
                  }
                } catch { /* API 403 if frozen */ }
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
                setActionError(e instanceof Error ? e.message : "Could not pay spendings");
              } finally {
                setBusy(false);
              }
            },
          },
        ],
        {
          cancelable: true,
          onDismiss: () => {
            if (!confirmed) setBusy(false);
          },
        },
      );
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Could not load spendings");
      setBusy(false);
    }
  };

  const takeAllCash = async () => {
    if (busy || billingReadonly) {
      if (billingReadonly) setActionError(BILLING_READONLY_MSG);
      return;
    }
    setActionError("");
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
        setActionError("No available cash to take");
        setBusy(false);
        return;
      }
      let confirmed = false;
      Alert.alert(
        "Fos",
        `Take available cash from ${payable.length} teammate(s) · ${formatMoney(total, payable[0]?.currency || selectedBal?.currency || "IDR")} via ${method}?`,
        [
          { text: "Cancel", style: "cancel", onPress: () => setBusy(false) },
          {
            text: "Take all",
            onPress: async () => {
              confirmed = true;
              try {
                try {
                  const b = await billingMe();
                  const frozen = isBillingReadOnly(b.billing_status);
                  setBillingReadonly(frozen);
                  if (frozen) {
                    setActionError(BILLING_READONLY_MSG);
                    return;
                  }
                } catch { /* API 403 if frozen */ }
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
                setActionError(e instanceof Error ? e.message : "Could not take cash");
              } finally {
                setBusy(false);
              }
            },
          },
        ],
        {
          cancelable: true,
          onDismiss: () => {
            if (!confirmed) setBusy(false);
          },
        },
      );
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Could not load cash");
      setBusy(false);
    }
  };

  return (
    <Screen scroll refreshing={booting && members.length > 0} onRefresh={() => void onPullRefresh()}>
      <TopBar onBack={onBack} onCancel={onBack} />
      <Label>Settlements</Label>
      {billingReadonly ? <Sub>{BILLING_READONLY_MSG}</Sub> : null}
      {!!actionError && <Sub>{actionError}</Sub>}
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
        disabled={busy || billingReadonly}
      />
      <Btn
        title={busy ? "…" : "Take all available cash"}
        variant="secondary"
        onPress={takeAllCash}
        disabled={busy || billingReadonly}
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
          Spendings {formatMoney(selectedBal.spendings, selectedBal.currency || "IDR")} · available{" "}
          {formatMoney(
            selectedBal.available_spendings ?? selectedBal.spendings,
            selectedBal.currency || "IDR",
          )}
          {" · "}
          Cash {formatMoney(selectedBal.cash_on_hand, selectedBal.currency || "IDR")} · available{" "}
          {formatMoney(
            selectedBal.available_cash ?? selectedBal.cash_on_hand,
            selectedBal.currency || "IDR",
          )}
          {reserved > 0
            ? ` · reserved ${formatMoney(reserved, selectedBal.currency || "IDR")}`
            : ""}
        </Sub>
      )}
      <Label>Amount</Label>
      <Field
        keyboardType="decimal-pad"
        value={amount}
        onChangeText={(text) => {
          amountDirty.current = true;
          setAmount(text);
        }}
        maxLength={24}
      />
      <View style={styles.kinds}>
        <Chip
          label={kind === "expense_payout" ? "Pay available" : "Take available"}
          on={Number(amount) === suggested && suggested > 0}
          onPress={() => {
            if (suggested > 0) {
              amountDirty.current = false;
              setAmount(String(suggested));
            }
          }}
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
      <Field value={note} onChangeText={setNote} maxLength={2000} />
      <Btn title={busy ? "…" : "Record settlement"} onPress={submit} disabled={busy || billingReadonly} />
        </>
      )}
    </Screen>
  );
}

const styles = StyleSheet.create({
  kinds: { flexDirection: "row", gap: 8, marginBottom: 8, flexWrap: "wrap" },
});
