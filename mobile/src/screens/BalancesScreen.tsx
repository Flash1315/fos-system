import React, { useState } from "react";
import { Alert, FlatList, RefreshControl, Text, StyleSheet } from "react-native";
import { useFocusEffect } from "../useFocus";
import { myOrg, teamBalances, type TeamBalance } from "../api";
import { Screen, Sub, TopBar } from "../components/ui";
import { formatMoney } from "../format";
import { colors } from "../theme";

export function BalancesScreen({ onBack }: { onBack: () => void }) {
  const [rows, setRows] = useState<TeamBalance[]>([]);
  const [currency, setCurrency] = useState("IDR");
  const [refreshing, setRefreshing] = useState(false);

  const reload = async () => {
    try {
      const [list, org] = await Promise.all([teamBalances(), myOrg()]);
      setRows(list);
      setCurrency(org.currency);
    } catch (e) {
      Alert.alert("Fos", e instanceof Error ? e.message : "Failed");
    }
  };

  useFocusEffect(reload);

  return (
    <Screen>
      <TopBar onBack={onBack} onCancel={onBack} />
      <Text style={styles.title}>Team balances</Text>
      <Sub>Spendings = my pocket owed. Cash = held cash on hand.</Sub>
      <FlatList
        data={rows}
        keyExtractor={(item) => String(item.user_id)}
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
        ListEmptyComponent={<Sub>No teammates</Sub>}
        renderItem={({ item }) => (
          <Text style={styles.row}>
            <Text style={styles.name}>{item.full_name}</Text> · {item.role}
            {"\n"}
            <Text style={styles.meta}>
              Cash {formatMoney(item.cash_on_hand, currency)} · Spendings {formatMoney(item.spendings, currency)}
              {item.pending_count ? ` · ${item.pending_count} pending` : ""}
            </Text>
          </Text>
        )}
      />
    </Screen>
  );
}

const styles = StyleSheet.create({
  title: { color: colors.text, fontSize: 26, fontWeight: "700", marginVertical: 8 },
  row: {
    backgroundColor: colors.card,
    borderRadius: 12,
    padding: 12,
    marginBottom: 8,
    color: colors.text,
  },
  name: { fontWeight: "700", color: colors.text },
  meta: { color: colors.muted, marginTop: 4 },
});
