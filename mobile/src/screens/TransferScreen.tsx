import React, { useEffect, useRef, useState } from "react";
import { Alert, View, StyleSheet } from "react-native";
import { BILLING_READONLY_MSG, billingMe, isBillingReadOnly, makeIdempotencyKey, me, myBalance, onResumeRefresh, orgDirectory, transferCash, type User } from "../api";
import { formatMoney, parseFiniteMoney } from "../format";
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
  const [held, setHeld] = useState(0);
  const [reserved, setReserved] = useState(0);
  const [available, setAvailable] = useState(0);
  const [currency, setCurrency] = useState("IDR");
  const [bootError, setBootError] = useState("");
  const [booting, setBooting] = useState(true);
  const [billingReadonly, setBillingReadonly] = useState(false);
  const [formError, setFormError] = useState("");
  const submitLock = useRef(false);
  const idemKeyRef = useRef<string | null>(null);
  const bootstrapGen = useRef(0);

  useEffect(() => {
    idemKeyRef.current = null;
  }, [email, amount, comment]);

  const bootstrap = async () => {
    const gen = ++bootstrapGen.current;
    setBooting(true);
    setBootError("");
    try {
      const u = await me();
      if (gen !== bootstrapGen.current) return;
      const rows = await orgDirectory();
      if (gen !== bootstrapGen.current) return;
      setMembers(rows.filter((m) => m.id !== u.id));
      const bal = await myBalance();
      if (gen !== bootstrapGen.current) return;
      setHeld(bal.cash_on_hand);
      setReserved(bal.reserved_cash ?? 0);
      setAvailable(bal.available_cash ?? bal.cash_on_hand);
      setCurrency(bal.currency);
    } catch (e) {
      if (gen !== bootstrapGen.current) return;
      setBootError(e instanceof Error ? e.message : "Could not load balances");
    } finally {
      if (gen === bootstrapGen.current) setBooting(false);
    }
  };

  useEffect(() => {
    void bootstrap();
  }, []);

  useEffect(() => {
    void billingMe()
      .then((b) => setBillingReadonly(isBillingReadOnly(b.billing_status)))
      .catch(() => {});
  }, []);

  useEffect(() => onResumeRefresh(() => {
    void bootstrap();
    void billingMe()
      .then((b) => setBillingReadonly(isBillingReadOnly(b.billing_status)))
      .catch(() => {});
  }), []);

  const submit = async () => {
    if (busy || billingReadonly || submitLock.current || bootError || booting) {
      if (billingReadonly) {
        setFormError(BILLING_READONLY_MSG);
        return;
      }
      if (bootError || booting) setFormError(bootError || "Still loading balances");
      return;
    }
    setFormError("");
    const value = parseFiniteMoney(amount);
    if (!email.trim() || value == null) {
      setFormError("Recipient and amount (at least 0.01) required");
      return;
    }
    if (comment.trim().length > 2000) {
      setFormError("Comment is too long (max 2000 characters)");
      return;
    }
    if (value > available) {
      setFormError(
        `Only ${formatMoney(available, currency)} available ` +
          `(${formatMoney(held, currency)} held, ${formatMoney(reserved, currency)} reserved).`,
      );
      return;
    }
    submitLock.current = true;
    if (!idemKeyRef.current) idemKeyRef.current = makeIdempotencyKey("xfer");
    setBusy(true);
    Alert.alert(
      "Fos",
      `Transfer ${formatMoney(value, currency)} to ${email.trim()}?`,
      [
        {
          text: "Cancel",
          style: "cancel",
          onPress: () => {
            submitLock.current = false;
            setBusy(false);
          },
        },
        {
          text: "Transfer",
          onPress: async () => {
            try {
              try {
                const b = await billingMe();
                const frozen = isBillingReadOnly(b.billing_status);
                setBillingReadonly(frozen);
                if (frozen) {
                  setFormError(BILLING_READONLY_MSG);
                  return;
                }
              } catch {
                /* API will 403 if frozen */
              }
              const bal = await myBalance();
              const freshAvailable = bal.available_cash ?? bal.cash_on_hand;
              if (value > freshAvailable + 1e-6) {
                setHeld(bal.cash_on_hand);
                setReserved(bal.reserved_cash ?? 0);
                setAvailable(freshAvailable);
                setCurrency(bal.currency);
                setFormError(
                  `Only ${formatMoney(freshAvailable, bal.currency)} available now ` +
                    `(${formatMoney(bal.cash_on_hand, bal.currency)} held, ${formatMoney(bal.reserved_cash ?? 0, bal.currency)} reserved).`,
                );
                return;
              }
              await transferCash(
                {
                  to_email: email.trim().toLowerCase(),
                  amount: value,
                  comment: comment.trim(),
                },
                { idempotencyKey: idemKeyRef.current || undefined },
              );
              idemKeyRef.current = null;
              Alert.alert("Fos", "Transfer recorded — cash balances updated");
              onDone();
            } catch (e) {
              setFormError(e instanceof Error ? e.message : "Transfer failed");
            } finally {
              submitLock.current = false;
              setBusy(false);
            }
          },
        },
      ],
    );
  };

  return (
    <Screen scroll onRefresh={() => void bootstrap()} refreshing={booting && !bootError && members.length > 0}>
      <TopBar onBack={onBack} onCancel={onBack} />
      <Label>Transfer cash to teammate</Label>
      {billingReadonly ? <Sub>{BILLING_READONLY_MSG}</Sub> : null}
      <Sub>Moves available cash on hand immediately (approved transfer pair).</Sub>
      {booting ? (
        <Sub>Loading balances…</Sub>
      ) : bootError ? (
        <>
          <Sub>Could not load — {bootError}</Sub>
          <Btn title="Retry" variant="ghost" onPress={bootstrap} />
        </>
      ) : (
        <Sub>
          Held {formatMoney(held, currency)}
          {reserved > 0 ? ` · reserved ${formatMoney(reserved, currency)}` : ""}
          {" · "}
          available {formatMoney(available, currency)}
        </Sub>
      )}
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
        maxLength={254}
      />
      <Label>Amount</Label>
      <Field keyboardType="decimal-pad" value={amount} onChangeText={setAmount} maxLength={24} />
      <Label>Comment</Label>
      <Field value={comment} onChangeText={setComment} maxLength={2000} />
      <Btn
        title={busy ? "…" : "Submit transfer"}
        onPress={submit}
        disabled={busy || billingReadonly || booting || !!bootError}
      />
      {!!formError && <Sub>{formError}</Sub>}
    </Screen>
  );
}

const styles = StyleSheet.create({
  kinds: { flexDirection: "row", gap: 8, marginBottom: 8, flexWrap: "wrap" },
});
