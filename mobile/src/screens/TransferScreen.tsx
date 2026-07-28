import React, { useEffect, useState } from "react";
import { Alert, View, StyleSheet } from "react-native";
import { me, myBalance, orgDirectory, transferCash, type User } from "../api";
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

  const bootstrap = async () => {
    setBooting(true);
    setBootError("");
    try {
      const u = await me();
      const rows = await orgDirectory();
      setMembers(rows.filter((m) => m.id !== u.id));
      const bal = await myBalance();
      setHeld(bal.cash_on_hand);
      setReserved(bal.reserved_cash ?? 0);
      setAvailable(bal.available_cash ?? bal.cash_on_hand);
      setCurrency(bal.currency);
    } catch (e) {
      setBootError(e instanceof Error ? e.message : "Could not load balances");
    } finally {
      setBooting(false);
    }
  };

  useEffect(() => {
    void bootstrap();
  }, []);

  const submit = async () => {
    if (bootError || booting) {
      Alert.alert("Fos", bootError || "Still loading balances");
      return;
    }
    const value = Number(amount.replace(",", "."));
    if (!email.trim() || !value || value <= 0) {
      Alert.alert("Fos", "Recipient and amount required");
      return;
    }
    if (value > available) {
      Alert.alert(
        "Fos",
        `Only ${available.toLocaleString()} ${currency} available ` +
          `(${held.toLocaleString()} held, ${reserved.toLocaleString()} reserved).`,
      );
      return;
    }
    Alert.alert(
      "Fos",
      `Transfer ${value.toLocaleString()} ${currency} to ${email.trim()}?`,
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Transfer",
          onPress: async () => {
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
          },
        },
      ],
    );
  };

  return (
    <Screen scroll>
      <TopBar onBack={onBack} onCancel={onBack} />
      <Label>Transfer cash to teammate</Label>
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
          Held {held.toLocaleString()} {currency}
          {reserved > 0 ? ` · reserved ${reserved.toLocaleString()}` : ""}
          {" · "}
          available {available.toLocaleString()}
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
      />
      <Label>Amount</Label>
      <Field keyboardType="decimal-pad" value={amount} onChangeText={setAmount} />
      <Label>Comment</Label>
      <Field value={comment} onChangeText={setComment} />
      <Btn
        title={busy ? "…" : "Submit transfer"}
        onPress={submit}
        disabled={busy || booting || !!bootError}
      />
    </Screen>
  );
}

const styles = StyleSheet.create({
  kinds: { flexDirection: "row", gap: 8, marginBottom: 8, flexWrap: "wrap" },
});
