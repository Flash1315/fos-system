import React, { useState } from "react";
import { Alert, FlatList, Text, View, StyleSheet } from "react-native";
import { useFocusEffect } from "../useFocus";
import { decideRecord, pendingRecords, type MoneyRecord } from "../api";
import { Btn, Row, Screen, Sub, TopBar } from "../components/ui";
import { colors } from "../theme";

export function ApproveScreen({
  busy,
  setBusy,
  onBack,
  onRecord,
}: {
  busy: boolean;
  setBusy: (v: boolean) => void;
  onBack: () => void;
  onRecord: (id: number) => void;
}) {
  const [rows, setRows] = useState<MoneyRecord[]>([]);

  const reload = async () => {
    try {
      setRows(await pendingRecords());
    } catch (e) {
      Alert.alert("Fos", e instanceof Error ? e.message : "Failed");
    }
  };

  useFocusEffect(reload);

  const decide = async (id: number, approve: boolean) => {
    setBusy(true);
    try {
      await decideRecord(id, approve);
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
      <Text style={styles.title}>Approvals</Text>
      <FlatList
        data={rows}
        keyExtractor={(item) => String(item.id)}
        ListEmptyComponent={<Sub>No pending records</Sub>}
        renderItem={({ item }) => (
          <View style={styles.row}>
            <Text style={styles.rowTitle} onPress={() => onRecord(item.id)}>
              {item.kind} · {item.amount.toLocaleString()} {item.currency}
            </Text>
            <Text style={styles.rowMeta}>
              {item.created_by_name || "—"} · {item.category || item.comment || "—"}
            </Text>
            <Row>
              <Btn title="Approve" disabled={busy} onPress={() => decide(item.id, true)} />
              <Btn title="Reject" variant="danger" disabled={busy} onPress={() => decide(item.id, false)} />
            </Row>
          </View>
        )}
      />
    </Screen>
  );
}

const styles = StyleSheet.create({
  title: { color: colors.text, fontSize: 26, fontWeight: "700", marginVertical: 8 },
  row: { backgroundColor: colors.card, borderRadius: 12, padding: 12, marginBottom: 8 },
  rowTitle: { color: colors.text, fontWeight: "600", textTransform: "capitalize" },
  rowMeta: { color: colors.muted, marginTop: 4 },
});
