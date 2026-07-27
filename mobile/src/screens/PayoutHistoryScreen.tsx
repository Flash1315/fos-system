import React, { useState } from "react";
import { Alert, FlatList, RefreshControl, Text, StyleSheet, View } from "react-native";
import { useFocusEffect } from "../useFocus";
import { listMyPayouts, listOrgPayouts, type User } from "../api";
import { Chip, Screen, Sub, TopBar } from "../components/ui";
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
          <Text style={styles.row}>
            <Text style={styles.rowTitle}>
              {item.kind === "expense_payout" ? "Expense payout" : "Income handover"}
              {" · "}
              {formatMoney(item.amount, item.currency)}
            </Text>
            {"\n"}
            <Text style={styles.rowMeta}>
              {item.user_name} · {item.payment_method} · {formatWhen(item.created_at)}
              {item.balance_after ? ` · left ${formatMoney(item.balance_after, item.currency)}` : ""}
              {item.overpayment ? ` · overpay ${formatMoney(item.overpayment, item.currency)}` : ""}
              {item.note ? ` · ${item.note}` : ""}
            </Text>
          </Text>
        )}
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
    color: colors.text,
  },
  rowTitle: { color: colors.text, fontWeight: "600" },
  rowMeta: { color: colors.muted },
});
