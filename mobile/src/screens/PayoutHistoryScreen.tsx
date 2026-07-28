import React, { useState } from "react";
import { Alert, FlatList, RefreshControl, Text, StyleSheet, View } from "react-native";
import { useFocusEffect } from "../useFocus";
import { listMyPayouts, listOrgPayouts, voidPayout, type User } from "../api";
import { NoteModal } from "../components/NoteModal";
import { Btn, Chip, Screen, Sub, TopBar } from "../components/ui";
import { formatMoney, formatWhen } from "../format";
import { colors } from "../theme";

type PayoutRow = {
  id: number;
  user_id: number;
  user_name: string;
  kind: string;
  amount: number;
  currency: string;
  payment_method: string;
  note: string;
  overpayment?: number;
  balance_after?: number;
  is_voided?: boolean;
  void_note?: string;
  can_void?: boolean;
  void_blocked_reason?: string | null;
  created_at: string;
};

export function PayoutHistoryScreen({
  user,
  onBack,
}: {
  user: User;
  onBack: () => void;
}) {
  const isManager = user.role === "owner" || user.role === "manager";
  const [scope, setScope] = useState<"mine" | "org">(isManager ? "org" : "mine");
  const [rows, setRows] = useState<PayoutRow[]>([]);
  const [refreshing, setRefreshing] = useState(false);
  const [voidId, setVoidId] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);

  const reload = async () => {
    try {
      const data = scope === "org" && isManager ? await listOrgPayouts() : await listMyPayouts();
      setRows(data);
    } catch (e) {
      Alert.alert("Fos", e instanceof Error ? e.message : "Failed");
    }
  };

  useFocusEffect(reload);
  React.useEffect(() => {
    void reload();
  }, [scope]);

  return (
    <Screen>
      <TopBar onBack={onBack} onCancel={onBack} />
      <Text style={styles.title}>Payout history</Text>
      {isManager && (
        <View style={styles.kinds}>
          <Chip label="Org" on={scope === "org"} onPress={() => setScope("org")} />
          <Chip label="Mine" on={scope === "mine"} onPress={() => setScope("mine")} />
        </View>
      )}
      <FlatList
        data={rows}
        keyExtractor={(item) => String(item.id)}
        contentContainerStyle={{ paddingTop: 8, paddingBottom: 40 }}
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
        ListEmptyComponent={<Sub>No settlements yet</Sub>}
        renderItem={({ item }) => (
          <View style={styles.row}>
            <Text style={styles.rowTitle}>
              {item.kind === "expense_payout" ? "Expense payout" : "Income handover"}
              {" · "}
              {formatMoney(item.amount, item.currency)}
              {item.is_voided ? " · voided" : ""}
            </Text>
            <Text style={styles.rowMeta}>
              {item.user_name} · {item.payment_method} · {formatWhen(item.created_at)}
              {item.balance_after ? ` · left ${formatMoney(item.balance_after, item.currency)}` : ""}
              {item.overpayment ? ` · overpay ${formatMoney(item.overpayment, item.currency)}` : ""}
              {item.note ? ` · ${item.note}` : ""}
              {item.void_note ? ` · void: ${item.void_note}` : ""}
            </Text>
            {isManager && !!item.can_void && (
              <Btn
                title="Void"
                variant="ghost"
                disabled={busy}
                onPress={() => setVoidId(item.id)}
              />
            )}
            {isManager &&
              !item.is_voided &&
              !item.can_void &&
              !!item.void_blocked_reason && (
                <Text style={styles.rowMeta}>{item.void_blocked_reason}</Text>
              )}
          </View>
        )}
      />
      <NoteModal
        visible={voidId != null}
        title="Void settlement"
        onCancel={() => setVoidId(null)}
        onSubmit={async (note) => {
          const id = voidId;
          setVoidId(null);
          if (id == null) return;
          setBusy(true);
          try {
            await voidPayout(id, note || "voided");
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
  kinds: { flexDirection: "row", gap: 8, marginBottom: 8, flexWrap: "wrap" },
  row: {
    backgroundColor: colors.card,
    borderRadius: 12,
    padding: 12,
    marginBottom: 8,
  },
  rowTitle: { color: colors.text, fontWeight: "600" },
  rowMeta: { color: colors.muted, marginTop: 4 },
});
