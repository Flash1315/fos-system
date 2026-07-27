import React, { useState } from "react";
import { Alert, FlatList, Text, StyleSheet, View } from "react-native";
import { useFocusEffect } from "../useFocus";
import {
  listMembers,
  resetMemberPassword,
  setMemberActive,
  setMemberRole,
  type User,
} from "../api";
import { NoteModal } from "../components/NoteModal";
import { Btn, Chip, Screen, Sub, TopBar } from "../components/ui";
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

  const reload = async () => {
    try {
      setRows(await listMembers());
    } catch (e) {
      Alert.alert("Fos", e instanceof Error ? e.message : "Failed");
    }
  };

  useFocusEffect(reload);

  const toggle = async (member: User) => {
    if (currentUser.role !== "owner") {
      Alert.alert("Fos", "Only owner can activate/deactivate");
      return;
    }
    setBusy(true);
    try {
      await setMemberActive(member.id, !member.is_active);
      await reload();
    } catch (e) {
      Alert.alert("Fos", e instanceof Error ? e.message : "Failed");
    } finally {
      setBusy(false);
    }
  };

  const changeRole = async (member: User, role: "owner" | "manager" | "employee") => {
    if (currentUser.role !== "owner") return;
    if (member.role === role) return;
    setBusy(true);
    try {
      await setMemberRole(member.id, role);
      await reload();
    } catch (e) {
      Alert.alert("Fos", e instanceof Error ? e.message : "Failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Screen>
      <TopBar onBack={onBack} onCancel={onBack} />
      <Text style={styles.title}>Team</Text>
      <FlatList
        data={rows}
        keyExtractor={(item) => String(item.id)}
        ListEmptyComponent={<Sub>No members</Sub>}
        renderItem={({ item }) => (
          <View style={styles.card}>
            <Text style={styles.row}>
              {item.full_name} · {item.role}
              {"\n"}
              <Text style={styles.meta}>
                {item.email} · {item.is_active === false ? "inactive" : "active"}
              </Text>
            </Text>
            {currentUser.role === "owner" && item.id !== currentUser.id && (
              <>
                <View style={styles.kinds}>
                  {(["employee", "manager", "owner"] as const).map((r) => (
                    <Chip
                      key={r}
                      label={r}
                      on={item.role === r}
                      onPress={() => changeRole(item, r)}
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
                  title="Reset password"
                  variant="ghost"
                  disabled={busy}
                  onPress={() => setResetId(item.id)}
                />
              </>
            )}
          </View>
        )}
      />
      <NoteModal
        visible={resetId != null}
        title="New password (min 6)"
        onCancel={() => setResetId(null)}
        onSubmit={async (pwd) => {
          const id = resetId;
          setResetId(null);
          if (id == null) return;
          if (!pwd || pwd.length < 6) {
            Alert.alert("Fos", "Password must be at least 6 characters");
            return;
          }
          setBusy(true);
          try {
            await resetMemberPassword(id, pwd);
            Alert.alert("Fos", "Password reset");
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
