import React, { useState } from "react";
import { Alert, FlatList, Text, StyleSheet } from "react-native";
import { useFocusEffect } from "../useFocus";
import { listMembers, setMemberActive, type User } from "../api";
import { Btn, Row, Screen, Sub, TopBar } from "../components/ui";
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

  return (
    <Screen>
      <TopBar onBack={onBack} onCancel={onBack} />
      <Text style={styles.title}>Team</Text>
      <FlatList
        data={rows}
        keyExtractor={(item) => String(item.id)}
        ListEmptyComponent={<Sub>No members</Sub>}
        renderItem={({ item }) => (
          <Row>
            <Text style={styles.row}>
              {item.full_name} · {item.role}
              {"\n"}
              <Text style={styles.meta}>{item.email} · {item.is_active === false ? "inactive" : "active"}</Text>
            </Text>
            {currentUser.role === "owner" && item.id !== currentUser.id && (
              <Btn
                title={item.is_active === false ? "Activate" : "Deactivate"}
                variant="ghost"
                disabled={busy}
                onPress={() => toggle(item)}
              />
            )}
          </Row>
        )}
      />
    </Screen>
  );
}

const styles = StyleSheet.create({
  title: { color: colors.text, fontSize: 26, fontWeight: "700", marginVertical: 8 },
  row: { color: colors.text, flex: 1, fontWeight: "600" },
  meta: { color: colors.muted, fontWeight: "400" },
});
