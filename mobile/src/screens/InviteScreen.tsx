import React, { useEffect, useState } from "react";
import { Alert, Share, View, StyleSheet } from "react-native";
import { inviteUser, myOrg, type InviteResult, type User } from "../api";
import { Btn, Chip, Field, Label, LinkText, Screen, Sub, TopBar } from "../components/ui";
import { passwordStrengthError } from "../format";

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
  const [lastInvite, setLastInvite] = useState<{
    res: InviteResult;
    email: string;
    slug: string;
    usedTempPassword: boolean;
  } | null>(null);
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

  const shareText = (payload: {
    res: InviteResult;
    email: string;
    slug: string;
    usedTempPassword: boolean;
  }) => {
    if (payload.res.invite_token) {
      return (
        `Fos invite\nSlug: ${payload.slug}\nEmail: ${payload.email}\n` +
        `Invite token: ${payload.res.invite_token}\n\n` +
        `Open Accept invite, paste the token, and set a password.`
      );
    }
    return (
      `Fos invite\nSlug: ${payload.slug}\nEmail: ${payload.email}\n` +
      `Password: (the temporary password you set)`
    );
  };

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
    if (setTempPassword) {
      const pwErr = passwordStrengthError(password);
      if (pwErr) {
        Alert.alert("Fos", pwErr);
        return;
      }
      if (password !== passwordConfirm) {
        Alert.alert("Fos", "Passwords do not match");
        return;
      }
    }
    const mode = setTempPassword ? "temporary password" : "invite token";
    Alert.alert(
      "Fos",
      `Invite ${fullName.trim()} <${email.trim().toLowerCase()}> as ${role} via ${mode}?`,
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
      const invitedEmail = email.trim().toLowerCase();
      const res = await inviteUser({
        email: invitedEmail,
        full_name: fullName.trim(),
        role,
        ...(setTempPassword
          ? { password, password_confirm: passwordConfirm }
          : {}),
      });
      const payload = {
        res,
        email: invitedEmail,
        slug: orgSlug,
        usedTempPassword: setTempPassword,
      };
      setLastInvite(payload);
      const mailNote = res.email_sent ? " Invite email was sent." : "";
      Alert.alert("Fos", `Teammate invited.${mailNote} Keep the details below to share.`);
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
      <Field value={fullName} onChangeText={setFullName} maxLength={200} />
      <Label>Email</Label>
      <Field
        autoCapitalize="none"
        keyboardType="email-address"
        value={email}
        onChangeText={setEmail}
        maxLength={254}
      />
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
            placeholder="min 8 characters, letter + digit"
            maxLength={128}
          />
          <Label>Confirm password</Label>
          <Field
            secureTextEntry={!showPassword}
            value={passwordConfirm}
            onChangeText={setPasswordConfirm}
            placeholder="repeat password"
            maxLength={128}
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
      <Btn title={busy ? "…" : "Invite"} onPress={submit} disabled={busy} />

      {lastInvite && (
        <>
          <Label>Last invite — share before leaving</Label>
          <Sub>{shareText(lastInvite)}</Sub>
          {lastInvite.res.email_sent ? <Sub>Email delivery attempted.</Sub> : null}
          <Btn
            title="Share invite details"
            variant="secondary"
            onPress={async () => {
              try {
                await Share.share({ message: shareText(lastInvite) });
              } catch (e) {
                Alert.alert("Fos", e instanceof Error ? e.message : "Share failed");
              }
            }}
          />
          <Btn
            title="Done"
            onPress={() => {
              setLastInvite(null);
              onDone();
            }}
          />
        </>
      )}
    </Screen>
  );
}

const styles = StyleSheet.create({
  kinds: { flexDirection: "row", gap: 8, marginBottom: 8, flexWrap: "wrap" },
});
