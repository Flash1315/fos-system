import React, { useState } from "react";
import { Alert, FlatList, RefreshControl, Text, View, StyleSheet } from "react-native";
import { useFocusEffect } from "../useFocus";
import { decideBatch, decideRecord, pendingRecords, type MoneyRecord } from "../api";
import { NoteModal } from "../components/NoteModal";
import { Btn, Row, Screen, Sub, TopBar } from "../components/ui";
import { formatMoney, formatWhen } from "../format";
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
  const [refreshing, setRefreshing] = useState(false);
  const [rejectId, setRejectId] = useState<number | null>(null);
  const [rejectAllOpen, setRejectAllOpen] = useState(false);

  const reload = async () => {
    try {
      setRows(await pendingRecords());
    } catch (e) {
      Alert.alert("Fos", e instanceof Error ? e.message : "Failed");
    }
  };

  useFocusEffect(reload);

  const runDecide = async (id: number, approve: boolean, note = "") => {
    setBusy(true);
    try {
      await decideRecord(id, approve, note);
      await reload();
    } catch (e) {
      Alert.alert("Fos", e instanceof Error ? e.message : "Failed");
    } finally {
      setBusy(false);
    }
  };

  const approveAll = async () => {
    if (!rows.length) return;
    setBusy(true);
    try {
      await decideBatch(
        rows.map((r) => r.id),
        true,
      );
      await reload();
    } catch (e) {
      Alert.alert("Fos", e instanceof Error ? e.message : "Failed");
    } finally {
      setBusy(false);
    }
  };

  const rejectAll = async (note: string) => {
    if (!rows.length) return;
    setBusy(true);
    try {
      await decideBatch(
        rows.map((r) => r.id),
        false,
        note || "batch reject",
      );
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
      {rows.length > 0 && (
        <Row>
          <Btn
            title={busy ? "…" : `Approve all (${rows.length})`}
            onPress={approveAll}
            disabled={busy}
          />
          <Btn
            title="Reject all"
            variant="danger"
            onPress={() => setRejectAllOpen(true)}
            disabled={busy}
          />
        </Row>
      )}
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
        ListEmptyComponent={<Sub>No pending records</Sub>}
        renderItem={({ item }) => (
          <View style={styles.row}>
            <Text style={styles.rowTitle} onPress={() => onRecord(item.id)}>
              {item.kind} · {formatMoney(item.amount, item.currency)}
            </Text>
            <Text style={styles.rowMeta}>
              {item.created_by_name || "—"} · {item.category || item.comment || "—"}
              {item.purpose ? ` · ${item.purpose}` : ""}
              {item.payment_source === "my_pocket"
                ? " · my pocket"
                : item.payment_source === "cash_on_hand"
                  ? " · cash"
                  : ""}
            </Text>
            <Text style={styles.rowMeta}>{formatWhen(item.created_at)}</Text>
            <Row>
              <Btn title="Approve" disabled={busy} onPress={() => runDecide(item.id, true)} />
              <Btn
                title="Reject"
                variant="danger"
                disabled={busy}
                onPress={() => setRejectId(item.id)}
              />
            </Row>
          </View>
        )}
      />
      <NoteModal
        visible={rejectId != null}
        title="Reject record"
        onCancel={() => setRejectId(null)}
        onSubmit={async (note) => {
          const id = rejectId;
          setRejectId(null);
          if (id != null) await runDecide(id, false, note);
        }}
      />
      <NoteModal
        visible={rejectAllOpen}
        title="Reject all pending"
        onCancel={() => setRejectAllOpen(false)}
        onSubmit={async (note) => {
          setRejectAllOpen(false);
          await rejectAll(note);
        }}
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
