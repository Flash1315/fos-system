import React, { useState } from "react";
import { Alert, View, StyleSheet } from "react-native";
import { inviteUser, type User } from "../api";
import { Btn, Chip, Field, Label, Screen, TopBar } from "../components/ui";

export function InviteScreen({
  busy,
  setBusy,
  currentRole,
  onBack,
  onDone,
}: {
  busy: boolean;
  setBusy: (v: boolean) => void;
  currentRole: User["role"];
  onBack: () => void;
  onDone: () => void;
}) {
  const [email, setEmail] = useState("");
  const [fullName, setFullName] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<"employee" | "manager" | "owner">("employee");
  const roles =
    currentRole === "owner"
      ? (["employee", "manager", "owner"] as const)
      : (["employee", "manager"] as const);

  const submit = async () => {
    if (!email.trim() || !fullName.trim() || password.length < 6) {
      Alert.alert("Fos", "Name, email, and password (6+) required");
      return;
    }
    setBusy(true);
    try {
      await inviteUser({
        email: email.trim(),
        full_name: fullName.trim(),
        role,
        password,
      });
      Alert.alert("Fos", "Teammate invited");
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
      <Label>Invite teammate</Label>
      <Label>Full name</Label>
      <Field value={fullName} onChangeText={setFullName} />
      <Label>Email</Label>
      <Field autoCapitalize="none" keyboardType="email-address" value={email} onChangeText={setEmail} />
      <Label>Password</Label>
      <Field secureTextEntry value={password} onChangeText={setPassword} />
      <Label>Role</Label>
      <View style={styles.kinds}>
        {roles.map((r) => (
          <Chip key={r} label={r} on={role === r} onPress={() => setRole(r)} />
        ))}
      </View>
      <Btn title={busy ? "…" : "Send invite"} onPress={submit} disabled={busy} />
    </Screen>
  );
}

const styles = StyleSheet.create({
  kinds: { flexDirection: "row", gap: 8, marginBottom: 8, flexWrap: "wrap" },
});
