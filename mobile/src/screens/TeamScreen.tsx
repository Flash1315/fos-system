import React, { useState } from "react";
import { Alert, FlatList, RefreshControl, Share, Text, StyleSheet, View } from "react-native";
import { useFocusEffect } from "../useFocus";
import {
  listMembers,
  resetMemberPassword,
  issueMemberResetToken,
  setMemberActive,
  setMemberRole,
  type User,
} from "../api";
import { NoteModal } from "../components/NoteModal";
import { Btn, Chip, Label, Screen, Sub, TopBar } from "../components/ui";
import { passwordStrengthError } from "../format";
import { colors } from "../theme";

export function TeamScreen({
  busy,
  setBusy,
  currentUser,
  onBack,
}: {
  busy: boolean;
  setBusy: (v: boolean) => void;
  currentUser: User;
  onBack: () => void;
}) {
  const [rows, setRows] = useState<User[]>([]);
  const [resetId, setResetId] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [lastReset, setLastReset] = useState<{
    name: string;
    slug: string;
    email: string;
    token: string;
    emailSent?: boolean;
  } | null>(null);

  const reload = async () => {
    try {
      setLoadError("");
      setRows(await listMembers());
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : "Failed");
      Alert.alert("Fos", e instanceof Error ? e.message : "Failed");
    } finally {
      setLoading(false);
    }
  };

  useFocusEffect(reload);

  const toggle = async (member: User) => {
    if (busy) return;
    if (currentUser.role !== "owner") {
      Alert.alert("Fos", "Only owner can activate/deactivate");
      return;
    }
    const nextActive = member.is_active === false;
    const activateMsg =
      member.must_set_password
        ? `Activate ${member.full_name}? They must still set a password (issue a reset token if they lost the invite).`
        : `Activate ${member.full_name}?`;
    const deactivateMsg =
      `Deactivate ${member.full_name}? They will not be able to log in. ` +
      "Blocked if they still have pending records, settlement requests, or nonzero cash/spendings.";
    Alert.alert("Fos", nextActive ? activateMsg : deactivateMsg, [
      { text: "Cancel", style: "cancel" },
      {
        text: nextActive ? "Activate" : "Deactivate",
        style: nextActive ? "default" : "destructive",
        onPress: async () => {
          if (busy) return;
          setBusy(true);
          try {
            await setMemberActive(member.id, nextActive);
            await reload();
          } catch (e) {
            Alert.alert("Fos", e instanceof Error ? e.message : "Failed");
          } finally {
            setBusy(false);
          }
        },
      },
    ]);
  };

  const changeRole = async (member: User, role: "owner" | "manager" | "employee") => {
    if (busy) return;
    if (currentUser.role !== "owner") return;
    if (member.role === role) return;
    Alert.alert("Fos", `Change ${member.full_name} role to ${role}? Their current sessions will end.`, [
      { text: "Cancel", style: "cancel" },
      {
        text: "Change",
        onPress: async () => {
          if (busy) return;
          setBusy(true);
          try {
            await setMemberRole(member.id, role);
            await reload();
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
    <Screen>
      <TopBar onBack={onBack} onCancel={onBack} />
      <Text style={styles.title}>Team</Text>
      {currentUser.role === "owner" ? (
        <View style={styles.kinds}>
          <Chip
            label={showAdvanced ? "Hide advanced" : "Show advanced"}
            on={showAdvanced}
            onPress={() => setShowAdvanced((v) => !v)}
          />
        </View>
      ) : null}
      <FlatList
        data={rows}
        keyExtractor={(item) => String(item.id)}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            tintColor={colors.accent}
            onRefresh={async () => {
              setRefreshing(true);
              await reload();
              setRefreshing(false);
            }}
          />
        }
        ListEmptyComponent={
          <Sub>
            {loading
              ? "Loading…"
              : loadError
                ? `Could not load — ${loadError}`
                : "No members"}
          </Sub>
        }
        ListHeaderComponent={
          loadError && !loading ? (
            <Btn title="Retry" variant="ghost" onPress={reload} />
          ) : null
        }
        renderItem={({ item }) => (
          <View style={styles.card}>
            <Text style={styles.row}>
              {item.full_name} · {item.role}
              {"\n"}
              <Text style={styles.meta}>
                {item.email} · {item.is_active === false ? "inactive" : "active"}
                {item.must_set_password ? " · must set password" : ""}
              </Text>
            </Text>
            {currentUser.role === "owner" && item.id !== currentUser.id && showAdvanced && (
              <>
                <View style={styles.kinds}>
                  {(["employee", "manager", "owner"] as const).map((r) => (
                    <Chip
                      key={r}
                      label={r}
                      on={item.role === r}
                      onPress={() => {
                        if (!busy) void changeRole(item, r);
                      }}
                    />
                  ))}
                </View>
                <Btn
                  title={item.is_active === false ? "Activate" : "Deactivate"}
                  variant="ghost"
                  disabled={busy}
                  onPress={() => toggle(item)}
                />
                <Btn
                  title="Issue reset token"
                  variant="ghost"
                  disabled={busy}
                  onPress={() => {
                    Alert.alert(
                      "Fos",
                      `Issue a one-time reset token for ${item.full_name}? Their current sessions will be signed out.`,
                      [
                        { text: "Cancel", style: "cancel" },
                        {
                          text: "Issue",
                          onPress: async () => {
                            setBusy(true);
                            try {
                              let res;
                              try {
                                res = await issueMemberResetToken(item.id);
                              } catch (first) {
                                const msg =
                                  first instanceof Error ? first.message : "Failed";
                                if (!/already exists|force=true/i.test(msg)) {
                                  throw first;
                                }
                                const rotate = await new Promise<boolean>((resolve) => {
                                  Alert.alert(
                                    "Fos",
                                    "An active token already exists. Rotate and invalidate the previous one?",
                                    [
                                      {
                                        text: "Cancel",
                                        style: "cancel",
                                        onPress: () => resolve(false),
                                      },
                                      {
                                        text: "Rotate",
                                        style: "destructive",
                                        onPress: () => resolve(true),
                                      },
                                    ],
                                  );
                                });
                                if (!rotate) return;
                                res = await issueMemberResetToken(item.id, { force: true });
                              }
                              const payload = {
                                name: item.full_name,
                                slug: res.organization_slug,
                                email: res.email,
                                token: res.invite_token || "",
                                emailSent: res.email_sent,
                              };
                              setLastReset(payload);
                              Alert.alert(
                                "Fos",
                                res.email_sent && !res.invite_token
                                  ? "Reset email was sent — share the company slug if needed."
                                  : `Reset token issued${res.email_sent ? " (email sent)" : ""}. Keep the details below to share.`,
                              );
                              await reload();
                            } catch (e) {
                              Alert.alert("Fos", e instanceof Error ? e.message : "Failed");
                            } finally {
                              setBusy(false);
                            }
                          },
                        },
                      ],
                    );
                  }}
                />
                <Btn
                  title="Set password (owner)"
                  variant="ghost"
                  disabled={busy}
                  onPress={() => setResetId(item.id)}
                />
              </>
            )}
          </View>
        )}
      />
      {lastReset && (
        <View style={styles.card}>
          <Label>
            {lastReset.token
              ? "Last reset token — share before leaving"
              : "Last reset — email sent"}
          </Label>
          <Sub>
            {lastReset.token
              ? `Share with ${lastReset.name}:\nSlug: ${lastReset.slug}\nEmail: ${lastReset.email}\nReset token: ${lastReset.token}\n\nThey open Accept invite and set a new password.`
              : `Reset email sent to ${lastReset.email} (${lastReset.slug}). Ask them to check their inbox.`}
          </Sub>
          {lastReset.emailSent ? <Sub>Email delivery attempted.</Sub> : null}
          <Btn
            title="Share reset details"
            variant="secondary"
            onPress={async () => {
              try {
                await Share.share({
                  message: lastReset.token
                    ? `Fos password reset\nSlug: ${lastReset.slug}\nEmail: ${lastReset.email}\n` +
                      `Reset token: ${lastReset.token}\n\nOpen Accept invite and set a new password.`
                    : `Fos password reset\nSlug: ${lastReset.slug}\nEmail: ${lastReset.email}\n` +
                      `Reset email was sent — check your inbox.`,
                });
              } catch (e) {
                Alert.alert("Fos", e instanceof Error ? e.message : "Share failed");
              }
            }}
          />
          <Btn title="Dismiss" variant="ghost" onPress={() => setLastReset(null)} />
        </View>
      )}
      <NoteModal
        visible={resetId != null}
        title="New password (min 8)"
        required
        secureTextEntry
        confirmField
        minLength={8}
        maxLength={128}
        label="New password"
        placeholder="min 8 characters, letter + digit"
        confirmLabel="Confirm password"
        confirmPlaceholder="repeat password"
        onCancel={() => setResetId(null)}
        onSubmit={async (pwd) => {
          const id = resetId;
          setResetId(null);
          if (id == null) return;
          const pwErr = passwordStrengthError(pwd);
          if (pwErr) {
            Alert.alert("Fos", pwErr);
            return;
          }
          setBusy(true);
          try {
            await resetMemberPassword(id, pwd, pwd);
            Alert.alert("Fos", "Password reset — their other sessions signed out");
            await reload();
          } catch (e) {
            Alert.alert("Fos", e instanceof Error ? e.message : "Failed");
          } finally {
            setBusy(false);
          }
        }}
      />
    </Screen>
  );
}

const styles = StyleSheet.create({
  title: { color: colors.text, fontSize: 26, fontWeight: "700", marginVertical: 8 },
  card: { backgroundColor: colors.card, borderRadius: 12, padding: 12, marginBottom: 8 },
  row: { color: colors.text, fontWeight: "600" },
  meta: { color: colors.muted, fontWeight: "400" },
  kinds: { flexDirection: "row", gap: 8, marginTop: 8, flexWrap: "wrap" },
});
