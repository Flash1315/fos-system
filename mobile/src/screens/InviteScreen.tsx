import React, { useEffect, useState } from "react";
import { Alert, View, StyleSheet } from "react-native";
import { inviteUser, myOrg, type User } from "../api";
import { Btn, Chip, Field, Label, LinkText, Screen, Sub, TopBar } from "../components/ui";

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
  const [showPassword, setShowPassword] = useState(false);
  const [orgSlug, setOrgSlug] = useState("");
  const [slugError, setSlugError] = useState("");
  const [role, setRole] = useState<"employee" | "manager" | "owner">("employee");
  const roles =
    currentRole === "owner"
      ? (["employee", "manager", "owner"] as const)
      : (["employee", "manager"] as const);

  const loadSlug = async () => {
    try {
      setSlugError("");
      const org = await myOrg();
      setOrgSlug(org.slug);
    } catch (e) {
      setOrgSlug("");
      setSlugError(e instanceof Error ? e.message : "Could not load company slug");
    }
  };

  useEffect(() => {
    void loadSlug();
  }, []);

  const submit = async () => {
    if (!orgSlug) {
      Alert.alert("Fos", "Company slug not loaded — tap Retry first");
      return;
    }
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
      Alert.alert(
        "Fos",
        `Teammate invited.\n\nShare login:\nSlug: ${orgSlug}\nEmail: ${email.trim()}\nPassword: (the one you set)`,
      );
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
      <Sub>
        They log in with company slug{orgSlug ? ` /${orgSlug}` : ""}, the email below, and the
        temporary password you set.
      </Sub>
      {!!slugError && (
        <>
          <Sub>Could not load slug — {slugError}</Sub>
          <Btn title="Retry" variant="ghost" onPress={loadSlug} />
        </>
      )}
      <Label>Full name</Label>
      <Field value={fullName} onChangeText={setFullName} />
      <Label>Email</Label>
      <Field autoCapitalize="none" keyboardType="email-address" value={email} onChangeText={setEmail} />
      <Label>Password</Label>
      <Field
        secureTextEntry={!showPassword}
        value={password}
        onChangeText={setPassword}
        placeholder="min 6 characters"
      />
      <LinkText onPress={() => setShowPassword((v) => !v)}>
        {showPassword ? "Hide password" : "Show password"}
      </LinkText>
      <Label>Role</Label>
      <View style={styles.kinds}>
        {roles.map((r) => (
          <Chip key={r} label={r} on={role === r} onPress={() => setRole(r)} />
        ))}
      </View>
      <Btn
        title={busy ? "…" : "Send invite"}
        onPress={submit}
        disabled={busy || !orgSlug}
      />
    </Screen>
  );
}

const styles = StyleSheet.create({
  kinds: { flexDirection: "row", gap: 8, marginBottom: 8, flexWrap: "wrap" },
});
