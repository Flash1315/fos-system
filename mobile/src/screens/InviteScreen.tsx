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
  const [passwordConfirm, setPasswordConfirm] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [setTempPassword, setSetTempPassword] = useState(false);
  const [orgSlug, setOrgSlug] = useState("");
  const [slugError, setSlugError] = useState("");
  const [role, setRole] = useState<"employee" | "manager" | "owner">("employee");
  const roles =
    currentRole === "owner"
      ? (["employee", "manager", "owner"] as const)
      : (["employee"] as const);

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
    if (busy) return;
    if (!orgSlug) {
      Alert.alert("Fos", "Company slug not loaded — tap Retry first");
      return;
    }
    if (!email.trim() || !fullName.trim()) {
      Alert.alert("Fos", "Name and email required");
      return;
    }
    if (setTempPassword && password.length < 6) {
      Alert.alert("Fos", "Temporary password must be at least 6 characters");
      return;
    }
    if (setTempPassword && password !== passwordConfirm) {
      Alert.alert("Fos", "Passwords do not match");
      return;
    }
    const mode = setTempPassword ? "temporary password" : "invite token";
    Alert.alert(
      "Fos",
      `Invite ${fullName.trim()} <${email.trim()}> as ${role} via ${mode}?`,
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Send invite",
          onPress: () => void doInvite(),
        },
      ],
    );
  };

  const doInvite = async () => {
    if (busy) return;
    setBusy(true);
    try {
      const res = await inviteUser({
        email: email.trim(),
        full_name: fullName.trim(),
        role,
        ...(setTempPassword
          ? { password, password_confirm: passwordConfirm }
          : {}),
      });
      if (res.invite_token) {
        Alert.alert(
          "Fos",
          `Teammate invited.\n\nShare:\nSlug: ${orgSlug}\nEmail: ${email.trim()}\nInvite token: ${res.invite_token}\n\nThey open Accept invite, paste the token, and set their own password.`,
        );
      } else {
        Alert.alert(
          "Fos",
          `Teammate invited.\n\nShare login:\nSlug: ${orgSlug}\nEmail: ${email.trim()}\nPassword: (the one you set)`,
        );
      }
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
        Default: share an invite token — they set their own password. Optional: set a temporary
        password yourself.
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
      <View style={styles.kinds}>
        <Chip
          label="Invite token (recommended)"
          on={!setTempPassword}
          onPress={() => setSetTempPassword(false)}
        />
        <Chip
          label="Temp password"
          on={setTempPassword}
          onPress={() => setSetTempPassword(true)}
        />
      </View>
      {setTempPassword && (
        <>
          <Label>Temporary password</Label>
          <Field
            secureTextEntry={!showPassword}
            value={password}
            onChangeText={setPassword}
            placeholder="min 6 characters"
          />
          <Label>Confirm password</Label>
          <Field
            secureTextEntry={!showPassword}
            value={passwordConfirm}
            onChangeText={setPasswordConfirm}
            placeholder="repeat password"
          />
          <LinkText onPress={() => setShowPassword((v) => !v)}>
            {showPassword ? "Hide password" : "Show password"}
          </LinkText>
        </>
      )}
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
