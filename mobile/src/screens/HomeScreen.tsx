import React, { useEffect, useState } from "react";
import { Alert, FlatList, Pressable, RefreshControl, Text, View, StyleSheet } from "react-native";
import { useFocusEffect } from "../useFocus";
import { myBalance, myOrg, myRecords, type MoneyRecord, type User } from "../api";
import { Brand, Btn, Card, Chip, Label, LinkText, Row, Screen, Sub } from "../components/ui";
import { formatMoney, formatWhen, statusColor } from "../format";
import { colors } from "../theme";

export function HomeScreen({
  user,
  onCreate,
  onApprove,
  onInvite,
  onTeam,
  onReports,
  onLedger,
  onRecord,
  onLogout,
}: {
  user: User | null;
  onCreate: () => void;
  onApprove: () => void;
  onInvite: () => void;
  onTeam: () => void;
  onReports: () => void;
  onLedger: () => void;
  onRecord: (id: number) => void;
  onLogout: () => void;
}) {
  const [balance, setBalance] = useState("—");
  const [orgName, setOrgName] = useState("");
  const [rows, setRows] = useState<MoneyRecord[]>([]);
  const [status, setStatus] = useState<"" | "pending" | "approved" | "rejected">("");
  const [refreshing, setRefreshing] = useState(false);

  const reload = async () => {
    try {
      const [b, org, list] = await Promise.all([
        myBalance(),
        myOrg(),
        myRecords({ status: status || undefined }),
      ]);
      setBalance(formatMoney(b.cash_on_hand, b.currency));
      setOrgName(org.name);
      setRows(list);
    } catch (e) {
      Alert.alert("Fos", e instanceof Error ? e.message : "Load failed");
    }
  };

  useFocusEffect(reload);
  useEffect(() => {
    void reload();
  }, [status]);

  const isManager = user?.role === "owner" || user?.role === "manager";

  return (
    <Screen>
      <View style={styles.topRow}>
        <View>
          <Brand small />
          <Sub>
            {orgName ? `${orgName} · ` : ""}
            {user?.full_name} · {user?.role}
          </Sub>
        </View>
        <LinkText onPress={onLogout}>Log out</LinkText>
      </View>
      <Card>
        <Label>Cash on hand</Label>
        <Text style={styles.balance}>{balance}</Text>
      </Card>
      <Row>
        <Btn title="New record" onPress={onCreate} />
        {isManager && <Btn title="Approvals" onPress={onApprove} variant="secondary" />}
      </Row>
      {isManager && (
        <Row>
          <Btn title="Invite" onPress={onInvite} variant="ghost" />
          <Btn title="Team" onPress={onTeam} variant="ghost" />
          <Btn title="Reports" onPress={onReports} variant="ghost" />
        </Row>
      )}
      {isManager && <Btn title="Org ledger" onPress={onLedger} variant="ghost" />}
      <View style={styles.filters}>
        {(["", "pending", "approved", "rejected"] as const).map((s) => (
          <Chip key={s || "all"} label={s || "all"} on={status === s} onPress={() => setStatus(s)} />
        ))}
      </View>
      <FlatList
        data={rows}
        keyExtractor={(item) => String(item.id)}
        contentContainerStyle={{ paddingBottom: 40 }}
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
        ListHeaderComponent={<Text style={styles.section}>My records</Text>}
        ListEmptyComponent={<Sub>No records yet</Sub>}
        renderItem={({ item }) => (
          <Pressable style={styles.row} onPress={() => onRecord(item.id)}>
            <Text style={styles.rowTitle}>
              {item.kind} · <Text style={{ color: statusColor(item.status) }}>{item.status}</Text>
            </Text>
            <Text style={styles.rowMeta}>
              {formatMoney(item.amount, item.currency)} · {item.category || "—"}
            </Text>
            <Text style={styles.rowMeta}>{formatWhen(item.created_at)}</Text>
          </Pressable>
        )}
      />
    </Screen>
  );
}

const styles = StyleSheet.create({
  topRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  balance: { color: colors.text, fontSize: 24, fontWeight: "700" },
  section: { color: colors.text, fontWeight: "600", marginBottom: 8, marginTop: 8 },
  filters: { flexDirection: "row", gap: 8, marginBottom: 8, flexWrap: "wrap" },
  row: { backgroundColor: colors.card, borderRadius: 12, padding: 12, marginBottom: 8 },
  rowTitle: { color: colors.text, fontWeight: "600", textTransform: "capitalize" },
  rowMeta: { color: colors.muted, marginTop: 4 },
});
